"""PyLevate dev server — HTTP file serving, HMR via WebSocket, file watching."""

from __future__ import annotations

import asyncio
import functools
import mimetypes
import webbrowser
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread
from typing import Set

import websockets
from rich.console import Console
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

from pylevate.config import Config

console = Console()

# ---------------------------------------------------------------------------
# HMR client injection: a tiny snippet that loads the full client
# (js/hmr-client.js — reload, CSS refresh, and compile-error overlay),
# served by this dev server at /__pylevate/hmr-client.js.
# ---------------------------------------------------------------------------

_FRAMEWORK_JS_DIR = Path(__file__).resolve().parent.parent / "js"

HMR_CLIENT_SCRIPT = """\
<script>window.__PYLEVATE_HMR_PORT__ = __HMR_PORT__;</script>
<script src="/__pylevate/hmr-client.js"></script>
"""

# ---------------------------------------------------------------------------
# HTTP request handler — serves files and injects HMR client
# ---------------------------------------------------------------------------


class _HMRHTTPRequestHandler(SimpleHTTPRequestHandler):
    """Serves static files from *directory* and injects the HMR snippet."""

    hmr_port: int = 3001

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Suppress default stderr logging; we use Rich instead.
        pass

    def do_POST(self) -> None:  # noqa: N802
        """Handle POST /api/compile for the playground."""
        if self.path == "/api/compile":
            import json
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8")
            try:
                data = json.loads(body)
                source = data.get("source", "")
                mode = data.get("mode", "app")
                filename = data.get("filename", "playground.py")

                from pylevate.compiler.py2js import compile_source

                result = compile_source(source, filename=filename, mode=mode)
                response = {
                    "js": result.js,
                    "css": "\n".join(result.css_chunks),
                    "errors": [str(e) for e in result.errors],
                    "warnings": [str(w) for w in result.warnings],
                }
            except Exception as exc:
                response = {"js": "", "css": "", "errors": [str(exc)], "warnings": []}

            payload = json.dumps(response).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle CORS preflight."""
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        # The HMR client is served from the framework install, not the project.
        if self.path.split("?")[0] == "/__pylevate/hmr-client.js":
            try:
                body = (_FRAMEWORK_JS_DIR / "hmr-client.js").read_bytes()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
            return

        path = self.translate_path(self.path)
        # Serve index.html for directory requests
        if Path(path).is_dir():
            path = str(Path(path) / "index.html")

        # History-API fallback: extensionless paths (client-side routes like
        # /settings/profile) fall back to the SPA's index.html.
        if not Path(path).exists() and not Path(path).suffix:
            path = self.translate_path("/index.html")

        try:
            content = Path(path).read_bytes()
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        except PermissionError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return

        content_type, _ = mimetypes.guess_type(path)
        content_type = content_type or "application/octet-stream"

        # Inject HMR client into HTML responses
        if content_type == "text/html":
            html = content.decode("utf-8", errors="replace")
            snippet = HMR_CLIENT_SCRIPT.replace(
                "__HMR_PORT__", str(self.hmr_port)
            )
            if "</body>" in html:
                html = html.replace("</body>", snippet + "</body>")
            else:
                html += snippet
            content = html.encode("utf-8")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)


# ---------------------------------------------------------------------------
# File-change handler (watchdog)
# ---------------------------------------------------------------------------


class _ChangeHandler(FileSystemEventHandler):
    """Watches for .py and .css changes and pushes events onto an asyncio queue."""

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
        super().__init__()
        self._loop = loop
        self._queue = queue

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = Path(event.src_path)
        # Skip build artifacts and node_modules
        src_str = str(src)
        if any(d in src_str for d in ("/dist/", "/build_tmp/", "/node_modules/", "/.pixi/")):
            return
        if src.suffix in (".py", ".css"):
            self._loop.call_soon_threadsafe(self._queue.put_nowait, src)


# ---------------------------------------------------------------------------
# DevServer
# ---------------------------------------------------------------------------


class DevServer:
    """Runs an HTTP static server, a WebSocket HMR server, and a file watcher."""

    def __init__(self, project_dir: Path, config: Config) -> None:
        self.project_dir = project_dir.resolve()
        self.config = config
        self.serve_dir = self.project_dir / config.out_dir / "web"
        self._ws_clients: Set[websockets.WebSocketServerProtocol] = set()
        self._change_queue: asyncio.Queue[Path] = asyncio.Queue()

    # -- public API ---------------------------------------------------------

    def start(self, open_browser: bool = False) -> None:
        """Start the dev server (blocks until interrupted)."""
        # Ensure the serve directory exists so the HTTP handler doesn't error.
        self.serve_dir.mkdir(parents=True, exist_ok=True)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._change_queue = asyncio.Queue()

        try:
            loop.run_until_complete(self._run(open_browser))
        except KeyboardInterrupt:
            pass
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    # -- internals ----------------------------------------------------------

    async def _run(self, open_browser: bool) -> None:
        loop = asyncio.get_running_loop()

        # 0. Initial build
        console.print("[cyan]Running initial build...[/cyan]")
        await self._rebuild()

        # 1. Start HTTP server in a background thread
        http_thread = self._start_http_server()

        # 2. Start WebSocket server
        ws_server = await websockets.serve(
            self._ws_handler,
            "localhost",
            self.config.hmr_port,
        )
        console.print(
            f"[green]Dev server listening on "
            f"http://localhost:{self.config.dev_port}[/green]"
        )
        console.print(
            f"[dim]HMR WebSocket on ws://localhost:{self.config.hmr_port}[/dim]"
        )

        # 3. Start file watcher
        observer = Observer()
        handler = _ChangeHandler(loop, self._change_queue)
        observer.schedule(handler, str(self.project_dir), recursive=True)
        observer.start()

        # 4. Optionally open browser
        if open_browser:
            webbrowser.open(f"http://localhost:{self.config.dev_port}")

        # 5. Process file-change events forever
        try:
            await self._watch_loop()
        finally:
            observer.stop()
            observer.join()
            ws_server.close()
            await ws_server.wait_closed()

    def _start_http_server(self) -> Thread:
        handler_cls = type(
            "_Handler",
            (_HMRHTTPRequestHandler,),
            {"hmr_port": self.config.hmr_port},
        )
        handler = functools.partial(handler_cls, directory=str(self.serve_dir))
        httpd = HTTPServer(("localhost", self.config.dev_port), handler)
        thread = Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return thread

    async def _ws_handler(
        self, ws: websockets.WebSocketServerProtocol, path: str = "/"
    ) -> None:
        self._ws_clients.add(ws)
        try:
            async for _ in ws:
                pass  # We only send; ignore incoming messages.
        finally:
            self._ws_clients.discard(ws)

    async def _watch_loop(self) -> None:
        while True:
            changed_file = await self._change_queue.get()

            # Debounce: drain any additional queued changes
            await asyncio.sleep(0.05)
            while not self._change_queue.empty():
                try:
                    changed_file = self._change_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

            console.print(
                f"[cyan]Change detected:[/cyan] "
                f"{changed_file.relative_to(self.project_dir)}"
            )

            # Rebuild via the compiler pipeline
            success = await self._rebuild(changed_file)

            if success:
                msg_type = "css" if changed_file.suffix == ".css" else "reload"
                await self._notify_clients(msg_type, str(changed_file.name))

    async def _rebuild(self, changed_file: Path | None = None) -> bool:
        """Rebuild the project. Returns True on success."""
        import time as _time

        try:
            from pylevate.compiler.pipeline import Pipeline

            t0 = _time.perf_counter()
            pipeline = Pipeline(project_dir=self.project_dir, config=self.config)
            loop = asyncio.get_running_loop()

            if changed_file and hasattr(pipeline, "rebuild"):
                result = await loop.run_in_executor(
                    None, pipeline.rebuild, changed_file
                )
            else:
                result = await loop.run_in_executor(None, pipeline.build)

            elapsed = (_time.perf_counter() - t0) * 1000

            for warning in result.warnings:
                console.print(f"  [yellow]warning: {warning}[/yellow]")

            if not result.success:
                for err in result.errors:
                    console.print(f"  [red]{err}[/red]")
                # Send error to HMR clients
                await self._notify_error(result.errors)
                return False

            console.print(
                f"[green]Rebuild complete[/green] [dim]({elapsed:.0f}ms)[/dim]"
            )
            # Clear any previous error overlay
            await self._notify_clients("clear-error", "")
            return True
        except Exception as exc:
            console.print(f"[red]Rebuild failed: {exc}[/red]")
            await self._notify_error([str(exc)])
            return False

    async def _notify_clients(self, msg_type: str, file_name: str) -> None:
        import json

        payload = json.dumps({"type": msg_type, "file": file_name})
        await self._broadcast(payload)

    async def _notify_error(self, errors: list[str]) -> None:
        import json
        import re

        # Send first error to the overlay. Compile errors are formatted as
        # "file:line:col: message" (CompileError.__str__) or "file: message".
        message = errors[0] if errors else "Unknown error"
        file, line, col = "", 0, 0
        m = re.match(r"^(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+): (?P<msg>.*)", message, re.DOTALL)
        if m:
            file, line, col = m.group("file"), int(m.group("line")), int(m.group("col"))
            message = m.group("msg")
        else:
            m = re.match(r"^(?P<file>[^:\n]+\.py): (?P<msg>.*)", message, re.DOTALL)
            if m:
                file, message = m.group("file"), m.group("msg")
        payload = json.dumps({
            "type": "error",
            "message": message,
            "file": file,
            "line": line,
            "col": col,
        })
        await self._broadcast(payload)

    async def _broadcast(self, payload: str) -> None:
        stale: list[websockets.WebSocketServerProtocol] = []
        for ws in self._ws_clients:
            try:
                await ws.send(payload)
            except websockets.ConnectionClosed:
                stale.append(ws)
        for ws in stale:
            self._ws_clients.discard(ws)

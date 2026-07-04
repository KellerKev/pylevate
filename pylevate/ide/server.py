"""IDE server — a DevServer with a switchable active project and IDE routes."""

from __future__ import annotations

import asyncio
import functools
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import websockets
from watchdog.observers import Observer

from pylevate.config import Config
from pylevate.ide.handler import IDEHandler, WorkspaceState
from pylevate.scaffold import npm_install
from pylevate.server import DevServer, _ChangeHandler, console


class _IDEActions:
    """Thread-safe entry points the HTTP handler uses to drive the server loop."""

    def __init__(self, ide_server: "IDEServer") -> None:
        self._ide = ide_server

    def open_project(self, name: str) -> None:
        asyncio.run_coroutine_threadsafe(self._ide._open_project(name), self._ide._loop)

    def install_and_open(self, name: str) -> None:
        def _work() -> None:
            status, detail = npm_install(self._ide.state.workspace_dir / name)
            with self._ide.state.lock:
                self._ide.state.npm[name] = status if status == "ok" else f"{status}: {detail}".rstrip(": ")
            self.open_project(name)

        threading.Thread(target=_work, daemon=True).start()


class IDEServer(DevServer):
    """Serves the IDE UI, workspace/file APIs, and the active project's build."""

    def __init__(self, workspace_dir: Path, config: Config) -> None:
        workspace_dir = workspace_dir.resolve()
        # DevServer wants a project_dir; until a project is opened we point it
        # at the workspace and skip building.
        super().__init__(project_dir=workspace_dir, config=config)
        # Don't let DevServer.start() create workspace/dist/web — until a
        # project is opened there is nothing to serve.
        self.serve_dir = workspace_dir
        self.workspace_dir = workspace_dir
        self.state = WorkspaceState(workspace_dir=workspace_dir)
        self.actions = _IDEActions(self)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._observer: Observer | None = None

        # The workspace itself may be a project (has pylevate.config.py) —
        # single-project mode. Its display name maps back to workspace_dir.
        self._auto_open = (workspace_dir / "pylevate.config.py").exists()
        if self._auto_open:
            self.state.root_project = workspace_dir.name

    # -- lifecycle -------------------------------------------------------------

    async def _run(self, open_browser: bool) -> None:
        self._loop = asyncio.get_running_loop()

        http_thread = self._start_http_server()

        ws_server = await websockets.serve(
            self._ws_handler, "localhost", self.config.hmr_port,
        )
        console.print(
            f"[green]PyLevate IDE on http://localhost:{self.config.dev_port}/__pylevate/ide[/green]"
        )
        console.print(f"[dim]Workspace: {self.workspace_dir}[/dim]")
        console.print(f"[dim]HMR WebSocket on ws://localhost:{self.config.hmr_port}[/dim]")

        self._observer = Observer()
        self._observer.start()

        if self._auto_open:
            await self._open_project(None)

        if open_browser:
            webbrowser.open(f"http://localhost:{self.config.dev_port}/__pylevate/ide")

        try:
            await self._watch_loop()
        finally:
            self._observer.stop()
            self._observer.join()
            ws_server.close()
            await ws_server.wait_closed()

    def _start_http_server(self) -> Thread:
        handler_cls = type(
            "_IDEHandler",
            (IDEHandler,),
            {"hmr_port": self.config.hmr_port},
        )
        handler = functools.partial(handler_cls, directory=str(self.workspace_dir))
        httpd = ThreadingHTTPServer(("localhost", self.config.dev_port), handler)
        httpd.ide_state = self.state
        httpd.ide_actions = self.actions
        thread = Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return thread

    # -- project switching --------------------------------------------------------

    async def _open_project(self, name: str | None) -> None:
        """(Re)point the server at a project. Runs on the event loop.

        name=None (or the root-project name) opens the workspace itself.
        """
        if name is None or name == self.state.root_project:
            project_dir = self.workspace_dir
        else:
            project_dir = self.workspace_dir / name
        display = name or project_dir.name

        with self.state.lock:
            self.state.build = {"status": "building", "errors": [], "ms": 0}

        self.project_dir = project_dir.resolve()
        self.config = Config.load(self.project_dir)
        self.serve_dir = self.project_dir / self.config.out_dir / "web"
        self.serve_dir.mkdir(parents=True, exist_ok=True)

        with self.state.lock:
            self.state.active_project = display
            self.state.serve_dir = self.serve_dir

        if self._observer is not None:
            self._observer.unschedule_all()
            # Drop events queued for the previous project.
            while not self._change_queue.empty():
                try:
                    self._change_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            change_handler = _ChangeHandler(self._loop, self._change_queue)
            self._observer.schedule(change_handler, str(self.project_dir), recursive=True)

        console.print(f"[cyan]Opening project:[/cyan] {display}")
        await self._rebuild()
        await self._notify_clients("reload", "")

    # -- build status tracking -------------------------------------------------------

    async def _rebuild(self, changed_file: Path | None = None) -> bool:
        with self.state.lock:
            self.state.build = {"status": "building", "errors": [], "ms": 0}
        import time as _time

        t0 = _time.perf_counter()
        success = await super()._rebuild(changed_file)
        elapsed = (_time.perf_counter() - t0) * 1000
        with self.state.lock:
            self.state.build = {
                "status": "ok" if success else "error",
                "errors": [] if success else ["Build failed — see the error overlay/panel"],
                "ms": round(elapsed),
            }
        return success

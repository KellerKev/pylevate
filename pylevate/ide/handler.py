"""HTTP handler for the IDE server.

Extends the dev-server handler with /api/ide/* routes and the IDE UI page.
Route logic delegates to pure functions in files.py and to the actions object
the server attaches (`self.server.ide_actions`), so tests can drive this
handler with a fabricated state and recorded actions.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pylevate.ide import files
from pylevate.scaffold import TEMPLATES_DIR, VALID_TEMPLATES, ScaffoldError, scaffold_project
from pylevate.server import _HMRHTTPRequestHandler

_IDE_STATIC = Path(__file__).resolve().parent / "static"


@dataclass
class WorkspaceState:
    """Shared, lock-guarded state between HTTP threads and the server loop."""

    workspace_dir: Path
    active_project: str | None = None
    serve_dir: Path | None = None
    # Set when the workspace directory itself is a project (single-project
    # mode): the display name that maps back to workspace_dir.
    root_project: str | None = None
    build: dict = field(default_factory=lambda: {"status": "idle", "errors": [], "ms": 0})
    npm: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "workspace": str(self.workspace_dir),
                "activeProject": self.active_project,
                "build": dict(self.build),
                "npm": dict(self.npm),
            }


class IDEHandler(_HMRHTTPRequestHandler):
    """Dev-server handler plus the IDE UI and workspace/file APIs."""

    @property
    def _state(self) -> WorkspaceState:
        return self.server.ide_state

    @property
    def _actions(self):
        return self.server.ide_actions

    # -- helpers -------------------------------------------------------------

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def _project_dir(self, name: str) -> Path:
        # Single-project mode: the workspace directory itself is the project.
        if name and name == self._state.root_project:
            return self._state.workspace_dir
        return files.resolve_project(self._state.workspace_dir, name)

    # -- routing ---------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in ("/__pylevate/ide", "/__pylevate/ide/"):
            self._serve_ide_ui()
            return
        if path == "/api/ide/workspace":
            projects = files.list_projects(self._state.workspace_dir)
            if self._state.root_project:
                projects = [self._state.root_project, *projects]
            self._send_json(200, {
                "projects": projects,
                "templates": [t for t in VALID_TEMPLATES if (TEMPLATES_DIR / t).is_dir()],
                **self._state.snapshot(),
            })
            return
        if path == "/api/ide/status":
            self._send_json(200, self._state.snapshot())
            return
        if path == "/api/ide/tree":
            self._with_project(query, lambda project_dir: self._send_json(
                200, {"tree": files.list_tree(project_dir)}
            ))
            return
        if path == "/api/ide/file":
            def _serve(project_dir: Path) -> None:
                rel = (query.get("path") or [""])[0]
                content = files.read_file(project_dir, rel)
                self._send_json(200, {"path": rel, "content": content})
            self._with_project(query, _serve)
            return

        # No active project: the root redirects into the IDE.
        if path == "/" and self._state.active_project is None:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/__pylevate/ide")
            self.end_headers()
            return

        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/api/ide/create":
            self._handle_create()
            return
        if path == "/api/ide/open":
            self._handle_open()
            return
        super().do_POST()

    def do_PUT(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path != "/api/ide/file":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            body = self._read_json_body()
            project_dir = self._project_dir(body.get("project", ""))
            files.write_file(project_dir, body.get("path", ""), body.get("content", ""))
        except files.FileAccessError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except (ValueError, OSError) as exc:
            self._send_json(400, {"error": f"Bad request: {exc}"})
            return
        self._send_json(200, {"ok": True})

    # -- route bodies -------------------------------------------------------------

    def _with_project(self, query: dict, fn) -> None:
        try:
            project_dir = self._project_dir((query.get("project") or [""])[0])
            fn(project_dir)
        except files.FileAccessError as exc:
            self._send_json(400, {"error": str(exc)})

    def _handle_create(self) -> None:
        try:
            body = self._read_json_body()
            name = body.get("name", "")
            template = body.get("template", "app")
            scaffold_project(name, template, self._state.workspace_dir)
        except ScaffoldError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except (ValueError, OSError) as exc:
            self._send_json(400, {"error": f"Bad request: {exc}"})
            return
        with self._state.lock:
            self._state.npm[name] = "installing"
        self._actions.install_and_open(name)
        self._send_json(202, {"project": name, "npm": "installing"})

    def _handle_open(self) -> None:
        try:
            body = self._read_json_body()
            name = body.get("project", "")
            self._project_dir(name)  # validate before scheduling
        except files.FileAccessError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except (ValueError, OSError) as exc:
            self._send_json(400, {"error": f"Bad request: {exc}"})
            return
        self._actions.open_project(name)
        self._send_json(202, {"project": name})

    # -- IDE UI ------------------------------------------------------------------

    def _serve_ide_ui(self) -> None:
        try:
            html = (_IDE_STATIC / "index.html").read_text(encoding="utf-8")
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        config = json.dumps({
            "hmrPort": self.hmr_port,
            **self._state.snapshot(),
        })
        html = html.replace("__PYLEVATE_IDE_CONFIG__", config)
        data = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # -- static serving against the switchable project -----------------------------

    def translate_path(self, path: str) -> str:
        serve_dir = self._state.serve_dir
        if serve_dir is not None:
            self.directory = str(serve_dir)
        return super().translate_path(path)

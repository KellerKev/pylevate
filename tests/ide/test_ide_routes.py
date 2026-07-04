"""Route tests for the IDE HTTP handler, run against a live handler with a
fabricated WorkspaceState and recorded actions — no asyncio loop, no watcher."""

import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from pylevate.ide.handler import IDEHandler, WorkspaceState
from pylevate.scaffold import scaffold_project


class _RecordingActions:
    def __init__(self):
        self.opened = []
        self.installed = []

    def open_project(self, name):
        self.opened.append(name)

    def install_and_open(self, name):
        self.installed.append(name)


@pytest.fixture()
def ide_server(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    scaffold_project("demo", "app", workspace)

    handler_cls = type("_TestIDEHandler", (IDEHandler,), {"hmr_port": 0})
    import functools
    handler = functools.partial(handler_cls, directory=str(workspace))
    server = ThreadingHTTPServer(("localhost", 0), handler)
    server.ide_state = WorkspaceState(workspace_dir=workspace)
    server.ide_actions = _RecordingActions()
    threading.Thread(target=server.serve_forever, daemon=True).start()

    yield server, workspace

    server.shutdown()


def _request(port, method, path, body=None):
    conn = http.client.HTTPConnection("localhost", port, timeout=10)
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers={"Content-Type": "application/json"})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    try:
        return response, json.loads(data)
    except json.JSONDecodeError:
        return response, data


class TestIDERoutes:
    def test_workspace_listing(self, ide_server):
        server, _ = ide_server
        response, payload = _request(server.server_address[1], "GET", "/api/ide/workspace")
        assert response.status == 200
        assert payload["projects"] == ["demo"]
        assert "app" in payload["templates"]
        assert payload["activeProject"] is None

    def test_status(self, ide_server):
        server, _ = ide_server
        response, payload = _request(server.server_address[1], "GET", "/api/ide/status")
        assert response.status == 200
        assert payload["build"]["status"] == "idle"

    def test_tree_and_file_round_trip(self, ide_server):
        server, workspace = ide_server
        port = server.server_address[1]
        response, payload = _request(port, "GET", "/api/ide/tree?project=demo")
        assert response.status == 200
        names = {e["name"] for e in payload["tree"]}
        assert "main.py" in names

        response, payload = _request(port, "GET", "/api/ide/file?project=demo&path=main.py")
        assert response.status == 200
        assert "mount" in payload["content"]

        response, payload = _request(port, "PUT", "/api/ide/file",
                                     {"project": "demo", "path": "main.py", "content": "x = 1\n"})
        assert response.status == 200
        assert (workspace / "demo" / "main.py").read_text() == "x = 1\n"

    def test_create_scaffolds_and_schedules(self, ide_server):
        server, workspace = ide_server
        port = server.server_address[1]
        response, payload = _request(port, "POST", "/api/ide/create",
                                     {"name": "fresh", "template": "app"})
        assert response.status == 202
        assert (workspace / "fresh" / "main.py").exists()
        assert server.ide_actions.installed == ["fresh"]
        assert server.ide_state.npm["fresh"] == "installing"

    def test_create_invalid_template_400(self, ide_server):
        server, _ = ide_server
        response, payload = _request(server.server_address[1], "POST", "/api/ide/create",
                                     {"name": "x", "template": "nope"})
        assert response.status == 400

    def test_open_validates_then_schedules(self, ide_server):
        server, _ = ide_server
        port = server.server_address[1]
        response, _ = _request(port, "POST", "/api/ide/open", {"project": "demo"})
        assert response.status == 202
        assert server.ide_actions.opened == ["demo"]

        response, _ = _request(port, "POST", "/api/ide/open", {"project": "ghost"})
        assert response.status == 400

    def test_traversal_rejected(self, ide_server):
        server, _ = ide_server
        port = server.server_address[1]
        response, _ = _request(port, "GET", "/api/ide/file?project=demo&path=../../etc/passwd")
        assert response.status == 400
        response, _ = _request(port, "GET", "/api/ide/tree?project=..")
        assert response.status == 400

    def test_unknown_api_route_404_not_spa_fallback(self, ide_server):
        server, _ = ide_server
        response, _ = _request(server.server_address[1], "GET", "/api/ide/unknown")
        assert response.status == 404

    def test_root_redirects_to_ide_when_no_project(self, ide_server):
        server, _ = ide_server
        conn = http.client.HTTPConnection("localhost", server.server_address[1], timeout=10)
        conn.request("GET", "/")
        response = conn.getresponse()
        response.read()
        conn.close()
        assert response.status == 302
        assert response.getheader("Location") == "/__pylevate/ide"

    def test_root_project_workspace_tree_and_file(self, tmp_path):
        # Single-project mode: the workspace directory itself is the project.
        workspace = tmp_path / "solo-app"
        workspace.mkdir()
        scaffold_project("inner", "app", tmp_path)  # scratch template source
        for item in (tmp_path / "inner").iterdir():
            item.rename(workspace / item.name)
        (tmp_path / "inner").rmdir()

        handler_cls = type("_TestIDEHandler2", (IDEHandler,), {"hmr_port": 0})
        import functools
        handler = functools.partial(handler_cls, directory=str(workspace))
        server = ThreadingHTTPServer(("localhost", 0), handler)
        server.ide_state = WorkspaceState(
            workspace_dir=workspace,
            active_project="solo-app",
            root_project="solo-app",
        )
        server.ide_actions = _RecordingActions()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            port = server.server_address[1]
            response, payload = _request(port, "GET", "/api/ide/workspace")
            assert payload["projects"][0] == "solo-app"

            response, payload = _request(port, "GET", "/api/ide/tree?project=solo-app")
            assert response.status == 200
            assert any(e["name"] == "main.py" for e in payload["tree"])

            response, payload = _request(port, "GET", "/api/ide/file?project=solo-app&path=main.py")
            assert response.status == 200
            assert "mount" in payload["content"]
        finally:
            server.shutdown()

    def test_ide_ui_served_with_config(self, ide_server):
        server, _ = ide_server
        response, body = _request(server.server_address[1], "GET", "/__pylevate/ide")
        assert response.status == 200
        text = body if isinstance(body, (str, bytes)) else json.dumps(body)
        if isinstance(text, bytes):
            text = text.decode()
        assert "__PYLEVATE_IDE_CONFIG__" not in text  # token replaced
        assert "activeProject" in text

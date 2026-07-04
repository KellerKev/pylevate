"""Tests for the dev-server LLM proxy."""

import http.client
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pylevate.ide.llm_proxy import (
    ProxyConfigError,
    origin_allowed,
    resolve_upstream,
)


class TestResolveUpstream:
    def test_custom_base_url(self):
        target = resolve_upstream(
            "chat/completions", None,
            {"PYLEVATE_LLM_BASE_URL": "http://localhost:11434/v1",
             "PYLEVATE_LLM_API_KEY": "k1"},
        )
        assert target.url == "http://localhost:11434/v1/chat/completions"
        assert target.headers["Authorization"] == "Bearer k1"

    def test_custom_base_without_key_sends_no_auth(self):
        target = resolve_upstream(
            "chat/completions", None, {"PYLEVATE_LLM_BASE_URL": "http://localhost:11434/v1"}
        )
        assert "Authorization" not in target.headers

    def test_openai_key(self):
        target = resolve_upstream("chat/completions", "openai", {"OPENAI_API_KEY": "sk-x"})
        assert target.url == "https://api.openai.com/v1/chat/completions"
        assert target.headers["Authorization"] == "Bearer sk-x"

    def test_anthropic_key(self):
        target = resolve_upstream("v1/messages", "anthropic", {"ANTHROPIC_API_KEY": "sk-ant"})
        assert target.url == "https://api.anthropic.com/v1/messages"
        assert target.headers["x-api-key"] == "sk-ant"
        assert target.headers["anthropic-version"] == "2023-06-01"

    def test_anthropic_auto_detected_from_subpath(self):
        target = resolve_upstream("v1/messages", None, {"ANTHROPIC_API_KEY": "sk-ant"})
        assert target.provider == "anthropic"

    def test_custom_base_preferred_without_hint(self):
        target = resolve_upstream(
            "chat/completions", None,
            {"PYLEVATE_LLM_BASE_URL": "http://x/v1", "OPENAI_API_KEY": "sk"},
        )
        assert target.url.startswith("http://x/v1")

    def test_nothing_configured_raises(self):
        with pytest.raises(ProxyConfigError):
            resolve_upstream("chat/completions", None, {})

    def test_unknown_subpath_rejected(self):
        with pytest.raises(ProxyConfigError):
            resolve_upstream("admin/keys", None, {"OPENAI_API_KEY": "sk"})

    def test_error_never_contains_key_value(self):
        try:
            resolve_upstream("chat/completions", "anthropic", {"OPENAI_API_KEY": "sk-secret"})
        except ProxyConfigError as exc:
            assert "sk-secret" not in str(exc)


class TestOriginAllowed:
    def test_no_origin_ok(self):
        assert origin_allowed(None)

    def test_localhost_ok(self):
        assert origin_allowed("http://localhost:3000")
        assert origin_allowed("http://127.0.0.1:4000")

    def test_remote_rejected(self):
        assert not origin_allowed("https://evil.example")
        assert not origin_allowed("http://localhost.evil.example")


# ---------------------------------------------------------------------------
# Integration: real handler <- proxy -> stub SSE upstream
# ---------------------------------------------------------------------------


class _StubUpstream(BaseHTTPRequestHandler):
    """Emits three SSE chunks with small delays."""

    seen_auth: list[str] = []  # class-level capture of Authorization headers

    def log_message(self, *a):  # noqa: A002
        pass

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        payload = json.loads(body)
        if payload.get("fail"):
            self.send_response(500)
            error = b'{"error": {"message": "upstream boom"}}'
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(error)))
            self.end_headers()
            self.wfile.write(error)
            return
        _StubUpstream.seen_auth.append(self.headers.get("Authorization", ""))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for i in range(3):
            self.wfile.write(f'data: {{"n": {i}}}\n\n'.encode())
            self.wfile.flush()
            time.sleep(0.05)


@pytest.fixture()
def proxy_setup(monkeypatch):
    """A stub upstream plus a dev-server handler with the proxy wired in."""
    from pylevate.server import _HMRHTTPRequestHandler

    upstream = ThreadingHTTPServer(("localhost", 0), _StubUpstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    upstream_url = f"http://localhost:{upstream.server_address[1]}"

    monkeypatch.setenv("PYLEVATE_LLM_BASE_URL", upstream_url)
    monkeypatch.setenv("PYLEVATE_LLM_API_KEY", "server-side-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    server = ThreadingHTTPServer(("localhost", 0), _HMRHTTPRequestHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    yield server.server_address[1]

    server.shutdown()
    upstream.shutdown()


class TestProxyIntegration:
    def test_streams_chunks_and_attaches_key(self, proxy_setup):
        _StubUpstream.seen_auth.clear()
        conn = http.client.HTTPConnection("localhost", proxy_setup, timeout=10)
        conn.request(
            "POST", "/api/llm/chat/completions",
            body=json.dumps({"model": "m", "stream": True}),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        assert response.status == 200
        assert "text/event-stream" in response.getheader("Content-Type", "")
        body = response.read().decode()
        assert body.count("data:") == 3
        # The server-side key was attached upstream, invisible to the client.
        assert _StubUpstream.seen_auth == ["Bearer server-side-key"]
        conn.close()

    def test_upstream_error_passed_through(self, proxy_setup):
        conn = http.client.HTTPConnection("localhost", proxy_setup, timeout=10)
        conn.request("POST", "/api/llm/chat/completions", body=json.dumps({"fail": True}))
        response = conn.getresponse()
        assert response.status == 500
        assert b"upstream boom" in response.read()
        conn.close()

    def test_unknown_subpath_rejected(self, proxy_setup):
        conn = http.client.HTTPConnection("localhost", proxy_setup, timeout=10)
        conn.request("POST", "/api/llm/whatever", body="{}")
        response = conn.getresponse()
        assert response.status == 503
        assert b"proxy_not_configured" in response.read()
        conn.close()

    def test_forbidden_origin(self, proxy_setup):
        conn = http.client.HTTPConnection("localhost", proxy_setup, timeout=10)
        conn.request(
            "POST", "/api/llm/chat/completions", body="{}",
            headers={"Origin": "https://evil.example"},
        )
        response = conn.getresponse()
        assert response.status == 403
        conn.close()

    def test_no_config_returns_503(self, proxy_setup, monkeypatch):
        monkeypatch.delenv("PYLEVATE_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("PYLEVATE_LLM_API_KEY", raising=False)
        conn = http.client.HTTPConnection("localhost", proxy_setup, timeout=10)
        conn.request("POST", "/api/llm/chat/completions", body="{}")
        response = conn.getresponse()
        assert response.status == 503
        payload = json.loads(response.read())
        assert "OPENAI_API_KEY" in payload["error"]["message"]
        conn.close()

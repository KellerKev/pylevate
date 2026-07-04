"""Dev-server LLM proxy: forwards chat/embedding requests to a provider,
attaching the API key from environment variables so it never reaches the
browser. Streaming (SSE) responses are piped through chunk by chunk.

Contract (matches js/pylevate-ai-runtime.js proxy mode):
- Browser POSTs /api/llm/<subpath> with the provider wire-format body.
- Optional header X-Pylevate-Provider: openai | anthropic | custom.
- Env resolution: PYLEVATE_LLM_BASE_URL (+ PYLEVATE_LLM_API_KEY) for custom
  upstreams; OPENAI_API_KEY -> api.openai.com/v1; ANTHROPIC_API_KEY ->
  api.anthropic.com. Keys are never echoed in responses or logs.

Localhost-only by design: the dev server binds localhost, this route sends no
Access-Control-Allow-Origin, and non-localhost Origins are rejected.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Sub-paths the proxy will forward. Anything else is rejected.
ALLOWED_SUBPATHS = ("chat/completions", "embeddings", "v1/messages")

DEFAULT_TIMEOUT = 300.0

_ANTHROPIC_VERSION = "2023-06-01"


class ProxyConfigError(Exception):
    """No usable upstream is configured for the requested provider."""


@dataclass
class UpstreamTarget:
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    provider: str = "openai"


def resolve_upstream(subpath: str, provider_hint: str | None, env: dict) -> UpstreamTarget:
    """Pick the upstream URL and auth headers for a proxied request.

    The browser never chooses the upstream host — only which configured
    provider to use. Raises ProxyConfigError when nothing is configured.
    """
    if subpath not in ALLOWED_SUBPATHS:
        raise ProxyConfigError(f"Unsupported proxy path: {subpath}")

    custom_base = env.get("PYLEVATE_LLM_BASE_URL", "").rstrip("/")
    provider = (provider_hint or "").lower()
    if not provider:
        # No hint: the wire format (and therefore the provider family) is
        # determined by the sub-path the client chose.
        if subpath == "v1/messages":
            provider = "anthropic"
        elif custom_base:
            provider = "custom"
        else:
            provider = "openai"

    if provider == "custom" or (provider == "openai" and custom_base and not env.get("OPENAI_API_KEY")):
        if not custom_base:
            raise ProxyConfigError(
                "No LLM upstream configured. Set PYLEVATE_LLM_BASE_URL "
                "(+ PYLEVATE_LLM_API_KEY), OPENAI_API_KEY, or ANTHROPIC_API_KEY."
            )
        key = env.get("PYLEVATE_LLM_API_KEY", "") or env.get("OPENAI_API_KEY", "")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        return UpstreamTarget(url=f"{custom_base}/{subpath}", headers=headers, provider="custom")

    if provider == "anthropic":
        key = env.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ProxyConfigError(
                "Anthropic requested but ANTHROPIC_API_KEY is not set."
            )
        return UpstreamTarget(
            url=f"https://api.anthropic.com/{subpath}",
            headers={"x-api-key": key, "anthropic-version": _ANTHROPIC_VERSION},
            provider="anthropic",
        )

    if provider == "openai":
        key = env.get("OPENAI_API_KEY", "")
        if not key:
            raise ProxyConfigError("OpenAI requested but OPENAI_API_KEY is not set.")
        return UpstreamTarget(
            url=f"https://api.openai.com/v1/{subpath}",
            headers={"Authorization": f"Bearer {key}"},
            provider="openai",
        )

    raise ProxyConfigError(
        "No LLM API key configured. Set OPENAI_API_KEY, ANTHROPIC_API_KEY, "
        "or PYLEVATE_LLM_API_KEY + PYLEVATE_LLM_BASE_URL."
    )


def origin_allowed(origin: str | None) -> bool:
    """Only same-machine pages may spend the configured API key."""
    if not origin:
        return True  # same-origin fetch / non-browser client
    return origin.startswith(("http://localhost:", "http://127.0.0.1:",
                              "http://localhost/", "http://127.0.0.1/")) \
        or origin in ("http://localhost", "http://127.0.0.1")


def handle_llm_proxy(handler, subpath: str) -> None:
    """Serve one POST /api/llm/<subpath> request on a BaseHTTPRequestHandler.

    Runs on the handler's own thread (server must be threading); streams the
    upstream response through without buffering.
    """
    if not origin_allowed(handler.headers.get("Origin")):
        _send_json(handler, 403, {"error": {"message": "Origin not allowed", "code": "forbidden"}})
        return

    try:
        content_len = int(handler.headers.get("Content-Length", 0))
        body = handler.rfile.read(content_len)
        target = resolve_upstream(
            subpath, handler.headers.get("X-Pylevate-Provider"), dict(os.environ)
        )
    except ProxyConfigError as exc:
        _send_json(handler, 503, {"error": {"message": str(exc), "code": "proxy_not_configured"}})
        return
    except (ValueError, OSError) as exc:
        _send_json(handler, 400, {"error": {"message": f"Bad request: {exc}", "code": "bad_request"}})
        return

    timeout = float(os.environ.get("PYLEVATE_LLM_TIMEOUT", DEFAULT_TIMEOUT))
    request = urllib.request.Request(
        target.url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", **target.headers},
    )

    try:
        upstream = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 — host fixed server-side
    except urllib.error.HTTPError as exc:
        # Pass the provider's error payload through — it's useful to the client.
        payload = exc.read()
        handler.send_response(exc.code)
        handler.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)
        log.info("llm proxy: %s -> %s (%d)", subpath, target.provider, exc.code)
        return
    except (urllib.error.URLError, OSError) as exc:
        _send_json(handler, 502, {
            "error": {"message": f"Upstream request failed: {getattr(exc, 'reason', exc)}",
                      "code": "proxy_error"},
        })
        return

    try:
        with upstream:
            handler.send_response(upstream.status)
            handler.send_header(
                "Content-Type", upstream.headers.get("Content-Type", "text/event-stream")
            )
            handler.send_header("Cache-Control", "no-cache")
            # Stream until upstream EOF, then close the connection — no
            # Content-Length. Legal under the handler's HTTP/1.0; if
            # protocol_version is ever bumped to 1.1 this must switch to
            # chunked transfer encoding.
            handler.send_header("Connection", "close")
            handler.end_headers()
            while True:
                chunk = upstream.read(8192)
                if not chunk:
                    break
                handler.wfile.write(chunk)
                handler.wfile.flush()
        log.info("llm proxy: %s -> %s (%d)", subpath, target.provider, upstream.status)
    except (BrokenPipeError, ConnectionResetError):
        # Browser navigated away mid-stream — nothing to do.
        pass


def _send_json(handler, status: int, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)

"""Type stubs for the PyLevate AI client (pylevate.ai).

IDE autocomplete / type checking only — never shipped. The compiler rewrites
`from pylevate.ai import ...` to 'pylevate-ai-runtime' (js/pylevate-ai-runtime.js).

Conventions when calling from Python:
- Keyword arguments compile to a single trailing options object, which is
  exactly what these APIs expect: `client.chat(msgs, on_token=...)`.
- Callbacks MUST be lambdas (`on_token=lambda t: store.push(t)`) — a bare
  method reference like `self.on_token` loses `this` in the compiled JS.
"""

from __future__ import annotations

from typing import Any, Callable


class AIError(Exception):
    """Raised on provider/network errors. Fields: status, code, provider."""

    status: int | None
    code: str | None
    provider: str | None


class AIClient:
    """Streaming LLM client for OpenAI-compatible APIs and Anthropic.

    Args:
        base_url:  provider base URL. OpenAI-compatible examples:
                   'https://api.openai.com/v1', 'http://localhost:11434/v1'
                   (Ollama), 'http://localhost:1234/v1' (LM Studio).
                   'https://api.anthropic.com' selects the Anthropic adapter.
                   A leading '/' (e.g. '/api/llm') selects dev-server proxy
                   mode: same-origin requests, API key stays server-side.
        api_key:   provider key; omit for local servers and proxy mode.
        model:     default model for all calls.
        provider:  'openai' | 'anthropic' (auto-detected from base_url).
        system:    default system prompt.
        max_tokens: default max tokens (Anthropic default 4096).
    """

    def __init__(self, base_url: str = "", api_key: str = "", model: str = "",
                 provider: str = "", system: str | None = None,
                 max_tokens: int | None = None, headers: dict | None = None) -> None: ...

    async def chat(self, messages: list, on_token: Callable[[str], None] | None = None,
                   on_event: Callable[[dict], None] | None = None,
                   system: str | None = None, model: str = "",
                   tools: list | None = None, max_tokens: int | None = None,
                   signal: Any = None, stream: bool = True) -> dict:
        """Streaming chat completion. Returns the assistant message dict
        {id, role, content, tool_calls?, finish_reason, usage}."""
        ...

    async def complete(self, prompt: str | list, system: str | None = None,
                       model: str = "", max_tokens: int | None = None,
                       signal: Any = None) -> str:
        """Non-streaming one-shot completion; returns the reply text."""
        ...

    async def embeddings(self, texts: list[str], model: str = "",
                         signal: Any = None) -> list[list[float]]:
        """Embeddings via the OpenAI-compatible endpoint (not Anthropic)."""
        ...

    async def run_tools(self, messages: list, tools: list | None = None,
                        on_step: Callable[[dict], None] | None = None,
                        on_token: Callable[[str], None] | None = None,
                        max_steps: int = 10, signal: Any = None) -> dict:
        """Agentic loop: model → tools → model until the model stops asking.
        on_step receives {'type': 'turn'|'assistant_text'|'tool_call'|'tool_result', ...}.
        Returns {'messages': full transcript, 'final': final assistant message}."""
        ...


def tool(name: str = "", description: str = "", parameters: dict | None = None,
         handler: Callable[[dict], Any] | None = None) -> dict:
    """Declare a tool for AIClient.run_tools.

    parameters is a JSON Schema object; handler receives the parsed arguments
    dict and returns a string (or JSON-serializable value)."""
    ...


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    ...


def chunk_text(text: str, max_chars: int = 500) -> list[str]:
    """Split text into ~max_chars chunks on paragraph/sentence boundaries."""
    ...

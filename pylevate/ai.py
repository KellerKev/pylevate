"""pylevate.ai — LLM client (IDE-facing import path).

At build time the compiler rewrites this import to the JS runtime package
'pylevate-ai-runtime'; this module only serves editors and type checkers.
"""

from pylevate.runtime.ai import (
    AIClient,
    AIError,
    chunk_text,
    cosine_similarity,
    tool,
)

__all__ = [
    "AIClient",
    "AIError",
    "chunk_text",
    "cosine_similarity",
    "tool",
]

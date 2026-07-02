"""Type stubs for PyLevate signals.

For IDE autocomplete and type checking only — never shipped to browser.
"""

from __future__ import annotations
from typing import Any, Callable


def signal(initial: Any = None) -> Any:
    """Create a reactive signal."""
    return initial


def computed(fn: Callable) -> Any:
    """Create a computed signal derived from other signals."""
    return fn


def effect(fn: Callable) -> None:
    """Register a side effect that runs when dependencies change."""


def batch(fn: Callable) -> None:
    """Batch multiple signal updates into a single re-render."""

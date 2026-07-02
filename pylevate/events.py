"""PyLevate event bus for the **desktop** (CPython) — a pure-Python port of
``js/pylevate-events.js``.

In the browser, ``from pylevate.events import game_events`` is compiled to the JS
EventBus singleton. This module is the desktop equivalent so hybrid ``game.py``
that emits/subscribes to events also runs under real pygame (``python main.py``).
Same ``on`` / ``once`` / ``emit`` / ``off`` API.
"""
from __future__ import annotations

from typing import Callable


class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, set[Callable]] = {}

    def on(self, event: str, callback: Callable):
        """Subscribe. Returns an unsubscribe callable."""
        self._listeners.setdefault(event, set()).add(callback)
        return lambda: self._listeners.get(event, set()).discard(callback)

    def once(self, event: str, callback: Callable):
        def wrapper(*args):
            unsub()
            callback(*args)
        unsub = self.on(event, wrapper)
        return unsub

    def emit(self, event: str, *args) -> None:
        for cb in list(self._listeners.get(event, ())):
            try:
                cb(*args)
            except Exception as e:  # match the JS bus: log, don't crash the loop
                print(f"[game_events] listener for {event!r} raised: {e}")

    def off(self, event: str | None = None, callback: Callable | None = None) -> None:
        if callback is not None and event is not None:
            self._listeners.get(event, set()).discard(callback)
        elif event is not None:
            self._listeners.pop(event, None)
        else:
            self._listeners.clear()


# Singleton — shared across game and UI code, mirroring the JS default export.
game_events = EventBus()

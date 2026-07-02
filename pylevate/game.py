"""PyLevate game API for the **desktop** (CPython) — backed by real pygame.

In the browser this import is compiled away: the PyLevate compiler maps the
string ``pylevate.game`` to the Phaser runtime, so this file is never imported
during a browser build (and pygame is never needed there). It exists so the
*same* source file runs locally too:

    pip install pygame
    python main.py

It re-exports pygame, so ``import pylevate.game as pg`` is plain pygame on the
desktop — same names and (real int) constants your browser game already uses.

Supported = the pygame subset PyLevate compiles (init, display, draw, key, font,
image, time, event, mixer, sprite, Rect, Surface, K_*/QUIT). PyLevate-only bits
(arcade ``physics``) aren't part of desktop pygame — using them raises a clear
error.
"""
from __future__ import annotations

try:
    import pygame as _pg
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "PyLevate games need pygame to run on the desktop:\n"
        "    pip install pygame\n"
        "(In the browser, PyLevate compiles this import away — pygame isn't "
        "needed there.)"
    ) from exc

# Bring the whole pygame surface (functions, classes, and the real integer
# K_*/QUIT/KEYDOWN/... constants) into this namespace.
from pygame import *  # noqa: F401,F403

# Submodules and a couple of names that `import *` doesn't reliably re-export.
init = _pg.init
quit = _pg.quit
draw = _pg.draw
display = _pg.display
event = _pg.event
font = _pg.font
image = _pg.image
key = _pg.key
mixer = _pg.mixer
sprite = _pg.sprite
time = _pg.time
Rect = _pg.Rect
Surface = _pg.Surface

# PyLevate exposes Sprite at the top level (pygame only has pygame.sprite.Sprite).
Sprite = _pg.sprite.Sprite


class _UnsupportedOnDesktop:
    """Stand-in for PyLevate/Phaser-only APIs that have no pygame equivalent."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, attr: str):
        raise NotImplementedError(
            f"pylevate.game.{self._name} is a browser/Phaser-only feature with no "
            f"desktop pygame equivalent. Avoid it for code meant to run both places."
        )


# Phaser arcade physics — not part of pygame.
physics = _UnsupportedOnDesktop("physics")

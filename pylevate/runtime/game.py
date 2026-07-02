"""Type stubs for PyLevate game mode (pygame-compatible API).

For IDE autocomplete and type checking only — never shipped to browser.
Import as: import pylevate.game as pg
"""

from __future__ import annotations
from typing import Any

# Constants
QUIT = "quit"
KEYDOWN = "keydown"
KEYUP = "keyup"
K_LEFT = "LEFT"
K_RIGHT = "RIGHT"
K_UP = "UP"
K_DOWN = "DOWN"
K_SPACE = "SPACE"
K_RETURN = "ENTER"
K_ESCAPE = "ESC"


def init() -> None: ...


class display:
    @staticmethod
    def set_mode(size: tuple[int, int]) -> Any: ...
    @staticmethod
    def set_caption(title: str) -> None: ...
    @staticmethod
    def flip() -> None: ...


class time:
    @staticmethod
    def Clock() -> Any: ...


class event:
    @staticmethod
    def get() -> list: ...


class key:
    @staticmethod
    def get_pressed() -> dict: ...


class image:
    @staticmethod
    def load(path: str) -> Any: ...


class mixer:
    @staticmethod
    def Sound(path: str) -> Any: ...


class Sprite:
    image: Any
    rect: Any

    def update(self) -> None: ...
    def kill(self) -> None: ...


class sprite:
    Sprite = Sprite

    @staticmethod
    def Group() -> Any: ...
    @staticmethod
    def spritecollide(sprite: Any, group: Any, dokill: bool) -> list: ...
    @staticmethod
    def groupcollide(g1: Any, g2: Any, d1: bool, d2: bool) -> dict: ...


class draw:
    @staticmethod
    def rect(surface: Any, color: Any, rect: Any) -> None: ...
    @staticmethod
    def circle(surface: Any, color: Any, center: Any, radius: int) -> None: ...
    @staticmethod
    def line(surface: Any, color: Any, start: Any, end: Any, width: int = 1) -> None: ...


class font:
    @staticmethod
    def Font(name: str | None, size: int) -> Any: ...


class physics:
    @staticmethod
    def body(sprite: Any) -> Any: ...

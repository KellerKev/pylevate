"""Type stubs for PyLevate native bridge (Capacitor).

For IDE autocomplete and type checking only — never shipped to browser.
"""

from __future__ import annotations
from typing import Any


class Camera:
    @staticmethod
    async def get_photo(quality: int = 90, result_type: str = "uri") -> Any: ...


class Geolocation:
    @staticmethod
    async def get_current_position() -> Any: ...


class Haptics:
    @staticmethod
    async def impact(style: str = "medium") -> None: ...


class Storage:
    @staticmethod
    async def get(key: str) -> Any: ...
    @staticmethod
    async def set(key: str, value: Any) -> None: ...
    @staticmethod
    async def remove(key: str) -> None: ...


class Share:
    @staticmethod
    async def share(title: str = "", text: str = "", url: str = "") -> Any: ...


class PushNotifications:
    @staticmethod
    async def register() -> None: ...
    @staticmethod
    async def get_delivered_notifications() -> list: ...

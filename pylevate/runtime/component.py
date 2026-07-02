"""Type stubs for PyLevate app components.

These are for IDE autocomplete and type checking only — never shipped to browser.
"""

from __future__ import annotations
from typing import Any


class Tag:
    """Base for semantic custom tags (CSS framework class wrappers)."""
    tag_name: str = "div"
    ident_class: str = ""

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)

    def __call__(self, **attrs: Any) -> "Tag":
        return self


class _HProxy:
    """Proxy that generates tag builders: h.div(...), h.span(...), etc."""

    def __getattr__(self, tag_name: str) -> type:
        def factory(**attrs: Any) -> Any:
            return (tag_name, attrs)
        factory.__name__ = tag_name
        return factory

    class Template:
        """Meta-tag for control flow (For, If, Elif, Else, Is)."""
        def __init__(self, **kw: Any) -> None: ...


h = _HProxy()


class SlotsEnum:
    """Declare named slots on a component."""

    @classmethod
    def slot(cls) -> Any:
        return cls


class Slot:
    """Individual slot reference."""
    def __init__(self, name: str = "default") -> None:
        self.name = name

    def slot(self) -> Any:
        return self


class Component:
    """Base class for all PyLevate UI components."""

    props: dict[str, Any]
    template: dict[Any, Any]

    def __init__(self, **kw: Any) -> None: ...

    def on_mount(self) -> None:
        """Called after component mounts to DOM."""

    def on_unmount(self) -> None:
        """Called before component unmounts from DOM."""

    def on_update(self, prev_props: dict) -> None:
        """Called after component updates."""

    def get_context(self, props: dict) -> dict:
        """Pre-render hook to compute derived values."""
        return props

    @staticmethod
    def template_factory(cls: type) -> dict:
        """For recursive components — receives the class to self-reference."""
        return {}


def state(initial: Any = None) -> Any:
    """Declare a reactive state field. Compiles to signal()."""
    return initial


def css(source: str) -> Any:
    """Declare scoped CSS. Extracted and processed at compile time."""
    return {}


def prop(default: Any = None) -> Any:
    """Declare a component prop with a default value."""
    return default


def mount(component: type, selector: str) -> None:
    """Mount a component to a DOM element."""


def computed(fn: Any) -> Any:
    """Decorator: computed value derived from signals."""
    return fn


def action(fn: Any) -> Any:
    """Decorator: action that mutates store state."""
    return fn


def effect(fn: Any) -> Any:
    """Decorator: side effect that runs when dependencies change."""
    return fn


class Store:
    """Base class for cross-component state stores."""


class App:
    """Application entry point with optional router."""

    def __init__(self, router: Any = None, theme: str = "") -> None: ...

    def mount(self, selector: str) -> None: ...


class Router:
    """Client-side router."""

    def __init__(self, routes: list[tuple[str, type]]) -> None: ...


def page(title: str = "", route: str = "") -> Any:
    """Decorator: mark a component as a routable page."""
    def decorator(cls: type) -> type:
        return cls
    return decorator

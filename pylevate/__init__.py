"""PyLevate — Python-syntax full-stack framework compiling to Preact + Phaser."""

__version__ = "0.1.0"

from pylevate.config import Config

# IDE/typecheck stubs for the app-mode API. These never execute in the
# browser — the compiler rewrites `from pylevate import ...` to the JS
# runtime package. Re-exporting them here makes user projects resolve in
# editors and type checkers.
from pylevate.runtime.component import (
    App,
    Component,
    Router,
    Slot,
    SlotsEnum,
    Store,
    Tag,
    action,
    computed,
    css,
    effect,
    h,
    mount,
    page,
    prop,
    state,
)

__all__ = [
    "Config",
    "App",
    "Component",
    "Router",
    "Slot",
    "SlotsEnum",
    "Store",
    "Tag",
    "action",
    "computed",
    "css",
    "effect",
    "h",
    "mount",
    "page",
    "prop",
    "state",
]

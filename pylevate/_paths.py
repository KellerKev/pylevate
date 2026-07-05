"""Locate the framework's bundled JS runtime assets.

The ``js/`` directory (baselib + the ``pylevate-*-runtime.js`` bundles, the HMR
client, …) must be found in two layouts:

* **Installed wheel** — ``js/`` is force-included into the package, so it lives at
  ``<site-packages>/pylevate/js`` (a child of this package).
* **Editable / source checkout** — ``js/`` sits at the repo root, a *sibling* of
  the ``pylevate`` package (``<repo>/js``).

``framework_js_dir()`` returns whichever exists, preferring the packaged copy.
"""
from __future__ import annotations

from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent


def framework_js_dir() -> Path:
    """Return the directory holding the framework's runtime ``.js`` assets."""
    packaged = _PKG_DIR / "js"
    if packaged.is_dir():
        return packaged
    return _PKG_DIR.parent / "js"

"""CSS scoping — hash-suffix class names per file path."""

import hashlib
import re
from pathlib import Path


def scope(css_source: str, file_path: Path) -> tuple[str, dict[str, str]]:
    """Scope CSS class names with a SHA1-based suffix derived from file path.

    Returns (scoped_css, class_map) where class_map maps original → scoped names.
    """
    suffix = hashlib.sha1(str(file_path).encode()).hexdigest()[:6]
    class_map: dict[str, str] = {}

    def replace_class(match: re.Match) -> str:
        original = match.group(1)
        scoped = f"{original}-{suffix}"
        class_map[original] = scoped
        return f".{scoped}"

    # Match CSS class selectors (start with letter or hyphen, not digits)
    # Avoid matching decimal values like 0.5rem or color values like #fff
    scoped_css = re.sub(r"\.([a-zA-Z_][\w-]*)", replace_class, css_source)
    return scoped_css, class_map


def apply_class_map(js_source: str, class_map: dict[str, str]) -> str:
    """Replace class name references in JS source using the class map.

    Only replaces in className attribute contexts and styles.xxx references.

    Two passes, in this order, each touching a name exactly once:
      1. Quoted ``className: '...'`` values: every whitespace-separated token that is a
         known class is swapped whole. Matching whole tokens (not word boundaries) keeps
         ``lnk`` from rewriting the ``lnk`` inside ``lnk-hide``.
      2. ``styles.xxx`` references. Running this after pass 1 means a className
         expression that starts with ``styles.x`` is not scoped a second time
         (``"x-abc123"`` would otherwise match pass 1 and become ``x-abc123-abc123``).
    """
    if not class_map:
        return js_source

    def replace_in_classname(m: re.Match) -> str:
        prefix, value, quote = m.group(1), m.group(3), m.group(4)
        value = re.sub(r"\S+", lambda t: class_map.get(t.group(0), t.group(0)), value)
        return f"{prefix}{value}{quote}"

    result = re.sub(r"""(className:\s*(['"]))((?:(?!\2).)+?)(\2)""", replace_in_classname, js_source)

    def replace_ref(m: re.Match) -> str:
        scoped = class_map.get(m.group(1))
        return f'"{scoped}"' if scoped is not None else m.group(0)

    # an identifier after ``styles.`` — the whole identifier, so styles.btn never
    # rewrites the front of styles.btnGroup
    return re.sub(r"\bstyles\.([A-Za-z_$][\w$]*)", replace_ref, result)


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
    """
    result = js_source
    for original, scoped in class_map.items():
        # Replace styles.xxx references
        result = result.replace(f"styles.{original}", f'"{scoped}"')

    # Replace class names inside className: '...' attribute values.
    # Matches className: 'value' and replaces known class names within the value.
    def replace_in_classname(m: re.Match) -> str:
        prefix = m.group(1)  # "className: '"
        value = m.group(2)   # the class name(s)
        quote = m.group(3)   # closing quote
        # Replace each known class name in the value (handles space-separated lists)
        for original, scoped in class_map.items():
            value = re.sub(rf"\b{re.escape(original)}\b", scoped, value)
        return f"{prefix}{value}{quote}"

    result = re.sub(
        r"""(className:\s*['"])([^'"]+)(['"])""",
        replace_in_classname,
        result,
    )
    return result

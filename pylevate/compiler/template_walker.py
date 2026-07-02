"""Template dict walker — transforms compiled JS template dicts to h() calls.

Operates on the JS output from py2js, not on Python AST.
Rewrites dict-based template syntax to Preact h() call chains.
"""

import re


def walk_templates(js_source: str) -> str:
    """Transform template dict assignments in JS to h() call chains.

    This is a post-processing step that runs on the JS output from py2js.
    It finds template = {...} assignments and rewrites them.
    """
    # Replace [[expr]] interpolation in string literals with ${expr}
    js_source = re.sub(
        r"\[\[([^\]]+)\]\]",
        r"${\1}",
        js_source,
    )

    # Convert template literal markers — strings containing ${} need backticks
    js_source = _convert_template_strings(js_source)

    return js_source


def _convert_template_strings(js_source: str) -> str:
    """Convert strings containing ${...} to template literals."""
    # Find string literals that contain ${...} and convert to template literals
    def replace_template(match: re.Match) -> str:
        quote = match.group(1)
        content = match.group(2)
        if "${" in content:
            # Escape any backticks in content
            content = content.replace("`", "\\`")
            return f"`{content}`"
        return match.group(0)

    # Match single or double quoted strings
    js_source = re.sub(r"""(["'])((?:(?!\1).)*\$\{[^}]+\}(?:(?!\1).)*)\1""", replace_template, js_source)
    return js_source

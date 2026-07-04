"""Type stubs for PyLevate chat components (pylevate.chat).

These are for IDE autocomplete and type checking only — never shipped to the
browser. The compiler rewrites `from pylevate.chat import ...` to the JS
runtime package 'pylevate-chat-runtime' (js/pylevate-chat-runtime.js).

Message shape used throughout (plain JSON dicts, Store-persistable):
    {'id': str, 'role': 'user'|'assistant'|'tool', 'content': str,
     'tool_calls': list | None, 'tool_call_id': str | None}
"""

from __future__ import annotations

from typing import Any

from pylevate.runtime.component import Component, SlotsEnum


class ChatWindow(Component):
    """Flex-column chat layout shell.

    Slots:
        header: settings bar / title area (ChatWindow.S.header())
        footer: pinned footer area (ChatWindow.S.footer())
    Children become the scrolling body.
    """

    class S(SlotsEnum):
        header = ()
        footer = ()


class MessageList(Component):
    """Scrollable transcript with smart autoscroll.

    Props:
        messages:       list of message dicts
        streaming_text: partial assistant text while a reply streams (or None)
        streaming:      True while a request is in flight
        markdown:       render assistant content as markdown (default True)
        empty_text:     placeholder shown when there are no messages
    """

    def __init__(self, messages: list | None = None, streaming_text: str | None = None,
                 streaming: bool = False, markdown: bool = True,
                 empty_text: str = "", **kw: Any) -> None: ...


class MessageBubble(Component):
    """One chat message bubble.

    Props: role ('user'|'assistant'), content, streaming (blinking caret),
    markdown (assistant content rendered as markdown when True).
    """

    def __init__(self, role: str = "assistant", content: str = "",
                 streaming: bool = False, markdown: bool = True, **kw: Any) -> None: ...


class ChatInput(Component):
    """Auto-growing textarea; Enter sends, Shift+Enter inserts a newline.

    Props:
        on_send:     callback receiving the trimmed text. Pass a bound method
                     via the template ({'self.send'}) or a lambda.
        disabled:    disable while a reply streams
        placeholder: input placeholder text
    """

    def __init__(self, on_send: Any = None, disabled: bool = False,
                 placeholder: str = "", **kw: Any) -> None: ...


class TypingIndicator(Component):
    """Three-dot typing pulse."""


class ToolCallCard(Component):
    """Collapsible display of one tool invocation.

    Props: name, args (dict or JSON string), result (str|None),
    status ('running'|'done'|'error'), open (expanded by default).
    """

    def __init__(self, name: str = "", args: Any = None, result: str | None = None,
                 status: str = "done", open: bool = False, **kw: Any) -> None: ...


class Markdown(Component):
    """Renders markdown source as sanitized HTML (escape-first, safe links)."""

    def __init__(self, source: str = "", **kw: Any) -> None: ...

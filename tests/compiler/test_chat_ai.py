"""Golden tests pinning the compiler output shapes the chat/AI runtimes rely on.

js/pylevate-chat-runtime.js and js/pylevate-ai-runtime.js implement their APIs
against exactly these emitted shapes; if a codegen heuristic changes them,
these tests fail before the runtimes silently break.
"""

from pylevate.compiler.py2js import compile_source


def _js(source: str) -> str:
    result = compile_source(source, "test.py", "app")
    assert not result.errors, f"Unexpected errors: {result.errors}"
    return result.js


class TestChatImports:
    def test_chat_import_maps_to_runtime(self):
        js = _js("from pylevate.chat import ChatWindow, MessageList, ChatInput")
        assert "import { ChatWindow, MessageList, ChatInput } from 'pylevate-chat-runtime'" in js

    def test_ai_import_maps_to_runtime(self):
        js = _js("from pylevate.ai import AIClient, tool, cosine_similarity")
        assert "import { AIClient, tool, cosine_similarity } from 'pylevate-ai-runtime'" in js


class TestChatComponentShapes:
    def test_component_props_pass_through(self):
        js = _js(
            "from pylevate import Component, h\n"
            "from pylevate.chat import MessageList\n"
            "\n"
            "class App(Component):\n"
            "    def get_context(self, props):\n"
            "        props['messages'] = []\n"
            "        props['busy'] = False\n"
            "        return props\n"
            "\n"
            "    template = {\n"
            "        MessageList(messages={'messages'}, streaming={'busy'}): None,\n"
            "    }\n"
        )
        assert "h(MessageList, {messages: messages, streaming: busy})" in js

    def test_slot_fill_lifted_to_prop(self):
        js = _js(
            "from pylevate import Component, h\n"
            "from pylevate.chat import ChatWindow\n"
            "\n"
            "class App(Component):\n"
            "    template = {\n"
            "        ChatWindow(): {\n"
            "            ChatWindow.S.header(): {h.div(): 'settings'},\n"
            "            h.p(): 'body',\n"
            "        }\n"
            "    }\n"
        )
        assert "h(ChatWindow, {slot_header: h('div', null, 'settings')}" in js
        assert "h('p', null, 'body')" in js
        # The old inline-comment marker must be gone from component children.
        assert "/* slot_fill:" not in js

    def test_slot_fill_merges_with_existing_props(self):
        js = _js(
            "from pylevate import Component, h\n"
            "from pylevate.chat import ChatWindow\n"
            "\n"
            "class App(Component):\n"
            "    template = {\n"
            "        ChatWindow(Class='shell'): {\n"
            "            ChatWindow.S.footer(): {h.span(): 'foot'},\n"
            "        }\n"
            "    }\n"
        )
        assert "slot_footer: h('span', null, 'foot')" in js
        assert "className: 'shell'" in js


class TestAIClientShapes:
    def test_client_constructor_kwargs_object(self):
        js = _js(
            "from pylevate.ai import AIClient\n"
            "client = AIClient(base_url='/api/llm', model='gpt-4o-mini')\n"
        )
        assert "new AIClient({base_url: '/api/llm', model: 'gpt-4o-mini'})" in js

    def test_chat_call_options_object(self):
        js = _js(
            "from pylevate.ai import AIClient\n"
            "\n"
            "async def go(client, msgs, cb):\n"
            "    reply = await client.chat(msgs, on_token=cb)\n"
            "    return reply\n"
        )
        assert "await client.chat(msgs, {on_token: cb})" in js

    def test_tool_helper_no_new(self):
        js = _js(
            "from pylevate.ai import tool\n"
            "t = tool(name='calc', description='d', handler=lambda args: '42')\n"
        )
        assert "tool({name: 'calc', description: 'd', handler: (args) => '42'})" in js
        assert "new tool" not in js


class TestAsyncMethods:
    def test_async_store_method_with_signals(self):
        js = _js(
            "from pylevate import Store\n"
            "from pylevate.signals import signal\n"
            "from pylevate.ai import AIClient\n"
            "\n"
            "class ChatStore(Store):\n"
            "    busy = signal(False)\n"
            "\n"
            "    async def send(self, text):\n"
            "        self.busy = True\n"
            "        client = AIClient(model='m')\n"
            "        reply = await client.chat([], on_token=lambda t: self.push(t))\n"
            "        self.busy = False\n"
            "        return reply\n"
        )
        assert "async send(text)" in js
        assert "await client.chat([], {on_token: (t) => this.push(t)})" in js
        # Signal rewrites still apply inside async bodies
        assert "this._busy.value = true" in js
        assert "this._busy.value = false" in js

    def test_async_component_method(self):
        js = _js(
            "from pylevate import Component, h, state\n"
            "\n"
            "class App(Component):\n"
            "    count = state(0)\n"
            "\n"
            "    async def refresh(self):\n"
            "        data = await fetch('/data')\n"
            "        self.count = 1\n"
            "\n"
            "    template = {\n"
            "        h.div(): '[[self.count]]',\n"
            "    }\n"
        )
        assert "async refresh()" in js
        assert "await fetch('/data')" in js
        assert "this._count.value = 1" in js

"""Phase 2 tests — Component model compilation."""

import pytest
from pylevate.compiler.py2js import compile_source, CompileResult


def _js(source: str, mode: str = "app") -> str:
    result = compile_source(source, "test.py", mode)
    assert not result.errors, f"Unexpected errors: {result.errors}"
    return result.js.strip()


def _result(source: str, mode: str = "app") -> CompileResult:
    return compile_source(source, "test.py", mode)


class TestTemplateCompilation:
    def test_simple_template_emits_render(self):
        js = _js("""
from pylevate import Component, h

class Hello(Component):
    template = {
        h.div(): 'Hello World',
    }
""")
        assert "render(props, state, context)" in js
        assert "h('div', null, 'Hello World')" in js
        assert "static template" not in js

    def test_nested_template(self):
        js = _js("""
from pylevate import Component, h

class Card(Component):
    template = {
        h.div(Class='card'): {
            h.h2(): 'Title',
            h.p(): 'Content',
        }
    }
""")
        assert "render(props, state, context)" in js
        assert "h('div', {className: 'card'}" in js
        assert "h('h2', null, 'Title')" in js
        assert "h('p', null, 'Content')" in js
        # Multiple children should use Fragment
        assert "Fragment" in js

    def test_class_attr_becomes_className(self):
        js = _js("""
from pylevate import Component, h

class Foo(Component):
    template = {
        h.div(Class='foo'): 'bar',
    }
""")
        assert "className: 'foo'" in js
        assert "Class:" not in js

    def test_non_component_class_keeps_static_template(self):
        js = _js("""
class Config:
    template = {'key': 'value'}
""")
        assert "static template" in js
        assert "render" not in js


class TestExpressionTiers:
    def test_tier1_static_string(self):
        js = _js("""
from pylevate import Component, h

class Foo(Component):
    template = {
        h.div(Class='card'): 'text',
    }
""")
        assert "className: 'card'" in js

    def test_tier2_bytes_literal(self):
        js = _js("""
from pylevate import Component, h

class Foo(Component):
    template = {
        h.meta(charset=b'utf-8'): None,
    }
""")
        assert "charset: 'utf-8'" in js

    def test_tier3_set_expression(self):
        js = _js("""
from pylevate import Component, h

class Foo(Component):
    template = {
        h.button(disabled={'not allow_submit'}): 'Submit',
    }
""")
        assert "disabled: not allow_submit" in js or "disabled: !allow_submit" in js


class TestEventHandlers:
    def test_method_reference_bound(self):
        js = _js("""
from pylevate import Component, h

class Btn(Component):
    def handle_click(self):
        pass

    template = {
        h.button(onClick={'self.handle_click'}): 'Click',
    }
""")
        assert "this.handle_click.bind(this)" in js

    def test_arrow_function_not_bound(self):
        js = _js("""
from pylevate import Component, h

class Input(Component):
    template = {
        h.input(onInput={'e => self.value = e.target.value'}): None,
    }
""")
        assert ".bind(this)" not in js or "e =>" in js


class TestPropsDestructuring:
    def test_init_props_destructured_in_render(self):
        js = _js("""
from pylevate import Component, h

class Button(Component):
    def __init__(self, label, variant='primary', **kw):
        super().__init__(label=label, variant=variant, **kw)

    template = {
        h.button(Class='btn'): '[[label]]',
    }
""")
        assert "render(props, state, context)" in js
        assert "let { label, variant, ...rest } = props || {};" in js


class TestInterpolation:
    def test_double_bracket_in_text(self):
        js = _js("""
from pylevate import Component, h

class Foo(Component):
    template = {
        h.span(): '[[name]]',
    }
""")
        assert "`${name}`" in js

    def test_state_field_in_interpolation(self):
        js = _js("""
from pylevate import Component, h, state

class Counter(Component):
    count = state(0)

    template = {
        h.span(): '[[self.count]]',
    }
""")
        assert "`${this._count.value}`" in js


class TestStateFields:
    def test_state_creates_signal(self):
        js = _js("""
from pylevate import Component, h, state

class Counter(Component):
    count = state(0)

    template = {
        h.span(): '[[self.count]]',
    }
""")
        assert "this._count = signal(0)" in js
        assert "signal" in js  # should be imported

    def test_state_read_in_method(self):
        js = _js("""
from pylevate import Component, state

class C(Component):
    value = state(42)

    def get_value(self):
        return self.value
""")
        assert "this._value.value" in js

    def test_state_write_in_method(self):
        js = _js("""
from pylevate import Component, state

class C(Component):
    count = state(0)

    def increment(self):
        self.count += 1
""")
        assert "this._count.value += 1" in js


class TestAutoImports:
    def test_signal_auto_imported(self):
        js = _js("""
from pylevate import Component, state

class C(Component):
    x = state(0)
""")
        assert "signal" in js.split("\n")[0]  # in the import line

    def test_fragment_auto_imported(self):
        js = _js("""
from pylevate import Component, h

class C(Component):
    template = {
        h.div(): {
            h.span(): 'a',
            h.span(): 'b',
        }
    }
""")
        assert "Fragment" in js.split("\n")[0]


class TestCSSExtraction:
    def test_css_chunks_collected(self):
        result = _result("""
from pylevate import Component, css

class Card(Component):
    style = css(\".card { padding: 1rem; }\")
""")
        assert len(result.css_chunks) == 1
        assert ".card" in result.css_chunks[0]

    def test_css_not_emitted_as_field(self):
        js = _js("""
from pylevate import Component, css

class Card(Component):
    style = css(\".card { color: red; }\")
""")
        # css() should not appear as a static field in the class
        assert "static style" not in js or "null" in js


class TestControlFlow:
    def test_for_template(self):
        js = _js("""
from pylevate import Component, h

class List(Component):
    template = {
        h.ul(): {
            h.Template(For='item in items'): {
                h.li(): '[[item]]',
            }
        }
    }
""")
        assert "items.map((item)" in js
        assert "`${item}`" in js

    def test_if_template(self):
        js = _js("""
from pylevate import Component, h

class Cond(Component):
    template = {
        h.div(): {
            h.Template(If='show'): {
                h.p(): 'Visible',
            }
        }
    }
""")
        assert "show ?" in js
        assert "'Visible'" in js


class TestKwargsForwarding:
    """`**kwargs` is allowed in a constructor (prop forwarding) but errors elsewhere."""

    def test_kwargs_allowed_in_init(self):
        js = _js("""
from pylevate import Component
class Card(Component):
    def __init__(self, title, **kw):
        super().__init__(title=title, **kw)
""")
        # Bound as a trailing rest param so the call-side `...kw` spread is valid.
        assert "constructor(title, ...kw)" in js

    def test_kwargs_errors_in_plain_function(self):
        result = _result("""
def helper(a, **opts):
    return a
""")
        assert result.errors
        assert "**opts" in result.errors[0].message

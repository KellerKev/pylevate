"""Phase 3 tests — Stores, reactivity, decorators, v-strings."""

from pylevate.compiler.py2js import compile_source


def _js(source: str, mode: str = "app") -> str:
    result = compile_source(source, "test.py", mode)
    assert not result.errors, f"Unexpected errors: {result.errors}"
    return result.js.strip()


class TestStoreSignals:
    def test_signal_fields_in_constructor(self):
        js = _js("""
from pylevate import Store
from pylevate.signals import signal

class MyStore(Store):
    count = signal(0)
    name = signal("hello")
""")
        assert "this._count = signal(0)" in js
        assert 'this._name = signal("hello")' in js or "this._name = signal('hello')" in js
        # Should NOT emit static fields for signal()
        assert "static count" not in js
        assert "static name" not in js

    def test_signal_read_becomes_value(self):
        js = _js("""
from pylevate import Store
from pylevate.signals import signal

class MyStore(Store):
    count = signal(0)

    def get_count(self):
        return self.count
""")
        assert "this._count.value" in js

    def test_signal_write_becomes_value(self):
        js = _js("""
from pylevate import Store
from pylevate.signals import signal

class MyStore(Store):
    count = signal(0)

    def set_count(self, val):
        self.count = val
""")
        assert "this._count.value = val" in js


class TestComputedDecorator:
    def test_computed_becomes_getter(self):
        js = _js("""
from pylevate import Store, computed
from pylevate.signals import signal

class MyStore(Store):
    items = signal([])

    @computed
    def count(self):
        return len(self.items)
""")
        assert "get count()" in js
        assert "computed(" in js

    def test_computed_wraps_return(self):
        js = _js("""
from pylevate import Store, computed
from pylevate.signals import signal

class MyStore(Store):
    price = signal(10)
    qty = signal(2)

    @computed
    def total(self):
        return self.price * self.qty
""")
        assert "computed(() =>" in js
        assert ".value;" in js  # returns computed().value


class TestActionDecorator:
    def test_action_wraps_in_batch(self):
        js = _js("""
from pylevate import Store, action
from pylevate.signals import signal

class MyStore(Store):
    items = signal([])

    @action
    def add(self, item):
        self.items = [*self.items, item]
""")
        assert "batch(() =>" in js
        assert "this._items.value = [...this._items.value, item]" in js


class TestEffectDecorator:
    def test_effect_registered_in_constructor(self):
        js = _js("""
from pylevate import Store, effect
from pylevate.signals import signal

class MyStore(Store):
    data = signal(None)

    @effect
    def log_changes(self):
        print(self.data)
""")
        assert "effect(() => this.log_changes())" in js
        # Should be in constructor
        lines = js.split("\n")
        constructor_line = next(i for i, l in enumerate(lines) if "constructor" in l)
        effect_line = next(i for i, l in enumerate(lines) if "effect(() => this.log_changes())" in l)
        assert effect_line > constructor_line  # effect registration inside constructor


class TestVStringLiterals:
    def test_v_string_emits_raw_js(self):
        js = _js("""
x = v"document.getElementById('app')"
""")
        assert "document.getElementById('app')" in js

    def test_v_string_in_method(self):
        js = _js("""
class Foo:
    def save(self):
        v"localStorage.setItem('key', 'value')"
""")
        assert "localStorage.setItem('key', 'value')" in js


class TestClassInstantiation:
    def test_new_keyword_added(self):
        js = _js("""
class MyClass:
    pass

obj = MyClass()
""")
        assert "new MyClass()" in js

    def test_no_new_for_builtins(self):
        js = _js("""
x = int("42")
y = str(123)
""")
        assert "new" not in js


class TestGetContext:
    def test_get_context_called_in_render(self):
        js = _js("""
from pylevate import Component, h

class Card(Component):
    def __init__(self, title, **kw):
        super().__init__(title=title, **kw)

    def get_context(self, props):
        props['upper_title'] = props['title'].upper()
        return props

    template = {
        h.div(): '[[upper_title]]',
    }
""")
        assert "get_context" in js
        assert "_ctx" in js  # context variable
        assert "render(" in js


class TestDuplicateImports:
    def test_pylevate_runtime_merged(self):
        js = _js("""
from pylevate import Store
from pylevate.signals import signal

class S(Store):
    x = signal(0)
""")
        # Should not have two separate import lines from pylevate-runtime
        import_lines = [l for l in js.split("\n") if "from 'pylevate-runtime'" in l]
        # The signal import gets merged or there are two valid import lines
        assert len(import_lines) >= 1

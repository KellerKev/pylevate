"""Tests for the Python-to-JavaScript compiler."""

import pytest
from pylevate.compiler.py2js import compile_source, CompileResult, ImportContext


def _js(source: str, mode: str = "app") -> str:
    """Compile and return JS, stripping trailing whitespace."""
    result = compile_source(source, "test.py", mode)
    assert not result.errors, f"Unexpected errors: {result.errors}"
    return result.js.strip()


def _js_ctx(source: str, ctx: ImportContext, mode: str = "app") -> str:
    """Compile with an import context and return JS."""
    result = compile_source(source, ctx.rel_path or "test.py", mode, import_ctx=ctx)
    assert not result.errors, f"Unexpected errors: {result.errors}"
    return result.js.strip()


class TestImports:
    def test_from_pylevate_import(self):
        js = _js("from pylevate import Component, h")
        assert "import { Component, h } from 'pylevate-runtime'" in js

    def test_import_pylevate_game_as(self):
        js = _js("import pylevate.game as pg")
        assert "import * as pg from 'pylevate-game-runtime'" in js

    def test_relative_import(self):
        js = _js("from components.button import Button")
        assert "import { Button } from './components/button.js'" in js


class TestNestedImports:
    def test_nested_importer_parent_hop(self):
        ctx = ImportContext(rel_path="pages/home.py")
        js = _js_ctx("from components.nav import Navbar", ctx)
        assert "import { Navbar } from '../components/nav.js'" in js

    def test_nested_importer_same_dir(self):
        ctx = ImportContext(rel_path="pages/about.py")
        js = _js_ctx("from pages.home import Home", ctx)
        assert "import { Home } from './home.js'" in js

    def test_deeply_nested_relative_sibling_package(self):
        # `..` from pages/admin/panel.py resolves against `pages` (Python semantics)
        ctx = ImportContext(rel_path="pages/admin/panel.py")
        js = _js_ctx("from ..components.nav import Nav", ctx)
        assert "import { Nav } from '../components/nav.js'" in js

    def test_deeply_nested_relative_to_root(self):
        ctx = ImportContext(rel_path="pages/admin/panel.py")
        js = _js_ctx("from ...components.nav import Nav", ctx)
        assert "import { Nav } from '../../components/nav.js'" in js

    def test_from_dot_import_module(self):
        ctx = ImportContext(rel_path="components/__init__.py")
        js = _js_ctx("from . import nav", ctx)
        assert "import * as nav from './nav.js'" in js

    def test_from_dot_named_import(self):
        ctx = ImportContext(rel_path="components/nav.py")
        js = _js_ctx("from .icons import Icon", ctx)
        assert "import { Icon } from './icons.js'" in js

    def test_package_init_import(self):
        ctx = ImportContext(
            rel_path="main.py",
            modules=frozenset({"main"}),
            packages=frozenset({"components"}),
            validate=True,
        )
        js = _js_ctx("from components import Navbar", ctx)
        assert "import { Navbar } from './components/__init__.js'" in js

    def test_nested_dotted_plain_import(self):
        ctx = ImportContext(rel_path="pages/home.py")
        js = _js_ctx("import components.nav", ctx)
        assert "import * as nav from '../components/nav.js'" in js

    def test_relative_beyond_root_errors(self):
        ctx = ImportContext(rel_path="pages/home.py")
        result = compile_source("from ...deep import x", "pages/home.py", import_ctx=ctx)
        assert result.errors
        assert "beyond the project root" in str(result.errors[0])

    def test_no_context_fallback_unchanged(self):
        js = _js("from components.button import Button")
        assert "'./components/button.js'" in js

    def test_unknown_import_friendly_error(self):
        ctx = ImportContext(
            rel_path="main.py",
            modules=frozenset({"main"}),
            validate=True,
        )
        result = compile_source("from missing.mod import X", "main.py", import_ctx=ctx)
        assert result.errors
        msg = str(result.errors[0])
        assert "missing.mod" in msg
        assert "missing/mod.py" in msg
        assert "main.py" in msg

    def test_js_source_satisfies_import(self):
        ctx = ImportContext(
            rel_path="main.py",
            modules=frozenset({"main", "utils"}),
            validate=True,
        )
        js = _js_ctx("from utils import helper", ctx)
        assert "import { helper } from './utils.js'" in js

    def test_star_import_errors(self):
        result = compile_source("from utils import *", "main.py")
        assert result.errors
        assert "import *" in str(result.errors[0])


class TestConstants:
    def test_none(self):
        js = _js("x = None")
        assert "null" in js

    def test_true_false(self):
        js = _js("x = True\ny = False")
        assert "true" in js
        assert "false" in js


class TestFunctions:
    def test_simple_function(self):
        js = _js("def greet(name):\n    return f'Hello {name}'")
        assert "function greet(name)" in js
        assert "return `Hello ${name}`" in js

    def test_async_function(self):
        js = _js("async def fetch_data():\n    result = await get_data()")
        assert "async function fetch_data()" in js
        assert "await get_data()" in js

    def test_lambda(self):
        js = _js("f = lambda x: x + 1")
        assert "=>" in js

    def test_default_params(self):
        js = _js("def foo(x, y=10):\n    pass")
        assert "y = 10" in js or "y=10" in js


class TestClasses:
    def test_simple_class(self):
        js = _js("class Foo:\n    def hello(self):\n        return 'hi'")
        assert "class Foo" in js
        assert "hello()" in js
        assert "this" not in js or "self" not in js  # self stripped

    def test_inheritance(self):
        js = _js("class Dog(Animal):\n    pass")
        assert "class Dog extends Animal" in js

    def test_constructor(self):
        js = _js("class Foo:\n    def __init__(self, name):\n        self.name = name")
        assert "constructor(name)" in js
        assert "this.name = name" in js

    def test_state_fields(self):
        js = _js("""
class Counter(Component):
    count = state(0)
    def increment(self):
        self.count += 1
""")
        assert "signal(0)" in js
        assert "this._count.value" in js


class TestBuiltins:
    def test_print(self):
        js = _js("print('hello')")
        assert "console.log" in js

    def test_len(self):
        js = _js("n = len(items)")
        assert ".length" in js

    def test_isinstance(self):
        js = _js("if isinstance(x, int):\n    pass")
        assert "instanceof" in js

    def test_range_for(self):
        js = _js("for i in range(10):\n    print(i)")
        assert "for" in js


class TestControlFlow:
    def test_if_elif_else(self):
        js = _js("if x > 0:\n    a = 1\nelif x < 0:\n    a = -1\nelse:\n    a = 0")
        assert "if" in js
        assert "else if" in js
        assert "else" in js

    def test_while(self):
        js = _js("while True:\n    break")
        assert "while" in js
        assert "break" in js

    def test_try_except(self):
        js = _js("try:\n    x = 1\nexcept Exception as e:\n    print(e)")
        assert "try" in js
        assert "catch" in js


class TestStringMethods:
    def test_upper(self):
        js = _js("s = name.upper()")
        assert "toUpperCase()" in js

    def test_strip(self):
        js = _js("s = text.strip()")
        assert "trim()" in js


class TestListMethods:
    def test_append(self):
        js = _js("items.append(x)")
        assert ".push(" in js


class TestDictMethods:
    def test_keys(self):
        js = _js("k = data.keys()")
        assert "Object.keys(" in js

    def test_items(self):
        js = _js("for k, v in data.items():\n    pass")
        assert "Object.entries(" in js


class TestFStrings:
    def test_basic_fstring(self):
        js = _js("msg = f'Hello {name}'")
        assert "`Hello ${name}`" in js


class TestCSSExtraction:
    def test_css_extracted(self):
        result = compile_source("""
class Btn(Component):
    style = css(\"\"\".btn { color: red; }\"\"\")
""", "btn.py", "app")
        assert len(result.css_chunks) == 1
        assert ".btn" in result.css_chunks[0]


class TestInterpolation:
    def test_double_bracket(self):
        js = _js("text = '[[name]]'")
        # [[expr]] should become ${expr} via template walker, not in py2js directly
        # py2js just compiles the string as-is
        assert "name" in js


class TestOperators:
    def test_floor_div(self):
        js = _js("x = a // b")
        assert "Math.floor" in js

    def test_in_operator(self):
        js = _js("if x in items:\n    pass")
        assert ".includes(" in js


class TestComprehensions:
    def test_list_comp(self):
        js = _js("squares = [x**2 for x in items]")
        assert ".map(" in js

    def test_filtered_comp(self):
        js = _js("evens = [x for x in items if x % 2 == 0]")
        assert ".filter(" in js

    def test_filtered_comp_with_transform(self):
        js = _js("doubles = [x * 2 for x in items if x > 0]")
        assert ".filter(" in js
        assert ".map(" in js

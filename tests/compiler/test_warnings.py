"""Tests for compile-time warnings (kwargs on native JS APIs)."""

from pylevate.compiler.py2js import compile_source


def _compile(source: str, mode: str = "app"):
    result = compile_source(source, "test.py", mode)
    assert not result.errors, f"Unexpected errors: {result.errors}"
    return result


class TestNativeKwargsWarning:
    def test_kwargs_on_native_global_attribute_warns(self):
        result = _compile("document.createElement('div', is_='x-btn')")
        assert len(result.warnings) == 1
        assert "document" in result.warnings[0].message
        # JS is still emitted with the object convention
        assert "document.createElement('div', {is_: 'x-btn'})" in result.js

    def test_kwargs_on_bare_native_fn_warns(self):
        result = _compile("fetch('/api', method='POST')")
        assert len(result.warnings) == 1
        assert "fetch" in result.warnings[0].message

    def test_kwargs_on_component_no_warning(self):
        result = _compile(
            "class MyComponent:\n"
            "    pass\n"
            "\n"
            "c = MyComponent(title='x')\n"
        )
        assert result.warnings == []

    def test_kwargs_on_user_function_no_warning(self):
        result = _compile("def foo(a, b=1):\n    pass\n\nfoo(1, b=2)")
        assert result.warnings == []

    def test_print_kwargs_no_warning(self):
        # `print` maps to console.log, but the user wrote Python — don't warn.
        result = _compile("print('a', 'b')")
        assert result.warnings == []

    def test_positional_native_call_no_warning(self):
        result = _compile("x = document.getElementById('app')")
        assert result.warnings == []

    def test_warning_has_location(self):
        result = _compile("x = 1\nfetch('/api', method='GET')")
        assert result.warnings[0].file == "test.py"
        assert result.warnings[0].line == 2

"""Tests for CSS scoping."""

from pathlib import Path
from pylevate.compiler.css_scoper import scope, apply_class_map


class TestScope:
    def test_basic_scoping(self):
        css = ".btn { color: red; }"
        scoped, class_map = scope(css, Path("components/button.py"))
        assert "btn" in class_map
        assert class_map["btn"].startswith("btn-")
        assert len(class_map["btn"]) == len("btn-") + 6

    def test_deterministic(self):
        css = ".card { padding: 1rem; }"
        _, map1 = scope(css, Path("card.py"))
        _, map2 = scope(css, Path("card.py"))
        assert map1 == map2

    def test_different_files_different_suffixes(self):
        css = ".btn { color: red; }"
        _, map1 = scope(css, Path("button.py"))
        _, map2 = scope(css, Path("card.py"))
        assert map1["btn"] != map2["btn"]

    def test_multiple_classes(self):
        css = ".card { border: 1px; } .card-header { font-weight: bold; }"
        scoped, class_map = scope(css, Path("card.py"))
        assert "card" in class_map
        assert "card-header" in class_map

    def test_scoped_css_contains_suffix(self):
        css = ".btn { color: red; }"
        scoped, class_map = scope(css, Path("x.py"))
        suffix = class_map["btn"].split("-")[-1]
        assert f".btn-{suffix}" in scoped


class TestApplyClassMap:
    def test_replaces_styles_ref(self):
        js = 'h("div", {class: styles.card})'
        result = apply_class_map(js, {"card": "card-abc123"})
        assert '"card-abc123"' in result
        assert "styles.card" not in result

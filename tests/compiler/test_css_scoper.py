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

    def test_classname_literal_whole_tokens(self):
        js = "h('a', {className: 'lnk lnk-hide'})"
        result = apply_class_map(js, {"lnk": "lnk-abc123", "lnk-hide": "lnk-hide-abc123"})
        assert "className: 'lnk-abc123 lnk-hide-abc123'" in result

    def test_prefix_class_does_not_clobber_longer_name(self):
        js = "h('a', {className: 'card-header'})"
        result = apply_class_map(js, {"card": "card-abc123", "card-header": "card-header-abc123"})
        assert "className: 'card-header-abc123'" in result

    def test_expression_starting_with_styles_ref_scoped_once(self):
        js = "h('a', {className: styles.ws + (on ? ' ' + styles.awake : '')})"
        result = apply_class_map(js, {"ws": "ws-abc123", "awake": "awake-abc123"})
        assert 'className: "ws-abc123" + (on ? \' \' + "awake-abc123" : \'\')' in result
        assert "abc123-abc123" not in result

    def test_styles_ref_matches_whole_identifier(self):
        js = "h('a', {className: styles.btnGroup, title: styles.btn})"
        result = apply_class_map(js, {"btn": "btn-abc123"})
        assert "styles.btnGroup" in result
        assert 'title: "btn-abc123"' in result

    def test_unknown_classes_left_alone(self):
        js = "h('a', {className: 'external lnk'})"
        result = apply_class_map(js, {"lnk": "lnk-abc123"})
        assert "className: 'external lnk-abc123'" in result

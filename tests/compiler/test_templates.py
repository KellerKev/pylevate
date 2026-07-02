"""Phase 4 tests — Full template syntax coverage."""

from pylevate.compiler.py2js import compile_source


def _js(source: str, mode: str = "app") -> str:
    result = compile_source(source, "test.py", mode)
    assert not result.errors, f"Unexpected errors: {result.errors}"
    return result.js.strip()


class TestForLoop:
    def test_basic_for(self):
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
        assert "items.map((item) =>" in js
        assert "`${item}`" in js

    def test_for_with_nested_children(self):
        js = _js("""
from pylevate import Component, h

class Grid(Component):
    template = {
        h.div(): {
            h.Template(For='card in cards'): {
                h.div(Class='card'): {
                    h.h3(): '[[card["title"]]]',
                    h.p(): '[[card["body"]]]',
                }
            }
        }
    }
""")
        assert "cards.map((card) =>" in js
        assert "h('div', {className: 'card'}" in js

    def test_for_destructured(self):
        js = _js("""
from pylevate import Component, h

class Table(Component):
    template = {
        h.div(): {
            h.Template(For='key, value in entries'): {
                h.span(): '[[key]]: [[value]]',
            }
        }
    }
""")
        assert "entries.map((key, value) =>" in js or "entries.map(([key, value]) =>" in js


class TestIfElseChain:
    def test_simple_if(self):
        js = _js("""
from pylevate import Component, h

class C(Component):
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
        assert ": null)" in js

    def test_if_else(self):
        js = _js("""
from pylevate import Component, h

class C(Component):
    template = {
        h.div(): {
            h.Template(If='logged_in'): {
                h.p(): 'Welcome',
            },
            h.Template(Else=''): {
                h.p(): 'Please log in',
            },
        }
    }
""")
        assert "logged_in ?" in js
        assert "'Welcome'" in js
        assert "'Please log in'" in js
        # Else should NOT appear as a separate standalone element
        js_lines = js.split("\n")
        render_line = [l for l in js_lines if "return" in l][0]
        # Should be a single ternary, not two separate expressions
        assert render_line.count("?") >= 1

    def test_if_elif_else(self):
        js = _js("""
from pylevate import Component, h

class C(Component):
    template = {
        h.div(): {
            h.Template(If='status === "active"'): {
                h.span(): 'Active',
            },
            h.Template(Elif='status === "pending"'): {
                h.span(): 'Pending',
            },
            h.Template(Else=''): {
                h.span(): 'Unknown',
            },
        }
    }
""")
        # Should produce chained ternary
        assert "?" in js
        assert "'Active'" in js
        assert "'Pending'" in js
        assert "'Unknown'" in js

    def test_elif_not_duplicated(self):
        """Elif/Else entries consumed by If should not appear as standalone elements."""
        js = _js("""
from pylevate import Component, h

class C(Component):
    template = {
        h.div(): {
            h.Template(If='a'): {
                h.span(): 'A',
            },
            h.Template(Else=''): {
                h.span(): 'B',
            },
            h.p(): 'Always shown',
        }
    }
""")
        # 'Always shown' should be a separate sibling, not inside the ternary
        assert "'Always shown'" in js
        # Count h('span') calls — should be exactly 2 (one for A, one for B)
        assert js.count("h('span'") == 2


class TestSlots:
    def test_default_slot(self):
        js = _js("""
from pylevate import Component, SlotsEnum, h

class Card(Component):
    class S(SlotsEnum):
        default = ()

    template = {
        h.div(Class='card'): {
            S.default.slot(): '',
        }
    }
""")
        assert "children" in js  # default slot uses props.children

    def test_default_slot_with_fallback(self):
        js = _js("""
from pylevate import Component, SlotsEnum, h

class Card(Component):
    class S(SlotsEnum):
        default = ()

    template = {
        h.div(): {
            S.default.slot(): {
                h.p(): 'Default content',
            },
        }
    }
""")
        assert "children ||" in js or "(children ||" in js

    def test_named_slot(self):
        js = _js("""
from pylevate import Component, SlotsEnum, h

class Modal(Component):
    class S(SlotsEnum):
        default = ()
        header = ()

    template = {
        h.div(): {
            S.header.slot(): {
                h.h2(): 'Default Header',
            },
            S.default.slot(): '',
        }
    }
""")
        assert "slot_header" in js  # named slot prop


class TestTagSubclass:
    def test_tag_emits_create_tag(self):
        js = _js("""
from pylevate import Tag

class NavItem(Tag):
    tag_name = 'a'
    ident_class = 'navbar-item'
""")
        assert "createTag" in js
        assert "'a'" in js
        assert "'navbar-item'" in js
        assert "class NavItem" not in js  # should NOT be a class


class TestIsDirective:
    def test_dynamic_component(self):
        js = _js("""
from pylevate import Component, h

class C(Component):
    template = {
        h.div(): {
            h.Template(Is='widget_type'): {
                h.p(): 'content',
            }
        }
    }
""")
        assert "h(widget_type" in js


class TestComponentProps:
    def test_component_call_in_template(self):
        js = _js("""
from pylevate import Component, h

class App(Component):
    template = {
        h.div(): {
            Button(label='Click', variant='primary'): None,
        }
    }
""")
        assert "h(Button," in js
        assert "label: 'Click'" in js
        assert "variant: 'primary'" in js

    def test_component_with_children(self):
        js = _js("""
from pylevate import Component, h

class App(Component):
    template = {
        h.div(): {
            Card(title='Hello'): {
                h.p(): 'Card body content',
            },
        }
    }
""")
        assert "h(Card," in js
        assert "'Card body content'" in js


class TestNoneChild:
    def test_none_child_no_children(self):
        js = _js("""
from pylevate import Component, h

class C(Component):
    template = {
        h.input(type='text'): None,
    }
""")
        # h('input', {type: 'text'}) — no children arg
        assert "h('input', {type: 'text'})" in js

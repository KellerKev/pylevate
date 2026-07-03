"""
PyLevate Python-to-JavaScript compiler.

Uses Python's ast module to parse Python source and emit clean ES6 JavaScript.
Replaces RapydScript-NG with a native Python implementation.

Public API:
    compile_source(source, filename, mode) -> CompileResult
"""

from __future__ import annotations

import ast
import posixpath
import re
import textwrap
from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

@dataclass
class CompileError:
    """A single compilation error or warning."""
    file: str
    line: int
    col: int
    message: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}:{self.col}: {self.message}"


@dataclass
class CompileResult:
    """Result of a compilation run."""
    js: str
    source_map: dict | None = None
    errors: list[CompileError] = field(default_factory=list)
    css_chunks: list[str] = field(default_factory=list)
    warnings: list[CompileError] = field(default_factory=list)


@dataclass(frozen=True)
class ImportContext:
    """Project context for resolving local imports.

    Without a context (playground, tests, single-file compiles) the resolver
    assumes the importer sits at the project root and skips validation.
    """
    rel_path: str | None = None            # importer's project-relative posix path, e.g. "pages/home.py"
    modules: frozenset[str] = frozenset()  # dotted names of resolvable modules: {"main", "pages.home", "utils"}
    packages: frozenset[str] = frozenset() # dotted names of dirs containing __init__.py: {"components"}
    validate: bool = False


# ---------------------------------------------------------------------------
# Import rewriting helpers
# ---------------------------------------------------------------------------

_PYLEVATE_MODULE_MAP: dict[str, str] = {
    "pylevate":         "pylevate-runtime",
    "pylevate.game":    "pylevate-game-runtime",
    "pylevate.native":  "pylevate-native-runtime",
    "pylevate.signals": "pylevate-runtime",
    "pylevate.events":  "pylevate-events",
}


# Python stdlib modules that should be elided or shimmed, not imported as files
_STDLIB_ELIDE: set[str] = {"random", "math", "json", "time", "os", "sys", "typing"}


def _map_module(py_module: str) -> str:
    """Map a Python module path to its JS runtime package."""
    if py_module in _PYLEVATE_MODULE_MAP:
        return _PYLEVATE_MODULE_MAP[py_module]
    # Sub-packages: pylevate.foo.bar -> pylevate-foo-bar-runtime
    if py_module.startswith("pylevate."):
        parts = py_module.split(".")
        return "-".join(parts) + "-runtime"
    # Python stdlib modules — elide (handled by baselib or inline)
    if py_module in _STDLIB_ELIDE:
        return "__stdlib__"
    # Local project imports: components.button → ./components/button.js
    if "." in py_module:
        parts = py_module.split(".")
        return "./" + "/".join(parts) + ".js"
    # Single-name imports (e.g., 'utils') → relative
    return f"./{py_module}.js"


# ---------------------------------------------------------------------------
# String method mapping
# ---------------------------------------------------------------------------

_STRING_METHOD_MAP: dict[str, str] = {
    "upper":      "toUpperCase",
    "lower":      "toLowerCase",
    "strip":      "trim",
    "lstrip":     "trimStart",
    "rstrip":     "trimEnd",
    "startswith": "startsWith",
    "endswith":   "endsWith",
    "find":       "indexOf",
    "rfind":      "lastIndexOf",
    "replace":    "replace",
    "split":      "split",
    "join":       "join",
    "count":      "split",  # special-cased in visitor
    "isdigit":    "match",  # special-cased
}

# Builtin function mapping
_BUILTIN_MAP: dict[str, str] = {
    "print":  "console.log",
    "str":    "String",
    "int":    "parseInt",
    "float":  "parseFloat",
    "abs":    "Math.abs",
    "pow":    "Math.pow",
    # bool/min/max/round intentionally NOT mapped — they fall through to the
    # baselib globals (Python-truthy bool, iterable-aware min/max, round(x,n)).
    "sorted": "Array.from",  # special-cased
    "reversed": "Array.from",  # special-cased
    "enumerate": None,  # special-cased
    "zip":   None,  # special-cased
    "map":   None,  # special-cased
    "filter": None,  # special-cased
    "sum":   None,  # special-cased
    "any":   None,  # special-cased
    "all":   None,  # special-cased
    "dict":  "Object",  # special-cased
    "list":  "Array.from",
    "tuple": "Array.from",
    "set":   None,  # special-cased
    "type":  None,  # special-cased
    "hasattr": None,  # special-cased
    "getattr": None,  # special-cased
    "setattr": None,  # special-cased
    "delattr": None,  # special-cased
    "super":  "super",
}


# ---------------------------------------------------------------------------
# Operator maps
# ---------------------------------------------------------------------------

_BINOP_MAP = {
    ast.Add:      "+",
    ast.Sub:      "-",
    ast.Mult:     "*",
    ast.Div:      "/",
    ast.FloorDiv: None,  # special: Math.floor(a / b)
    ast.Mod:      "%",
    ast.Pow:      "**",
    ast.LShift:   "<<",
    ast.RShift:   ">>",
    ast.BitOr:    "|",
    ast.BitXor:   "^",
    ast.BitAnd:   "&",
    ast.MatMult:  None,  # unsupported
}

_UNARYOP_MAP = {
    ast.UAdd:   "+",
    ast.USub:   "-",
    ast.Not:    "!",
    ast.Invert: "~",
}

# Component lifecycle hooks (spec) -> Preact lifecycle method names.
_LIFECYCLE_METHOD_MAP = {
    "on_mount": "componentDidMount",
    "on_unmount": "componentWillUnmount",
    "on_update": "componentDidUpdate",
}

_CMPOP_MAP = {
    ast.Eq:    "===",
    ast.NotEq: "!==",
    ast.Lt:    "<",
    ast.LtE:   "<=",
    ast.Gt:    ">",
    ast.GtE:   ">=",
    ast.Is:    "===",
    ast.IsNot: "!==",
    ast.In:    None,  # special-cased
    ast.NotIn: None,  # special-cased
}

_BOOLOP_MAP = {
    ast.And: "&&",
    ast.Or:  "||",
}

_AUGASSIGN_MAP = {
    ast.Add:    "+=",
    ast.Sub:    "-=",
    ast.Mult:   "*=",
    ast.Div:    "/=",
    ast.Mod:    "%=",
    ast.Pow:    "**=",
    ast.LShift: "<<=",
    ast.RShift: ">>=",
    ast.BitOr:  "|=",
    ast.BitXor: "^=",
    ast.BitAnd: "&=",
    ast.FloorDiv: None,  # special
}



# ---------------------------------------------------------------------------
# Native JS globals: kwargs on calls rooted here trigger a compile warning,
# since the trailing-object convention rarely matches their signatures.
# ---------------------------------------------------------------------------

_JS_NATIVE_ROOTS: frozenset[str] = frozenset({
    "window", "document", "console", "Math", "JSON", "Promise", "fetch",
    "localStorage", "sessionStorage", "navigator", "history", "location",
    "Date", "RegExp", "URL", "URLSearchParams", "Intl", "crypto",
    "performance", "setTimeout", "setInterval", "clearTimeout",
    "clearInterval", "requestAnimationFrame", "WebSocket", "Audio", "Image",
})


# ---------------------------------------------------------------------------
# Template attribute name mapping (Python → JS/HTML)
# ---------------------------------------------------------------------------

_TEMPLATE_ATTR_MAP: dict[str, str] = {
    "Class": "className",
    "For_": "htmlFor",
    "Style": "style",
    "Tab_index": "tabIndex",
    "on_click": "onClick",
    "on_change": "onChange",
    "on_input": "onInput",
    "on_submit": "onSubmit",
    "on_key_down": "onKeyDown",
    "on_key_up": "onKeyUp",
    "on_mouse_enter": "onMouseEnter",
    "on_mouse_leave": "onMouseLeave",
    "on_focus": "onFocus",
    "on_blur": "onBlur",
}


# ---------------------------------------------------------------------------
# JS code emitter / AST visitor
# ---------------------------------------------------------------------------

class _JSEmitter(ast.NodeVisitor):
    """Walk a Python AST and emit JavaScript source code."""

    def __init__(self, filename: str, mode: str, import_ctx: ImportContext | None = None):
        self.filename = filename
        self.mode = mode  # "app" | "game" | "hybrid"
        self.import_ctx = import_ctx or ImportContext()
        self.errors: list[CompileError] = []
        self.warnings: list[CompileError] = []
        self.css_chunks: list[str] = []
        self._indent = 0
        self._lines: list[str] = []
        self._in_class: str | None = None
        self._in_method = False
        self._class_properties: dict[str, list[str]] = {}  # class -> property names
        self._class_state_fields: dict[str, list[tuple[str, str]]] = {}  # class -> [(name, init_expr)]
        self._class_css: dict[str, str] = {}  # class -> css string
        self._class_has_constructor: dict[str, bool] = {}
        self._class_is_component: dict[str, bool] = {}  # class -> extends Component?
        self._class_template: dict[str, ast.Dict | None] = {}  # class -> template AST
        self._class_init_props: dict[str, list[tuple[str, str | None]]] = {}  # class -> [(name, default)]
        self._class_effect_methods: dict[str, list[str]] = {}  # class -> [method_names]
        self._class_has_get_context: dict[str, bool] = {}  # class -> has get_context?
        self._class_context_keys: dict[str, list[str]] = {}  # class -> keys get_context adds to props
        self._declared_vars: list[set[str]] = [set()]  # stack of scopes

    # -- Helpers -----------------------------------------------------------

    def _error(self, node: ast.AST, msg: str) -> None:
        self.errors.append(CompileError(
            file=self.filename,
            line=getattr(node, "lineno", 0),
            col=getattr(node, "col_offset", 0),
            message=msg,
        ))

    def _warn(self, node: ast.AST, msg: str) -> None:
        self.warnings.append(CompileError(
            file=self.filename,
            line=getattr(node, "lineno", 0),
            col=getattr(node, "col_offset", 0),
            message=msg,
        ))

    def _emit(self, text: str) -> None:
        indent = "  " * self._indent
        for line in text.split("\n"):
            self._lines.append(f"{indent}{line}" if line.strip() else "")

    def _emit_raw(self, text: str) -> None:
        self._lines.append(text)

    def _indent_block(self):
        return _IndentContext(self)

    def get_source(self) -> str:
        return "\n".join(self._lines)

    # -- Module (top-level) ------------------------------------------------

    def visit_Module(self, node: ast.Module) -> None:
        # First pass: collect class-level metadata (state fields, css, properties)
        for stmt in node.body:
            if isinstance(stmt, ast.ClassDef):
                self._prescan_class(stmt)
        # Second pass: emit
        for stmt in node.body:
            self.visit(stmt)

    # -- Imports -----------------------------------------------------------

    def _importer_base_parts(self) -> tuple[str, ...]:
        """Directory of the importing module as dotted-path parts ('' → root)."""
        rel = self.import_ctx.rel_path
        if not rel:
            return ()
        parent = posixpath.dirname(rel)
        return tuple(p for p in parent.split("/") if p)

    def _resolve_import(self, module: str, level: int, node: ast.AST) -> str | None:
        """Resolve a Python module reference to a JS import specifier.

        Returns None when the import should not be emitted (stdlib elide is
        signalled by the '__stdlib__' sentinel; hard failures append an error).
        """
        if level == 0:
            mapped = _map_module(module)
            if not mapped.startswith("./"):
                # pylevate-* runtime package or __stdlib__ sentinel
                return mapped
            target = module.split(".")
        else:
            base = self._importer_base_parts()
            if level - 1 > len(base):
                self._error(node, f"Relative import '{'.' * level}{module}' reaches beyond the project root")
                return None
            kept = base[: len(base) - (level - 1)] if level > 1 else base
            target = list(kept) + (module.split(".") if module else [])

        dotted = ".".join(target)
        ctx = self.import_ctx
        if dotted in ctx.packages:
            target = target + ["__init__"]
        elif ctx.validate and dotted not in ctx.modules:
            expected = "/".join(t for t in target if t)
            self._error(
                node,
                f"Cannot resolve import '{dotted}' — expected {expected}.py or {expected}.js "
                f"in the project. Local imports must match a source file; "
                f"framework imports must start with 'pylevate'.",
            )
            return None

        target_path = "/".join(target) + ".js"
        base_dir = "/".join(self._importer_base_parts())
        rel = posixpath.relpath(target_path, base_dir) if base_dir else target_path
        if not rel.startswith("."):
            rel = f"./{rel}"
        return rel

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            js_mod = self._resolve_import(alias.name, 0, node)
            if js_mod is None:
                continue
            if js_mod == "__stdlib__":
                self._emit(f"// stdlib: {alias.name} (shimmed by baselib)")
                continue
            local = alias.asname or alias.name.split(".")[-1]
            self._emit(f"import * as {local} from '{js_mod}';")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if node.level > 0 and not module:
            # `from . import nav` / `from .. import x`: each alias is a module.
            for alias in node.names:
                js_mod = self._resolve_import(alias.name, node.level, node)
                if js_mod is None or js_mod == "__stdlib__":
                    continue
                local = alias.asname or alias.name
                self._emit(f"import * as {local} from '{js_mod}';")
            return
        js_mod = self._resolve_import(module, node.level, node)
        if js_mod is None:
            return
        if js_mod == "__stdlib__":
            self._emit(f"// stdlib: {module} (shimmed by baselib)")
            return
        names = []
        for alias in node.names:
            if alias.name == "*":
                self._error(
                    node,
                    f"'from {module} import *' is not supported — "
                    f"JavaScript modules have no star re-export into scope; import names explicitly",
                )
                return
            local = alias.asname or alias.name
            if local != alias.name:
                names.append(f"{alias.name} as {local}")
            else:
                names.append(alias.name)
        self._emit(f"import {{ {', '.join(names)} }} from '{js_mod}';")

    # -- Class definitions -------------------------------------------------

    def _prescan_class(self, node: ast.ClassDef) -> None:
        """Collect state(), css(), template, props, and @property info before emitting."""
        cname = node.name
        self._class_state_fields[cname] = []
        self._class_css[cname] = ""
        self._class_properties[cname] = []
        self._class_has_constructor[cname] = False
        self._class_template[cname] = None
        self._class_init_props[cname] = []
        self._class_effect_methods[cname] = []
        self._class_has_get_context[cname] = False
        self._class_context_keys[cname] = []

        # Detect if this class extends Component, Store, or Tag
        is_component = any(
            (isinstance(b, ast.Name) and b.id in ("Component", "Store"))
            or (isinstance(b, ast.Attribute) and b.attr in ("Component", "Store"))
            for b in node.bases
        )
        is_tag = any(
            (isinstance(b, ast.Name) and b.id == "Tag")
            or (isinstance(b, ast.Attribute) and b.attr == "Tag")
            for b in node.bases
        )
        self._class_is_component[cname] = is_component or is_tag

        for item in node.body:
            # state(init_value) or signal(init_value) at class level
            if isinstance(item, ast.Assign) and len(item.targets) == 1:
                target = item.targets[0]
                if isinstance(target, ast.Name) and isinstance(item.value, ast.Call):
                    if (isinstance(item.value.func, ast.Name)
                            and item.value.func.id in ("state", "signal")):
                        init = self._expr(item.value.args[0]) if item.value.args else "null"
                        self._class_state_fields[cname].append((target.id, init))
                    elif isinstance(item.value.func, ast.Name) and item.value.func.id == "css":
                        if item.value.args and isinstance(item.value.args[0], ast.Constant):
                            self._class_css[cname] = item.value.args[0].value
                            self.css_chunks.append(item.value.args[0].value)
                # Detect template = {...}
                if (isinstance(target, ast.Name)
                        and target.id == "template"
                        and isinstance(item.value, ast.Dict)):
                    self._class_template[cname] = item.value

            # Detect @property, @effect
            if isinstance(item, ast.FunctionDef):
                for dec in item.decorator_list:
                    if isinstance(dec, ast.Name) and dec.id == "property":
                        self._class_properties[cname].append(item.name)
                    elif isinstance(dec, ast.Name) and dec.id == "effect":
                        self._class_effect_methods[cname].append(item.name)
                if item.name == "get_context":
                    self._class_has_get_context[cname] = True
                    self._class_context_keys[cname] = self._extract_context_keys(item)
                if item.name == "template_factory":
                    # template_factory returns a template dict — handle at emit time
                    pass
                if item.name == "__init__":
                    self._class_has_constructor[cname] = True
                    # Extract prop names from __init__ params
                    self._class_init_props[cname] = self._extract_init_props(item)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # Check if this is a Tag subclass — emit as createTag() call
        is_tag = any(
            (isinstance(b, ast.Name) and b.id == "Tag")
            for b in node.bases
        )
        if is_tag:
            self._emit_tag_class(node)
            return

        # Decorators
        for dec in node.decorator_list:
            dec_js = self._expr(dec)
            # We'll wrap the class after emission
            # For now just note it; simple decorators applied as wrappers
            pass

        bases = [self._expr(b) for b in node.bases]
        extends = f" extends {bases[0]}" if bases else ""

        decorator_names = []
        for dec in node.decorator_list:
            decorator_names.append(self._expr(dec))

        # Top-level classes get 'export' so they can be imported by other modules
        export = "export " if self._in_class is None else ""
        self._emit(f"{export}class {node.name}{extends} {{")
        old_class = self._in_class
        self._in_class = node.name

        with self._indent_block():
            # Emit state fields as signal initialisations in constructor
            # (handled inside __init__ visitor or synthesized)
            state_fields = self._class_state_fields.get(node.name, [])
            had_init = self._class_has_constructor.get(node.name, False)

            effect_methods = self._class_effect_methods.get(node.name, [])

            # If there are state fields or effects but no __init__, synthesize a constructor
            if (state_fields or effect_methods) and not had_init:
                self._emit("constructor(...args) {")
                with self._indent_block():
                    if bases:
                        self._emit("super(...args);")
                    for fname, init_val in state_fields:
                        if self.mode in ("app", "hybrid"):
                            self._emit(f"this._{fname} = signal({init_val});")
                        else:
                            self._emit(f"this.{fname} = {init_val};")
                    # Register @effect methods
                    for eff_name in effect_methods:
                        self._emit(f"effect(() => this.{eff_name}());")
                self._emit("}")

            # Public accessors for signal fields: internal reads are rewritten
            # to this._x.value at compile time, but cross-module consumers
            # (store.count from another file) need real properties.
            if state_fields and self.mode in ("app", "hybrid"):
                for fname, _ in state_fields:
                    self._emit(f"get {fname}() {{ return this._{fname}.value; }}")
                    self._emit(f"set {fname}(v) {{ this._{fname}.value = v; }}")

            for item in node.body:
                # Skip class-level state() and css() assignments (handled above)
                if isinstance(item, ast.Assign) and len(item.targets) == 1:
                    tgt = item.targets[0]
                    if isinstance(tgt, ast.Name) and isinstance(item.value, ast.Call):
                        func = item.value.func
                        if isinstance(func, ast.Name) and func.id in ("state", "signal", "css"):
                            continue
                # Skip class-level simple assignments -> emit as static or skip
                if isinstance(item, ast.Assign):
                    self._visit_class_assign(item)
                    continue
                # Skip string docstrings
                if (isinstance(item, ast.Expr)
                        and isinstance(item.value, ast.Constant)
                        and isinstance(item.value.value, str)):
                    continue
                # Nested class (e.g. SlotsEnum)
                if isinstance(item, ast.ClassDef):
                    # Emit as static nested — skip for now, just note it
                    continue
                self.visit(item)

            # Emit @property getters/setters
            props = self._class_properties.get(node.name, [])
            # These are handled inline in visit_FunctionDef via decorator detection

        self._emit("}")

        # Wrap with decorators (applied bottom-up)
        for dec_name in reversed(decorator_names):
            if dec_name not in ("property",):
                self._emit(f"{node.name} = {dec_name}({node.name});")

        self._emit("")
        self._in_class = old_class

    def _emit_tag_class(self, node: ast.ClassDef) -> None:
        """Emit a Tag subclass as a createTag() call."""
        tag_name = "div"
        ident_class = ""
        for item in node.body:
            if isinstance(item, ast.Assign) and len(item.targets) == 1:
                t = item.targets[0]
                if isinstance(t, ast.Name) and isinstance(item.value, ast.Constant):
                    if t.id == "tag_name":
                        tag_name = item.value.value
                    elif t.id == "ident_class":
                        ident_class = item.value.value
        export = "export " if self._in_class is None else ""
        self._emit(f"{export}const {node.name} = createTag('{tag_name}', '{ident_class}');")
        self._emit("")

    def _visit_class_assign(self, node: ast.Assign) -> None:
        """Handle class-level assignments like `props = {...}` or `template = {...}`."""
        if len(node.targets) != 1:
            return
        target = node.targets[0]
        if isinstance(target, ast.Name):
            name = target.id
            # If this is `template = {...}` on a Component, emit render() instead
            if (name == "template"
                    and self._in_class
                    and self._class_is_component.get(self._in_class, False)
                    and isinstance(node.value, ast.Dict)):
                self._emit_render_from_template(node.value)
                return
            # If this is `props = {...}`, skip (handled via __init__ or directly)
            if name == "props" and self._in_class and self._class_is_component.get(self._in_class, False):
                # Emit as default props
                val = self._expr(node.value)
                self._emit(f"static defaultProps = {val};")
                return
            val = self._expr(node.value)
            self._emit(f"static {name} = {val};")

    # -- Template compilation (dict → render with h() calls) ------------------

    def _extract_init_props(self, func_node: ast.FunctionDef) -> list[tuple[str, str | None]]:
        """Extract (name, default_expr) pairs from __init__ parameters."""
        props: list[tuple[str, str | None]] = []
        args = func_node.args
        # Skip 'self' (first param for methods)
        param_names = [a.arg for a in args.args[1:]]
        # Defaults are right-aligned to params
        num_no_default = len(param_names) - len(args.defaults)
        for i, name in enumerate(param_names):
            if name == "kw":
                continue  # **kw
            default_idx = i - num_no_default
            if default_idx >= 0:
                props.append((name, self._expr(args.defaults[default_idx])))
            else:
                props.append((name, None))
        return props

    def _extract_context_keys(self, func_node: ast.FunctionDef) -> list[str]:
        """Collect string keys that get_context assigns onto its props param.

        `props['chevron'] = ...` adds a derived value the template can
        reference as [[chevron]]; render() must destructure those keys from
        the get_context result so the interpolation resolves.
        """
        params = [a.arg for a in func_node.args.args]
        props_param = params[1] if len(params) > 1 else None
        if props_param is None:
            return []
        keys: list[str] = []
        for stmt in ast.walk(func_node):
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == props_param
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)
                        and target.slice.value.isidentifier()
                        and target.slice.value not in keys):
                    keys.append(target.slice.value)
        return keys

    def _emit_render_from_template(self, template_dict: ast.Dict) -> None:
        """Compile a template dict into a render() method with h() calls."""
        self._emit("render(props, state, context) {")
        with self._indent_block():
            # Destructure props if __init__ props were declared
            init_props = self._class_init_props.get(self._in_class, [])
            if init_props:
                prop_names = [p[0] for p in init_props]
                self._emit(f"let {{ {', '.join(prop_names)}, ...rest }} = props || {{}};")

            # Call get_context() if defined — it can add derived props
            has_gc = self._class_has_get_context.get(self._in_class, False)
            if has_gc:
                if init_props:
                    prop_names_str = ", ".join(p[0] for p in init_props)
                    self._emit(f"const _ctx = this.get_context({{ {prop_names_str}, ...rest }});")
                    # Reassign props from context
                    self._emit(f"({{ {', '.join(p[0] for p in init_props)}, ...rest }} = _ctx);")
                else:
                    self._emit("const _ctx = this.get_context(props || {});")
                # Bind derived keys get_context added so [[key]] interpolations
                # resolve as locals (init props are already destructured above).
                init_prop_names = {p[0] for p in init_props}
                ctx_keys = [
                    k for k in self._class_context_keys.get(self._in_class, [])
                    if k not in init_prop_names
                ]
                if ctx_keys:
                    self._emit(f"const {{ {', '.join(ctx_keys)} }} = _ctx;")

            # Children from parent (passed as props.children by Preact)
            self._emit("const children = props && props.children;")

            # Compile the template dict to h() call chain
            h_expr = self._compile_template_dict(template_dict)
            self._emit(f"return {h_expr};")
        self._emit("}")

    def _compile_template_dict(self, node: ast.Dict) -> str:
        """Compile a template dict AST to nested h() calls.

        Each key is an h.tag(...) call or component call → becomes h('tag', attrs, children)
        Each value is either a string (text child), None, or a nested dict (child elements).
        """
        if len(node.keys) == 0:
            return "null"

        parts: list[str] = []
        skip_indices: set[int] = set()
        i = 0
        while i < len(node.keys):
            if i in skip_indices:
                i += 1
                continue
            key = node.keys[i]
            value = node.values[i]
            # Detect If → collect consumed Elif/Else indices
            if isinstance(key, ast.Call):
                _, _, ctrl = self._parse_template_key(key)
                if "If" in ctrl:
                    consumed = self._find_elif_else_indices(node.keys, i)
                    skip_indices.update(consumed)
            compiled = self._compile_template_entry(key, value, node.keys, node.values, i)
            parts.append(compiled)
            i += 1

        if len(parts) == 1:
            return parts[0]
        return f"h(Fragment, null, {', '.join(parts)})"

    def _find_elif_else_indices(self, keys: list, if_index: int) -> set[int]:
        """Find indices of Elif/Else entries following an If entry."""
        consumed: set[int] = set()
        j = if_index + 1
        while j < len(keys):
            k = keys[j]
            if isinstance(k, ast.Call):
                _, _, ctrl = self._parse_template_key(k)
                if "Elif" in ctrl or "Else" in ctrl:
                    consumed.add(j)
                    if "Else" in ctrl:
                        break  # Else is terminal
                    j += 1
                    continue
            break
        return consumed

    def _compile_template_entry(
        self, key: ast.expr, value: ast.expr,
        all_keys: list, all_values: list, index: int
    ) -> str:
        """Compile a single key:value pair from the template dict."""
        if key is None:
            # {**spread} — shouldn't appear in templates, skip
            return "null"

        # Detect h.tag(...) calls — key is Call(func=Attribute(value=Name('h'), attr=tag_name))
        tag_name, attrs, control = self._parse_template_key(key)

        # Handle control flow: h.Template(For=...), h.Template(If=...), etc.
        if tag_name == "Template":
            return self._compile_template_control(control, value, all_keys, all_values, index)

        # Handle slot definitions: S.name.slot() → renders children or named slot prop
        if self._is_slot_call(key):
            fallback = self._compile_template_value(value)
            slot_name = self._extract_slot_name(key)
            if slot_name == "default":
                # Default slot: use props.children with optional fallback
                if fallback != "null":
                    return f"(children || {fallback})"
                return "children"
            else:
                # Named slot: use props.slot_<name> with optional fallback
                slot_prop = f"slot_{slot_name}"
                if fallback != "null":
                    return f"(props && props.{slot_prop} ? props.{slot_prop} : {fallback})"
                return f"(props && props.{slot_prop})"

        # Handle slot fills: Comp.S.name() → pass children as named slot prop
        if self._is_slot_fill(key):
            slot_name = self._extract_slot_fill_name(key)
            slot_children = self._compile_template_value(value)
            # Return as a named prop to be collected by parent component call
            return f"/* slot_fill:{slot_name} */ {slot_children}"

        # Compile children
        children = self._compile_template_value(value)

        # Build attrs object
        attrs_js = self._compile_template_attrs(attrs)

        if children and children != "null":
            return f"h({tag_name}, {attrs_js}, {children})"
        else:
            return f"h({tag_name}, {attrs_js})"

    def _parse_template_key(self, key: ast.expr) -> tuple[str, list[ast.keyword], dict]:
        """Parse a template dict key into (tag_name, attrs_kwargs, control_directives).

        Patterns:
        - h.div(Class='foo', onClick={...})  → ('div', [kw...], {})
        - h.Template(For='x in xs')          → ('Template', [], {'For': ...})
        - ComponentName(prop=val)             → ('ComponentName', [kw...], {})
        - h.div()                             → ('div', [], {})
        """
        control: dict[str, ast.expr] = {}

        if isinstance(key, ast.Call):
            func = key.func
            # h.tagname(...)
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "h":
                tag_name = func.attr
                if tag_name == "Template":
                    for kw in key.keywords:
                        if kw.arg in ("For", "If", "Elif", "Else", "Is"):
                            control[kw.arg] = kw.value
                    return "Template", list(key.keywords), control
                return f"'{tag_name}'", list(key.keywords), control
            # ComponentName(...)
            elif isinstance(func, ast.Name):
                return func.id, list(key.keywords), control
            # module.Component(...)
            elif isinstance(func, ast.Attribute):
                return self._expr(func), list(key.keywords), control

        # Bare name (unlikely but handle)
        if isinstance(key, ast.Name):
            return key.id, [], control

        # Fallback
        return self._expr(key), [], control

    def _compile_template_attrs(self, keywords: list[ast.keyword]) -> str:
        """Compile template tag attributes to a JS object literal.

        Expression tiers:
        - static string: Class='card'     → class: 'card'
        - bytes literal: charset=b'utf-8' → charset: 'utf-8'
        - set expression: onClick={'handler'} → onClick: handler
        """
        if not keywords:
            return "null"

        pairs: list[str] = []
        for kw in keywords:
            if kw.arg is None:
                continue
            # Skip control flow directives
            if kw.arg in ("For", "If", "Elif", "Else", "Is"):
                continue

            attr_name = kw.arg
            # Map Python attr names to JS: Class → className, etc.
            js_attr = _TEMPLATE_ATTR_MAP.get(attr_name, attr_name)

            value_node = kw.value
            val_js = self._compile_template_attr_value(value_node)
            pairs.append(f"{js_attr}: {val_js}")

        if not pairs:
            return "null"
        return "{" + ", ".join(pairs) + "}"

    def _compile_template_attr_value(self, node: ast.expr) -> str:
        """Compile a template attribute value respecting expression tiers.

        Tier 1 — static string (ast.Constant str):  'card' → 'card'
        Tier 2 — bytes literal (ast.Constant bytes): b'utf-8' → 'utf-8' (no processing)
        Tier 3 — set wrapping (ast.Set with one str): {'handler'} → handler (JS expression)
        """
        # Tier 2: bytes literal → raw string, no processing
        if isinstance(node, ast.Constant) and isinstance(node.value, bytes):
            return repr(node.value.decode("utf-8"))

        # Tier 3: set with one string element → JS expression
        if isinstance(node, ast.Set) and len(node.elts) == 1:
            elt = node.elts[0]
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                expr = elt.value
                # Replace self.x with this.x and handle state fields
                expr = self._rewrite_template_expr(expr)
                return expr
            # If the set element is not a string constant, compile it
            return self._expr(elt)

        # Tier 1: static string
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return repr(node.value)

        # Any other expression — compile normally
        return self._expr(node)

    def _compile_template_value(self, value: ast.expr) -> str:
        """Compile a template dict value (children).

        - None → null (no children)
        - str → text node (with [[expr]] interpolation)
        - '' → empty (no meaningful child)
        - dict → nested h() calls
        """
        if value is None or (isinstance(value, ast.Constant) and value.value is None):
            return "null"

        # Empty string → no children
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            text = value.value
            if not text:
                return "null"
            # Handle [[expr]] interpolation
            text = self._rewrite_template_interpolation(text)
            return text

        # Nested dict → recursive compilation
        if isinstance(value, ast.Dict):
            return self._compile_template_dict(value)

        # Anything else → compile as expression
        return self._expr(value)

    def _compile_template_control(
        self, control: dict, value: ast.expr,
        all_keys: list, all_values: list, index: int
    ) -> str:
        """Compile Template control flow directives (For, If, Elif, Else, Is)."""
        children = self._compile_template_value(value)

        if "For" in control:
            for_node = control["For"]
            if isinstance(for_node, ast.Constant) and isinstance(for_node.value, str):
                for_expr = for_node.value
                # Parse 'item in items' → items.map((item) => ...)
                parts = for_expr.split(" in ", 1)
                if len(parts) == 2:
                    var_name = parts[0].strip()
                    iterable = self._rewrite_template_expr(parts[1].strip())
                    return f"{iterable}.map(({var_name}) => {children})"
            # Fallback
            return f"/* For: unsupported */ {children}"

        if "If" in control:
            cond_node = control["If"]
            cond = self._compile_template_condition(cond_node)
            # Look ahead for Elif/Else siblings
            else_part = self._compile_template_elif_chain(all_keys, all_values, index)
            return f"({cond} ? {children} : {else_part})"

        if "Elif" in control:
            # Handled by _compile_template_elif_chain from the If branch
            # Should not be reached standalone
            cond = self._compile_template_condition(control["Elif"])
            return f"({cond} ? {children} : null)"

        if "Else" in control:
            return children

        if "Is" in control:
            is_node = control["Is"]
            if isinstance(is_node, ast.Constant) and isinstance(is_node.value, str):
                comp_expr = self._rewrite_template_expr(is_node.value)
                return f"h({comp_expr}, null, {children})"
            return f"h({self._expr(is_node)}, null, {children})"

        return children

    def _compile_template_elif_chain(
        self, all_keys: list, all_values: list, if_index: int
    ) -> str:
        """Look ahead from an If template for Elif/Else siblings."""
        # Check next siblings for Elif/Else
        next_idx = if_index + 1
        if next_idx < len(all_keys):
            next_key = all_keys[next_idx]
            if isinstance(next_key, ast.Call):
                _, _, next_control = self._parse_template_key(next_key)
                if "Elif" in next_control:
                    next_children = self._compile_template_value(all_values[next_idx])
                    cond = self._compile_template_condition(next_control["Elif"])
                    else_part = self._compile_template_elif_chain(all_keys, all_values, next_idx)
                    return f"({cond} ? {next_children} : {else_part})"
                if "Else" in next_control:
                    return self._compile_template_value(all_values[next_idx])
        return "null"

    def _compile_template_condition(self, node: ast.expr) -> str:
        """Compile a template condition expression.

        String conditions are Python expressions (`not`, `and`, `or`, ...), so
        they go through the AST expression compiler — the regex rewriter would
        leave Python operators in the JS output.
        """
        expr_str: str | None = None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            expr_str = node.value
        elif isinstance(node, ast.Set) and len(node.elts) == 1:
            elt = node.elts[0]
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                expr_str = elt.value
        if expr_str is not None:
            try:
                parsed = ast.parse(expr_str, mode="eval").body
            except SyntaxError:
                return self._rewrite_template_expr(expr_str)
            return self._expr(parsed)
        return self._expr(node)

    def _rewrite_template_expr(self, expr: str) -> str:
        """Rewrite Python expressions in templates to JS.

        - self.x → this.x (or this._x.value for state fields)
        - len(x) → x.length
        - Arrow function expressions like 'e => self.x = e.target.value' are handled
        """
        import re as _re
        state_names = [f for f, _ in self._class_state_fields.get(self._in_class or "", [])]

        # self.field → this.field or this._field.value
        def rewrite_self(m: _re.Match) -> str:
            field = m.group(1)
            if field in state_names:
                return f"this._{field}.value"
            return f"this.{field}"

        expr = _re.sub(r"self\.(\w+)", rewrite_self, expr)

        # Bind method references: if expr is exactly `this.methodName` (simple method ref),
        # bind it so `this` is preserved in event handlers.
        # Skip if it's an arrow function or already a call.
        if (_re.match(r"^this\.\w+$", expr)
                and "=>" not in expr
                and "(" not in expr):
            # Check it's not a state field (those have .value already)
            field_name = expr.split(".")[-1]
            if field_name not in state_names and not field_name.startswith("_"):
                expr = f"{expr}.bind(this)"

        return expr

    def _rewrite_template_interpolation(self, text: str) -> str:
        """Rewrite [[expr]] interpolations in template text to JS template literals."""
        if "[[" not in text:
            return repr(text)

        result = []
        i = 0
        while i < len(text):
            if text[i:i+2] == "[[":
                # Find matching ]] — track bracket depth
                j = i + 2
                depth = 0
                while j < len(text):
                    if text[j] == "[":
                        depth += 1
                    elif text[j] == "]":
                        if depth == 0 and j + 1 < len(text) and text[j+1] == "]":
                            # Found closing ]]
                            expr = text[i+2:j]
                            expr = self._rewrite_template_expr(expr)
                            result.append(f"${{{expr}}}")
                            i = j + 2
                            break
                        elif depth > 0:
                            depth -= 1
                    j += 1
                else:
                    # No closing ]] found, treat as literal
                    result.append(text[i])
                    i += 1
            else:
                result.append(text[i])
                i += 1

        joined = "".join(result)
        joined = joined.replace("`", "\\`")
        return f"`{joined}`"

    def _is_slot_call(self, key: ast.expr) -> bool:
        """Check if a template key is a slot definition like S.default.slot()."""
        if isinstance(key, ast.Call) and isinstance(key.func, ast.Attribute):
            return key.func.attr == "slot"
        return False

    def _extract_slot_name(self, key: ast.expr) -> str:
        """Extract slot name from S.name.slot() or similar."""
        if isinstance(key, ast.Call) and isinstance(key.func, ast.Attribute):
            # S.default.slot() → func is Attribute(value=Attribute(value=Name('S'), attr='default'), attr='slot')
            val = key.func.value
            if isinstance(val, ast.Attribute):
                return val.attr
            if isinstance(val, ast.Name):
                return val.id
        return "default"

    def _is_slot_fill(self, key: ast.expr) -> bool:
        """Check if a template key is a slot fill like Modal.S.header()."""
        if isinstance(key, ast.Call) and isinstance(key.func, ast.Attribute):
            # Modal.S.header() → func is Attribute(value=Attribute(value=Attribute(...), attr='header'))
            val = key.func
            if isinstance(val, ast.Attribute) and isinstance(val.value, ast.Attribute):
                return val.value.attr == "S" or isinstance(val.value.value, ast.Attribute)
        return False

    def _extract_slot_fill_name(self, key: ast.expr) -> str:
        """Extract slot name from Comp.S.name()."""
        if isinstance(key, ast.Call) and isinstance(key.func, ast.Attribute):
            return key.func.attr
        return "default"

    # -- Function / method definitions -------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._emit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._emit_function(node, is_async=True)

    def _emit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool) -> None:
        is_method = self._in_class is not None
        async_prefix = "async " if is_async else ""

        # Detect decorators
        is_property_getter = False
        is_property_setter = False
        is_static = False
        is_classmethod = False
        is_computed = False
        is_action = False
        is_effect = False
        applied_decorators: list[str] = []

        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                if dec.id == "property":
                    is_property_getter = True
                elif dec.id == "computed":
                    # In Store context: emit as getter wrapping computed()
                    # In other context: treat as property getter
                    if self._in_class and self._class_is_component.get(self._in_class, False):
                        is_computed = True
                    else:
                        is_property_getter = True
                elif dec.id == "action":
                    is_action = True
                elif dec.id == "effect":
                    is_effect = True
                elif dec.id == "staticmethod":
                    is_static = True
                elif dec.id == "classmethod":
                    is_classmethod = True
                else:
                    applied_decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                # e.g. @something.setter
                if dec.attr == "setter":
                    is_property_setter = True
                else:
                    applied_decorators.append(self._expr(dec))
            elif isinstance(dec, ast.Call):
                applied_decorators.append(self._expr(dec))

        # Build parameter list. Constructors may take **kwargs (prop forwarding).
        params = self._build_params(node.args, is_method and not is_static,
                                    allow_kwargs=node.name == "__init__")

        # Method name translation
        name = node.name
        if name == "__init__":
            name = "constructor"
        elif (
            self._in_class
            and self._class_is_component.get(self._in_class, False)
            and name in _LIFECYCLE_METHOD_MAP
        ):
            # Spec lifecycle hooks (on_mount/on_unmount/on_update) — Preact only
            # calls its own names, so emit those.
            name = _LIFECYCLE_METHOD_MAP[name]

        # State field initialisation for __init__
        state_inits: list[str] = []
        if node.name == "__init__" and self._in_class:
            for fname, init_val in self._class_state_fields.get(self._in_class, []):
                if self.mode in ("app", "hybrid"):
                    state_inits.append(f"this._{fname} = signal({init_val});")
                else:
                    state_inits.append(f"this.{fname} = {init_val};")

        # Emit
        if is_method:
            if is_computed:
                self._emit(f"get {name}() {{")
            elif is_property_getter:
                self._emit(f"get {name}() {{")
            elif is_property_setter:
                self._emit(f"set {name}({params}) {{")
            elif is_static or is_classmethod:
                self._emit(f"static {async_prefix}{name}({params}) {{")
            elif name == "constructor":
                self._emit(f"constructor({params}) {{")
            else:
                self._emit(f"{async_prefix}{name}({params}) {{")
        else:
            export = "export " if self._in_class is None else ""
            self._emit(f"{export}{async_prefix}function {name}({params}) {{")

        old_in_method = self._in_method
        self._in_method = is_method
        self._push_scope()

        # Add parameters to declared vars so they won't get `let` inside body
        strip_self = is_method and not is_static
        for arg in node.args.args:
            if not (strip_self and arg.arg in ("self", "cls")):
                self._declared_vars[-1].add(arg.arg)
        if node.args.vararg:
            self._declared_vars[-1].add(node.args.vararg.arg)
        for kw in node.args.kwonlyargs:
            self._declared_vars[-1].add(kw.arg)

        with self._indent_block():
            # Inject state field initialisations after super() call or at top
            if state_inits and node.name == "__init__":
                # Find if first statement is super().__init__() and emit body up to that
                found_super = False
                for i, stmt in enumerate(node.body):
                    if self._is_super_call(stmt):
                        self.visit(stmt)
                        for si in state_inits:
                            self._emit(si)
                        for stmt2 in node.body[i + 1:]:
                            self.visit(stmt2)
                        found_super = True
                        break
                if not found_super:
                    for si in state_inits:
                        self._emit(si)
                    self._emit_body(node.body)
            elif is_computed:
                # @computed: wrap body return in computed(() => expr).value
                self._emit(f"return computed(() => {{")
                with self._indent_block():
                    self._emit_body(node.body)
                self._emit("}).value;")
            elif is_effect:
                # @effect: register with effect() in constructor instead
                # Emit body directly — constructor will call _init_effects()
                self._emit_body(node.body)
            elif is_action:
                # @action: wrap body in batch()
                self._emit("batch(() => {")
                with self._indent_block():
                    self._emit_body(node.body)
                self._emit("});")
            else:
                self._emit_body(node.body)

        self._emit("}")

        self._pop_scope()
        self._in_method = old_in_method

        # Apply non-property decorators
        if not is_method and applied_decorators:
            for dec_name in reversed(applied_decorators):
                self._emit(f"{node.name} = {dec_name}({node.name});")

    def _is_super_call(self, stmt: ast.stmt) -> bool:
        """Check if statement is super().__init__(...) or super().__init__(...)."""
        if not isinstance(stmt, ast.Expr):
            return False
        call = stmt.value
        if not isinstance(call, ast.Call):
            return False
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr == "__init__":
            if isinstance(func.value, ast.Call):
                if isinstance(func.value.func, ast.Name) and func.value.func.id == "super":
                    return True
        return False

    def _build_params(self, args: ast.arguments, strip_self: bool,
                      allow_kwargs: bool = False) -> str:
        """Build JS parameter list from Python function arguments."""
        parts: list[str] = []
        all_args = args.args[:]
        defaults = args.defaults[:]

        # Pad defaults to align with args
        while len(defaults) < len(all_args):
            defaults.insert(0, None)

        for arg, default in zip(all_args, defaults):
            if strip_self and arg.arg == "self":
                continue
            if strip_self and arg.arg == "cls":
                continue
            if default is not None:
                parts.append(f"{arg.arg} = {self._expr(default)}")
            else:
                parts.append(arg.arg)

        # *args -> ...args
        if args.vararg:
            parts.append(f"...{args.vararg.arg}")

        # keyword-only args
        for kw, default in zip(args.kwonlyargs, args.kw_defaults):
            if default is not None:
                parts.append(f"{kw.arg} = {self._expr(default)}")
            else:
                parts.append(kw.arg)

        # **kwargs: not representable as JS keyword params. In a constructor it is
        # the idiomatic prop-forwarding pattern (`def __init__(self, x, **kw):
        # super().__init__(x=x, **kw)`), so emit it as a trailing rest param — the
        # call side spreads it as `...kw`, so it must be a bound name (dropping it
        # silently, as before, left `kw` undefined at runtime). Everywhere else it
        # would silently drop keyword args, so fail loudly.
        if args.kwarg:
            if allow_kwargs:
                parts.append(f"...{args.kwarg.arg}")
            else:
                self._error(args.kwarg, f"`**{args.kwarg.arg}` (arbitrary keyword args) is not "
                                  "supported — declare explicit keyword arguments instead "
                                  f"(e.g. `def f(a, b=1, c=2)` rather than `**{args.kwarg.arg}`).")

        return ", ".join(parts)

    # -- Statements --------------------------------------------------------

    def visit_Expr(self, node: ast.Expr) -> None:
        # String literal at statement level -> skip (docstring)
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return
        js = self._expr(node.value)
        self._emit(f"{js};")

    def visit_Return(self, node: ast.Return) -> None:
        if node.value:
            self._emit(f"return {self._expr(node.value)};")
        else:
            self._emit("return;")

    def visit_Assign(self, node: ast.Assign) -> None:
        value_js = self._expr(node.value)

        for target in node.targets:
            # Check if we're assigning to a state signal in app mode
            if (self.mode in ("app", "hybrid")
                    and self._in_class
                    and self._in_method
                    and isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"):
                field_name = target.attr
                state_names = [f for f, _ in self._class_state_fields.get(self._in_class, [])]
                if field_name in state_names:
                    self._emit(f"this._{field_name}.value = {value_js};")
                    continue

            target_js = self._assign_target_decl(target)
            if target_js is not None:
                self._emit(f"{target_js} = {value_js};")

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value:
            target_js = self._assign_target_decl(node.target)
            self._emit(f"{target_js} = {self._expr(node.value)};")

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        target_js = self._assign_target(node.target)
        op_type = type(node.op)
        if op_type == ast.FloorDiv:
            self._emit(f"{target_js} = Math.floor({target_js} / {self._expr(node.value)});")
        elif op_type in _AUGASSIGN_MAP and _AUGASSIGN_MAP[op_type]:
            self._emit(f"{target_js} {_AUGASSIGN_MAP[op_type]} {self._expr(node.value)};")
        else:
            self._error(node, f"Unsupported augmented assignment operator: {op_type.__name__}")

    def _assign_target(self, target: ast.expr) -> str | None:
        """Convert an assignment target to JS lvalue (no 'let' prefix)."""
        if isinstance(target, ast.Name):
            return target.id
        if isinstance(target, ast.Attribute):
            return self._expr(target)
        if isinstance(target, ast.Subscript):
            return self._expr(target)
        if isinstance(target, (ast.Tuple, ast.List)):
            # Destructuring
            elts = [self._assign_target(e) or self._expr(e) for e in target.elts]
            return f"[{', '.join(elts)}]"
        return self._expr(target)

    def _assign_target_decl(self, target: ast.expr) -> str:
        """Convert an assignment target to JS with 'let' declaration where appropriate."""
        raw = self._assign_target(target)
        if isinstance(target, (ast.Attribute, ast.Subscript)):
            return raw  # no declaration needed for property/index assignment
        if self._in_class and not self._in_method:
            return raw  # class body — no let

        # Track variable names to avoid re-declaring with let
        names = self._extract_names(target)
        scope = self._declared_vars[-1]
        all_new = all(n not in scope for n in names)
        scope.update(names)

        if all_new:
            # Top-level module scope (depth 1 = initial scope, no nesting)
            if (not self._in_class
                    and not self._in_method
                    and len(self._declared_vars) == 1):
                return f"export let {raw}"
            return f"let {raw}"
        return raw

    def _extract_names(self, target: ast.expr) -> list[str]:
        """Extract variable names from an assignment target."""
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, (ast.Tuple, ast.List)):
            names = []
            for e in target.elts:
                names.extend(self._extract_names(e))
            return names
        if isinstance(target, ast.Starred):
            return self._extract_names(target.value)
        return []

    def _push_scope(self) -> None:
        self._declared_vars.append(set())

    def _pop_scope(self) -> None:
        self._declared_vars.pop()

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self._emit(f"delete {self._expr(target)};")

    def visit_Pass(self, node: ast.Pass) -> None:
        # No-op; emit nothing (or a comment for readability)
        pass

    def visit_Break(self, node: ast.Break) -> None:
        self._emit("break;")

    def visit_Continue(self, node: ast.Continue) -> None:
        self._emit("continue;")

    def visit_Global(self, node: ast.Global) -> None:
        # Silently ignoring `global x; x = ...` made the rebind a new LOCAL in JS
        # (a silent bug). Fail loudly.
        self._error(node, f"`global {', '.join(node.names)}` is not supported — keep the "
                          "variable at module scope and assign it directly, or pass it "
                          "in/return it instead of rebinding a global.")

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self._error(node, f"`nonlocal {', '.join(node.names)}` is not supported — "
                          "restructure to pass values in/out rather than rebinding an "
                          "enclosing variable.")

    # -- Control flow ------------------------------------------------------

    def _collect_assigned_names(self, stmts: list[ast.stmt]) -> list[str]:
        """Simple Name targets assigned anywhere in ``stmts``.

        Recurses into compound statements but not into nested functions/classes
        (their own scopes). Used to hoist declarations: Python variables are
        function-scoped, so a first assignment inside a branch must not become
        a block-scoped ``let`` in JS.
        """
        names: list[str] = []

        def collect_target(t: ast.expr) -> None:
            if isinstance(t, ast.Name):
                names.append(t.id)
            elif isinstance(t, (ast.Tuple, ast.List)):
                for e in t.elts:
                    collect_target(e)
            elif isinstance(t, ast.Starred):
                collect_target(t.value)

        def walk(stmt_list: list[ast.stmt]) -> None:
            for stmt in stmt_list:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if isinstance(stmt, ast.Assign):
                    for t in stmt.targets:
                        collect_target(t)
                elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
                    collect_target(stmt.target)
                for field in ("body", "orelse", "finalbody"):
                    walk(getattr(stmt, field, []) or [])
                for handler in getattr(stmt, "handlers", []) or []:
                    walk(handler.body)

        walk(stmts)
        return list(dict.fromkeys(names))

    def _hoist_branch_declarations(self, *stmt_lists: list[ast.stmt], force: bool = False) -> None:
        """Emit ``let`` upfront for names first assigned inside nested blocks.

        Only inside function/method scopes — module-level keeps the existing
        ``export let`` behavior — UNLESS ``force`` is set. force=True is used for
        game/hybrid ``while`` loops: the loop-hoister later relocates the loop
        body into the Phaser ``update`` function, so a variable first assigned
        inside an if/else in the loop must be declared at module scope (not
        block-scoped) or it's undefined once moved.
        """
        if len(self._declared_vars) <= 1 and not force:
            return
        names: list[str] = []
        for sl in stmt_lists:
            names.extend(self._collect_assigned_names(sl))
        scope = self._declared_vars[-1]
        new = [n for n in dict.fromkeys(names) if n not in scope]
        if new:
            self._emit(f"let {', '.join(new)};")
            scope.update(new)

    def visit_If(self, node: ast.If) -> None:
        self._hoist_branch_declarations(node.body, node.orelse)
        self._emit(f"if ({self._truthy(node.test)}) {{")
        with self._indent_block():
            self._emit_body(node.body)
        # Handle elif chain
        orelse = node.orelse
        while orelse:
            if len(orelse) == 1 and isinstance(orelse[0], ast.If):
                elif_node = orelse[0]
                self._emit(f"}} else if ({self._expr(elif_node.test)}) {{")
                with self._indent_block():
                    self._emit_body(elif_node.body)
                orelse = elif_node.orelse
            else:
                self._emit("} else {")
                with self._indent_block():
                    self._emit_body(orelse)
                orelse = []
        self._emit("}")

    def visit_For(self, node: ast.For) -> None:
        self._hoist_branch_declarations(node.body, node.orelse)
        # Detect range() pattern
        if self._is_range_call(node.iter):
            self._emit_range_for(node)
            return

        # Detect dict.items() pattern
        if self._is_items_call(node.iter):
            target_js = self._assign_target(node.target)
            obj_js = self._expr(node.iter.func.value)
            self._emit(f"for (let {target_js} of Object.entries({obj_js})) {{")
            with self._indent_block():
                self._emit_body(node.body)
            self._emit("}")
            return

        # Detect enumerate() pattern
        if (isinstance(node.iter, ast.Call)
                and isinstance(node.iter.func, ast.Name)
                and node.iter.func.id == "enumerate"):
            iterable = self._expr(node.iter.args[0]) if node.iter.args else "[]"
            if isinstance(node.target, (ast.Tuple, ast.List)) and len(node.target.elts) == 2:
                idx = self._expr(node.target.elts[0])
                val = self._expr(node.target.elts[1])
                self._emit(f"for (let [{idx}, {val}] of {iterable}.entries()) {{")
            else:
                tgt = self._expr(node.target)
                self._emit(f"for (let {tgt} of {iterable}.entries()) {{")
            with self._indent_block():
                self._emit_body(node.body)
            self._emit("}")
            return

        target_js = self._expr(node.target)
        iter_js = self._expr(node.iter)
        self._emit(f"for (let {target_js} of {iter_js}) {{")
        with self._indent_block():
            self._emit_body(node.body)
        self._emit("}")
        if node.orelse:
            # for...else not directly supported; emit with flag
            self._error(node, "for...else is not supported; rewrite without else clause")

    def _is_range_call(self, node: ast.expr) -> bool:
        return (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "range")

    def _emit_range_for(self, node: ast.For) -> None:
        args = node.iter.args
        var = self._expr(node.target)
        if len(args) == 1:
            end = self._expr(args[0])
            self._emit(f"for (let {var} = 0; {var} < {end}; {var}++) {{")
        elif len(args) == 2:
            start = self._expr(args[0])
            end = self._expr(args[1])
            self._emit(f"for (let {var} = {start}; {var} < {end}; {var}++) {{")
        elif len(args) == 3:
            start = self._expr(args[0])
            end = self._expr(args[1])
            step = self._expr(args[2])
            self._emit(f"for (let {var} = {start}; {var} < {end}; {var} += {step}) {{")
        else:
            self._error(node, "range() takes 1-3 arguments")
            return
        with self._indent_block():
            self._emit_body(node.body)
        self._emit("}")

    def _is_items_call(self, node: ast.expr) -> bool:
        return (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "items"
                and not node.args)

    def visit_While(self, node: ast.While) -> None:
        # Game/hybrid loop bodies become the Phaser update fn — hoist their
        # branch-first-assigned vars to module scope so they survive the move.
        self._hoist_branch_declarations(node.body, force=self.mode in ("game", "hybrid"))
        self._emit(f"while ({self._truthy(node.test)}) {{")
        with self._indent_block():
            self._emit_body(node.body)
        self._emit("}")
        if node.orelse:
            self._error(node, "while...else is not supported; rewrite without else clause")

    def visit_With(self, node: ast.With) -> None:
        self._hoist_branch_declarations(node.body)
        # No direct JS equivalent for general `with`; emit as block with comment
        self._emit("{ // with block")
        with self._indent_block():
            for item in node.items:
                ctx = self._expr(item.context_expr)
                if item.optional_vars:
                    var = self._expr(item.optional_vars)
                    self._emit(f"let {var} = {ctx};")
                else:
                    self._emit(f"{ctx};")
            self._emit_body(node.body)
        self._emit("}")

    # -- Exception handling ------------------------------------------------

    def visit_Try(self, node: ast.Try) -> None:
        handler_bodies = [handler.body for handler in node.handlers]
        self._hoist_branch_declarations(node.body, node.orelse, node.finalbody, *handler_bodies)
        self._emit("try {")
        with self._indent_block():
            self._emit_body(node.body)

        for handler in node.handlers:
            if handler.name:
                self._emit(f"}} catch ({handler.name}) {{")
            else:
                self._emit("} catch (_err) {")
            with self._indent_block():
                self._emit_body(handler.body)

        if not node.handlers:
            # try without except must have finally
            pass

        if node.finalbody:
            self._emit("} finally {")
            with self._indent_block():
                self._emit_body(node.finalbody)

        self._emit("}")

        if node.orelse:
            # try...else -> emit after try (no direct JS equivalent)
            self._emit("// try-else block:")
            self._emit_body(node.orelse)

    # Python 3.11+ TryStar not handled (except*)
    visit_TryStar = visit_Try

    def visit_Raise(self, node: ast.Raise) -> None:
        if node.exc:
            exc_js = self._expr_as_exception(node.exc)
            if node.cause:
                self._emit(f"throw {exc_js}; // caused by: {self._expr(node.cause)}")
            else:
                self._emit(f"throw {exc_js};")
        else:
            self._emit("throw _err;")

    def _expr_as_exception(self, node: ast.expr) -> str:
        """Emit an expression for use after 'throw', ensuring 'new' is prepended for constructors."""
        if isinstance(node, ast.Call):
            func = node.func
            # Map Python exception names to JS Error
            _EXCEPTION_MAP = {
                "Exception": "Error",
                "ValueError": "Error",
                "TypeError": "TypeError",
                "KeyError": "Error",
                "IndexError": "RangeError",
                "AttributeError": "Error",
                "RuntimeError": "Error",
                "NotImplementedError": "Error",
                "StopIteration": "Error",
                "OSError": "Error",
                "IOError": "Error",
            }
            if isinstance(func, ast.Name) and func.id in _EXCEPTION_MAP:
                js_name = _EXCEPTION_MAP[func.id]
                args_js = self._call_args(node)
                return f"new {js_name}({args_js})"
            # Generic: assume it's a constructor
            func_js = self._expr(func)
            args_js = self._call_args(node)
            return f"new {func_js}({args_js})"
        # If it's a name (re-raise a variable), just emit it
        return self._expr(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        test = self._expr(node.test)
        if node.msg:
            msg = self._expr(node.msg)
            self._emit(f'if (!({test})) {{ throw new Error({msg}); }}')
        else:
            self._emit(f'if (!({test})) {{ throw new Error("Assertion failed: {test}"); }}')

    # -- Yield / Await -----------------------------------------------------

    def visit_Yield(self, node: ast.Yield) -> str:
        if node.value:
            return f"yield {self._expr(node.value)}"
        return "yield"

    def visit_YieldFrom(self, node: ast.YieldFrom) -> str:
        return f"yield* {self._expr(node.value)}"

    # -- Expressions (all return strings) ----------------------------------

    def _expr(self, node: ast.expr | None) -> str:
        """Convert an expression node to a JavaScript string."""
        if node is None:
            return "undefined"

        method = f"_expr_{type(node).__name__}"
        if hasattr(self, method):
            return getattr(self, method)(node)

        # Fallback: try generic_visit
        self._error(node, f"Unsupported expression type: {type(node).__name__}")
        return f"/* unsupported: {type(node).__name__} */"

    def _expr_Constant(self, node: ast.Constant) -> str:
        if node.value is None:
            return "null"
        if node.value is True:
            return "true"
        if node.value is False:
            return "false"
        if isinstance(node.value, str):
            # Check for v"..." raw JS literal
            # This is detected at the JoinedStr / FormattedValue level instead
            return self._js_string(node.value)
        if isinstance(node.value, bytes):
            # Bytes literal -> raw string
            return self._js_string(node.value.decode("utf-8", errors="replace"))
        if isinstance(node.value, (int, float)):
            return repr(node.value)
        if isinstance(node.value, complex):
            return f"/* complex: {node.value} */"
        if node.value is ...:
            return "undefined"
        return repr(node.value)

    def _js_string(self, s: str) -> str:
        """Emit a JavaScript string literal. Convert [[expr]] to template literal."""
        if "[[" in s and "]]" in s:
            return self._template_literal(s)
        # Escape for JS
        escaped = s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        return f"'{escaped}'"

    def _template_literal(self, s: str) -> str:
        """Convert [[expr]] interpolation to JS template literal ${expr}."""
        result = s.replace("\\", "\\\\").replace("`", "\\`")
        result = re.sub(r'\[\[(.+?)\]\]', r'${\1}', result)
        return f"`{result}`"

    def _expr_JoinedStr(self, node: ast.JoinedStr) -> str:
        """f-strings -> template literals."""
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value).replace("`", "\\`").replace("\\", "\\\\"))
            elif isinstance(value, ast.FormattedValue):
                expr_js = self._expr(value.value)
                if value.format_spec:
                    # Format spec not directly translatable; just use expression
                    parts.append(f"${{{expr_js}}}")
                else:
                    parts.append(f"${{{expr_js}}}")
            else:
                parts.append(f"${{{self._expr(value)}}}")
        return f"`{''.join(parts)}`"

    def _expr_Name(self, node: ast.Name) -> str:
        name = node.id
        if name == "self":
            return "this"
        if name == "None":
            return "null"
        if name == "True":
            return "true"
        if name == "False":
            return "false"
        # Check if reading a state field
        if (self.mode in ("app", "hybrid")
                and self._in_class
                and self._in_method
                and name in [f for f, _ in self._class_state_fields.get(self._in_class, [])]):
            return f"this._{name}.value"
        return name

    def _expr_Attribute(self, node: ast.Attribute) -> str:
        value_js = self._expr(node.value)
        attr = node.attr

        # self.x -> this.x (with state signal awareness)
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            if (self.mode in ("app", "hybrid") and self._in_class):
                state_names = [f for f, _ in self._class_state_fields.get(self._in_class, [])]
                if attr in state_names:
                    return f"this._{attr}.value"
            return f"this.{attr}"

        # __name__ -> .name (for type/class checks)
        if attr == "__name__":
            return f"{value_js}.name"
        if attr == "__class__":
            return f"{value_js}.constructor"
        if attr == "__dict__":
            return f"Object.entries({value_js})"

        return f"{value_js}.{attr}"

    def _expr_Subscript(self, node: ast.Subscript) -> str:
        value_js = self._expr(node.value)
        sl = node.slice

        # Slice
        if isinstance(sl, ast.Slice):
            return self._emit_slice(value_js, sl)

        idx_js = self._expr(sl)
        # Negative indexing
        if isinstance(sl, ast.UnaryOp) and isinstance(sl.op, ast.USub):
            return f"{value_js}.at({idx_js})"

        return f"{value_js}[{idx_js}]"

    def _emit_slice(self, value_js: str, sl: ast.Slice) -> str:
        lower = self._expr(sl.lower) if sl.lower else "0"
        upper = self._expr(sl.upper) if sl.upper else ""
        step = self._expr(sl.step) if sl.step else None

        if step:
            # Step slices (incl. negative like arr[::-1]) need Python semantics —
            # the old `.slice().filter(i % step)` had wrong indices.
            lo = self._expr(sl.lower) if sl.lower else "null"
            hi = self._expr(sl.upper) if sl.upper else "null"
            return f"__slice({value_js}, {lo}, {hi}, {step})"

        if upper:
            return f"{value_js}.slice({lower}, {upper})"
        if sl.lower:
            return f"{value_js}.slice({lower})"
        return f"{value_js}.slice()"

    def _expr_Starred(self, node: ast.Starred) -> str:
        return f"...{self._expr(node.value)}"

    def _expr_Call(self, node: ast.Call) -> str:
        # Special-case certain builtins and patterns
        func = node.func

        # v"..." raw JS literal: Call(func=Name('v'), args=[Constant(str)])
        # Actually in Python ast, v"..." is parsed as a name 'v' followed by a string
        # This is NOT valid Python. RapydScript uses it as special syntax.
        # In standard Python we detect it differently - see _expr_Constant for string handling.

        # Handle: super().__init__(...) -> super(...)
        if (isinstance(func, ast.Attribute)
                and func.attr == "__init__"
                and isinstance(func.value, ast.Call)
                and isinstance(func.value.func, ast.Name)
                and func.value.func.id == "super"):
            args_js = self._call_args(node)
            return f"super({args_js})"

        # super() alone -> super
        if isinstance(func, ast.Name) and func.id == "super" and not node.args:
            return "super"

        # print() -> console.log()
        if isinstance(func, ast.Name) and func.id == "print":
            args_js = self._call_args(node)
            return f"console.log({args_js})"

        # len(x) -> x.length
        if isinstance(func, ast.Name) and func.id == "len" and len(node.args) == 1:
            arg = self._expr(node.args[0])
            return f"{arg}.length"

        # isinstance(x, T) -> x instanceof T
        if isinstance(func, ast.Name) and func.id == "isinstance" and len(node.args) == 2:
            obj = self._expr(node.args[0])
            typ = self._expr(node.args[1])
            return f"({obj} instanceof {typ})"

        # hasattr(x, 'a') -> 'a' in x
        if isinstance(func, ast.Name) and func.id == "hasattr" and len(node.args) == 2:
            obj = self._expr(node.args[0])
            attr = self._expr(node.args[1])
            return f"({attr} in {obj})"

        # getattr(x, 'a') -> x['a'] or x['a'] ?? default
        if isinstance(func, ast.Name) and func.id == "getattr":
            obj = self._expr(node.args[0])
            attr = self._expr(node.args[1])
            if len(node.args) >= 3:
                default = self._expr(node.args[2])
                return f"({obj}[{attr}] ?? {default})"
            return f"{obj}[{attr}]"

        # setattr(x, 'a', v) -> x['a'] = v
        if isinstance(func, ast.Name) and func.id == "setattr" and len(node.args) == 3:
            obj = self._expr(node.args[0])
            attr = self._expr(node.args[1])
            val = self._expr(node.args[2])
            return f"({obj}[{attr}] = {val})"

        # sum(iter) -> iter.reduce((a, b) => a + b, 0)
        if isinstance(func, ast.Name) and func.id == "sum" and len(node.args) >= 1:
            arg = self._expr(node.args[0])
            start = self._expr(node.args[1]) if len(node.args) > 1 else "0"
            return f"{arg}.reduce((a, b) => a + b, {start})"

        # any(iter) -> iter.some(Boolean)
        if isinstance(func, ast.Name) and func.id == "any" and len(node.args) == 1:
            return f"{self._expr(node.args[0])}.some(Boolean)"

        # all(iter) -> iter.every(Boolean)
        if isinstance(func, ast.Name) and func.id == "all" and len(node.args) == 1:
            return f"{self._expr(node.args[0])}.every(Boolean)"

        # sorted(x) -> [...x].sort()
        if isinstance(func, ast.Name) and func.id == "sorted":
            arg = self._expr(node.args[0]) if node.args else "[]"
            # Check for key= kwarg
            key_fn = None
            reverse = False
            for kw in node.keywords:
                if kw.arg == "key":
                    key_fn = self._expr(kw.value)
                elif kw.arg == "reverse":
                    reverse = True
            if key_fn and reverse:
                return f"[...{arg}].sort((a, b) => {{ const _kf = {key_fn}; let ka = _kf(a), kb = _kf(b); return ka < kb ? 1 : ka > kb ? -1 : 0; }})"
            if key_fn:
                return f"[...{arg}].sort((a, b) => {{ const _kf = {key_fn}; let ka = _kf(a), kb = _kf(b); return ka < kb ? -1 : ka > kb ? 1 : 0; }})"
            if reverse:
                return f"[...{arg}].sort().reverse()"
            return f"[...{arg}].sort()"

        # reversed(x) -> [...x].reverse()
        if isinstance(func, ast.Name) and func.id == "reversed" and len(node.args) == 1:
            return f"[...{self._expr(node.args[0])}].reverse()"

        # set(x) -> new Set(x)
        if isinstance(func, ast.Name) and func.id == "set":
            if node.args:
                return f"new Set({self._expr(node.args[0])})"
            return "new Set()"

        # dict(x) -> Object.fromEntries(x) or {}
        if isinstance(func, ast.Name) and func.id == "dict":
            if node.args:
                return f"Object.fromEntries({self._expr(node.args[0])})"
            if node.keywords:
                pairs = []
                for kw in node.keywords:
                    if kw.arg:
                        pairs.append(f"{kw.arg}: {self._expr(kw.value)}")
                    else:
                        pairs.append(f"...{self._expr(kw.value)}")
                return f"{{{', '.join(pairs)}}}"
            return "{}"

        # type(x) -> typeof x (rough approximation)
        if isinstance(func, ast.Name) and func.id == "type" and len(node.args) == 1:
            return f"typeof {self._expr(node.args[0])}"

        # map(fn, iter) -> iter.map(fn)
        if isinstance(func, ast.Name) and func.id == "map" and len(node.args) == 2:
            fn = self._expr(node.args[0])
            it = self._expr(node.args[1])
            return f"{it}.map({fn})"

        # filter(fn, iter) -> iter.filter(fn)
        if isinstance(func, ast.Name) and func.id == "filter" and len(node.args) == 2:
            fn = self._expr(node.args[0])
            it = self._expr(node.args[1])
            return f"{it}.filter({fn})"

        # zip(a, b) -> a.map((x, i) => [x, b[i]])
        if isinstance(func, ast.Name) and func.id == "zip" and len(node.args) == 2:
            a = self._expr(node.args[0])
            b = self._expr(node.args[1])
            return f"{a}.map((_x, _i) => [_x, {b}[_i]])"

        # enumerate(iter) -> iter.map((v, i) => [i, v])
        if isinstance(func, ast.Name) and func.id == "enumerate" and len(node.args) == 1:
            it = self._expr(node.args[0])
            return f"{it}.map((_v, _i) => [_i, _v])"

        # state() -> signal() in app mode
        if isinstance(func, ast.Name) and func.id == "state" and self.mode in ("app", "hybrid"):
            args_js = self._call_args(node)
            return f"signal({args_js})"

        # css() -> extract and return empty (CSS handled separately)
        if isinstance(func, ast.Name) and func.id == "css":
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                self.css_chunks.append(node.args[0].value)
            return "null /* css extracted */"

        # String method translations
        if isinstance(func, ast.Attribute) and func.attr in _STRING_METHOD_MAP:
            obj = self._expr(func.value)
            js_method = _STRING_METHOD_MAP[func.attr]
            args_js = self._call_args(node)

            if func.attr == "count":
                # s.count(x) -> s.split(x).length - 1
                return f"({obj}.split({args_js}).length - 1)"
            if func.attr == "isdigit":
                return f"/^\\d+$/.test({obj})"
            if func.attr == "join":
                # Python: sep.join(list) -> JS: list.join(sep)
                return f"{args_js}.join({obj})"
            return f"{obj}.{js_method}({args_js})"

        # .append() -> .push()
        if isinstance(func, ast.Attribute) and func.attr == "append":
            obj = self._expr(func.value)
            args_js = self._call_args(node)
            return f"{obj}.push({args_js})"

        # .extend() -> .push(...x)
        if isinstance(func, ast.Attribute) and func.attr == "extend":
            obj = self._expr(func.value)
            args_js = self._call_args(node)
            return f"{obj}.push(...{args_js})"

        # .pop() -> .pop()  (same)
        # .insert(i, x) -> .splice(i, 0, x)
        if isinstance(func, ast.Attribute) and func.attr == "insert" and len(node.args) == 2:
            obj = self._expr(func.value)
            idx = self._expr(node.args[0])
            val = self._expr(node.args[1])
            return f"{obj}.splice({idx}, 0, {val})"

        # .remove(x) -> .splice(.indexOf(x), 1)
        if isinstance(func, ast.Attribute) and func.attr == "remove" and len(node.args) == 1:
            obj = self._expr(func.value)
            val = self._expr(node.args[0])
            return f"{obj}.splice({obj}.indexOf({val}), 1)"

        # .keys() -> Object.keys()
        if isinstance(func, ast.Attribute) and func.attr == "keys" and not node.args:
            obj = self._expr(func.value)
            return f"Object.keys({obj})"

        # .values() -> Object.values()
        if isinstance(func, ast.Attribute) and func.attr == "values" and not node.args:
            obj = self._expr(func.value)
            return f"Object.values({obj})"

        # .items() -> Object.entries()
        if isinstance(func, ast.Attribute) and func.attr == "items" and not node.args:
            obj = self._expr(func.value)
            return f"Object.entries({obj})"

        # .get(key, default) -> (obj[key] ?? default)
        # Only apply when exactly 1 or 2 positional args (dict-like usage)
        if (isinstance(func, ast.Attribute) and func.attr == "get"
                and 1 <= len(node.args) <= 2 and not node.keywords):
            obj = self._expr(func.value)
            key = self._expr(node.args[0])
            default = self._expr(node.args[1]) if len(node.args) > 1 else "undefined"
            return f"({obj}[{key}] ?? {default})"

        # .update(other) -> Object.assign(obj, other)
        if isinstance(func, ast.Attribute) and func.attr == "update" and len(node.args) == 1:
            obj = self._expr(func.value)
            other = self._expr(node.args[0])
            return f"Object.assign({obj}, {other})"

        # Generic builtins from map
        if isinstance(func, ast.Name) and func.id in _BUILTIN_MAP:
            mapped = _BUILTIN_MAP[func.id]
            if mapped:
                args_js = self._call_args(node)
                return f"{mapped}({args_js})"

        # General call — add `new` for class instantiation (PascalCase names),
        # INCLUDING attribute constructors for the runtime CLASSES `pg.Surface(...)`
        # / `pg.Rect(...)` / `pg.sprite.Sprite(...)`. The original heuristic only
        # covered bare Names, so `pg.Surface(w,h)` compiled to a plain call and
        # crashed at runtime ("Class constructor Surface cannot be invoked without
        # 'new'"). NOTE: only real `class` exports get `new` here — the runtime's
        # other PascalCase callables (Group/Font/SysFont/Sound/Clock) are
        # method-shorthand FACTORIES, which are NOT constructors and would throw on
        # `new`, so they must stay plain calls.
        func_js = self._expr(func)
        args_js = self._call_args(node)
        _NO_NEW = ("String", "Boolean", "Number", "Array", "Object", "Set", "Map",
                   "Error", "TypeError", "ValueError", "KeyError", "Fragment",
                   "Promise", "Template")
        # Runtime classes that are reached as attributes (e.g. `pg.Surface`) and
        # genuinely need `new`. Factories (Group/Font/Sound/Clock) are excluded.
        _ATTR_CLASSES = ("Surface", "Rect", "Sprite")
        new_ctor = False
        if (isinstance(func, ast.Name) and func.id[0].isupper()
                and func.id not in _BUILTIN_MAP and func.id not in _NO_NEW):
            new_ctor = True
        elif isinstance(func, ast.Attribute) and func.attr in _ATTR_CLASSES:
            new_ctor = True
        if new_ctor:
            return f"new {func_js}({args_js})"
        return f"{func_js}({args_js})"

    def _call_args(self, node: ast.Call) -> str:
        """Build the arguments portion of a function call."""
        parts: list[str] = []
        for arg in node.args:
            parts.append(self._expr(arg))
        for kw in node.keywords:
            if kw.arg is None:
                # **kwargs spread
                parts.append(f"...{self._expr(kw.value)}")
            else:
                # keyword args: emit as object if mixed, or positional if simple
                pass  # handled below

        # If there are keyword arguments, wrap them in an object as last arg
        kw_parts = []
        for kw in node.keywords:
            if kw.arg is not None:
                kw_parts.append(f"{kw.arg}: {self._expr(kw.value)}")

        if kw_parts:
            self._maybe_warn_native_kwargs(node)
            positional = [self._expr(a) for a in node.args]
            spreads = [f"...{self._expr(kw.value)}" for kw in node.keywords if kw.arg is None]

            # For constructor calls like super().__init__(a=1, b=2),
            # some calls genuinely take keyword args as an object
            # Use heuristic: if calling a known class/constructor or Python-like function,
            # pass kwargs as object
            obj = "{" + ", ".join(kw_parts) + "}"
            all_parts = positional + spreads + [obj]
            return ", ".join(all_parts)

        return ", ".join(parts)

    def _maybe_warn_native_kwargs(self, node: ast.Call) -> None:
        """Warn when kwargs are passed to a call rooted at a native JS global.

        Kwargs always compile to a single trailing object literal, which is
        the PyLevate convention for components/stores but is generally wrong
        for native browser/JS APIs that expect positional arguments.
        """
        func = node.func
        while isinstance(func, ast.Attribute):
            func = func.value
        if not isinstance(func, ast.Name):
            return
        root = func.id
        if root not in _JS_NATIVE_ROOTS:
            return
        kw_example = next(kw.arg for kw in node.keywords if kw.arg is not None)
        self._warn(
            node,
            f"Keyword arguments compile to a single trailing object literal "
            f"(…, {{{kw_example}: …}}), but '{root}' is a native JS API that "
            f"generally takes positional arguments. If the object form is what "
            f"you want, pass a dict literal explicitly; otherwise use positional "
            f"arguments or a v\"...\" verbatim JS literal.",
        )

    # --- Python-style truthiness -----------------------------
    # Empty collections are falsy in Python but truthy in JS. Wrap boolean-context
    # tests in __truthy(...) (baselib), except where the expression is already a
    # boolean so we don't add noise.
    def _is_bool_expr(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Compare):
            return True
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return True
        if isinstance(node, ast.BoolOp):
            return all(self._is_bool_expr(v) for v in node.values)
        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in {"bool", "isinstance", "hasattr", "all", "any", "callable"}):
            return True
        return False

    def _truthy(self, node: ast.expr) -> str:
        js = self._expr(node)
        return js if self._is_bool_expr(node) else f"__truthy({js})"

    def _expr_BoolOp(self, node: ast.BoolOp) -> str:
        op = _BOOLOP_MAP[type(node.op)]
        parts = [self._expr(v) for v in node.values]
        return f" {op} ".join(parts)

    def _expr_BinOp(self, node: ast.BinOp) -> str:
        left = self._expr(node.left)
        right = self._expr(node.right)
        op_type = type(node.op)

        if op_type == ast.FloorDiv:
            return f"Math.floor({left} / {right})"
        if op_type == ast.MatMult:
            self._error(node, "Matrix multiplication (@) is not supported in JavaScript")
            return f"/* matmul */ ({left} @ {right})"

        op = _BINOP_MAP.get(op_type)
        if op:
            return f"({left} {op} {right})"
        return f"({left} /* unknown op */ {right})"

    def _expr_UnaryOp(self, node: ast.UnaryOp) -> str:
        op = _UNARYOP_MAP.get(type(node.op), "?")
        # `not x` needs Python truthiness so `not []` is True.
        if isinstance(node.op, ast.Not):
            return f"!__truthy({self._expr(node.operand)})"
        operand = self._expr(node.operand)
        return f"{op}{operand}"

    def _expr_Compare(self, node: ast.Compare) -> str:
        parts: list[str] = []
        left = self._expr(node.left)

        for op, comparator in zip(node.ops, node.comparators):
            right = self._expr(comparator)
            op_type = type(op)

            if op_type == ast.In:
                parts.append(f"{right}.includes({left})")
            elif op_type == ast.NotIn:
                parts.append(f"!{right}.includes({left})")
            else:
                js_op = _CMPOP_MAP.get(op_type, "===")
                parts.append(f"{left} {js_op} {right}")

            left = right

        return " && ".join(parts) if len(parts) > 1 else parts[0]

    def _expr_IfExp(self, node: ast.IfExp) -> str:
        """Ternary: x if cond else y -> cond ? x : y"""
        test = self._truthy(node.test)
        body = self._expr(node.body)
        orelse = self._expr(node.orelse)
        return f"({test} ? {body} : {orelse})"

    def _expr_Lambda(self, node: ast.Lambda) -> str:
        params = self._build_params(node.args, False)
        body = self._expr(node.body)
        return f"({params}) => {body}"

    def _expr_Dict(self, node: ast.Dict) -> str:
        pairs: list[str] = []
        for key, value in zip(node.keys, node.values):
            if key is None:
                # {**other}
                pairs.append(f"...{self._expr(value)}")
            else:
                key_js = self._expr(key)
                val_js = self._expr(value)
                # If key is a string constant, use it directly
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    # Use identifier-safe key or bracket notation
                    k = key.value
                    if k.isidentifier():
                        pairs.append(f"{k}: {val_js}")
                    else:
                        pairs.append(f"{key_js}: {val_js}")
                else:
                    pairs.append(f"[{key_js}]: {val_js}")
        return "{" + ", ".join(pairs) + "}"

    def _expr_List(self, node: ast.List) -> str:
        elts = [self._expr(e) for e in node.elts]
        return f"[{', '.join(elts)}]"

    def _expr_Tuple(self, node: ast.Tuple) -> str:
        # Tuples -> arrays in JS
        elts = [self._expr(e) for e in node.elts]
        return f"[{', '.join(elts)}]"

    def _expr_Set(self, node: ast.Set) -> str:
        elts = [self._expr(e) for e in node.elts]
        return f"new Set([{', '.join(elts)}])"

    # -- Comprehensions ----------------------------------------------------

    def _expr_ListComp(self, node: ast.ListComp) -> str:
        return self._emit_comprehension(node.elt, node.generators)

    def _expr_SetComp(self, node: ast.SetComp) -> str:
        inner = self._emit_comprehension(node.elt, node.generators)
        return f"new Set({inner})"

    def _expr_DictComp(self, node: ast.DictComp) -> str:
        # Object.fromEntries(iter.map(...))
        gen = node.generators[0]
        iter_js = f"__iter({self._expr(gen.iter)})"
        target_js = self._arrow_param(gen.target)
        key_js = self._expr(node.key)
        val_js = self._expr(node.value)

        result = f"{iter_js}"

        # Apply filters
        for cond in gen.ifs:
            result = f"{result}.filter(({target_js}) => {self._truthy(cond)})"

        result = f"Object.fromEntries({result}.map(({target_js}) => [{key_js}, {val_js}]))"

        # Handle nested generators
        for extra_gen in node.generators[1:]:
            self._error(node, "Nested dict comprehension generators are not fully supported")

        return result

    def _expr_GeneratorExp(self, node: ast.GeneratorExp) -> str:
        # Emit as array (generators don't exist the same way in JS)
        return self._emit_comprehension(node.elt, node.generators)

    def _arrow_param(self, target: ast.expr) -> str:
        """Emit an expression as an arrow function parameter (wraps tuples in destructuring)."""
        return self._expr(target)

    def _emit_comprehension(self, elt: ast.expr, generators: list[ast.comprehension]) -> str:
        """Emit [expr for x in iter if cond] -> iter.filter(...).map(...)"""
        if not generators:
            return "[]"

        gen = generators[0]
        iter_js = f"__iter({self._expr(gen.iter)})"
        target_js = self._arrow_param(gen.target)
        elt_js = self._expr(elt)

        result = iter_js

        # Detect range() and convert
        if self._is_range_call(gen.iter):
            result = self._range_to_array(gen.iter)

        # Apply filters
        for cond in gen.ifs:
            result = f"{result}.filter(({target_js}) => {self._truthy(cond)})"

        # Map to element expression
        if elt_js != target_js:
            result = f"{result}.map(({target_js}) => {elt_js})"

        # Handle nested generators (flatMap)
        for extra_gen in generators[1:]:
            inner_iter = self._expr(extra_gen.iter)
            inner_target = self._arrow_param(extra_gen.target)
            inner_elt = elt_js  # already set
            inner = inner_iter
            for cond in extra_gen.ifs:
                inner = f"{inner}.filter(({inner_target}) => {self._truthy(cond)})"
            result = f"{result}.flatMap(({target_js}) => {inner}.map(({inner_target}) => {inner_elt}))"

        return result

    def _range_to_array(self, node: ast.Call) -> str:
        """Convert range(n) to Array.from({length: n}, (_, i) => i)."""
        args = node.args
        if len(args) == 1:
            n = self._expr(args[0])
            return f"Array.from({{length: {n}}}, (_, _i) => _i)"
        elif len(args) == 2:
            start = self._expr(args[0])
            end = self._expr(args[1])
            return f"Array.from({{length: {end} - {start}}}, (_, _i) => _i + {start})"
        elif len(args) == 3:
            start = self._expr(args[0])
            end = self._expr(args[1])
            step = self._expr(args[2])
            return f"Array.from({{length: Math.ceil(({end} - {start}) / {step})}}, (_, _i) => {start} + _i * {step})"
        return "[]"

    # -- Await / NamedExpr -------------------------------------------------

    def _expr_Await(self, node: ast.Await) -> str:
        return f"await {self._expr(node.value)}"

    def _expr_NamedExpr(self, node: ast.NamedExpr) -> str:
        # Walrus operator: x := expr -> (x = expr)
        target = self._expr(node.target)
        value = self._expr(node.value)
        return f"({target} = {value})"

    # -- Yield inside expressions ------------------------------------------

    def _expr_Yield(self, node: ast.Yield) -> str:
        if node.value:
            return f"yield {self._expr(node.value)}"
        return "yield"

    def _expr_YieldFrom(self, node: ast.YieldFrom) -> str:
        return f"yield* {self._expr(node.value)}"

    # -- Raw JS escape hatch: v"..." ---------------------------------------
    # In Python's AST, a call like v"something" is not valid syntax.
    # We support it as a string with a v prefix that looks like a variable call.
    # Actually, RapydScript's v"..." is parsed in RapydScript, not in Python.
    # For Python source, we support it via a function call: v("raw js here")
    # OR we detect it at the string-concatenation level as Name('v') followed by Constant.
    # The most practical approach: treat any Call to function named 'v' with a string arg
    # as raw JS. Also handle it in Expr visitor.

    # Already handled in _expr_Call implicitly. Let's add explicit support:
    # When we see a bare expression `v"..."`, Python parses it as two tokens:
    # Name('v') and Constant(str) which is invalid. So we'll handle it as v("...") calls.

    # -- Helpers for body emission -----------------------------------------

    def _emit_body(self, stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            # Skip docstrings
            if (isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)):
                continue
            self.visit(stmt)

    def generic_visit(self, node: ast.AST) -> None:
        """Fallback for unhandled node types."""
        self._error(node, f"Unsupported Python construct: {type(node).__name__}")
        self._emit(f"/* unsupported: {type(node).__name__} */")


class _IndentContext:
    """Context manager for indentation."""

    def __init__(self, emitter: _JSEmitter):
        self.emitter = emitter

    def __enter__(self):
        self.emitter._indent += 1
        return self

    def __exit__(self, *args):
        self.emitter._indent -= 1


# ---------------------------------------------------------------------------
# Pre-processing: v"..." raw JS literal rewriting
# ---------------------------------------------------------------------------

_V_LITERAL_RE = re.compile(r'\bv"((?:[^"\\]|\\.)*)"')
_V_LITERAL_SINGLE_RE = re.compile(r"\bv'((?:[^'\\]|\\.)*)'")
# Triple-quoted (multi-line) forms. Must be applied before the single-line
# regexes, which would otherwise mis-match v""" as v"" plus garbage.
_V_TRIPLE_DQ_RE = re.compile(r'\bv"""(.*?)"""', re.DOTALL)
_V_TRIPLE_SQ_RE = re.compile(r"\bv'''(.*?)'''", re.DOTALL)


def _make_triple_replacer(quotes: str):
    def _replace(match: re.Match) -> str:
        content = match.group(1)
        # A raw triple-quoted Python string cannot end with a backslash or a
        # quote character adjacent to the closing quotes; a trailing newline
        # is harmless in verbatim JS and sidesteps both cases.
        if content.endswith("\\") or content.endswith(quotes[0]):
            content += "\n"
        return f"__raw_js__(r{quotes}{content}{quotes})"
    return _replace


def _v_literal_replacement(string_token: str) -> str:
    """Build the __raw_js__ call replacing a v-prefixed string token."""
    for quotes in ('"""', "'''"):
        if string_token.startswith(quotes):
            content = string_token[3:-3]
            # Raw triple-quoted strings cannot end with a backslash or a
            # quote adjacent to the closing quotes; a trailing newline is
            # harmless in verbatim JS.
            if content.endswith("\\") or content.endswith(quotes[0]):
                content += "\n"
            return f"__raw_js__(r{quotes}{content}{quotes})"
    return f"__raw_js__({string_token})"


def _rewrite_v_literals_regex(source: str) -> str:
    """Regex fallback used when the source doesn't tokenize (broken Python).

    Unlike the tokenizer path, this can mis-match v"..." sequences inside
    strings or comments — acceptable for a source that is already invalid.
    """
    source = _V_TRIPLE_DQ_RE.sub(_make_triple_replacer('"""'), source)
    source = _V_TRIPLE_SQ_RE.sub(_make_triple_replacer("'''"), source)
    source = _V_LITERAL_RE.sub(r'__raw_js__("\1")', source)
    source = _V_LITERAL_SINGLE_RE.sub(r"__raw_js__('\1')", source)
    return source


def _rewrite_v_literals(source: str) -> str:
    """Rewrite v"..." / v'...' / v\"\"\"...\"\"\" to __raw_js__(...) so Python's parser accepts them.

    Detection is tokenizer-based: a v-literal is a NAME token `v` immediately
    followed by a STRING token. Occurrences inside ordinary strings,
    docstrings, or comments are single tokens and are left untouched.
    Triple-quoted forms may span multiple lines and are wrapped as raw strings
    so backslashes inside the JS (regexes, escape sequences) survive intact.
    """
    import io
    import tokenize

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return _rewrite_v_literals_regex(source)

    # Collect (name_start, string_end, replacement) spans, positions as
    # (1-based row, 0-based col).
    spans: list[tuple[tuple[int, int], tuple[int, int], str]] = []
    for prev, tok in zip(tokens, tokens[1:]):
        if (prev.type == tokenize.NAME and prev.string == "v"
                and tok.type == tokenize.STRING
                and tok.start == prev.end):
            spans.append((prev.start, tok.end, _v_literal_replacement(tok.string)))

    if not spans:
        return source

    lines = source.splitlines(keepends=True)
    line_offsets = [0]
    for line in lines:
        line_offsets.append(line_offsets[-1] + len(line))

    def _abs(pos: tuple[int, int]) -> int:
        row, col = pos
        return line_offsets[row - 1] + col

    # Replace back-to-front so earlier offsets stay valid.
    for start, end, replacement in reversed(spans):
        source = source[: _abs(start)] + replacement + source[_abs(end):]
    return source


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def _postprocess(js: str) -> str:
    """Clean up the emitted JS and inject missing imports."""
    # Inject missing runtime imports
    js = _inject_missing_imports(js)

    lines = js.split("\n")
    # Remove excessive blank lines
    cleaned: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        cleaned.append(line)
        prev_blank = is_blank
    return "\n".join(cleaned)


def _inject_missing_imports(js: str) -> str:
    """Add imports for symbols used in compiled output but not explicitly imported."""
    needed: list[str] = []
    # Check for symbols that need to be imported from pylevate-runtime
    runtime_symbols = {
        "signal": "signal",
        "Fragment": "Fragment",
        "effect": "effect",
        "computed": "computed",
        "batch": "batch",
        "createTag": "createTag",
    }

    for symbol, import_name in runtime_symbols.items():
        # Check if symbol is used in the code but not in an existing import
        if re.search(rf"\b{symbol}\b", js):
            # Check if already imported
            if not re.search(rf"import\s+.*\b{import_name}\b.*from\s+['\"]pylevate-runtime['\"]", js):
                needed.append(import_name)

    if not needed:
        return js

    # Find the existing pylevate-runtime import line and extend it
    def extend_import(m: re.Match) -> str:
        existing = m.group(1)
        existing_names = [n.strip() for n in existing.split(",")]
        for name in needed:
            if name not in existing_names:
                existing_names.append(name)
        return f"import {{ {', '.join(existing_names)} }} from 'pylevate-runtime'"

    result = re.sub(
        r"import\s*\{\s*([^}]+)\s*\}\s*from\s*'pylevate-runtime'",
        extend_import,
        js,
        count=1,
    )

    # If no existing pylevate-runtime import, add one at the top
    if result == js and needed:
        import_line = f"import {{ {', '.join(needed)} }} from 'pylevate-runtime';\n"
        result = import_line + js

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compile_source(
    source: str,
    filename: str = "<stdin>",
    mode: str = "app",
    *,
    import_ctx: ImportContext | None = None,
) -> CompileResult:
    """
    Compile Python source code to JavaScript.

    Args:
        source:     Python source code string.
        filename:   Name of the source file (for error messages).
        mode:       Compilation mode — "app", "game", or "hybrid".
        import_ctx: Project context for local-import resolution/validation.
                    When omitted, the importer is assumed to sit at the
                    project root and import targets are not validated.

    Returns:
        CompileResult with the generated JS, any CSS chunks found, and errors.
    """
    errors: list[CompileError] = []

    # Pre-process: rewrite v"..." literals
    processed_source = _rewrite_v_literals(source)

    # Parse
    try:
        tree = ast.parse(processed_source, filename=filename)
    except SyntaxError as e:
        errors.append(CompileError(
            file=filename,
            line=e.lineno or 0,
            col=e.offset or 0,
            message=f"Syntax error: {e.msg}",
        ))
        return CompileResult(js="", errors=errors)

    # Emit
    emitter = _JSEmitter(filename=filename, mode=mode, import_ctx=import_ctx)

    # Inject __raw_js__ handler: the emitter treats calls to __raw_js__(str) as raw JS
    _patch_raw_js_support(emitter)

    emitter.visit(tree)
    errors.extend(emitter.errors)

    js = emitter.get_source()
    js = _postprocess(js)

    return CompileResult(
        js=js,
        source_map=None,  # TODO: source map generation
        errors=errors,
        css_chunks=emitter.css_chunks,
        warnings=emitter.warnings,
    )


def _raw_js_payload(node: ast.AST) -> str | None:
    """Return the raw-JS string if *node* is a __raw_js__("...") call, else None."""
    if (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "__raw_js__"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)):
        return node.args[0].value
    return None


def _patch_raw_js_support(emitter: _JSEmitter) -> None:
    """Patch the emitter so __raw_js__("code") emits raw JS."""
    original_expr_call = emitter._expr_Call
    original_visit_expr = emitter.visit_Expr

    def patched_expr_call(node: ast.Call) -> str:
        payload = _raw_js_payload(node)
        if payload is not None:
            # Multi-line raw JS in expression position needs parentheses so
            # constructs like object literals or IIFEs parse unambiguously.
            return f"({payload})" if "\n" in payload else payload
        return original_expr_call(node)

    def patched_visit_expr(node: ast.Expr) -> None:
        # Statement-position raw JS is emitted verbatim (no wrapping parens).
        payload = _raw_js_payload(node.value)
        if payload is not None:
            emitter._emit(f"{payload};")
            return
        original_visit_expr(node)

    emitter._expr_Call = patched_expr_call
    emitter.visit_Expr = patched_visit_expr


# ---------------------------------------------------------------------------
# Convenience: compile a file
# ---------------------------------------------------------------------------

def compile_file(path: str, mode: str = "app") -> CompileResult:
    """Read a Python file and compile it to JavaScript."""
    from pathlib import Path
    p = Path(path)
    source = p.read_text(encoding="utf-8")
    return compile_source(source, filename=str(p), mode=mode)

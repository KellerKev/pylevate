"""Orchestrates the full compilation pipeline: discover, compile, transform, bundle."""

from __future__ import annotations

import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from pylevate.config import Config

log = logging.getLogger(__name__)

# Lazy imports to keep module-level loading light and to tolerate missing
# sibling modules during early development.  Each is imported on first use
# inside the methods that need them.

_EXCLUDED_FILENAMES = {"pylevate.config.py"}


@dataclass
class BuildResult:
    success: bool
    errors: list[str] = field(default_factory=list)
    output_dir: Path = field(default_factory=lambda: Path("."))
    duration_ms: float = 0.0
    bundle_size: int = 0  # bytes
    warnings: list[str] = field(default_factory=list)


class Pipeline:
    """Compile a PyLevate project from Python sources to a bundled JS application.

    Supports both full builds (all sources) and incremental single-file
    rebuilds triggered by the HMR watcher.
    """

    def __init__(self, project_dir: Path, config: Config, production: bool = False) -> None:
        self.project_dir = project_dir.resolve()
        self.config = config
        self.production = production
        self.build_tmp = self.project_dir / "build_tmp"
        self.output_dir = self.project_dir / config.out_dir

        # framework_dir is the repo root (contains js/ and pylevate/).
        # __file__ is pylevate/compiler/pipeline.py → go up 3 levels.
        self.framework_dir = Path(__file__).resolve().parent.parent.parent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, target: str = "web") -> BuildResult:
        """Run a full build: discover, compile, transform, bundle."""
        t0 = time.perf_counter()
        errors: list[str] = []
        warnings: list[str] = []
        out_dir = self.output_dir / target if target != "web" else self.output_dir / "web"

        # 1. Prepare build_tmp (clean slate for full builds).
        self._prepare_build_dir(clean=True)

        # 2. Discover source files (.py and .js).
        sources = self._discover_sources()
        js_sources = self._discover_js_sources()

        if not sources and not js_sources:
            return BuildResult(
                success=False,
                errors=["No source files found in project"],
                output_dir=out_dir,
                duration_ms=_elapsed_ms(t0),
            )
        log.info("Discovered %d .py and %d .js source file(s)", len(sources), len(js_sources))

        # 3. Compile each .py file.
        modules, packages = self._build_import_context_sets(sources, js_sources)
        compiled_paths: list[Path] = []
        for src in sources:
            js_path, errs, warns = self._compile_file(src, modules=modules, packages=packages)
            errors.extend(errs)
            warnings.extend(warns)
            if js_path is not None:
                compiled_paths.append(js_path)

        # 4. Copy hand-written .js files (overwrites compiled .py→.js if both exist).
        for js_src in js_sources:
            rel = js_src.relative_to(self.project_dir)
            dst = self.build_tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(js_src, dst)

        if errors:
            return BuildResult(
                success=False,
                errors=errors,
                output_dir=out_dir,
                duration_ms=_elapsed_ms(t0),
                warnings=warnings,
            )

        # 5. Apply mode-specific transforms.
        for js_path in compiled_paths:
            errs = self._apply_transforms(js_path, target=target)
            errors.extend(errs)

        if errors:
            return BuildResult(
                success=False,
                errors=errors,
                output_dir=out_dir,
                duration_ms=_elapsed_ms(t0),
                warnings=warnings,
            )

        # 6. Bundle with esbuild.
        entry = self._entry_js_path()
        bundle_result = self._bundle(entry, out_dir, target=target)
        errors.extend(bundle_result.errors)

        # 7. Copy index.html (rewriting hashed asset names) and static CSS.
        self._copy_html(out_dir, bundle_result)
        self._copy_static_css(out_dir)

        duration = _elapsed_ms(t0)
        log.info("Build finished in %.0f ms (bundle %d bytes)", duration, bundle_result.bundle_size)

        return BuildResult(
            success=bundle_result.success and not errors,
            errors=errors,
            output_dir=out_dir,
            duration_ms=duration,
            bundle_size=bundle_result.bundle_size,
            warnings=warnings,
        )

    def rebuild(self, changed_file: Path, target: str = "web") -> BuildResult:
        """Incrementally recompile a single file and re-bundle."""
        t0 = time.perf_counter()
        errors: list[str] = []
        warnings: list[str] = []

        changed_file = changed_file.resolve()
        if not changed_file.is_file():
            return BuildResult(
                success=False,
                errors=[f"File not found: {changed_file}"],
                output_dir=self.output_dir,
                duration_ms=_elapsed_ms(t0),
            )

        self._prepare_build_dir(clean=False)

        # Re-derive the import context (cheap globs) so incremental rebuilds
        # resolve and validate imports the same way full builds do.
        modules, packages = self._build_import_context_sets(
            self._discover_sources(), self._discover_js_sources()
        )
        js_path, errs, warns = self._compile_file(changed_file, modules=modules, packages=packages)
        errors.extend(errs)
        warnings.extend(warns)

        if js_path is not None:
            errs = self._apply_transforms(js_path, target=target)
            errors.extend(errs)

        if errors:
            return BuildResult(
                success=False,
                errors=errors,
                output_dir=self.output_dir,
                duration_ms=_elapsed_ms(t0),
                warnings=warnings,
            )

        entry = self._entry_js_path()
        bundle_result = self._bundle(entry)
        errors.extend(bundle_result.errors)

        duration = _elapsed_ms(t0)
        log.info("Rebuild of %s finished in %.0f ms", changed_file.name, duration)

        return BuildResult(
            success=bundle_result.success and not errors,
            errors=errors,
            output_dir=self.output_dir,
            duration_ms=duration,
            bundle_size=bundle_result.bundle_size,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prepare_build_dir(self, clean: bool) -> None:
        if clean and self.build_tmp.exists():
            shutil.rmtree(self.build_tmp)
        self.build_tmp.mkdir(parents=True, exist_ok=True)

    def _discover_sources(self) -> list[Path]:
        """Return all .py files in the project, excluding config and build artifacts."""
        sources: list[Path] = []
        for py_file in sorted(self.project_dir.rglob("*.py")):
            # Skip config, build artifacts, and hidden directories.
            rel = py_file.relative_to(self.project_dir)
            parts = rel.parts
            if any(p.startswith(".") for p in parts):
                continue
            if "build_tmp" in parts or self.config.out_dir.rstrip("/") in parts:
                continue
            if py_file.name in _EXCLUDED_FILENAMES:
                continue
            sources.append(py_file)
        return sources

    def _build_import_context_sets(
        self, py_sources: list[Path], js_sources: list[Path]
    ) -> tuple[frozenset[str], frozenset[str]]:
        """Derive the dotted module and package names resolvable in this project."""
        modules: set[str] = set()
        packages: set[str] = set()
        for src in list(py_sources) + list(js_sources):
            rel = src.relative_to(self.project_dir).with_suffix("")
            parts = rel.as_posix().split("/")
            if parts[-1] == "__init__":
                if len(parts) > 1:
                    packages.add(".".join(parts[:-1]))
            else:
                modules.add(".".join(parts))
        return frozenset(modules), frozenset(packages)

    def _compile_file(
        self,
        src: Path,
        *,
        modules: frozenset[str] = frozenset(),
        packages: frozenset[str] = frozenset(),
    ) -> tuple[Path | None, list[str], list[str]]:
        """Compile a single .py file to JS inside build_tmp.

        Returns the output JS path (or None on failure), errors, and warnings.
        """
        from pylevate.compiler.py2js import ImportContext, compile_source  # noqa: F811

        rel = src.relative_to(self.project_dir)
        js_rel = rel.with_suffix(".js")
        out_path = self.build_tmp / js_rel
        out_path.parent.mkdir(parents=True, exist_ok=True)

        log.debug("Compiling %s -> %s", rel, js_rel)

        try:
            source_text = src.read_text(encoding="utf-8")
        except OSError as exc:
            return None, [f"Cannot read {rel}: {exc}"], []

        import_ctx = ImportContext(
            rel_path=rel.as_posix(),
            modules=modules,
            packages=packages,
            validate=bool(modules or packages),
        )
        try:
            result = compile_source(
                source_text, filename=str(rel), mode=self.config.mode, import_ctx=import_ctx
            )
        except Exception as exc:
            log.error("Compilation error in %s: %s", rel, exc)
            return None, [f"{rel}: {exc}"], []

        warnings = [str(w) for w in result.warnings]
        if result.errors:
            return None, [str(e) for e in result.errors], warnings

        js_code = result.js

        # Apply CSS scoping if any css chunks were extracted
        if result.css_chunks and self.config.mode in ("app", "hybrid"):
            from pylevate.compiler.css_scoper import scope, apply_class_map

            combined_css = "\n".join(result.css_chunks)
            scoped_css, class_map = scope(combined_css, src)

            # Write scoped CSS file alongside the JS
            css_path = out_path.with_suffix(".css")
            css_path.write_text(scoped_css, encoding="utf-8")

            # Apply scoped class names to the JS
            js_code = apply_class_map(js_code, class_map)

            # Inject CSS import at the top of the JS file
            css_rel_name = css_path.name
            js_code = f"import './{css_rel_name}';\n{js_code}"

        out_path.write_text(js_code, encoding="utf-8")
        return out_path, [], warnings

    def _apply_transforms(self, js_path: Path, target: str = "web") -> list[str]:
        """Run mode-specific transforms on a compiled JS file in-place."""
        errors: list[str] = []
        mode = self.config.mode
        modified = False

        try:
            js_code = js_path.read_text(encoding="utf-8")
        except OSError as exc:
            return [f"Cannot read compiled file {js_path.name}: {exc}"]

        try:
            # Game mode: hoist game loop (only for files that import the game runtime)
            is_game_file = "pylevate-game-runtime" in js_code
            if mode in ("game", "hybrid") and is_game_file and "while (" in js_code:
                from pylevate.compiler.loop_hoister import hoist_game_loop
                js_code = hoist_game_loop(js_code, js_path.stem)
                modified = True

            # Capacitor build: rewrite native imports to direct @capacitor/* packages
            if target == "capacitor" and "pylevate-native-runtime" in js_code:
                from pylevate.compiler.native_bridge import rewrite_native_import, rewrite_native_method_calls
                lines = js_code.split("\n")
                new_lines = []
                for line in lines:
                    if "pylevate-native-runtime" in line:
                        new_lines.append(rewrite_native_import(line))
                    else:
                        new_lines.append(line)
                js_code = "\n".join(new_lines)
                js_code = rewrite_native_method_calls(js_code)
                modified = True

        except Exception as exc:
            log.error("Transform error on %s: %s", js_path.name, exc)
            return [f"Transform error on {js_path.name}: {exc}"]

        if modified:
            js_path.write_text(js_code, encoding="utf-8")
        return errors

    def _discover_js_sources(self) -> list[Path]:
        """Return .js source files in the project (for Phase 1 hand-written JS)."""
        sources: list[Path] = []
        for js_file in sorted(self.project_dir.rglob("*.js")):
            rel = js_file.relative_to(self.project_dir)
            parts = rel.parts
            if any(p.startswith(".") for p in parts):
                continue
            if "build_tmp" in parts or "dist" in parts or "node_modules" in parts:
                continue
            sources.append(js_file)
        return sources

    def _entry_js_path(self) -> Path | list[Path]:
        """Derive the entry-point JS path(s) from the config entry field.

        In hybrid mode, returns multiple entries (UI + game files).
        """
        js_entry = self.build_tmp / Path(self.config.entry).with_suffix(".js")

        # Hybrid mode: find all top-level .js files that have game or app imports
        if self.config.mode == "hybrid":
            entries = []
            for js_file in sorted(self.build_tmp.glob("*.js")):
                if js_file.name.startswith("_"):
                    continue
                entries.append(js_file)
            if entries:
                return entries

        return js_entry

    def _bundle(self, entry: Path, out_dir: Path | None = None, target: str = "web"):
        """Call esbuild to produce the final bundle."""
        from pylevate.compiler.esbuild import bundle  # noqa: F811

        target_dir = out_dir or self.output_dir / "web"
        return bundle(
            entry=entry,
            out_dir=target_dir,
            build_tmp=self.build_tmp,
            framework_dir=self.framework_dir,
            mode=self.config.mode,
            production=self.production,
            target=target,
        )

    def _copy_html(self, out_dir: Path, bundle_result=None) -> None:
        """Copy index.html to the output directory, rewriting hashed asset names.

        When the bundle produced content-hashed outputs (production builds),
        local script/link references like ./main.js are rewritten to the
        hashed file names from esbuild's metafile.
        """
        html_src = self.project_dir / "index.html"
        if not html_src.exists():
            return
        out_dir.mkdir(parents=True, exist_ok=True)

        asset_map = _build_asset_map(bundle_result.outputs_meta) if bundle_result else {}
        if not asset_map:
            shutil.copy2(html_src, out_dir / "index.html")
            return

        html = html_src.read_text(encoding="utf-8")
        html = _rewrite_asset_refs(html, asset_map)
        (out_dir / "index.html").write_text(html, encoding="utf-8")

    def _copy_static_css(self, out_dir: Path) -> None:
        """Copy plain project .css files (e.g. styles/global.css) to the output.

        These are referenced from index.html or App(theme=...) and are not
        part of the esbuild module graph.
        """
        for css_file in sorted(self.project_dir.rglob("*.css")):
            rel = css_file.relative_to(self.project_dir)
            parts = rel.parts
            if any(p.startswith(".") for p in parts):
                continue
            if "build_tmp" in parts or "node_modules" in parts:
                continue
            if self.config.out_dir.rstrip("/") in parts or "dist" in parts:
                continue
            dst = out_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(css_file, dst)


def _build_asset_map(outputs_meta: list[dict]) -> dict[str, str]:
    """Map original entry basenames to their (hashed) output basenames.

    Returns an empty dict when output names match their entry names (dev
    builds), so callers can skip rewriting entirely.
    """
    asset_map: dict[str, str] = {}
    for meta in outputs_meta or []:
        entry_point = meta.get("entryPoint")
        if not entry_point:
            continue
        entry_name = Path(entry_point).stem
        out_name = Path(meta["path"]).name
        if out_name != f"{entry_name}.js":
            asset_map[f"{entry_name}.js"] = out_name
        css_bundle = meta.get("cssBundle")
        if css_bundle:
            css_out = Path(css_bundle).name
            if css_out != f"{entry_name}.css":
                asset_map[f"{entry_name}.css"] = css_out
    return asset_map


_ASSET_REF_RE = re.compile(r"""(?P<attr>src|href)=(?P<q>["'])(?P<url>\.?/[^"']+)(?P=q)""")


def _rewrite_asset_refs(html: str, asset_map: dict[str, str]) -> str:
    """Rewrite local src/href references in HTML per the asset map.

    Only ./-relative and /-absolute URLs are considered, so CDN references
    (https://...) are never touched.
    """
    def _sub(m: re.Match) -> str:
        url = m.group("url")
        name = url.rsplit("/", 1)[-1]
        hashed = asset_map.get(name)
        if not hashed:
            return m.group(0)
        new_url = url[: len(url) - len(name)] + hashed
        return f"{m.group('attr')}={m.group('q')}{new_url}{m.group('q')}"

    return _ASSET_REF_RE.sub(_sub, html)


def _elapsed_ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000

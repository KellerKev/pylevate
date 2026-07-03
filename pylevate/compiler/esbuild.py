"""Calls esbuild via a generated Node runner script to bundle compiled JS."""

from __future__ import annotations

import json
import logging
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class BundleResult:
    success: bool
    errors: list[str] = field(default_factory=list)
    output_files: list[Path] = field(default_factory=list)
    bundle_size: int = 0
    # Per-output metadata from esbuild's metafile:
    # {"path", "bytes", "entryPoint", "cssBundle"} — used to map entry names
    # to hashed output names for index.html rewriting.
    outputs_meta: list[dict] = field(default_factory=list)


def _generate_runner_script(
    entry: Path | list[Path],
    out_dir: Path,
    build_tmp: Path,
    framework_dir: Path,
    mode: str,
    production: bool,
    target: str = "web",
) -> Path:
    """Write a temporary esbuild runner to *build_tmp/_esbuild_runner.mjs*."""
    runner_path = build_tmp / "_esbuild_runner.mjs"

    runtime_alias = "pylevate-game-runtime" if mode == "game" else "pylevate-runtime"
    runtime_file = "pylevate-game-runtime.js" if mode == "game" else "pylevate-runtime.js"
    runtime_path = (framework_dir / "js" / runtime_file).as_posix()
    baselib_path = (framework_dir / "js" / "baselib.js").as_posix()

    # Build the alias map fed to esbuild.
    native_runtime_path = (framework_dir / "js" / "pylevate-native-runtime.js").as_posix()
    events_path = (framework_dir / "js" / "pylevate-events.js").as_posix()
    alias = {
        runtime_alias: runtime_path,
        "pylevate-native-runtime": native_runtime_path,
        "pylevate-events": events_path,
    }
    # In hybrid mode both runtimes should be resolvable.
    if mode == "hybrid":
        alias["pylevate-runtime"] = (framework_dir / "js" / "pylevate-runtime.js").as_posix()
        alias["pylevate-game-runtime"] = (framework_dir / "js" / "pylevate-game-runtime.js").as_posix()

    external: list[str] = []
    if mode in ("game", "hybrid"):
        external.append("phaser")
    if target == "capacitor":
        external.append("@capacitor/*")

    # nodePaths lets esbuild resolve packages from the user project's node_modules
    # even when the runtime JS files live outside the project tree.
    node_modules_dir = (build_tmp.parent / "node_modules").as_posix()

    # Production builds get content-hashed file names for cache busting;
    # dev builds keep stable names so index.html and the HMR flow work as-is.
    naming_opts = ""
    if production:
        naming_opts = (
            '    entryNames: "[name]-[hash]",\n'
            '    chunkNames: "chunks/[name]-[hash]",\n'
            '    assetNames: "assets/[name]-[hash]",\n'
        )

    dev_define = json.dumps({"__PYLEVATE_DEV__": "false" if production else "true"})

    script = textwrap.dedent(f"""\
        import esbuild from "esbuild";

        const result = await esbuild.build({{
            entryPoints: {json.dumps([e.as_posix() for e in (entry if isinstance(entry, list) else [entry])])},
            outdir: {json.dumps(out_dir.as_posix())},
            bundle: true,
            format: "esm",
            splitting: true,
            treeShaking: true,
            sourcemap: true,
            minify: {json.dumps(production)},
            define: {dev_define},
        {naming_opts}    alias: {json.dumps(alias)},
            external: {json.dumps(external)},
            inject: [{json.dumps(baselib_path)}],
            nodePaths: [{json.dumps(node_modules_dir)}],
            metafile: true,
            logLevel: "warning",
        }});

        // Emit a machine-readable summary on stdout.
        const outputs = Object.entries(result.metafile.outputs).map(([p, meta]) => ({{
            path: p,
            bytes: meta.bytes,
            entryPoint: meta.entryPoint || null,
            cssBundle: meta.cssBundle || null,
        }}));
        const totalBytes = outputs.reduce((sum, o) => sum + o.bytes, 0);
        console.log(JSON.stringify({{
            ok: true,
            outputs,
            totalBytes,
            errors: result.errors.map(e => e.text),
            warnings: result.warnings.map(w => w.text),
        }}));
    """)

    runner_path.write_text(script, encoding="utf-8")
    return runner_path


def bundle(
    entry: Path | list[Path],
    out_dir: Path,
    build_tmp: Path,
    framework_dir: Path,
    mode: str = "app",
    production: bool = False,
    target: str = "web",
) -> BundleResult:
    """Bundle compiled JS using esbuild via a Node subprocess.

    Parameters
    ----------
    entry:
        The main entry-point JS file inside *build_tmp*.
    out_dir:
        Directory where the final bundle is written.
    build_tmp:
        Scratch directory that holds compiled JS and the runner script.
    framework_dir:
        Root of the PyLevate package where ``js/`` assets live.
    mode:
        One of ``"app"``, ``"game"``, or ``"hybrid"``.
    production:
        Enable minification when ``True``.
    """
    build_tmp.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    runner_path = _generate_runner_script(
        entry=entry,
        out_dir=out_dir,
        build_tmp=build_tmp,
        framework_dir=framework_dir,
        mode=mode,
        production=production,
        target=target,
    )

    log.info("Running esbuild via %s", runner_path)

    # Find the project directory (parent of build_tmp) for node_modules resolution
    project_dir = build_tmp.parent
    try:
        proc = subprocess.run(
            ["node", runner_path.as_posix()],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=project_dir,
        )
    except FileNotFoundError:
        return BundleResult(
            success=False,
            errors=["'node' executable not found — is Node.js installed?"],
        )
    except subprocess.TimeoutExpired:
        return BundleResult(success=False, errors=["esbuild timed out after 60 s"])

    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        log.error("esbuild failed (exit %d): %s", proc.returncode, stderr)
        return BundleResult(success=False, errors=[stderr] if stderr else ["esbuild exited with non-zero status"])

    # Parse the JSON summary printed by the runner script.
    stdout = proc.stdout.strip()
    if not stdout:
        return BundleResult(success=False, errors=["esbuild produced no output"])

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        log.error("Failed to parse esbuild output: %s", exc)
        return BundleResult(success=False, errors=[f"Malformed esbuild output: {exc}"])

    outputs_meta = payload.get("outputs", [])
    output_files = [Path(o["path"]) for o in outputs_meta]
    total_bytes = payload.get("totalBytes", 0)
    errors = payload.get("errors", [])
    warnings = payload.get("warnings", [])

    for w in warnings:
        log.warning("esbuild: %s", w)

    return BundleResult(
        success=not errors,
        errors=errors,
        output_files=output_files,
        bundle_size=total_bytes,
        outputs_meta=outputs_meta,
    )

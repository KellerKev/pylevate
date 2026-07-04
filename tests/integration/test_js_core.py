"""Runs the node test scripts for the framework's JS:
- smoke tests for the dependency-free modules (markdown, AI core/client)
- the jsdom harness for the browser runtime (routing, rehydration, chat)
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
JS_TESTS = REPO_ROOT / "tests" / "js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
needs_dev_deps = pytest.mark.skipif(
    not (REPO_ROOT / "node_modules" / "jsdom").is_dir(),
    reason="repo dev dependencies not installed (run: npm install)",
)


def _run_node(script: str) -> None:
    result = subprocess.run(
        ["node", str(JS_TESTS / script)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"{script} failed:\n{result.stdout}\n{result.stderr}"
    assert "all assertions passed" in result.stdout


@needs_node
@pytest.mark.parametrize("script", ["md_smoke.mjs", "ai_core_smoke.mjs", "ai_runtime_smoke.mjs"])
def test_node_smoke(script):
    _run_node(script)


@needs_node
@needs_dev_deps
def test_runtime_jsdom():
    """Browser runtime under jsdom: mount, App/Router + @page titles, link
    navigation, <base href> sub-path routing, store rehydration incl. the
    on_rehydrate hook, and chat component rendering."""
    _run_node("runtime_jsdom.mjs")

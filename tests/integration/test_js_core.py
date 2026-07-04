"""Runs the node smoke tests for the dependency-free JS modules
(js/pylevate-md.js, js/pylevate-ai-core.js, js/pylevate-ai-runtime.js)."""

import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = Path(__file__).parents[1] / "js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


@needs_node
@pytest.mark.parametrize("script", ["md_smoke.mjs", "ai_core_smoke.mjs", "ai_runtime_smoke.mjs"])
def test_node_smoke(script):
    result = subprocess.run(
        ["node", str(JS_TESTS / script)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"{script} failed:\n{result.stdout}\n{result.stderr}"
    assert "all assertions passed" in result.stdout

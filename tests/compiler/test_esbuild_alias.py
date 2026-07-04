"""Tests for the esbuild runner's runtime alias map generation."""

import json
import re
from pathlib import Path

from pylevate.compiler.esbuild import _generate_runner_script

FRAMEWORK_DIR = Path(__file__).parents[2]


def _alias_map(tmp_path: Path, mode: str) -> dict:
    runner = _generate_runner_script(
        entry=tmp_path / "main.js",
        out_dir=tmp_path / "out",
        build_tmp=tmp_path,
        framework_dir=FRAMEWORK_DIR,
        mode=mode,
        production=False,
    )
    script = runner.read_text()
    match = re.search(r"alias: (\{.*?\}),\n", script)
    assert match, "alias map not found in runner script"
    return json.loads(match.group(1))


class TestAliasMap:
    def test_app_mode_resolves_all_runtimes(self, tmp_path):
        alias = _alias_map(tmp_path, "app")
        assert alias["pylevate-runtime"].endswith("js/pylevate-runtime.js")
        assert alias["pylevate-game-runtime"].endswith("js/pylevate-game-runtime.js")
        assert alias["pylevate-native-runtime"].endswith("js/pylevate-native-runtime.js")
        assert alias["pylevate-events"].endswith("js/pylevate-events.js")

    def test_game_mode_remaps_plain_runtime(self, tmp_path):
        alias = _alias_map(tmp_path, "game")
        assert alias["pylevate-runtime"].endswith("js/pylevate-game-runtime.js")

    def test_hybrid_mode_keeps_both(self, tmp_path):
        alias = _alias_map(tmp_path, "hybrid")
        assert alias["pylevate-runtime"].endswith("js/pylevate-runtime.js")
        assert alias["pylevate-game-runtime"].endswith("js/pylevate-game-runtime.js")

    def test_new_runtimes_picked_up_by_glob(self, tmp_path):
        # The chat/ai runtimes ship in js/ — the glob must expose them.
        alias = _alias_map(tmp_path, "app")
        assert alias["pylevate-chat-runtime"].endswith("js/pylevate-chat-runtime.js")
        assert alias["pylevate-ai-runtime"].endswith("js/pylevate-ai-runtime.js")

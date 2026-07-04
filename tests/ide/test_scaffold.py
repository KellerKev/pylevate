"""Tests for the shared project scaffolding (pylevate/scaffold.py)."""

import pytest

from pylevate.scaffold import (
    TEMPLATE_MODES,
    TEMPLATES_DIR,
    VALID_TEMPLATES,
    ScaffoldError,
    npm_install,
    scaffold_project,
)

EXISTING_TEMPLATES = [t for t in VALID_TEMPLATES if (TEMPLATES_DIR / t).is_dir()
                      and any((TEMPLATES_DIR / t).iterdir())]


class TestScaffoldProject:
    def test_all_shipped_templates_scaffold(self, tmp_path):
        assert len(EXISTING_TEMPLATES) >= 4
        for template in EXISTING_TEMPLATES:
            project = scaffold_project(f"proj-{template}", template, tmp_path)
            assert (project / "main.py").exists()
            assert (project / "index.html").exists()
            config = (project / "pylevate.config.py").read_text()
            assert f'mode="{TEMPLATE_MODES[template]}"' in config

    def test_invalid_name_rejected(self, tmp_path):
        for bad in ("../escape", ".hidden", "a/b", "", "-dash-first"):
            with pytest.raises(ScaffoldError):
                scaffold_project(bad, "app", tmp_path)

    def test_unknown_template_rejected(self, tmp_path):
        with pytest.raises(ScaffoldError):
            scaffold_project("ok", "nope", tmp_path)

    def test_existing_dir_rejected(self, tmp_path):
        (tmp_path / "taken").mkdir()
        with pytest.raises(ScaffoldError):
            scaffold_project("taken", "app", tmp_path)


class TestNpmInstall:
    def test_no_package_json_skipped(self, tmp_path):
        status, _ = npm_install(tmp_path)
        assert status == "skipped-no-package-json"

"""End-to-end pipeline tests: template project → compile → esbuild bundle.

Bundling tests need node + npm (and network for npm install); they skip
cleanly when unavailable. The compile-only test always runs.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pylevate.config import Config
from pylevate.compiler.pipeline import Pipeline

TEMPLATES = Path(__file__).parents[2] / "pylevate" / "templates"

node_missing = shutil.which("node") is None or shutil.which("npm") is None
needs_node = pytest.mark.skipif(node_missing, reason="node/npm not available")


def _scaffold(tmp_path_factory, template: str) -> Path:
    proj = tmp_path_factory.mktemp(f"e2e_{template}").resolve() / template
    shutil.copytree(TEMPLATES / template, proj)
    result = subprocess.run(
        ["npm", "install", "--silent"],
        cwd=proj, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        pytest.skip(f"npm install failed (offline?): {result.stderr[:200]}")
    return proj


@pytest.fixture(scope="session")
def app_project(tmp_path_factory):
    return _scaffold(tmp_path_factory, "app")


@pytest.fixture(scope="session")
def dashboard_project(tmp_path_factory):
    return _scaffold(tmp_path_factory, "dashboard")


def _local_html_refs(html: str) -> list[str]:
    return [
        url for url in re.findall(r'(?:src|href)=["\']([^"\']+)["\']', html)
        if not url.startswith(("http://", "https://"))
    ]


@needs_node
class TestAppTemplateE2E:
    def test_dev_build(self, app_project):
        result = Pipeline(project_dir=app_project, config=Config(mode="app")).build()
        assert result.success, result.errors
        out = app_project / "dist" / "web"
        assert (out / "main.js").exists()
        assert (out / "index.html").exists()
        html = (out / "index.html").read_text()
        for url in _local_html_refs(html):
            assert (out / url.lstrip("./")).exists(), f"unresolved reference: {url}"

    def test_production_build(self, app_project):
        result = Pipeline(
            project_dir=app_project, config=Config(mode="app"), production=True
        ).build()
        assert result.success, result.errors
        out = app_project / "dist" / "web"
        hashed_js = [f.name for f in out.iterdir() if re.fullmatch(r"main-[A-Z0-9]{8}\.js", f.name)]
        assert hashed_js, "expected a content-hashed main-<hash>.js"
        html = (out / "index.html").read_text()
        assert hashed_js[0] in html
        assert './main.js"' not in html
        for url in _local_html_refs(html):
            assert (out / url.lstrip("./")).exists(), f"unresolved reference: {url}"
        # Minified: the bundle should be a handful of long lines
        bundle = (out / hashed_js[0]).read_text()
        assert bundle.count("\n") < 20


@needs_node
class TestDashboardTemplateE2E:
    """Exercises routing (App/Router/page), nested imports, and stores."""

    def test_dev_build(self, dashboard_project):
        result = Pipeline(project_dir=dashboard_project, config=Config(mode="app")).build()
        assert result.success, result.errors
        out = dashboard_project / "dist" / "web"
        bundle = (out / "main.js").read_text()
        # Router runtime and page metadata made it into the bundle
        assert "__page__" in bundle
        # Dev define kept the rehydration machinery
        assert "__pylevate_state__" in bundle

    def test_production_build_strips_dev_machinery(self, dashboard_project):
        result = Pipeline(
            project_dir=dashboard_project, config=Config(mode="app"), production=True
        ).build()
        assert result.success, result.errors
        out = dashboard_project / "dist" / "web"
        hashed = [f for f in out.iterdir() if re.fullmatch(r"main-[A-Z0-9]{8}\.js", f.name)]
        assert hashed
        assert "__pylevate_state__" not in hashed[0].read_text()


@pytest.fixture(scope="session")
def chat_project(tmp_path_factory):
    return _scaffold(tmp_path_factory, "chat")


@needs_node
class TestChatTemplateE2E:
    """Exercises the chat/AI runtimes: pylevate.chat + pylevate.ai bundling."""

    def test_dev_build_bundles_chat_runtime(self, chat_project):
        result = Pipeline(project_dir=chat_project, config=Config(mode="app")).build()
        assert result.success, result.errors
        out = chat_project / "dist" / "web"
        bundle = (out / "main.js").read_text()
        assert "pl-chat-window" in bundle       # chat components bundled
        assert "AIClient" in bundle             # AI client bundled
        # Runtime CSS flowed through esbuild's cssBundle into main.css
        css = (out / "main.css").read_text()
        assert ".pl-message-list" in css
        assert ".pl-md" in css

    def test_production_build(self, chat_project):
        result = Pipeline(
            project_dir=chat_project, config=Config(mode="app"), production=True
        ).build()
        assert result.success, result.errors
        out = chat_project / "dist" / "web"
        hashed = [f.name for f in out.iterdir() if re.fullmatch(r"main-[A-Z0-9]{8}\.js", f.name)]
        assert hashed
        html = (out / "index.html").read_text()
        assert hashed[0] in html


class TestCompileOnly:
    """Pipeline coverage that runs without node: nested imports compile
    to correct relative specifiers."""

    @pytest.mark.parametrize("template", ["agent", "rag"])
    def test_ai_templates_compile(self, tmp_path, template):
        proj = tmp_path.resolve() / template
        shutil.copytree(TEMPLATES / template, proj)
        pipeline = Pipeline(project_dir=proj, config=Config(mode="app"))
        pipeline._prepare_build_dir(clean=True)
        sources = pipeline._discover_sources()
        modules, packages = pipeline._build_import_context_sets(
            sources, pipeline._discover_js_sources()
        )
        for src in sources:
            js_path, errors, _ = pipeline._compile_file(src, modules=modules, packages=packages)
            assert js_path is not None, f"{src}: {errors}"
        main_js = (proj / "build_tmp" / "main.js").read_text()
        assert "'pylevate-ai-runtime'" in main_js
        assert "'pylevate-chat-runtime'" in main_js

    def test_dashboard_nested_imports(self, tmp_path):
        proj = tmp_path.resolve() / "dash"
        shutil.copytree(TEMPLATES / "dashboard", proj)
        pipeline = Pipeline(project_dir=proj, config=Config(mode="app"))
        pipeline._prepare_build_dir(clean=True)
        sources = pipeline._discover_sources()
        modules, packages = pipeline._build_import_context_sets(
            sources, pipeline._discover_js_sources()
        )
        for src in sources:
            js_path, errors, _ = pipeline._compile_file(src, modules=modules, packages=packages)
            assert js_path is not None, f"{src}: {errors}"
        home_js = (proj / "build_tmp" / "pages" / "home.js").read_text()
        assert "from '../components/nav.js'" in home_js
        assert "from '../stores/counter.js'" in home_js

    def test_unknown_import_fails_with_friendly_error(self, tmp_path):
        proj = tmp_path.resolve() / "p"
        proj.mkdir()
        (proj / "index.html").write_text("<html><body></body></html>")
        (proj / "main.py").write_text("from missing.widget import W\n")
        pipeline = Pipeline(project_dir=proj, config=Config(mode="app"))
        pipeline._prepare_build_dir(clean=True)
        sources = pipeline._discover_sources()
        modules, packages = pipeline._build_import_context_sets(
            sources, pipeline._discover_js_sources()
        )
        js_path, errors, _ = pipeline._compile_file(sources[0], modules=modules, packages=packages)
        assert js_path is None
        assert any("missing/widget.py" in e for e in errors)

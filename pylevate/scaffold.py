"""Project scaffolding shared by the CLI (`pylevate init`) and the IDE."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from pylevate.config import Config

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

VALID_TEMPLATES = ("app", "game", "hybrid", "dashboard", "chat", "agent", "rag")

# Compilation mode per template — everything that isn't a game is app-mode.
TEMPLATE_MODES = {
    "app": "app",
    "game": "game",
    "hybrid": "hybrid",
    "dashboard": "app",
    "chat": "app",
    "agent": "app",
    "rag": "app",
}

# Doubles as the path-safety guard for project names in the IDE file APIs.
PROJECT_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class ScaffoldError(Exception):
    """A scaffolding request that cannot be fulfilled (bad name/template/target)."""


def scaffold_project(name: str, template: str, parent_dir: Path, *, mobile: bool = False) -> Path:
    """Create a new project from a template. Returns the project directory.

    Validates the name and template, copies the template tree, and writes
    pylevate.config.py. No npm install and no console output — callers own UX.
    """
    if not PROJECT_NAME_RE.fullmatch(name):
        raise ScaffoldError(
            f"Invalid project name '{name}' — use letters, digits, '.', '_', '-' "
            f"(must not start with a separator)."
        )
    if template not in VALID_TEMPLATES:
        raise ScaffoldError(
            f"Unknown template '{template}'. Choose from: {', '.join(VALID_TEMPLATES)}"
        )

    project_dir = parent_dir / name
    template_dir = TEMPLATES_DIR / template

    if project_dir.exists():
        raise ScaffoldError(f"Directory '{name}' already exists.")
    if not template_dir.exists() or not any(template_dir.iterdir()):
        raise ScaffoldError(f"Template directory not found or empty: {template_dir}")

    shutil.copytree(template_dir, project_dir)

    mode = TEMPLATE_MODES[template]
    config_content = (
        '"""PyLevate project configuration."""\n'
        "\n"
        "from pylevate.config import Config\n"
        "\n"
        "config = Config(\n"
        f'    mode="{mode}",\n'
        f'    entry="main.py",\n'
        f'    out_dir="dist/",\n'
        f"    dev_port=3000,\n"
        f"    hmr_port=3001,\n"
        ")\n"
    )
    (project_dir / "pylevate.config.py").write_text(config_content)

    if mobile:
        from pylevate.mobile.capacitor import (
            CapacitorProject,
            update_package_json,
            write_capacitor_config,
        )

        cap = CapacitorProject(
            project_dir=project_dir,
            config=Config(mode=mode, entry="main.py", out_dir="dist/"),
        )
        write_capacitor_config(cap)
        update_package_json(project_dir, ["ios"])

    return project_dir


def npm_install(project_dir: Path) -> tuple[str, str]:
    """Run npm install for a scaffolded project.

    Returns (status, detail): ('ok', ''), ('skipped-no-package-json', ''),
    ('skipped-no-npm', hint), or ('failed', stderr).
    """
    if not (project_dir / "package.json").exists():
        return "skipped-no-package-json", ""
    try:
        subprocess.run(
            ["npm", "install"],
            cwd=project_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except FileNotFoundError:
        return "skipped-no-npm", "npm not found — run 'npm install' manually."
    except subprocess.TimeoutExpired:
        return "failed", "npm install timed out after 600s"
    except subprocess.CalledProcessError as exc:
        return "failed", exc.stderr or "npm install failed"
    return "ok", ""

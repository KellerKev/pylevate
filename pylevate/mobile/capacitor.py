"""Capacitor integration — generates config, manages iOS/Android projects."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pylevate.config import Config

log = logging.getLogger(__name__)

CAPACITOR_DEPS = {
    "@capacitor/core": "^5.0.0",
    "@capacitor/cli": "^5.0.0",
}

CAPACITOR_PLATFORM_DEPS = {
    "ios": "@capacitor/ios",
    "android": "@capacitor/android",
}

NATIVE_PLUGIN_DEPS = {
    "@capacitor/camera": "^5.0.0",
    "@capacitor/geolocation": "^5.0.0",
    "@capacitor/haptics": "^5.0.0",
    "@capacitor/preferences": "^5.0.0",
    "@capacitor/share": "^5.0.0",
    "@capacitor/push-notifications": "^5.0.0",
}


@dataclass
class CapacitorProject:
    project_dir: Path
    config: Config
    app_id: str = ""
    app_name: str = ""

    def __post_init__(self):
        if not self.app_name:
            self.app_name = self.project_dir.name
        if not self.app_id:
            safe = self.app_name.replace("-", "").replace("_", "")
            self.app_id = f"com.pylevate.{safe}"


def init_capacitor(project_dir: Path, config: Config, platforms: list[str] | None = None) -> None:
    """Initialize Capacitor in an existing PyLevate project."""
    cap = CapacitorProject(project_dir=project_dir, config=config)

    # 1. Write capacitor.config.ts
    write_capacitor_config(cap)

    # 2. Update package.json with Capacitor deps
    update_package_json(project_dir, platforms or [])

    # 3. npm install
    _run_npm(project_dir, ["install"])

    # 4. Add platforms
    for platform in (platforms or []):
        _run_npx(project_dir, ["cap", "add", platform])


def write_capacitor_config(cap: CapacitorProject) -> None:
    """Write capacitor.config.ts to the project directory."""
    config_content = f"""import type {{ CapacitorConfig }} from '@capacitor/cli';

const config: CapacitorConfig = {{
  appId: '{cap.app_id}',
  appName: '{cap.app_name}',
  webDir: '{cap.config.out_dir}web',
  server: {{
    androidScheme: 'https',
  }},
}};

export default config;
"""
    (cap.project_dir / "capacitor.config.ts").write_text(config_content)
    log.info("Wrote capacitor.config.ts")


def update_package_json(project_dir: Path, platforms: list[str]) -> None:
    """Add Capacitor dependencies to package.json."""
    pkg_path = project_dir / "package.json"
    if not pkg_path.exists():
        return

    pkg = json.loads(pkg_path.read_text())
    deps = pkg.setdefault("dependencies", {})

    # Core Capacitor deps
    for name, version in CAPACITOR_DEPS.items():
        deps.setdefault(name, version)

    # Platform deps
    for platform in platforms:
        dep = CAPACITOR_PLATFORM_DEPS.get(platform)
        if dep:
            deps.setdefault(dep, "^5.0.0")

    pkg_path.write_text(json.dumps(pkg, indent=2) + "\n")
    log.info("Updated package.json with Capacitor deps")


def add_native_plugins(project_dir: Path, plugins: list[str]) -> None:
    """Add native plugin dependencies."""
    pkg_path = project_dir / "package.json"
    if not pkg_path.exists():
        return

    pkg = json.loads(pkg_path.read_text())
    deps = pkg.setdefault("dependencies", {})

    for plugin in plugins:
        if plugin in NATIVE_PLUGIN_DEPS:
            deps.setdefault(plugin, NATIVE_PLUGIN_DEPS[plugin])

    pkg_path.write_text(json.dumps(pkg, indent=2) + "\n")
    _run_npm(project_dir, ["install"])


def sync_capacitor(project_dir: Path) -> None:
    """Run `npx cap sync` to copy web assets and update native projects."""
    _run_npx(project_dir, ["cap", "sync"])


def open_ide(project_dir: Path, platform: str) -> None:
    """Open the native IDE (Xcode or Android Studio)."""
    _run_npx(project_dir, ["cap", "open", platform])


def run_on_device(project_dir: Path, platform: str) -> None:
    """Build and run on a connected device or simulator."""
    _run_npx(project_dir, ["cap", "run", platform])


def detect_used_plugins(project_dir: Path) -> list[str]:
    """Scan .py files for pylevate.native imports and return needed plugin packages."""
    from pylevate.compiler.native_bridge import CAPACITOR_MAP

    used: set[str] = set()
    for py_file in project_dir.rglob("*.py"):
        try:
            source = py_file.read_text()
        except OSError:
            continue
        for py_name, cap_pkg in CAPACITOR_MAP.items():
            if py_name in source:
                used.add(cap_pkg)
    return sorted(used)


# -- subprocess helpers -------------------------------------------------------

def _run_npm(project_dir: Path, args: list[str]) -> None:
    try:
        subprocess.run(
            ["npm"] + args,
            cwd=project_dir,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        log.warning("npm not found — skipping")
    except subprocess.CalledProcessError as e:
        log.error("npm %s failed: %s", " ".join(args), e.stderr)


def _run_npx(project_dir: Path, args: list[str]) -> None:
    try:
        subprocess.run(
            ["npx"] + args,
            cwd=project_dir,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        log.warning("npx not found")
    except subprocess.CalledProcessError as e:
        log.error("npx %s failed: %s", " ".join(args), e.stderr)

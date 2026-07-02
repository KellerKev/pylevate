"""Configuration dataclass and loader for pylevate.config.py files."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class Config:
    mode: Literal["app", "game", "hybrid"] = "app"
    entry: str = "main.py"
    out_dir: str = "dist/"
    dev_port: int = 3000
    hmr_port: int = 3001

    @staticmethod
    def load(project_dir: Path) -> "Config":
        """Load pylevate.config.py from a project directory."""
        config_path = project_dir / "pylevate.config.py"
        if not config_path.exists():
            return Config()

        spec = importlib.util.spec_from_file_location("_pylevate_config", config_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_pylevate_config"] = mod
        spec.loader.exec_module(mod)

        config = getattr(mod, "config", None)
        if isinstance(config, Config):
            return config

        return Config()

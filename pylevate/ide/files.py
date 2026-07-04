"""Workspace/project file access for the IDE — every path from the browser
goes through the guards in this module."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pylevate.scaffold import PROJECT_NAME_RE

EXCLUDED_DIRS = {"dist", "build_tmp", "node_modules", ".git", ".pixi", "__pycache__"}

# File types the editor may read/write.
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".md", ".txt", ".svg"}


class FileAccessError(Exception):
    """A file request that must be refused (traversal, binary, missing)."""


def list_projects(workspace_dir: Path) -> list[str]:
    """Projects are direct children of the workspace with a pylevate.config.py."""
    projects = []
    for child in sorted(workspace_dir.iterdir()):
        if child.is_dir() and (child / "pylevate.config.py").exists():
            projects.append(child.name)
    return projects


def resolve_project(workspace_dir: Path, name: str) -> Path:
    """Validate a project name and return its directory."""
    if not name or not PROJECT_NAME_RE.fullmatch(name):
        raise FileAccessError(f"Invalid project name: {name!r}")
    project_dir = (workspace_dir / name).resolve()
    if project_dir.parent != workspace_dir.resolve():
        raise FileAccessError(f"Invalid project name: {name!r}")
    if not project_dir.is_dir() or not (project_dir / "pylevate.config.py").exists():
        raise FileAccessError(f"Not a PyLevate project: {name}")
    return project_dir


def resolve_in_project(project_dir: Path, rel_path: str) -> Path:
    """Resolve a browser-supplied relative path inside the project, safely.

    Rejects absolute paths, null bytes, and anything that escapes the project
    directory after symlink resolution.
    """
    if not rel_path or "\x00" in rel_path:
        raise FileAccessError(f"Invalid path: {rel_path!r}")
    candidate = Path(rel_path)
    if candidate.is_absolute():
        raise FileAccessError(f"Absolute paths not allowed: {rel_path!r}")
    root = project_dir.resolve()
    full = (root / candidate).resolve()
    if full != root and root not in full.parents:
        raise FileAccessError(f"Path escapes the project: {rel_path!r}")
    return full


def list_tree(project_dir: Path) -> list[dict]:
    """Nested file tree: [{name, path, type: 'dir'|'file', children?}, ...]."""
    root = project_dir.resolve()

    def _walk(directory: Path) -> list[dict]:
        entries = []
        for child in sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if child.name.startswith(".") or child.name in EXCLUDED_DIRS:
                continue
            rel = child.relative_to(root).as_posix()
            if child.is_dir():
                entries.append({
                    "name": child.name, "path": rel, "type": "dir",
                    "children": _walk(child),
                })
            else:
                entries.append({"name": child.name, "path": rel, "type": "file"})
        return entries

    return _walk(root)


def read_file(project_dir: Path, rel_path: str) -> str:
    full = resolve_in_project(project_dir, rel_path)
    if not full.is_file():
        raise FileAccessError(f"Not a file: {rel_path}")
    if full.suffix.lower() not in TEXT_SUFFIXES:
        raise FileAccessError(f"Not an editable text file: {rel_path}")
    try:
        return full.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise FileAccessError(f"Not a UTF-8 text file: {rel_path}") from exc


def write_file(project_dir: Path, rel_path: str, content: str) -> None:
    """Atomic write: the watcher/compiler never sees a half-written file."""
    full = resolve_in_project(project_dir, rel_path)
    if full.suffix.lower() not in TEXT_SUFFIXES:
        raise FileAccessError(f"Not an editable text file: {rel_path}")
    full.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(full.parent), prefix=".pylevate-write-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(content)
        os.replace(tmp_name, full)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

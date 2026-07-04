"""Tests for the IDE file-access guards (pylevate/ide/files.py)."""

import pytest

from pylevate.ide.files import (
    FileAccessError,
    list_projects,
    list_tree,
    read_file,
    resolve_in_project,
    resolve_project,
    write_file,
)


@pytest.fixture()
def project(tmp_path):
    proj = tmp_path / "myproj"
    (proj / "pages").mkdir(parents=True)
    (proj / "dist").mkdir()
    (proj / "node_modules" / "x").mkdir(parents=True)
    (proj / "pylevate.config.py").write_text("config = None\n")
    (proj / "main.py").write_text("x = 1\n")
    (proj / "pages" / "home.py").write_text("y = 2\n")
    (proj / "dist" / "main.js").write_text("built")
    return proj


class TestResolveInProject:
    def test_happy_path(self, project):
        assert resolve_in_project(project, "pages/home.py").name == "home.py"

    def test_traversal_rejected(self, project):
        with pytest.raises(FileAccessError):
            resolve_in_project(project, "../outside.py")
        with pytest.raises(FileAccessError):
            resolve_in_project(project, "pages/../../outside.py")

    def test_absolute_rejected(self, project):
        with pytest.raises(FileAccessError):
            resolve_in_project(project, "/etc/passwd")

    def test_null_byte_rejected(self, project):
        with pytest.raises(FileAccessError):
            resolve_in_project(project, "main.py\x00.js")

    def test_symlink_escape_rejected(self, project, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.py").write_text("secret")
        (project / "link").symlink_to(outside)
        with pytest.raises(FileAccessError):
            resolve_in_project(project, "link/secret.py")


class TestResolveProject:
    def test_valid(self, project, tmp_path):
        assert resolve_project(tmp_path, "myproj") == project.resolve()

    def test_invalid_names(self, tmp_path):
        for bad in ("../x", "a/b", "", ".hidden"):
            with pytest.raises(FileAccessError):
                resolve_project(tmp_path, bad)

    def test_non_project_dir(self, tmp_path):
        (tmp_path / "plain").mkdir()
        with pytest.raises(FileAccessError):
            resolve_project(tmp_path, "plain")


class TestListing:
    def test_list_projects(self, project, tmp_path):
        (tmp_path / "not-a-project").mkdir()
        assert list_projects(tmp_path) == ["myproj"]

    def test_tree_excludes_artifacts(self, project):
        tree = list_tree(project)
        names = {entry["name"] for entry in tree}
        assert "main.py" in names
        assert "pages" in names
        assert "dist" not in names
        assert "node_modules" not in names
        pages = next(e for e in tree if e["name"] == "pages")
        assert pages["children"][0]["path"] == "pages/home.py"


class TestReadWrite:
    def test_round_trip(self, project):
        write_file(project, "pages/about.py", "z = 3\n")
        assert read_file(project, "pages/about.py") == "z = 3\n"

    def test_atomic_no_tmp_left_behind(self, project):
        write_file(project, "main.py", "x = 99\n")
        leftovers = [p for p in project.iterdir() if p.name.startswith(".pylevate-write-")]
        assert leftovers == []
        assert read_file(project, "main.py") == "x = 99\n"

    def test_non_text_suffix_rejected(self, project):
        with pytest.raises(FileAccessError):
            write_file(project, "evil.sh", "rm -rf /")
        with pytest.raises(FileAccessError):
            read_file(project, "photo.png")

    def test_read_missing_rejected(self, project):
        with pytest.raises(FileAccessError):
            read_file(project, "nope.py")

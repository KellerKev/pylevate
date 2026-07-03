"""Tests for production-build HTML asset-reference rewriting."""

from pylevate.compiler.pipeline import _build_asset_map, _rewrite_asset_refs


class TestBuildAssetMap:
    def test_hashed_entry_mapped(self):
        meta = [
            {"path": "dist/web/main-ABC123.js", "bytes": 10, "entryPoint": "build_tmp/main.js",
             "cssBundle": "dist/web/main-DEF456.css"},
            {"path": "dist/web/main-ABC123.js.map", "bytes": 5, "entryPoint": None, "cssBundle": None},
        ]
        assert _build_asset_map(meta) == {
            "main.js": "main-ABC123.js",
            "main.css": "main-DEF456.css",
        }

    def test_unhashed_dev_output_yields_empty_map(self):
        meta = [
            {"path": "dist/web/main.js", "bytes": 10, "entryPoint": "build_tmp/main.js",
             "cssBundle": "dist/web/main.css"},
        ]
        assert _build_asset_map(meta) == {}

    def test_multiple_entries(self):
        meta = [
            {"path": "dist/web/main-AAA.js", "bytes": 1, "entryPoint": "build_tmp/main.js", "cssBundle": None},
            {"path": "dist/web/game-BBB.js", "bytes": 1, "entryPoint": "build_tmp/game.js", "cssBundle": None},
        ]
        assert _build_asset_map(meta) == {"main.js": "main-AAA.js", "game.js": "game-BBB.js"}


class TestRewriteAssetRefs:
    HTML = (
        '<html><head>\n'
        '<link rel="stylesheet" href="./main.css">\n'
        '<script src="https://cdn.jsdelivr.net/npm/phaser@3/dist/phaser.min.js"></script>\n'
        '</head><body>\n'
        '<script type="module" src="./main.js"></script>\n'
        '<script type="module" src="./game.js"></script>\n'
        '<a href="/about">about</a>\n'
        '</body></html>\n'
    )

    def test_local_refs_rewritten(self):
        out = _rewrite_asset_refs(self.HTML, {"main.js": "main-ABC.js", "main.css": "main-DEF.css"})
        assert 'src="./main-ABC.js"' in out
        assert 'href="./main-DEF.css"' in out

    def test_cdn_ref_untouched(self):
        out = _rewrite_asset_refs(self.HTML, {"main.js": "main-ABC.js", "phaser.min.js": "nope.js"})
        assert "https://cdn.jsdelivr.net/npm/phaser@3/dist/phaser.min.js" in out

    def test_unknown_local_refs_untouched(self):
        out = _rewrite_asset_refs(self.HTML, {"main.js": "main-ABC.js"})
        assert 'src="./game.js"' in out
        assert 'href="/about"' in out

    def test_both_entries_rewritten(self):
        out = _rewrite_asset_refs(self.HTML, {"main.js": "main-AAA.js", "game.js": "game-BBB.js"})
        assert 'src="./main-AAA.js"' in out
        assert 'src="./game-BBB.js"' in out

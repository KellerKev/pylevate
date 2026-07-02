"""Phase 6 tests — Native bridge and Capacitor integration."""

from pylevate.compiler.py2js import compile_source
from pylevate.compiler.native_bridge import (
    rewrite_native_import,
    rewrite_native_method_calls,
    CAPACITOR_MAP,
)


def _js(source: str, mode: str = "app") -> str:
    result = compile_source(source, "test.py", mode)
    assert not result.errors, f"Unexpected errors: {result.errors}"
    return result.js.strip()


class TestNativeImportCompilation:
    def test_native_import_mapped(self):
        js = _js("from pylevate.native import Camera, Haptics")
        assert "pylevate-native-runtime" in js

    def test_native_classes_imported(self):
        js = _js("from pylevate.native import Camera, Geolocation, Storage")
        assert "Camera" in js
        assert "Geolocation" in js
        assert "Storage" in js


class TestNativeImportRewriting:
    def test_rewrite_single_import(self):
        line = "import { Camera } from 'pylevate-native-runtime';"
        result = rewrite_native_import(line)
        assert "@capacitor/camera" in result
        assert "Camera" in result

    def test_rewrite_multiple_imports(self):
        line = "import { Camera, Haptics, Storage } from 'pylevate-native-runtime';"
        result = rewrite_native_import(line)
        assert "@capacitor/camera" in result
        assert "@capacitor/haptics" in result
        assert "@capacitor/preferences" in result
        # Should produce separate import lines
        lines = result.strip().split("\n")
        assert len(lines) == 3

    def test_storage_renamed_to_preferences(self):
        line = "import { Storage } from 'pylevate-native-runtime';"
        result = rewrite_native_import(line)
        assert "@capacitor/preferences" in result
        assert "Preferences as Storage" in result


class TestMethodRewriting:
    def test_snake_to_camel(self):
        js = "Camera.get_photo({quality: 90})"
        result = rewrite_native_method_calls(js)
        assert "Camera.getPhoto({quality: 90})" in result

    def test_get_current_position(self):
        js = "Geolocation.get_current_position()"
        result = rewrite_native_method_calls(js)
        assert "Geolocation.getCurrentPosition()" in result

    def test_method_not_rewritten_if_already_camel(self):
        js = "Haptics.impact({style: 'medium'})"
        result = rewrite_native_method_calls(js)
        assert "Haptics.impact({style: 'medium'})" in result


class TestNativeComponentCompilation:
    def test_async_native_method(self):
        js = _js("""
from pylevate import Component, state
from pylevate.native import Camera, Haptics

class ProfileEditor(Component):
    avatar_url = state('')

    async def pick_avatar(self):
        photo = await Camera.get_photo(quality=90)
        self.avatar_url = photo.web_path
        await Haptics.impact(style='medium')
""")
        assert "async pick_avatar()" in js
        assert "await Camera.get_photo" in js or "await Camera.getPhoto" in js
        assert "await Haptics.impact" in js
        assert "this._avatar_url.value" in js


class TestCapacitorMap:
    def test_all_plugins_mapped(self):
        assert "Camera" in CAPACITOR_MAP
        assert "Geolocation" in CAPACITOR_MAP
        assert "Haptics" in CAPACITOR_MAP
        assert "Storage" in CAPACITOR_MAP
        assert "Share" in CAPACITOR_MAP
        assert "PushNotifications" in CAPACITOR_MAP

    def test_storage_maps_to_preferences(self):
        assert CAPACITOR_MAP["Storage"] == "@capacitor/preferences"

"""Native bridge — maps pylevate.native imports to Capacitor plugin packages."""

from __future__ import annotations

# Python class name → Capacitor npm package
CAPACITOR_MAP: dict[str, str] = {
    "Camera":            "@capacitor/camera",
    "Geolocation":       "@capacitor/geolocation",
    "Haptics":           "@capacitor/haptics",
    "Storage":           "@capacitor/preferences",
    "Share":             "@capacitor/share",
    "PushNotifications": "@capacitor/push-notifications",
}

# Python class name → JS import details (package, named export)
NATIVE_IMPORT_MAP: dict[str, tuple[str, str]] = {
    "Camera":            ("@capacitor/camera",             "Camera"),
    "Geolocation":       ("@capacitor/geolocation",        "Geolocation"),
    "Haptics":           ("@capacitor/haptics",            "Haptics"),
    "Storage":           ("@capacitor/preferences",        "Preferences"),
    "Share":             ("@capacitor/share",              "Share"),
    "PushNotifications": ("@capacitor/push-notifications", "PushNotifications"),
}

# Python method → JS method mapping (snake_case → camelCase)
METHOD_MAP: dict[str, str] = {
    "get_photo":                   "getPhoto",
    "get_current_position":        "getCurrentPosition",
    "impact":                      "impact",
    "get":                         "get",
    "set":                         "set",
    "remove":                      "remove",
    "share":                       "share",
    "register":                    "register",
    "get_delivered_notifications": "getDeliveredNotifications",
}


def rewrite_native_import(import_line: str) -> str:
    """Rewrite a pylevate.native import to direct Capacitor plugin imports.

    Input:  import { Camera, Haptics } from 'pylevate-native-runtime';
    Output: import { Camera } from '@capacitor/camera';
            import { Haptics } from '@capacitor/haptics';
    """
    # Parse the named imports
    import re
    m = re.match(r"import\s*\{\s*([^}]+)\s*\}\s*from\s*'pylevate-native-runtime';?", import_line)
    if not m:
        return import_line

    names = [n.strip() for n in m.group(1).split(",")]
    lines: list[str] = []

    for name in names:
        if name in NATIVE_IMPORT_MAP:
            pkg, js_name = NATIVE_IMPORT_MAP[name]
            if name == js_name:
                lines.append(f"import {{ {js_name} }} from '{pkg}';")
            else:
                lines.append(f"import {{ {js_name} as {name} }} from '{pkg}';")
        else:
            # Unknown native import — pass through
            lines.append(f"// WARNING: unknown native import: {name}")

    return "\n".join(lines)


def rewrite_native_method_calls(js_source: str) -> str:
    """Rewrite Python-style method names to Capacitor's camelCase.

    Camera.get_photo(quality=90) → Camera.getPhoto({quality: 90})
    """
    import re
    for py_method, js_method in METHOD_MAP.items():
        if py_method != js_method:
            js_source = re.sub(
                rf"\.{py_method}\(",
                f".{js_method}(",
                js_source,
            )
    return js_source

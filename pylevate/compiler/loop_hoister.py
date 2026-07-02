"""Game loop hoister — transforms pygame-style game code into Phaser Scene.

Takes compiled JS (from py2js with game mode imports) and restructures it into
a call to createGame() with preload/create/update functions.

The compiled JS has pygame API calls like:
  pg.image.load('assets/player.png')
  pg.display.set_mode([800, 600])
  while (running) { ... }

This module restructures into:
  createGame({ width, height, preloadFn, createFn, updateFn })
"""

import re


def hoist_game_loop(js_source: str, filename: str = "main") -> str:
    """Transform a pygame-style game file into createGame() structure.

    1. Preserve imports and class definitions (sprite classes)
    2. Scan for display.set_mode() to extract width/height
    3. Collect asset loads → preload function
    4. Collect setup code (before while loop) → create function
    5. Extract while loop body → update function
    6. Elide no-ops (fill, flip, draw, tick)
    """
    lines = js_source.split("\n")

    imports: list[str] = []
    class_defs: list[str] = []
    preload_stmts: list[str] = []
    create_stmts: list[str] = []
    update_stmts: list[str] = []

    width, height = 800, 600
    fps = 60
    bg_color = "0x000000"

    in_while = False
    in_class = False
    in_event_for = False
    class_buffer: list[str] = []
    brace_depth = 0
    event_brace_depth = 0

    for line in lines:
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            continue

        # Track class definitions FIRST (before import check, since classes can start with 'export')
        if re.match(r"(export\s+)?class\s+\w+", stripped) and not in_while:
            in_class = True
            class_buffer = [line]
            brace_depth = stripped.count("{") - stripped.count("}")
            if brace_depth <= 0 and "{" in stripped:
                in_class = False
                class_defs.append("\n".join(class_buffer))
            continue

        if in_class:
            class_buffer.append(line)
            brace_depth += stripped.count("{") - stripped.count("}")
            if brace_depth <= 0:
                in_class = False
                class_defs.append("\n".join(class_buffer))
            continue

        # Collect imports (after class check)
        if stripped.startswith("import ") or (stripped.startswith("export ") and "=" not in stripped and "class " not in stripped):
            imports.append(line)
            continue

        # Skip comment-only lines
        if stripped.startswith("//"):
            continue

        # Detect while loop start
        if re.match(r"while\s*\(", stripped) and not in_while:
            in_while = True
            brace_depth = stripped.count("{") - stripped.count("}")
            continue

        if in_while:
            brace_depth += stripped.count("{") - stripped.count("}")
            if brace_depth <= 0:
                in_while = False
                continue

            # Inside while loop — skip event loop boilerplate
            if _is_event_loop_start(stripped):
                in_event_for = True
                event_brace_depth = stripped.count("{") - stripped.count("}")
                continue

            if in_event_for:
                event_brace_depth += stripped.count("{") - stripped.count("}")
                if event_brace_depth <= 0:
                    in_event_for = False
                continue

            # Skip no-ops
            if _is_noop(stripped):
                continue

            # Collect background color from screen.fill()
            fill_match = re.search(r"\.fill\(\[?\(?\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", stripped)
            if fill_match:
                r, g, b = int(fill_match.group(1)), int(fill_match.group(2)), int(fill_match.group(3))
                bg_color = f"0x{r:02x}{g:02x}{b:02x}"
                continue

            update_stmts.append(f"    {_strip_export(stripped)}")
            continue

        # Outside while loop — classify
        # Extract display dimensions — but KEEP the `screen = set_mode(...)`
        # assignment (fall through to setup) so `screen` is defined at module
        # scope; immediate-mode draw passes it to pg.draw.*/screen.blit.
        # (Previously this line was dropped, leaving `screen` undefined for any
        # non-sprite game.)
        mode_match = re.search(r"set_mode\(\[?\(?\s*(\d+)\s*,\s*(\d+)", stripped)
        if mode_match:
            width = int(mode_match.group(1))
            height = int(mode_match.group(2))

        # Extract fps from clock.tick
        tick_match = re.search(r"\.tick\(\s*(\d+)\s*\)", stripped)
        if tick_match:
            fps = int(tick_match.group(1))
            continue

        # Skip no-ops outside loop
        if _is_noop(stripped):
            continue

        # Skip variable declarations for running, clock
        if re.match(r"(let|const|export\s+let)\s+(running|clock)\s*=", stripped):
            continue

        # Collect asset loads for preload
        asset = _extract_asset(stripped)
        if asset:
            preload_stmts.append(asset)

        # Everything else is setup → create (strip export from locals)
        stmt = _strip_export(stripped)
        create_stmts.append(f"    {stmt}")

    # Build output
    output: list[str] = []
    output.extend(imports)
    # The hoister synthesizes a bare createGame() call, but py2js only imports
    # the pg.* members the source actually uses — so createGame is never
    # imported and the module throws "createGame is not defined" at load.
    # Add the import explicitly.
    if not any("createGame" in imp for imp in imports):
        output.append("import { createGame } from 'pylevate-game-runtime';")
    output.append("")

    # Emit sprite classes
    for cls in class_defs:
        output.append(cls)
        output.append("")

    # Module-scope setup:
    # pygame-style pre-loop state (`let foo = ...`) must live at MODULE scope so
    # the hoisted loop body (`_update`, a separate function) can see and mutate
    # it. Emitting it inside `_create` made every loop variable an undefined free
    # reference, so games built but didn't run. Setup here is scene-independent
    # (var inits, set_mode, font, lazy sprite/group creation), safe at load.
    for stmt in create_stmts:
        output.append(stmt.strip())
    output.append("")

    # Emit preload function
    output.append("function _preload(scene) {")
    for key, asset_type, path in preload_stmts:
        output.append(f"  scene.load.{asset_type}('{key}', '{path}');")
    output.append("}")
    output.append("")

    # _create is a no-op now: setup already ran at module scope above.
    output.append("function _create(scene) {}")
    output.append("")

    # Emit update function
    output.append("function _update(scene) {")
    for stmt in update_stmts:
        output.append(stmt)
    output.append("}")
    output.append("")

    # Emit createGame call
    output.append("createGame({")
    output.append(f"  width: {width},")
    output.append(f"  height: {height},")
    output.append(f"  fps: {fps},")
    output.append(f"  backgroundColor: '{bg_color}',")
    output.append("  preloadFn: _preload,")
    output.append("  createFn: _create,")
    output.append("  updateFn: _update,")
    output.append("});")
    output.append("")

    return "\n".join(output)


def _strip_export(line: str) -> str:
    """Remove 'export ' prefix from a statement (not valid inside functions)."""
    if line.startswith("export "):
        return line[7:]
    return line


def _is_noop(line: str) -> bool:
    """Check if a line is a no-op in Phaser."""
    noop_patterns = [
        r".*\.flip\(\)",
        r".*display\.flip\(\)",
        r".*display\.update\(\)",
        r".*\.draw\(\s*screen",
        r"pg\.init\(\)",
        r".*\.set_caption\(",
        # clock.tick(fps): the `clock` var is intentionally not declared, and
        # Phaser drives the frame rate — so this is a no-op.
        r".*\.tick\(",
    ]
    return any(re.match(p, line) for p in noop_patterns)


def _is_event_loop_start(line: str) -> bool:
    """Check if a line starts the pygame event loop."""
    return bool(
        re.match(r"for\s.*\bpg\.event\.get", line)
        or re.match(r"for\s.*event\b.*\.get\(\)", line)
    )


def _extract_asset(line: str) -> tuple[str, str, str] | None:
    """Extract asset loading info from a line. Returns (key, type, path) or None."""
    # pg.image.load('path')
    m = re.search(r"""pg\.image\.load\(\s*["']([^"']+)["']\s*\)""", line)
    if m:
        path = m.group(1)
        key = _path_to_key(path)
        return (key, "image", path)

    # pg.mixer.Sound('path')
    m = re.search(r"""pg\.mixer\.Sound\(\s*["']([^"']+)["']\s*\)""", line)
    if m:
        path = m.group(1)
        key = _path_to_key(path)
        return (key, "audio", path)

    # pg.mixer.music.load('path')
    m = re.search(r"""pg\.mixer\.music\.load\(\s*["']([^"']+)["']\s*\)""", line)
    if m:
        path = m.group(1)
        key = _path_to_key(path)
        return (key, "audio", path)

    return None


def _path_to_key(path: str) -> str:
    """Convert an asset path to a stable key."""
    name = path.split("/")[-1].split(".")[0]
    return re.sub(r"[^a-zA-Z0-9]", "_", name)

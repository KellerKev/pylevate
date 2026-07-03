"""PyLevate CLI — scaffold, develop, build, and deploy Python-native apps."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from pylevate.config import Config

# ---------------------------------------------------------------------------
# Typer app & Rich console
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="pylevate",
    help="PyLevate — build native apps with Python.",
    add_completion=False,
)
mobile_app = typer.Typer(help="Mobile (Capacitor) commands.")
app.add_typer(mobile_app, name="mobile")

console = Console()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@app.command()
def init(
    name: str = typer.Argument("my-app", help="Project directory name."),
    template: str = typer.Option(
        "app",
        "--template",
        "-t",
        help="Project template.",
        show_default=True,
    ),
    mobile: bool = typer.Option(
        False, "--mobile", help="Pre-configure Capacitor for mobile builds."
    ),
) -> None:
    """Scaffold a new PyLevate project."""
    valid_templates = ("app", "game", "hybrid", "dashboard")
    # Compilation mode per template — the dashboard template is an app-mode
    # project (Config.mode has no "dashboard" value).
    template_modes = {"app": "app", "game": "game", "hybrid": "hybrid", "dashboard": "app"}
    if template not in valid_templates:
        console.print(
            f"[red]Unknown template '[bold]{template}[/bold]'. "
            f"Choose from: {', '.join(valid_templates)}[/red]"
        )
        raise typer.Exit(code=1)

    project_dir = Path.cwd() / name
    template_dir = TEMPLATES_DIR / template

    if project_dir.exists():
        console.print(f"[red]Directory '{name}' already exists.[/red]")
        raise typer.Exit(code=1)

    if not template_dir.exists() or not any(template_dir.iterdir()):
        console.print(
            f"[red]Template directory not found or empty: {template_dir}[/red]"
        )
        raise typer.Exit(code=1)

    # -- Copy template files ------------------------------------------------
    with console.status(f"[cyan]Scaffolding project from '{template}' template..."):
        shutil.copytree(template_dir, project_dir)

    # -- Write pylevate.config.py ------------------------------------------
    mode = template_modes[template]
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

    # -- Capacitor pre-configuration ---------------------------------------
    if mobile:
        from pylevate.mobile.capacitor import write_capacitor_config, update_package_json, CapacitorProject

        cap = CapacitorProject(
            project_dir=project_dir,
            config=Config(mode=mode, entry="main.py", out_dir="dist/"),
        )
        write_capacitor_config(cap)
        update_package_json(project_dir, ["ios"])
        console.print("[green]Capacitor config created.[/green]")

    # -- npm install (if package.json exists) ------------------------------
    package_json = project_dir / "package.json"
    if package_json.exists():
        with console.status("[cyan]Running npm install..."):
            try:
                subprocess.run(
                    ["npm", "install"],
                    cwd=project_dir,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError:
                console.print(
                    "[yellow]npm not found — skipping dependency install. "
                    "Run 'npm install' manually.[/yellow]"
                )
            except subprocess.CalledProcessError as exc:
                console.print(f"[red]npm install failed:[/red]\n{exc.stderr}")

    console.print(
        Panel(
            f"[green bold]Project '{name}' created![/green bold]\n\n"
            f"  cd {name}\n"
            "  pylevate dev",
            title="Next steps",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# dev
# ---------------------------------------------------------------------------


@app.command()
def dev(
    port: int = typer.Option(3000, "--port", "-p", help="Dev server port."),
    hmr_port: int = typer.Option(3001, "--hmr-port", help="HMR WebSocket port."),
    open_browser: bool = typer.Option(
        False, "--open", "-o", help="Open browser on start."
    ),
) -> None:
    """Start the dev server with file watching and HMR."""
    project_dir = Path.cwd()
    config = Config.load(project_dir)
    config.dev_port = port
    config.hmr_port = hmr_port

    # Lazy import to avoid circular / heavy imports at CLI parse time.
    from pylevate.server import DevServer

    console.print(
        f"[cyan]Starting dev server on http://localhost:{port} "
        f"(HMR on ws://localhost:{hmr_port})...[/cyan]"
    )

    server = DevServer(project_dir=project_dir, config=config)
    try:
        server.start(open_browser=open_browser)
    except KeyboardInterrupt:
        console.print("\n[yellow]Dev server stopped.[/yellow]")


# ---------------------------------------------------------------------------
# playground
# ---------------------------------------------------------------------------


@app.command()
def playground(
    port: int = typer.Option(4000, "--port", "-p", help="Playground server port."),
) -> None:
    """Launch the interactive playground."""
    playground_dir = Path(__file__).resolve().parent.parent / "playground"
    if not playground_dir.exists():
        console.print("[red]Playground directory not found.[/red]")
        raise typer.Exit(code=1)

    from pylevate.server import DevServer

    config = Config(mode="app", entry="main.py", out_dir="dist/", dev_port=port)

    console.print(f"[cyan]Playground at http://localhost:{port}[/cyan]")

    # Serve playground files directly
    import http.server
    import functools
    import threading

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(playground_dir)
    )

    # We need the compile API too — use the HMR handler that has POST support
    from pylevate.server import _HMRHTTPRequestHandler

    api_handler = type(
        "_PlaygroundHandler",
        (_HMRHTTPRequestHandler,),
        {"hmr_port": 0},
    )
    api_handler_partial = functools.partial(
        api_handler, directory=str(playground_dir)
    )

    httpd = http.server.HTTPServer(("localhost", port), api_handler_partial)
    console.print(f"[green]Playground listening on http://localhost:{port}[/green]")

    import webbrowser
    webbrowser.open(f"http://localhost:{port}")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[yellow]Playground stopped.[/yellow]")


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


@app.command()
def build(
    target: str = typer.Option(
        "web",
        "--target",
        "-t",
        help="Build target (web, capacitor, all).",
    ),
    out_dir: str = typer.Option("dist/", "--out-dir", "-o", help="Output directory."),
    analyze: bool = typer.Option(
        False, "--analyze", help="Show bundle size analysis after build."
    ),
    no_minify: bool = typer.Option(
        False, "--no-minify", help="Skip minification and asset hashing."
    ),
) -> None:
    """Create a production build."""
    valid_targets = ("web", "capacitor", "all")
    if target not in valid_targets:
        console.print(
            f"[red]Unknown target '[bold]{target}[/bold]'. "
            f"Choose from: {', '.join(valid_targets)}[/red]"
        )
        raise typer.Exit(code=1)

    project_dir = Path.cwd()
    config = Config.load(project_dir)
    config.out_dir = out_dir

    from pylevate.compiler.pipeline import Pipeline

    targets = ["web", "capacitor"] if target == "all" else [target]

    for tgt in targets:
        with console.status(f"[cyan]Building for {tgt}..."):
            try:
                pipeline = Pipeline(
                    project_dir=project_dir, config=config, production=not no_minify
                )
                result = pipeline.build(target=tgt)
            except Exception as exc:
                console.print(f"[red]Build failed ({tgt}): {exc}[/red]")
                raise typer.Exit(code=1) from exc

        for warning in result.warnings:
            console.print(f"[yellow]warning: {warning}[/yellow]")

        if not result.success:
            for err in result.errors:
                console.print(f"[red]{err}[/red]")
            console.print(f"[red]Build failed ({tgt}).[/red]")
            raise typer.Exit(code=1)

        console.print(f"[green]Build complete ({tgt}) -> {out_dir}{tgt}/[/green]")

    if analyze:
        console.print("[cyan]Bundle analysis:[/cyan]")
        out_path = Path(out_dir)
        if out_path.exists():
            for f in sorted(out_path.rglob("*")):
                if f.is_file():
                    size_kb = f.stat().st_size / 1024
                    console.print(f"  {f.relative_to(out_path)}  [dim]{size_kb:.1f} KB[/dim]")
        else:
            console.print("[yellow]Output directory not found.[/yellow]")


# ---------------------------------------------------------------------------
# mobile subcommands
# ---------------------------------------------------------------------------


@mobile_app.command("init")
def mobile_init(
    platform: str = typer.Argument(
        "ios", help="Platform to initialize (ios, android, or both)."
    ),
) -> None:
    """Initialize Capacitor for mobile builds."""
    from pylevate.mobile.capacitor import init_capacitor

    project_dir = Path.cwd()
    config = Config.load(project_dir)
    platforms = ["ios", "android"] if platform == "both" else [platform]

    with console.status(f"[cyan]Initializing Capacitor ({', '.join(platforms)})..."):
        try:
            init_capacitor(project_dir, config, platforms)
        except Exception as exc:
            console.print(f"[red]Capacitor init failed: {exc}[/red]")
            raise typer.Exit(code=1) from exc

    console.print(f"[green]Capacitor initialized for {', '.join(platforms)}.[/green]")


@mobile_app.command("ios")
def mobile_ios() -> None:
    """Build for Capacitor, sync, and open Xcode."""
    _mobile_build_and_open("ios")


@mobile_app.command("android")
def mobile_android() -> None:
    """Build for Capacitor, sync, and open Android Studio."""
    _mobile_build_and_open("android")


@mobile_app.command("run")
def mobile_run(
    platform: str = typer.Argument(..., help="Platform to run (ios or android)."),
) -> None:
    """Build, sync, and run on a connected device or simulator."""
    if platform not in ("ios", "android"):
        console.print(f"[red]Unknown platform '{platform}'. Use 'ios' or 'android'.[/red]")
        raise typer.Exit(code=1)

    from pylevate.compiler.pipeline import Pipeline
    from pylevate.mobile.capacitor import sync_capacitor, run_on_device

    project_dir = Path.cwd()
    config = Config.load(project_dir)

    # Build for capacitor
    with console.status("[cyan]Building for Capacitor..."):
        pipeline = Pipeline(project_dir=project_dir, config=config)
        result = pipeline.build(target="capacitor")
        if not result.success:
            for e in result.errors:
                console.print(f"  [red]{e}[/red]")
            raise typer.Exit(code=1)

    # Sync native project
    with console.status(f"[cyan]Syncing {platform}..."):
        sync_capacitor(project_dir)

    # Run
    console.print(f"[cyan]Running on {platform}...[/cyan]")
    run_on_device(project_dir, platform)


def _mobile_build_and_open(platform: str) -> None:
    """Build for Capacitor, sync, and open the native IDE."""
    from pylevate.compiler.pipeline import Pipeline
    from pylevate.mobile.capacitor import sync_capacitor, open_ide

    project_dir = Path.cwd()
    config = Config.load(project_dir)

    with console.status("[cyan]Building for Capacitor..."):
        pipeline = Pipeline(project_dir=project_dir, config=config)
        result = pipeline.build(target="capacitor")
        if not result.success:
            for e in result.errors:
                console.print(f"  [red]{e}[/red]")
            raise typer.Exit(code=1)

    with console.status(f"[cyan]Syncing {platform}..."):
        sync_capacitor(project_dir)

    console.print(f"[green]Opening {platform} project...[/green]")
    open_ide(project_dir, platform)


# ---------------------------------------------------------------------------
# Entry-point for `python -m pylevate.cli`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()

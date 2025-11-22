"""Configuration management CLI commands for DevClean."""

import os
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from .settings import (
    DevCleanConfig,
    create_sample_config,
    get_config_path,
    load_config,
    save_config,
)

config_app = typer.Typer(
    name="config",
    help="Manage DevClean configuration",
    no_args_is_help=True,
)
console = Console()


@config_app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config"),
    global_config: bool = typer.Option(
        False, "--global", "-g", help="Create global config in home directory"
    ),
) -> None:
    """Create a sample configuration file."""
    if global_config:
        config_path = Path.home() / ".devclean.toml"
    else:
        config_path = Path.cwd() / ".devclean.toml"

    if config_path.exists() and not force:
        console.print(f"[yellow]Config file already exists: {config_path}[/yellow]")
        console.print("Use --force to overwrite or --global for global config")
        raise typer.Exit(1)

    try:
        create_sample_config(config_path)
        console.print(f"[green]✓ Created config file: {config_path}[/green]")
        console.print()
        console.print("Next steps:")
        console.print("  • [cyan]devclean config edit[/cyan] - Edit the configuration")
        console.print("  • [cyan]devclean config show[/cyan] - View current settings")
        console.print(
            "  • [cyan]devclean config add-protected ~/important[/cyan] - Add protected paths"
        )
    except Exception as e:
        console.print(f"[red]Error creating config: {e}[/red]")
        raise typer.Exit(1)


@config_app.command()
def show(
    config_file: Path | None = typer.Option(None, "--config", "-c", help="Path to config file"),
) -> None:
    """Display current configuration."""
    try:
        config = load_config(config_file)
        config_path = config_file or get_config_path()

        console.print(f"[bold]Configuration from: {config_path}[/bold]")
        if not config_path.exists():
            console.print("[dim]  (using defaults - no config file found)[/dim]")
        console.print()

        # Scan settings
        table = Table(title="Scan Settings", show_header=False)
        table.add_column("Setting", style="cyan")
        table.add_column("Value")

        table.add_row("Minimum size", f"{config.scan.min_size_mb} MB")
        table.add_row("Include venvs", "✓" if config.scan.include_venvs else "✗")
        table.add_row("Include node_modules", "✓" if config.scan.include_node_modules else "✗")
        table.add_row("Timeout", f"{config.scan.timeout_seconds} seconds")
        table.add_row("Max depth", str(config.scan.max_depth))
        table.add_row("Parallel workers", str(config.scan.parallel_workers))

        console.print(table)
        console.print()

        # Display settings
        table = Table(title="Display Settings", show_header=False)
        table.add_column("Setting", style="cyan")
        table.add_column("Value")

        table.add_row("Show progress", "✓" if config.display.show_progress else "✗")
        table.add_row("Color output", "✓" if config.display.color_output else "✗")
        table.add_row("Table format", config.display.table_format)
        table.add_row("Size units", config.display.size_units)

        console.print(table)
        console.print()

        # Safety settings
        table = Table(title="Safety Settings", show_header=False)
        table.add_column("Setting", style="cyan")
        table.add_column("Value")

        table.add_row("Require confirmation", "✓" if config.safety.require_confirmation else "✗")
        table.add_row("Protected paths", f"{len(config.safety.protected_paths)} paths")
        table.add_row(
            "Never delete patterns", f"{len(config.safety.never_delete_patterns)} patterns"
        )
        table.add_row("Always safe patterns", f"{len(config.safety.always_safe_patterns)} patterns")

        console.print(table)

        if config.safety.protected_paths:
            console.print()
            table = Table(title="Protected Paths", show_header=False)
            table.add_column("Path", style="dim")
            for path in config.safety.protected_paths:
                table.add_row(path)
            console.print(table)

    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)


@config_app.command()
def edit(
    config_file: Path | None = typer.Option(None, "--config", "-c", help="Path to config file"),
) -> None:
    """Open configuration file in $EDITOR."""
    config_path = config_file or get_config_path()

    if not config_path.exists():
        console.print(f"[yellow]Config file doesn't exist: {config_path}[/yellow]")
        create = typer.confirm("Create it now?")
        if create:
            create_sample_config(config_path)
            console.print(f"[green]Created config file: {config_path}[/green]")
        else:
            raise typer.Exit(1)

    editor = os.environ.get("EDITOR", "nano")
    try:
        subprocess.run([editor, str(config_path)], check=True)
        console.print("[green]✓ Config file updated[/green]")
    except subprocess.CalledProcessError:
        console.print(f"[red]Error opening editor: {editor}[/red]")
        console.print(f"Set EDITOR environment variable or edit manually: {config_path}")
        raise typer.Exit(1)
    except FileNotFoundError:
        console.print(f"[red]Editor not found: {editor}[/red]")
        console.print(f"Set EDITOR environment variable or edit manually: {config_path}")
        raise typer.Exit(1)


@config_app.command("add-protected")
def add_protected(
    path: str = typer.Argument(..., help="Path to add to protected paths"),
    config_file: Path | None = typer.Option(None, "--config", "-c", help="Path to config file"),
) -> None:
    """Add a path to the protected paths list."""
    try:
        config = load_config(config_file)
        config_path = config_file or get_config_path()

        # Expand and resolve the path
        target_path = str(Path(path).expanduser().resolve())

        if target_path in config.safety.protected_paths:
            console.print(f"[yellow]Path already protected: {target_path}[/yellow]")
            return

        config.safety.protected_paths.append(target_path)
        save_config(config, config_path)

        console.print(f"[green]✓ Added protected path: {target_path}[/green]")
        console.print(f"[dim]Updated config: {config_path}[/dim]")

    except Exception as e:
        console.print(f"[red]Error updating config: {e}[/red]")
        raise typer.Exit(1)


@config_app.command("add-safe")
def add_safe(
    pattern: str = typer.Argument(..., help="Pattern to add to always safe patterns"),
    config_file: Path | None = typer.Option(None, "--config", "-c", help="Path to config file"),
) -> None:
    """Add a pattern to the always safe patterns list."""
    try:
        config = load_config(config_file)
        config_path = config_file or get_config_path()

        if pattern in config.safety.always_safe_patterns:
            console.print(f"[yellow]Pattern already marked as safe: {pattern}[/yellow]")
            return

        config.safety.always_safe_patterns.append(pattern)
        save_config(config, config_path)

        console.print(f"[green]✓ Added safe pattern: {pattern}[/green]")
        console.print(f"[dim]Updated config: {config_path}[/dim]")

    except Exception as e:
        console.print(f"[red]Error updating config: {e}[/red]")
        raise typer.Exit(1)


@config_app.command("remove-protected")
def remove_protected(
    path: str = typer.Argument(..., help="Path to remove from protected paths"),
    config_file: Path | None = typer.Option(None, "--config", "-c", help="Path to config file"),
) -> None:
    """Remove a path from the protected paths list."""
    try:
        config = load_config(config_file)
        config_path = config_file or get_config_path()

        # Expand and resolve the path
        target_path = str(Path(path).expanduser().resolve())

        if target_path not in config.safety.protected_paths:
            console.print(f"[yellow]Path not in protected paths: {target_path}[/yellow]")
            return

        config.safety.protected_paths.remove(target_path)
        save_config(config, config_path)

        console.print(f"[green]✓ Removed protected path: {target_path}[/green]")
        console.print(f"[dim]Updated config: {config_path}[/dim]")

    except Exception as e:
        console.print(f"[red]Error updating config: {e}[/red]")
        raise typer.Exit(1)


@config_app.command("remove-safe")
def remove_safe(
    pattern: str = typer.Argument(..., help="Pattern to remove from always safe patterns"),
    config_file: Path | None = typer.Option(None, "--config", "-c", help="Path to config file"),
) -> None:
    """Remove a pattern from the always safe patterns list."""
    try:
        config = load_config(config_file)
        config_path = config_file or get_config_path()

        if pattern not in config.safety.always_safe_patterns:
            console.print(f"[yellow]Pattern not in safe patterns: {pattern}[/yellow]")
            return

        config.safety.always_safe_patterns.remove(pattern)
        save_config(config, config_path)

        console.print(f"[green]✓ Removed safe pattern: {pattern}[/green]")
        console.print(f"[dim]Updated config: {config_path}[/dim]")

    except Exception as e:
        console.print(f"[red]Error updating config: {e}[/red]")
        raise typer.Exit(1)


@config_app.command("list-patterns")
def list_patterns(
    config_file: Path | None = typer.Option(None, "--config", "-c", help="Path to config file"),
) -> None:
    """List all configured patterns and paths."""
    try:
        config = load_config(config_file)

        # Protected paths
        if config.safety.protected_paths:
            table = Table(title="Protected Paths", show_header=False)
            table.add_column("Path", style="red")
            for path in config.safety.protected_paths:
                table.add_row(path)
            console.print(table)
            console.print()

        # Safe patterns
        if config.safety.always_safe_patterns:
            table = Table(title="Always Safe Patterns", show_header=False)
            table.add_column("Pattern", style="green")
            for pattern in config.safety.always_safe_patterns:
                table.add_row(pattern)
            console.print(table)
            console.print()

        # Never delete patterns
        if config.safety.never_delete_patterns:
            table = Table(title="Never Delete Patterns", show_header=False)
            table.add_column("Pattern", style="yellow")
            for pattern in config.safety.never_delete_patterns:
                table.add_row(pattern)
            console.print(table)
        else:
            console.print("[dim]No patterns configured[/dim]")

    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)


@config_app.command()
def validate(
    config_file: Path | None = typer.Option(None, "--config", "-c", help="Path to config file"),
) -> None:
    """Validate configuration file."""
    try:
        config = load_config(config_file)
        config_path = config_file or get_config_path()

        console.print(f"[green]✓ Configuration is valid: {config_path}[/green]")

        # Check for potential issues
        issues = []

        # Check protected paths exist
        for path in config.safety.protected_paths:
            if not Path(path).exists():
                issues.append(f"Protected path does not exist: {path}")

        # Check for reasonable values
        if config.scan.min_size_mb < 1:
            issues.append("min_size_mb should be at least 1 MB")

        if config.scan.parallel_workers < 1 or config.scan.parallel_workers > 16:
            issues.append("parallel_workers should be between 1 and 16")

        if issues:
            console.print()
            console.print("[yellow]Potential issues found:[/yellow]")
            for issue in issues:
                console.print(f"  • {issue}")

    except Exception as e:
        console.print(f"[red]Configuration validation failed: {e}[/red]")
        raise typer.Exit(1)

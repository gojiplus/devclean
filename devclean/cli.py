"""CLI interface for devclean."""

import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

app = typer.Typer(
    name="devclean",
    help="AI-powered disk cleanup for developers on macOS",
    no_args_is_help=False,
)
console = Console()


@app.command()
def scan(
    min_size: int = typer.Option(100, "--min-size", "-m", help="Minimum size in MB to report"),
    no_venvs: bool = typer.Option(False, "--no-venvs", help="Skip scanning for virtual environments"),
    no_node: bool = typer.Option(False, "--no-node", help="Skip scanning for node_modules"),
):
    """Quick scan to show what's taking space (no AI, no deletion)."""
    from .scanner import scan_all
    
    console.print("[dim]Scanning...[/dim]")
    
    result = scan_all(
        include_venvs=not no_venvs,
        include_node_modules=not no_node,
        min_size_mb=min_size,
    )
    
    if not result.all_items:
        console.print("[green]No significant cruft found![/green]")
        return
    
    # Display results in a table
    table = Table(title="Developer Cruft Found", show_lines=True)
    table.add_column("Size", style="cyan", justify="right")
    table.add_column("Category", style="magenta")
    table.add_column("Description")
    table.add_column("Status", style="dim")
    table.add_column("Path", style="dim")
    
    for item in result.items:
        status = ""
        if item.tool_installed is False:
            status = "[red]ORPHANED[/red]"
        elif item.tool_installed is True:
            status = "[green]in use[/green]"
        
        safe = "[green]safe[/green]" if item.safe else "[yellow]caution[/yellow]"
        
        table.add_row(
            item.size_human,
            item.category,
            item.description,
            f"{status} {safe}",
            str(item.path),
        )
    
    if result.venvs:
        for item in result.venvs:
            table.add_row(
                item.size_human,
                "venv",
                item.description,
                "[green]safe[/green]",
                str(item.path),
            )
    
    if result.node_modules:
        for item in result.node_modules:
            table.add_row(
                item.size_human,
                "node_modules",
                item.description,
                "[green]safe[/green]",
                str(item.path),
            )
    
    console.print(table)
    console.print()
    console.print(Panel(
        f"[bold]Total: {result.total_gb:.1f} GB[/bold] across {len(result.all_items)} items\n\n"
        f"Run [cyan]devclean chat[/cyan] for interactive AI-guided cleanup",
        border_style="blue",
    ))


@app.command()
def chat(
    api_key: Optional[str] = typer.Option(
        None, 
        "--api-key", 
        "-k", 
        envvar="ANTHROPIC_API_KEY",
        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)",
    ),
) -> None:
    """Interactive AI-powered cleanup session."""
    from .agent import run_agent
    
    if not api_key:
        console.print("[red]Error: No API key provided.[/red]")
        console.print("Set ANTHROPIC_API_KEY environment variable or use --api-key")
        raise typer.Exit(1)
    
    run_agent(api_key=api_key)


@app.command()
def clean(
    path: str = typer.Argument(..., help="Path to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
    sudo: bool = typer.Option(False, "--sudo", "-s", help="Use sudo for deletion"),
) -> None:
    """Delete a specific path (use with caution)."""
    import shutil
    import subprocess
    
    target = Path(path).expanduser()
    
    if not target.exists():
        console.print(f"[red]Path does not exist: {target}[/red]")
        raise typer.Exit(1)
    
    # Safety checks
    home = Path.home()
    protected = [home, home / "Documents", home / "Desktop", home / "Downloads", Path("/")]
    if target in protected:
        console.print(f"[red]Refusing to delete protected path: {target}[/red]")
        raise typer.Exit(1)
    
    # Get size
    from .scanner import get_dir_size
    size = get_dir_size(target)
    size_str = f"{size / (1024**3):.2f} GB" if size else "unknown size"
    
    if not force:
        confirm = typer.confirm(f"Delete {target} ({size_str})?")
        if not confirm:
            console.print("[dim]Cancelled[/dim]")
            raise typer.Exit(0)
    
    try:
        if sudo:
            result = subprocess.run(
                ["sudo", "rm", "-rf", str(target)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                console.print(f"[red]Error: {result.stderr}[/red]")
                raise typer.Exit(1)
        else:
            shutil.rmtree(target)
        
        console.print(f"[green]Deleted {target} ({size_str} freed)[/green]")
        
    except PermissionError:
        console.print(f"[red]Permission denied. Try with --sudo[/red]")
        raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """DevClean - AI-powered disk cleanup for developers."""
    if ctx.invoked_subcommand is None:
        # Default to chat if API key is available, otherwise scan
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            from .agent import run_agent
            run_agent(api_key=api_key)
        else:
            console.print(Panel(
                "[bold blue]DevClean[/bold blue] - AI-powered disk cleanup\n\n"
                "Commands:\n"
                "  [cyan]devclean scan[/cyan]  - Quick scan (no AI)\n"
                "  [cyan]devclean chat[/cyan]  - Interactive AI cleanup\n"
                "  [cyan]devclean clean PATH[/cyan] - Delete a path\n\n"
                "[dim]Set ANTHROPIC_API_KEY for AI features[/dim]",
                border_style="blue",
            ))


if __name__ == "__main__":
    app()

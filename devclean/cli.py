"""Command-line interface for DevClean."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .candidates import BULK_DELETABLE, Candidate, Tier
from .config_cli import config_app
from .exceptions import DevCleanError, UnsafePathError
from .safety import assert_safe_to_delete
from .scanner import ScanResult, scan_all
from .settings import DevCleanConfig, load_config
from .validation import sanitize_path

app = typer.Typer(
    name="devclean",
    help="Find and clean developer cruft on macOS.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()
app.add_typer(config_app)

TIER_STYLE = {
    Tier.AUTO: "green",
    Tier.VERIFIED: "green",
    Tier.PROBE: "yellow",
    Tier.INSPECT: "red",
}


def _human(size_bytes: int) -> str:
    gb = size_bytes / (1024**3)
    if gb >= 1:
        return f"{gb:.1f} GB"
    return f"{size_bytes / (1024**2):.0f} MB"


def _run_scan(
    min_size: int | None,
    no_venvs: bool,
    no_node: bool,
    no_project: bool,
    no_system: bool,
    no_temp: bool,
) -> ScanResult:
    config = load_config()
    return scan_all(
        min_size_mb=min_size if min_size is not None else config.scan.min_size_mb,
        include_venvs=config.scan.include_venvs and not no_venvs,
        include_node_modules=config.scan.include_node_modules and not no_node,
        include_project_cruft=not no_project,
        include_system_artifacts=config.scan.include_system_artifacts and not no_system,
        include_temporary_dirs=config.scan.include_temporary_dirs and not no_temp,
        additional_search_paths=config.additional_search_paths,
        project_max_depth=config.scan.max_depth,
        project_scan_timeout=config.scan.timeout_seconds,
    )


def _render(result: ScanResult) -> None:
    if not result.candidates:
        console.print("[green]Nothing found above the size floor.[/green]")
        for error in result.errors:
            console.print(f"[dim]scan warning: {error}[/dim]")
        return

    table = Table(title="Cleanup candidates")
    table.add_column("Size", justify="right", style="cyan")
    table.add_column("Tier")
    table.add_column("Category", style="magenta")
    table.add_column("What", overflow="fold")
    table.add_column("Comes back via", overflow="fold", style="dim")

    for candidate in result.candidates:
        table.add_row(
            candidate.size_human,
            f"[{TIER_STYLE[candidate.tier]}]{candidate.tier.value}[/]",
            candidate.category,
            str(candidate.path),
            candidate.recovery,
        )

    console.print(table)

    console.print(
        f"\n[bold]{_human(result.reclaimable_bytes)}[/bold] in "
        f"{len(result.bulk_deletable)} candidates can be removed without review."
    )

    needs_review = result.needs_review
    if needs_review:
        console.print(
            f"[yellow]{_human(sum(c.size_bytes for c in needs_review))}[/yellow] in "
            f"{len(needs_review)} candidates needs a look first:"
        )
        for candidate in needs_review:
            console.print(f"  [bold]{candidate.path}[/bold] ({candidate.size_human})")
            for concern in candidate.concerns:
                console.print(f"    [red]·[/red] {concern}")

    for error in result.errors:
        console.print(f"[dim]scan warning: {error}[/dim]")


@app.command()
def scan(
    min_size: int | None = typer.Option(
        None, "--min-size", "-m", help="Global size floor in MB"
    ),
    no_venvs: bool = typer.Option(False, "--no-venvs", help="Skip virtualenv scan"),
    no_node: bool = typer.Option(False, "--no-node", help="Skip node_modules scan"),
    no_project: bool = typer.Option(
        False, "--no-project", help="Skip project-local scan"
    ),
    no_system: bool = typer.Option(
        False, "--no-system", help="Skip system toolchain scan"
    ),
    no_temp: bool = typer.Option(
        False, "--no-temp", help="Skip temporary-directory scan"
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table"),
) -> None:
    """Scan for cruft. Read-only — never deletes anything."""
    result = _run_scan(min_size, no_venvs, no_node, no_project, no_system, no_temp)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "total_bytes": result.total_bytes,
                    "reclaimable_bytes": result.reclaimable_bytes,
                    "candidates": [c.to_dict() for c in result.candidates],
                    "errors": result.errors,
                },
                indent=2,
            )
        )
        return

    _render(result)


@app.command()
def plan(
    min_size: int | None = typer.Option(
        None, "--min-size", "-m", help="Global size floor in MB"
    ),
    no_venvs: bool = typer.Option(False, "--no-venvs", help="Skip virtualenv scan"),
    no_node: bool = typer.Option(False, "--no-node", help="Skip node_modules scan"),
    no_project: bool = typer.Option(
        False, "--no-project", help="Skip project-local scan"
    ),
    no_system: bool = typer.Option(
        False, "--no-system", help="Skip system toolchain scan"
    ),
    no_temp: bool = typer.Option(
        False, "--no-temp", help="Skip temporary-directory scan"
    ),
) -> None:
    """Show what a cleanup would do, grouped by tier. Deletes nothing."""
    result = _run_scan(min_size, no_venvs, no_node, no_project, no_system, no_temp)

    for tier in (Tier.AUTO, Tier.VERIFIED, Tier.PROBE, Tier.INSPECT):
        group = result.by_tier(tier)
        if not group:
            continue

        total = _human(sum(c.size_bytes for c in group))
        deletable = (
            "bulk-deletable" if tier in BULK_DELETABLE else "needs your decision"
        )
        console.print(
            f"\n[bold][{TIER_STYLE[tier]}]{tier.value}[/] — {total} ({deletable})[/bold]"
        )

        for candidate in group:
            multiplier = f" ×{candidate.member_count}"  # noqa: RUF001 - display glyph
            suffix = multiplier if candidate.member_count > 1 else ""
            console.print(f"  {candidate.size_human:>9}  {candidate.path}{suffix}")
            console.print(f"             [dim]back via: {candidate.recovery}[/dim]")
            for concern in candidate.concerns:
                console.print(f"             [red]concern:[/red] {concern}")

    console.print(
        "\nRun [bold]devclean clean --tier auto[/bold] to act on the safest group, "
        "or [bold]devclean clean PATH[/bold] for anything listed as needing a decision."
    )

    for error in result.errors:
        console.print(f"[dim]scan warning: {error}[/dim]")


def _delete(path: Path, use_sudo: bool = False) -> None:
    if use_sudo:
        subprocess.run(["sudo", "rm", "-rf", str(path)], check=True, timeout=300)
    else:
        shutil.rmtree(path)


@app.command()
def clean(
    path: str = typer.Argument(None, help="A single path to delete"),
    tier: str = typer.Option(
        None, "--tier", help="Delete a whole tier: auto or verified"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would happen, delete nothing"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
    use_sudo: bool = typer.Option(False, "--sudo", "-s", help="Use sudo to delete"),
    min_size: int | None = typer.Option(
        None, "--min-size", "-m", help="Global size floor in MB"
    ),
) -> None:
    """Delete a single path, or a whole tier with --tier.

    Only ``auto`` and ``verified`` may be deleted in bulk. Anything a probe
    objected to must be named explicitly, so a directory whose contents were
    never understood cannot be swept up by a batch command.
    """
    if not path and not tier:
        console.print("[red]Give a PATH or --tier.[/red]")
        raise typer.Exit(1)

    if path and tier:
        console.print("[red]Give a PATH or --tier, not both.[/red]")
        raise typer.Exit(1)

    config = load_config()

    if tier:
        _clean_tier(tier, dry_run, force, use_sudo, min_size, config)
        return

    target = sanitize_path(path)
    try:
        assert_safe_to_delete(
            target, config.safety.protected_paths, require_depth=False
        )
    except DevCleanError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if dry_run:
        console.print(f"[yellow]would delete[/yellow] {target}")
        return

    if not force and not typer.confirm(f"Delete {target}?"):
        console.print("Cancelled.")
        raise typer.Exit(0)

    try:
        _delete(target, use_sudo)
    except (OSError, subprocess.SubprocessError) as exc:
        console.print(f"[red]Failed to delete {target}: {exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[green]Deleted[/green] {target}")


def _clean_tier(
    tier_name: str,
    dry_run: bool,
    force: bool,
    use_sudo: bool,
    min_size: int | None,
    config: DevCleanConfig,
) -> None:
    try:
        tier = Tier(tier_name.lower())
    except ValueError as exc:
        console.print(f"[red]Unknown tier '{tier_name}'. Use auto or verified.[/red]")
        raise typer.Exit(1) from exc

    if tier not in BULK_DELETABLE:
        console.print(
            f"[red]Tier '{tier.value}' cannot be deleted in bulk.[/red] "
            "Those candidates were never content-verified, or a probe objected. "
            "Delete them one at a time with `devclean clean PATH`."
        )
        raise typer.Exit(1)

    result = _run_scan(min_size, False, False, False, True, False)
    targets: list[Candidate] = [c for c in result.by_tier(tier) if c.bulk_deletable]

    if not targets:
        console.print(f"Nothing in tier '{tier.value}'.")
        return

    total = _human(sum(c.size_bytes for c in targets))
    console.print(f"[bold]{len(targets)} candidates, {total}[/bold]")
    for candidate in targets:
        console.print(f"  {candidate.size_human:>9}  {candidate.path}")

    if dry_run:
        console.print("\n[yellow]--dry-run: nothing was deleted.[/yellow]")
        return

    if not force and not typer.confirm(f"\nDelete all {len(targets)} of these?"):
        console.print("Cancelled.")
        raise typer.Exit(0)

    freed = 0
    for candidate in targets:
        # Roll-ups carry a category name rather than a real path; they are
        # reported for visibility and cleaned by their own tooling.
        if not candidate.path.is_absolute():
            console.print(
                f"[dim]skipping roll-up {candidate.path} — clean these per project[/dim]"
            )
            continue
        try:
            assert_safe_to_delete(candidate.path, config.safety.protected_paths)
            _delete(candidate.path, use_sudo)
        except (UnsafePathError, OSError, subprocess.SubprocessError) as exc:
            console.print(f"[red]skipped {candidate.path}: {exc}[/red]")
            continue
        freed += candidate.size_bytes
        console.print(f"[green]deleted[/green] {candidate.path}")

    console.print(f"\n[bold green]Freed {_human(freed)}[/bold green]")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Find and clean developer cruft on macOS."""
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


if __name__ == "__main__":
    app()

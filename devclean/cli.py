"""Command-line interface for DevClean."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .candidates import BULK_DELETABLE, Candidate, Tier, footprint_bytes, format_bytes
from .codex_releases import unused_codex_releases
from .config import CRUFT_PATTERNS
from .config_cli import config_app
from .exceptions import DevCleanError, UnsafePathError
from .probes import inspect_environment, probe_node_modules
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


def _run_scan(
    min_size: int | None,
    no_venvs: bool,
    no_node: bool,
    no_project: bool,
    no_system: bool,
    no_temp: bool,
) -> ScanResult:
    config = load_config()
    result = scan_all(
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

    for candidate in result.bulk_deletable:
        try:
            assert_safe_to_delete(candidate.path, config.safety.protected_paths)
        except (DevCleanError, OSError) as exc:
            candidate.downgrade(str(exc))
    return result


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
        f"\n[bold]{format_bytes(result.reclaimable_bytes)}[/bold] in "
        f"{len(result.bulk_deletable)} candidates can be removed without review."
    )

    needs_review = result.needs_review
    if needs_review:
        console.print(
            f"[yellow]{format_bytes(footprint_bytes(needs_review))}[/yellow] in "
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

        total = format_bytes(footprint_bytes(group))
        eligible = sum(c.bulk_deletable for c in group)
        deletable = f"{eligible} bulk-eligible" if eligible else "review individually"
        console.print(
            f"\n[bold][{TIER_STYLE[tier]}]{tier.value}[/] — {total} ({deletable})[/bold]"
        )

        for candidate in group:
            multiplier = f" ×{candidate.member_count}"  # noqa: RUF001 - display glyph
            suffix = multiplier if candidate.member_count > 1 else ""
            console.print(f"  {candidate.size_human:>9}  {candidate.path}{suffix}")
            if not candidate.path.is_absolute():
                console.print("             display total only")
            console.print(f"             [dim]back via: {candidate.recovery}[/dim]")
            for concern in candidate.concerns:
                console.print(f"             [red]concern:[/red] {concern}")

    console.print(
        "\nRun [bold]devclean clean --tier auto[/bold] to act on the safest group, "
        "or [bold]devclean clean PATH[/bold] for anything listed as needing a decision."
    )

    for error in result.errors:
        console.print(f"[dim]scan warning: {error}[/dim]")


def _owner_command(path: Path) -> list[str] | None:
    for pattern in CRUFT_PATTERNS:
        if not pattern.purge_command:
            continue
        cache = Path(pattern.path_template.format(home=Path.home()))
        if path == cache or path == cache.parent.resolve() / cache.name:
            argv = pattern.scoped_purge(path)
            if argv is None:
                raise UnsafePathError(
                    f"Review the scope of the owner's command: {pattern.purge_command}"
                )
            return argv
    return None


def _delete(path: Path, use_sudo: bool = False) -> None:
    if path.is_symlink():
        raise OSError(f"Refusing to follow a symbolic link: {path}")
    argv = _owner_command(path)
    if argv:
        subprocess.run(argv, check=True, timeout=300)
    elif use_sudo:
        subprocess.run(["sudo", "rm", "-rf", str(path)], check=True, timeout=300)
    elif path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def _free_space(path: Path | None = None) -> int | None:
    try:
        return shutil.disk_usage(path or Path.home()).free
    except OSError:
        return None


def _report_space_change(before: int | None, path: Path | None = None) -> None:
    after = _free_space(path)
    if before is None or after is None:
        console.print("Filesystem free-space change unavailable.")
        return
    change = after - before
    sign = "+" if change >= 0 else "-"
    console.print(
        f"Filesystem free-space change: {sign}{format_bytes(abs(change))} "
        f"on {path or Path.home()} (other activity can affect this)."
    )


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

    try:
        target = sanitize_path(path)
        assert_safe_to_delete(
            target, config.safety.protected_paths, require_depth=False
        )
        owner = _owner_command(target)
    except DevCleanError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    action = shlex.join(owner) if owner else f"delete {target}"
    if dry_run:
        console.print(f"[yellow]would[/yellow] {action}")
        return

    if not force and not typer.confirm(f"Proceed with {action}?"):
        console.print("Canceled.")
        raise typer.Exit(0)

    free_before = _free_space(target.parent)
    try:
        assert_safe_to_delete(
            target, config.safety.protected_paths, require_depth=False
        )
        _delete(target, use_sudo)
    except (DevCleanError, OSError, subprocess.SubprocessError) as exc:
        console.print(f"[red]Failed to clean {target}: {exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[green]Cleaned[/green] {target}")
    _report_space_change(free_before, target.parent)


@app.command()
def clean_codex_releases(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview old releases; delete nothing"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Skip confirmation, not safety checks"
    ),
) -> None:
    """Remove older Codex daemon releases, preserving current and running versions."""
    home = Path.home()
    config = load_config()
    try:
        current, targets, busy = unused_codex_releases(home)
        for target in targets:
            assert_safe_to_delete(target, config.safety.protected_paths)
    except (DevCleanError, OSError, ValueError) as exc:
        console.print(f"[red]Cannot clean Codex releases: {exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"Keeping current release: {current.name}")
    for target in busy:
        console.print(f"Keeping running release: {target.name}")
    if not targets:
        console.print("No unused older Codex releases to delete.")
        return
    for target in targets:
        console.print(f"  {target}")
    if dry_run:
        console.print("--dry-run: nothing was deleted.")
        return
    if not force and not typer.confirm(f"Delete these {len(targets)} old releases?"):
        console.print("Canceled.")
        return

    free_before = _free_space()
    try:
        for target in targets:
            identity = target.stat()
            latest, eligible, _busy = unused_codex_releases(home)
            if latest != current or target not in eligible:
                raise ValueError(
                    "Codex installation or process state changed; stopping cleanup"
                )
            assert_safe_to_delete(target, config.safety.protected_paths)
            checked = target.lstat()
            if target.is_symlink() or (identity.st_dev, identity.st_ino) != (
                checked.st_dev,
                checked.st_ino,
            ):
                raise ValueError(
                    f"Release directory changed during inspection: {target}"
                )
            _delete(target)
            console.print(f"Deleted {target.name}")
    except (DevCleanError, OSError, ValueError) as exc:
        console.print(f"[red]Cleanup stopped: {exc}[/red]")
        if isinstance(exc, PermissionError):
            console.print(
                "Check filesystem permissions and run from a terminal with write access."
            )
        _report_space_change(free_before)
        raise typer.Exit(1) from exc
    _report_space_change(free_before)


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

    total = format_bytes(footprint_bytes(targets))
    console.print(f"[bold]{len(targets)} candidates, {total}[/bold]")
    for candidate in targets:
        cmd = _owner_command(candidate.path)
        action = shlex.join(cmd) if cmd else str(candidate.path)
        console.print(f"  {candidate.size_human:>9}  {action}")

    if dry_run:
        console.print("\n[yellow]--dry-run: nothing was deleted.[/yellow]")
        return

    if not force and not typer.confirm(f"\nClean all {len(targets)} of these?"):
        console.print("Canceled.")
        raise typer.Exit(0)

    free_before = _free_space()
    deleted: list[Candidate] = []
    failures = 0
    for candidate in targets:
        try:
            assert_safe_to_delete(candidate.path, config.safety.protected_paths)
            if candidate.tier == Tier.VERIFIED:
                if candidate.category == "python":
                    _, concerns = inspect_environment(candidate.path)
                elif candidate.category == "node":
                    concerns = probe_node_modules(candidate.path)
                else:
                    concerns = ["no bulk cleanup check for this category"]
                if concerns:
                    raise UnsafePathError(", ".join(concerns))
            _delete(candidate.path, use_sudo)
        except (DevCleanError, OSError, subprocess.SubprocessError) as exc:
            failures += 1
            console.print(f"[red]skipped {candidate.path}: {exc}[/red]")
            continue
        deleted.append(candidate)
        console.print(f"[green]cleaned[/green] {candidate.path}")

    console.print(
        f"\nFootprint of successfully processed candidates: {format_bytes(footprint_bytes(deleted))} estimated from the scan."
    )
    _report_space_change(free_before)
    if failures:
        raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Find and clean developer cruft on macOS."""
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


if __name__ == "__main__":
    app()

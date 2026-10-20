"""Identify old Codex daemon installations without deleting application state."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def release_layout(home: Path) -> tuple[Path, list[Path]]:
    """Resolve the current installation and direct release directories.

    Args:
        home: Home directory containing the Codex installation.

    Returns:
        The resolved current release and non-symlink release directories.

    Raises:
        ValueError: If installation paths or the current link are unsafe.
    """
    root = home / ".codex"
    package = root / "packages/app-server-daemon"
    releases = package / "releases"
    if any(p.is_symlink() for p in (root, root / "packages", package, releases)):
        raise ValueError("Codex installation directories must not be symlinks")
    link = package / "current"
    if not link.is_symlink():
        raise ValueError(
            "Cannot identify the current Codex release: missing current link"
        )
    try:
        current = link.resolve(strict=True)
    except RuntimeError as exc:
        raise ValueError("The current Codex link contains a cycle") from exc
    if not current.is_dir() or current.parent != releases.resolve(strict=True):
        raise ValueError("The current Codex link points outside the release directory")
    return current, sorted(
        p for p in releases.iterdir() if p.is_dir() and not p.is_symlink()
    )


def _version(path: Path) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-[A-Za-z0-9_-]+)?", path.name)
    if match is None:
        return None
    return int(match[1]), int(match[2]), int(match[3])


def unused_codex_releases(home: Path) -> tuple[Path, list[Path], list[Path]]:
    """Find older releases whose executables are not open in visible processes.

    Args:
        home: Home directory containing the Codex installation.

    Returns:
        Current release, eligible old releases, and old releases still in use.

    Raises:
        ValueError: If installation or process state cannot be verified.
    """
    current, releases = release_layout(home)
    current_version = _version(current)
    if current_version is None or not (current / "bin/codex").is_file():
        raise ValueError(
            "The current Codex release lacks a recognized version or binary"
        )
    old = [
        p
        for p in releases
        if (version := _version(p)) is not None
        and version < current_version
        and (p / "bin/codex").is_file()
    ]
    if not old:
        return current, [], []
    try:
        result = subprocess.run(
            ["lsof", "-nP", "-d", "txt", "-F", "n"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(
            f"Cannot verify running Codex releases with lsof: {exc}"
        ) from exc
    executables = [
        Path(line[1:]) for line in result.stdout.splitlines() if line.startswith("n/")
    ]
    if result.returncode or result.stderr.strip() or not executables:
        raise ValueError(
            "lsof could not provide a complete process check; nothing deleted"
        )
    busy = [
        p for p in old if any(exe.is_relative_to(p.resolve()) for exe in executables)
    ]
    return current, [p for p in old if p not in busy], busy

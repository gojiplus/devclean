"""Inventory assistant history and installations without treating them as caches."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .candidates import Candidate, Tier
from .codex_releases import release_layout

_STORAGE = (
    (".codex/sessions", "history", "Codex session transcripts"),
    (".codex/archived_sessions", "history", "Codex archived sessions"),
    (".codex/.tmp", "staging", "Codex temporary plugin files"),
    (".codex/cache", "cache", "Codex cache"),
    (".codex/plugins", "installation", "Codex installed plugins"),
    (".claude/projects", "history", "Claude conversations and project memory"),
    (".claude/file-history", "history", "Claude file snapshots"),
    (".claude/backups", "history", "Claude backups"),
    (".claude/security", "installation", "Claude security dependencies"),
    (".claude/plugins", "installation", "Claude installed plugins"),
    (".claude/cache", "cache", "Claude cache"),
    (".claude/debug", "logs", "Claude debug logs"),
    (".claude/telemetry", "logs", "Claude telemetry"),
)
_CONCERNS = {
    "history": "May contain the only copy of conversations, memory, or undo data; deletion is irreversible without a backup",
    "installation": "Installed components may still be needed by the application",
    "staging": "Temporary files may belong to an active installation; close the application and inspect first",
    "cache": "Confirm the application can rebuild this cache and is not using it",
    "logs": "Deleting logs removes diagnostic evidence; close the application first",
    "database": "Application-managed state; do not delete SQLite files or journals while the application is running",
}


def find_assistant_storage(
    home: Path, get_size: Callable[[Path], int | None], min_size_mb: int = 100
) -> list[Candidate]:
    """Report assistant storage with explicit data-loss concerns.

    Args:
        home: Home directory to inspect.
        get_size: Function measuring allocated bytes without reading file contents.
        min_size_mb: Minimum size for each reported item.

    Returns:
        Inspection-only candidates, excluding credentials and settings.
    """
    candidates: list[Candidate] = []

    def add(path: Path, kind: str, description: str, evidence: list[str]) -> None:
        if path.is_symlink() or not path.exists():
            return
        size = get_size(path)
        if size is None or size < min_size_mb * 1024**2:
            return
        candidates.append(
            Candidate(
                path=path,
                size_bytes=size,
                category=f"assistant-{kind}",
                description=description,
                tier=Tier.INSPECT,
                recovery=(
                    "Restore from your own backup; application data is not necessarily reproducible"
                    if kind in {"history", "database"}
                    else "Use the owning application's installer or documented recovery procedure"
                ),
                evidence=evidence,
                concerns=[_CONCERNS[kind]],
            )
        )

    for relative, kind, description in _STORAGE:
        path = home / relative
        if any(parent.is_symlink() for parent in path.parents if parent != home):
            continue
        add(path, kind, description, ["known application storage location"])

    codex = home / ".codex"
    if codex.is_dir() and not codex.is_symlink():
        for path in sorted(codex.glob("*.sqlite*")):
            if path.is_file():
                add(path, "database", "Codex database or journal", [])

    try:
        current, versions = release_layout(home)
    except (OSError, RuntimeError, ValueError):
        return candidates
    for version in versions:
        if (
            version.is_dir()
            and not version.is_symlink()
            and version.resolve() != current
        ):
            add(
                version,
                "installation",
                f"Non-current Codex daemon release {version.name}",
                [
                    f"current release resolves to {current}",
                    "non-current does not prove no process is using this release",
                ],
            )
    return candidates

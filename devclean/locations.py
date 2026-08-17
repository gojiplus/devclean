"""Canonical filesystem locations used by scanning and safety checks."""

from __future__ import annotations

from pathlib import Path
from tempfile import gettempdir


def temporary_roots() -> list[Path]:
    """Return distinct macOS temporary roots in canonical form.

    ``/tmp`` resolves to ``/private/tmp`` on macOS.  Python's selected temp
    directory also captures the per-user directory normally supplied through
    ``TMPDIR`` under ``/var/folders``.
    """
    candidates = (
        Path("/private/tmp"),
        Path("/private/var/tmp"),
        Path(gettempdir()),
    )
    roots: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)
    return roots

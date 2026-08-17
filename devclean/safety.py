"""The single guard on deletion.

This logic previously existed in three independent copies that had drifted
apart: two in the agent tool layer and one in ``validation``. Only the
``validation`` copy honoured the user's configured ``protected_paths``, and the
agent path never consulted it. There is now one implementation and every caller
goes through it.
"""

from __future__ import annotations

from pathlib import Path

from .exceptions import PathNotFoundError, UnsafePathError
from .locations import temporary_roots

SYSTEM_ROOTS: tuple[str, ...] = (
    "/",
    "/System",
    "/Applications",
    "/Library",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/etc",
    "/var",
    "/opt",
    "/private",
)

HOME_SUBDIRS: tuple[str, ...] = (
    "Documents",
    "Desktop",
    "Downloads",
    "Pictures",
    "Music",
    "Movies",
    "Library",
    "Applications",
)
"""Directories directly under home that must never be deleted wholesale.

Only the directories themselves are protected, not their contents. Developer
cruft lives several levels inside ``~/Documents``; refusing anything with
``Documents`` among its path components would rule out every project
virtualenv on the machine.
"""

MIN_DEPTH_BELOW_HOME = 2
"""How deep under home a path must sit before bulk deletion will touch it.

``~/.cache/uv`` is depth 2 and fine. ``~/.cache`` is depth 1 and holds many
tools' data at once, so it needs an explicit per-path decision.
"""


def protected_paths(extra: list[str] | None = None) -> list[Path]:
    """Build the full protected set: system roots, home, its top-level dirs, plus extras."""
    home = Path.home().resolve()
    paths: list[Path] = [Path(root).resolve() for root in SYSTEM_ROOTS]
    paths.append(home)
    paths.extend(home / name for name in HOME_SUBDIRS)
    paths.extend(temporary_roots())

    for candidate in extra or []:
        try:
            paths.append(Path(candidate).expanduser().resolve())
        except (OSError, RuntimeError, ValueError):
            continue

    return paths


def assert_safe_to_delete(
    path: Path,
    extra_protected: list[str] | None = None,
    require_depth: bool = True,
) -> None:
    """Raise unless ``path`` is safe to delete.

    Args:
        path: Directory to check. Should already be resolved.
        extra_protected: Additional protected paths from user configuration.
        require_depth: Enforce :data:`MIN_DEPTH_BELOW_HOME`. Relaxed for
            explicit single-path deletions, where the user named the target.

    Raises:
        PathNotFoundError: If the path does not exist.
        UnsafePathError: If deleting it would be unsafe.

    """
    if not path.exists():
        raise PathNotFoundError(f"Path does not exist: {path}")

    resolved = path.resolve()
    home = Path.home().resolve()

    # Named protections first, so a path on the list reports why it is on the
    # list rather than the more general ancestor rule below.
    for protected in protected_paths(extra_protected):
        if resolved == protected:
            raise UnsafePathError(f"Cannot delete protected path: {resolved}")

    try:
        if resolved.is_mount():
            raise UnsafePathError(f"Cannot delete a mounted filesystem: {resolved}")
    except OSError as exc:
        raise UnsafePathError(f"Cannot verify whether path is a mount point: {resolved}") from exc

    # An ancestor of home takes the whole account with it. Never bypassable.
    if home.is_relative_to(resolved):
        raise UnsafePathError(f"Refusing to delete a parent of your home directory: {resolved}")

    # Anything directly inside a system root is OS or application territory.
    for root in SYSTEM_ROOTS:
        root_path = Path(root).resolve()
        if root_path == Path("/"):
            continue
        if resolved.parent == root_path:
            raise UnsafePathError(f"Cannot delete a top-level entry of {root}: {resolved}")

    if resolved.is_relative_to(home):
        depth = len(resolved.relative_to(home).parts)
        if require_depth and depth < MIN_DEPTH_BELOW_HOME:
            raise UnsafePathError(
                f"{resolved} sits directly under your home directory; "
                "delete it explicitly by path if you mean it"
            )
    elif not any(resolved.is_relative_to(root) for root in temporary_roots()):
        raise UnsafePathError(
            f"Path is outside your home directory and recognized temporary roots: {resolved}"
        )


def is_safe_to_delete(
    path: Path,
    extra_protected: list[str] | None = None,
    require_depth: bool = True,
) -> bool:
    """Boolean form of :func:`assert_safe_to_delete`."""
    try:
        assert_safe_to_delete(path, extra_protected, require_depth)
    except (UnsafePathError, PathNotFoundError):
        return False
    return True

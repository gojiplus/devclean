"""Scan the filesystem for developer cruft.

Every result is a :class:`~devclean.candidates.Candidate` carrying the evidence
for its tier, so a caller can distinguish a cache the owning tool declares
disposable from a directory that merely has a suggestive name.
"""

from __future__ import annotations

import os
import subprocess
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .candidates import Candidate, Tier
from .config import (
    CRUFT_PATTERNS,
    PROJECT_CRUFT_NAMES,
    PROJECT_PROBE_NAMES,
    VENV_NAMES,
    VENV_SEARCH_DIRS,
    CruftPattern,
)
from .exceptions import ScanError, ScanTimeoutError
from .locations import temporary_roots
from .probes import probe_dist_dir, probe_node_modules, probe_venv, recovery_evidence
from .system_artifacts import find_system_artifacts


@dataclass
class ScanResult:
    """Results from a disk scan.

    One flat list. Grouping is a view over it, so adding a category needs no
    change here, in the CLI, or in any formatter.
    """

    candidates: list[Candidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def by_category(self) -> dict[str, list[Candidate]]:
        grouped: dict[str, list[Candidate]] = defaultdict(list)
        for candidate in self.candidates:
            grouped[candidate.category].append(candidate)
        return dict(grouped)

    def by_tier(self, tier: Tier) -> list[Candidate]:
        return [c for c in self.candidates if c.tier is tier]

    @property
    def bulk_deletable(self) -> list[Candidate]:
        """Candidates safe to delete without per-path approval."""
        return [c for c in self.candidates if c.bulk_deletable]

    @property
    def needs_review(self) -> list[Candidate]:
        """Candidates a probe objected to, or that were never content-checked."""
        return [c for c in self.candidates if not c.bulk_deletable]

    @property
    def total_bytes(self) -> int:
        """Bytes represented by candidates, without counting nested paths twice."""
        relative_total = sum(c.size_bytes for c in self.candidates if not c.path.is_absolute())
        sizes_by_path: dict[Path, int] = {}
        for candidate in self.candidates:
            if candidate.path.is_absolute():
                sizes_by_path[candidate.path] = max(
                    candidate.size_bytes,
                    sizes_by_path.get(candidate.path, 0),
                )

        roots: list[Path] = []
        absolute_total = 0
        for path, size in sorted(
            sizes_by_path.items(),
            key=lambda item: (len(item[0].parts), str(item[0])),
        ):
            if any(path.is_relative_to(root) for root in roots):
                continue
            roots.append(path)
            absolute_total += size

        return absolute_total + relative_total

    @property
    def total_gb(self) -> float:
        return self.total_bytes / (1024**3)

    @property
    def reclaimable_bytes(self) -> int:
        """Bytes in the bulk-deletable set only."""
        return sum(c.size_bytes for c in self.bulk_deletable)

    def sort(self) -> None:
        self.candidates.sort(key=lambda c: c.size_bytes, reverse=True)


@dataclass
class ProjectInventory:
    """One filesystem walk shared by every project-level scanner."""

    by_name: dict[str, list[Path]] = field(default_factory=lambda: defaultdict(list))
    virtualenvs: list[Path] = field(default_factory=list)

    def paths_named(self, name: str) -> list[Path]:
        """Return paths with an exact directory name."""
        return self.by_name.get(name, [])

    def extend_dependencies(self, other: ProjectInventory) -> None:
        """Merge dependency trees without importing other project artifacts."""
        seen_venvs = set(self.virtualenvs)
        for path in other.virtualenvs:
            if path not in seen_venvs:
                seen_venvs.add(path)
                self.virtualenvs.append(path)

        node_modules = self.by_name["node_modules"]
        seen_node_modules = set(node_modules)
        for path in other.paths_named("node_modules"):
            if path not in seen_node_modules:
                seen_node_modules.add(path)
                node_modules.append(path)


def get_dir_size(path: Path, timeout: int = 30, use_cache: bool = True) -> int | None:
    """Get directory size in bytes using du.

    Args:
        path: Path to directory to measure
        timeout: Timeout in seconds for the du command
        use_cache: Whether to use cached results

    Returns:
        Size in bytes, or None if measurement failed

    Raises:
        ScanTimeoutError: If the du command times out
        ScanError: If the du command cannot be run

    """
    from .cache import get_cache

    cache = get_cache() if use_cache else None

    if cache is not None:
        cached_entry = cache.get(path)
        if cached_entry is not None:
            if cached_entry.error:
                return None
            return cached_entry.size_bytes if cached_entry.exists else None

    try:
        if not path.exists():
            if cache is not None:
                cache.set(path, 0, False)
            return None

        result = subprocess.run(
            ["du", "-sk", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            # du -sk returns kilobytes
            size_bytes = int(result.stdout.split()[0]) * 1024
            if cache is not None:
                cache.set(path, size_bytes, True)
            return size_bytes

    except subprocess.TimeoutExpired as e:
        if cache is not None:
            cache.set(path, 0, True, f"Timeout: {e}")
        raise ScanTimeoutError(f"Timeout measuring directory size: {path}") from e
    except (ValueError, IndexError) as e:
        if cache is not None:
            cache.set(path, 0, True, f"Parse error: {e}")
        raise ScanError(f"Failed to parse directory size for {path}: {e}") from e
    except OSError as e:
        if cache is not None:
            cache.set(path, 0, True, str(e))
        raise ScanError(f"Error measuring directory size for {path}: {e}") from e
    return None


def check_command_exists(command: str) -> bool:
    """Check if a command/tool is installed."""
    try:
        # Extract just the binary name from "binary --version" style commands
        binary = command.split()[0]
        result = subprocess.run(
            ["which", binary],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _find_named_dirs(
    search_dir: Path,
    names: Iterable[str],
    maxdepth: int,
    timeout: int,
) -> list[Path]:
    """Find all requested names in one bounded filesystem walk."""
    requested = tuple(dict.fromkeys(names))
    if not requested:
        return []
    name_expression: list[str] = ["("]
    for index, name in enumerate(requested):
        if index:
            name_expression.append("-o")
        name_expression.extend(("-name", name))
    name_expression.append(")")
    command = [
        "find",
        str(search_dir),
        "-maxdepth",
        str(maxdepth),
        "(",
        "-name",
        ".git",
        "-o",
        "-name",
        ".hg",
        "-o",
        "-name",
        ".svn",
        ")",
        "-prune",
        "-o",
        "-type",
        "d",
        *name_expression,
        "-print",
        "-prune",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [Path(line) for line in result.stdout.splitlines() if line]


def _search_roots(
    home: Path,
    additional_search_paths: Iterable[str | Path] = (),
    *,
    include_defaults: bool = True,
) -> list[Path]:
    """Return existing, non-overlapping project search roots."""
    requested: list[Path] = []
    defaults: Iterable[str | Path] = VENV_SEARCH_DIRS if include_defaults else ()
    for raw in (*defaults, *additional_search_paths):
        rendered = str(raw).format(home=home)
        if rendered == "~":
            root = home
        elif rendered.startswith("~/"):
            root = home / rendered[2:]
        else:
            root = Path(rendered).expanduser()
        if not root.is_absolute():
            root = home / root
        try:
            root = root.resolve()
        except OSError:
            continue
        if root.is_dir():
            requested.append(root)

    roots: list[Path] = []
    for root in sorted(set(requested), key=lambda path: (len(path.parts), str(path))):
        if any(root == parent or root.is_relative_to(parent) for parent in roots):
            continue
        roots.append(root)
    return roots


def build_project_inventory(
    home: Path,
    additional_search_paths: Iterable[str | Path] = (),
    maxdepth: int = 8,
    timeout: int = 120,
    *,
    include_default_roots: bool = True,
    include_project_artifacts: bool = True,
) -> ProjectInventory:
    """Walk every project root once and index all relevant directory names."""
    names: tuple[str, ...] = (*VENV_NAMES, "node_modules")
    if include_project_artifacts:
        names = (*names, *PROJECT_CRUFT_NAMES, *PROJECT_PROBE_NAMES)
    names = tuple(dict.fromkeys(names))
    inventory = ProjectInventory()
    seen: set[Path] = set()

    for root in _search_roots(
        home,
        additional_search_paths,
        include_defaults=include_default_roots,
    ):
        for path in _find_named_dirs(root, names, maxdepth=maxdepth, timeout=timeout):
            if path in seen:
                continue
            seen.add(path)
            inventory.by_name[path.name].append(path)

    for name in VENV_NAMES:
        for path in inventory.paths_named(name):
            if not probe_venv(path):
                inventory.virtualenvs.append(path)

    if include_default_roots:
        try:
            home_children = sorted(home.iterdir())
        except OSError:
            home_children = []
        for path in home_children:
            try:
                if path.is_dir() and (path / "pyvenv.cfg").is_file() and path not in seen:
                    seen.add(path)
                    inventory.virtualenvs.append(path)
                elif path.name == "node_modules" and path.is_dir() and path not in seen:
                    seen.add(path)
                    inventory.by_name["node_modules"].append(path)
            except OSError:
                continue

    return inventory


def scan_known_cruft(home: Path, min_size_mb: int = 100) -> list[Candidate]:
    """Scan known per-user cache locations.

    A pattern's own ``min_size_mb`` overrides the global floor in both
    directions, so a small-but-worthwhile cache still surfaces when the global
    floor is high.
    """
    candidates: list[Candidate] = []

    for pattern in CRUFT_PATTERNS:
        try:
            candidate = _scan_pattern(pattern, home, min_size_mb)
        except (ScanError, ScanTimeoutError):
            continue
        if candidate is not None:
            candidates.append(candidate)

    return candidates


def _scan_pattern(pattern: CruftPattern, home: Path, min_size_mb: int) -> Candidate | None:
    path = Path(pattern.path_template.format(home=home))
    if not path.exists():
        return None

    size = get_dir_size(path)
    if size is None:
        return None

    floor = pattern.min_size_mb if pattern.min_size_mb is not None else min_size_mb
    if size < floor * 1024 * 1024:
        return None

    tool_installed = None
    if pattern.check_installed:
        tool_installed = check_command_exists(pattern.check_installed)

    evidence = []
    if pattern.purge_command:
        evidence.append(f"tool provides `{pattern.purge_command}`")
    if tool_installed is False:
        evidence.append("owning tool is not installed — orphaned data")

    # A documented purge command is the tool declaring its own cache
    # disposable. Without one, deletion is still probably fine but nothing
    # authoritative says so.
    tier = Tier.AUTO if pattern.purge_command else Tier.PROBE
    if not pattern.safe:
        tier = Tier.INSPECT

    candidate = Candidate(
        path=path,
        size_bytes=size,
        category=pattern.category,
        description=pattern.description,
        tier=tier,
        recovery=pattern.recovery,
        evidence=evidence,
    )
    if not pattern.safe:
        candidate.concerns.append("marked unsafe: may hold state you cannot regenerate")
    return candidate


def find_venvs(
    home: Path,
    min_size_mb: int = 50,
    *,
    inventory: ProjectInventory | None = None,
    additional_search_paths: Iterable[str | Path] = (),
    maxdepth: int = 8,
    timeout: int = 120,
) -> list[Candidate]:
    """Find Python virtual environments in project directories.

    Verified by ``pyvenv.cfg``. Without that marker a package such as
    ``node_modules/@next/env`` matches the name pattern and would be deleted.
    """
    candidates: list[Candidate] = []
    source = inventory or build_project_inventory(
        home,
        additional_search_paths,
        maxdepth=maxdepth,
        timeout=timeout,
    )

    for venv_path in source.virtualenvs:
        try:
            size = get_dir_size(venv_path, timeout=10)
        except (ScanError, ScanTimeoutError):
            continue
        if size is None or size < min_size_mb * 1024 * 1024:
            continue

        project = venv_path.parent
        evidence, extra_concerns = recovery_evidence(venv_path, project)
        evidence.insert(0, "pyvenv.cfg present")

        candidate = Candidate(
            path=venv_path,
            size_bytes=size,
            category="python",
            description=f"virtualenv in {project.name}",
            tier=Tier.VERIFIED,
            recovery="uv sync (or pip install -r requirements.txt)",
            evidence=evidence,
        )
        manifest_missing = [c for c in extra_concerns if "no manifest" in c]
        candidate.downgrade(*manifest_missing)
        candidates.append(candidate)

    return candidates


def find_node_modules(
    home: Path,
    min_size_mb: int = 50,
    *,
    inventory: ProjectInventory | None = None,
    additional_search_paths: Iterable[str | Path] = (),
    maxdepth: int = 8,
    timeout: int = 120,
) -> list[Candidate]:
    """Find node_modules directories that a package.json can restore."""
    candidates: list[Candidate] = []
    source = inventory or build_project_inventory(
        home,
        additional_search_paths,
        maxdepth=maxdepth,
        timeout=timeout,
    )

    for nm_path in source.paths_named("node_modules"):
        if "node_modules/node_modules" in str(nm_path):
            continue
        try:
            size = get_dir_size(nm_path, timeout=10)
        except (ScanError, ScanTimeoutError):
            continue
        if size is None or size < min_size_mb * 1024 * 1024:
            continue

        candidate = Candidate(
            path=nm_path,
            size_bytes=size,
            category="node",
            description=f"node_modules in {nm_path.parent.name}",
            tier=Tier.VERIFIED,
            recovery="npm install",
            evidence=["package.json present in parent"],
        )
        candidate.downgrade(*probe_node_modules(nm_path))
        candidates.append(candidate)

    return candidates


def find_project_cruft(
    home: Path,
    min_size_mb: int = 0,
    *,
    inventory: ProjectInventory | None = None,
    additional_search_paths: Iterable[str | Path] = (),
    maxdepth: int = 8,
    timeout: int = 120,
) -> list[Candidate]:
    """Roll up project-local caches that are numerous rather than large.

    Thousands of ``__pycache__`` directories are individually trivial and
    collectively gigabytes. Reporting them per-directory would bury everything
    else, so each category becomes one candidate covering every member.
    """
    candidates: list[Candidate] = []
    source = inventory or build_project_inventory(
        home,
        additional_search_paths,
        maxdepth=maxdepth,
        timeout=timeout,
    )

    for name, (category, recovery) in PROJECT_CRUFT_NAMES.items():
        members = source.paths_named(name)
        sizes = _get_dir_sizes_batched(members, timeout=timeout)
        members = [path for path in members if path in sizes]
        total = sum(sizes.values())

        if not members or total < min_size_mb * 1024 * 1024:
            continue

        candidates.append(
            Candidate(
                path=Path(name),
                size_bytes=total,
                category=category,
                description=f"{len(members)} {name} directories across your projects",
                tier=Tier.VERIFIED,
                recovery=recovery,
                evidence=[f"{len(members)} directories, all regenerated by tooling"],
                member_count=len(members),
            )
        )

    return candidates


def find_probed_project_dirs(
    home: Path,
    min_size_mb: int = 50,
    *,
    inventory: ProjectInventory | None = None,
    additional_search_paths: Iterable[str | Path] = (),
    maxdepth: int = 8,
    timeout: int = 120,
) -> list[Candidate]:
    """Find build output directories, and read them before proposing anything.

    ``dist/`` next to a ``pyproject.toml`` is the canonical false positive: the
    structure says build artifact, and the contents sometimes say irreplaceable
    data. Only :func:`~devclean.probes.probe_dist_dir` can tell them apart.
    """
    candidates: list[Candidate] = []
    source = inventory or build_project_inventory(
        home,
        additional_search_paths,
        maxdepth=maxdepth,
        timeout=timeout,
    )

    for name, (category, recovery) in PROJECT_PROBE_NAMES.items():
        for path in source.paths_named(name):
            project = path.parent
            if not any((project / m).is_file() for m in ("pyproject.toml", "setup.py")):
                continue

            try:
                size = get_dir_size(path, timeout=10)
            except (ScanError, ScanTimeoutError):
                continue
            if size is None or size < min_size_mb * 1024 * 1024:
                continue

            evidence, extra_concerns = recovery_evidence(path, project)
            candidate = Candidate(
                path=path,
                size_bytes=size,
                category=category,
                description=f"{name}/ in {project.name}",
                tier=Tier.PROBE,
                recovery=recovery,
                evidence=evidence,
            )
            candidate.downgrade(*probe_dist_dir(path))
            candidate.downgrade(*extra_concerns)
            candidates.append(candidate)

    return candidates


def _get_dir_sizes(paths: list[Path], timeout: int = 60) -> dict[Path, int]:
    """Measure several directories in one bounded ``du`` invocation."""
    if not paths:
        return {}
    try:
        result = subprocess.run(
            ["du", "-sk", *(str(path) for path in paths)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    sizes: dict[Path, int] = {}
    for line in result.stdout.splitlines():
        try:
            size_kb, raw_path = line.split(maxsplit=1)
            sizes[Path(raw_path)] = int(size_kb) * 1024
        except (ValueError, IndexError):
            continue
    return sizes


def _get_dir_sizes_batched(
    paths: list[Path], timeout: int = 60, batch_size: int = 128
) -> dict[Path, int]:
    """Measure many paths without exceeding the operating system's argv limit."""
    sizes: dict[Path, int] = {}
    for offset in range(0, len(paths), batch_size):
        sizes.update(_get_dir_sizes(paths[offset : offset + batch_size], timeout))
    return sizes


def find_temporary_dirs(
    min_size_mb: int = 100,
    roots: list[Path] | None = None,
    owner_uid: int | None = None,
) -> list[Candidate]:
    """Find large, user-owned directories directly inside temporary roots.

    A temporary location is useful evidence for where disk space went, but it
    does not prove that the contents are unused or reproducible.  These
    candidates therefore always require an explicit per-path decision.
    """
    candidates: list[Candidate] = []
    uid = os.getuid() if owner_uid is None else owner_uid
    floor = min_size_mb * 1024 * 1024

    for root in roots if roots is not None else temporary_roots():
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue

        owned_dirs: list[Path] = []
        for path in children:
            try:
                if (
                    path.is_symlink()
                    or not path.is_dir()
                    or path.is_mount()
                    or path.stat().st_uid != uid
                ):
                    continue
            except OSError:
                continue
            owned_dirs.append(path)

        sizes = _get_dir_sizes(owned_dirs)
        for path in owned_dirs:
            size = sizes.get(path)
            if size is None or size < floor:
                continue

            candidates.append(
                Candidate(
                    path=path,
                    size_bytes=size,
                    category="temporary",
                    description=f"user-owned directory in {root}",
                    tier=Tier.INSPECT,
                    recovery="No automatic recovery; inspect before deleting",
                    evidence=[
                        f"direct child of temporary root {root}",
                        "owned by the current user",
                    ],
                    concerns=[
                        "temporary location alone does not prove it is unused or reproducible; "
                        "confirm no process needs it and it is not the only copy"
                    ],
                )
            )

    return candidates


def scan_all(
    home: Path | None = None,
    include_venvs: bool = True,
    include_node_modules: bool = True,
    include_project_cruft: bool = True,
    include_system_artifacts: bool = True,
    include_temporary_dirs: bool = True,
    min_size_mb: int = 100,
    additional_search_paths: Iterable[str | Path] = (),
    project_max_depth: int = 8,
    project_scan_timeout: int = 120,
) -> ScanResult:
    """Run a full scan for all cruft types.

    Args:
        home: User's home directory (uses Path.home() if None)
        include_venvs: Whether to scan for Python virtual environments
        include_node_modules: Whether to scan for node_modules directories
        include_project_cruft: Whether to scan project-local caches and build output
        include_system_artifacts: Whether to inspect stale macOS toolchains
        include_temporary_dirs: Whether to scan macOS temporary roots
        min_size_mb: Global size floor, overridable per pattern
        additional_search_paths: User-configured project roots
        project_max_depth: Maximum depth for the shared project walk
        project_scan_timeout: Timeout in seconds for each project-root walk

    Returns:
        ScanResult containing all found candidates

    """
    from .cache import save_cache

    if home is None:
        home = Path.home()

    result = ScanResult()

    inventory: ProjectInventory | None = None
    if include_venvs or include_node_modules or include_project_cruft:
        try:
            inventory = build_project_inventory(
                home,
                additional_search_paths,
                maxdepth=project_max_depth,
                timeout=project_scan_timeout,
            )
        except Exception as exc:  # noqa: BLE001 - preserve the non-project scans
            result.errors.append(f"Error scanning project roots: {exc}")
            inventory = ProjectInventory()

        if include_temporary_dirs and (include_venvs or include_node_modules):
            try:
                temporary_inventory = build_project_inventory(
                    home,
                    temporary_roots(),
                    maxdepth=project_max_depth,
                    timeout=project_scan_timeout,
                    include_default_roots=False,
                    include_project_artifacts=False,
                )
                inventory.extend_dependencies(temporary_inventory)
            except Exception as exc:  # noqa: BLE001 - preserve every other scan stage
                result.errors.append(f"Error scanning temporary dependencies: {exc}")

    stages: list[tuple[str, Callable[[], list[Candidate]]]] = [
        ("known cruft", lambda: scan_known_cruft(home, min_size_mb))
    ]
    if include_venvs:
        stages.append(
            (
                "virtual environments",
                lambda: find_venvs(home, inventory=inventory),
            )
        )
    if include_node_modules:
        stages.append(
            (
                "node_modules",
                lambda: find_node_modules(home, inventory=inventory),
            )
        )
    if include_project_cruft:
        stages.append(
            (
                "project caches",
                lambda: find_project_cruft(home, inventory=inventory),
            )
        )
        stages.append(
            (
                "build output",
                lambda: find_probed_project_dirs(home, inventory=inventory),
            )
        )
    if include_system_artifacts:
        stages.append(
            (
                "system toolchains",
                lambda: find_system_artifacts(get_dir_size, min_size_mb),
            )
        )
    if include_temporary_dirs:
        stages.append(("temporary directories", lambda: find_temporary_dirs(min_size_mb)))

    try:
        for label, stage in stages:
            try:
                result.candidates.extend(stage())
            except Exception as e:  # noqa: BLE001 - one bad stage must not sink the scan
                result.errors.append(f"Error scanning {label}: {e}")
        result.sort()
    finally:
        try:
            save_cache()
        except OSError:
            pass

    return result

"""Scan the filesystem for developer cruft.

Every result is a :class:`~devclean.candidates.Candidate` carrying the evidence
for its tier, so a caller can distinguish a cache the owning tool declares
disposable from a directory that merely has a suggestive name.
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
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
from .probes import probe_dist_dir, probe_node_modules, probe_venv, recovery_evidence


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
        return sum(c.size_bytes for c in self.candidates)

    @property
    def total_gb(self) -> float:
        return self.total_bytes / (1024**3)

    @property
    def reclaimable_bytes(self) -> int:
        """Bytes in the bulk-deletable set only."""
        return sum(c.size_bytes for c in self.bulk_deletable)

    def sort(self) -> None:
        self.candidates.sort(key=lambda c: c.size_bytes, reverse=True)


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


def _find_dirs(search_dir: Path, name: str, maxdepth: int, timeout: int) -> list[Path]:
    """Shell out to find(1) for speed, returning matching directory paths."""
    try:
        result = subprocess.run(
            ["find", str(search_dir), "-type", "d", "-name", name, "-maxdepth", str(maxdepth)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [Path(line) for line in result.stdout.splitlines() if line]


def _search_roots(home: Path) -> list[Path]:
    roots = []
    for template in VENV_SEARCH_DIRS:
        root = Path(template.format(home=home))
        if root.exists():
            roots.append(root)
    return roots


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


def find_venvs(home: Path, min_size_mb: int = 50) -> list[Candidate]:
    """Find Python virtual environments in project directories.

    Verified by ``pyvenv.cfg``. Without that marker a package such as
    ``node_modules/@next/env`` matches the name pattern and would be deleted.
    """
    candidates: list[Candidate] = []
    seen: set[Path] = set()

    for root in _search_roots(home):
        for venv_name in VENV_NAMES:
            for venv_path in _find_dirs(root, venv_name, maxdepth=4, timeout=30):
                if venv_path in seen:
                    continue
                seen.add(venv_path)

                concerns = probe_venv(venv_path)
                if concerns:
                    # Not a virtualenv at all — not our business.
                    continue

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
                # A venv with no manifest cannot be rebuilt; that is worth a
                # human look even though the directory is genuinely a venv.
                manifest_missing = [c for c in extra_concerns if "no manifest" in c]
                candidate.downgrade(*manifest_missing)
                candidates.append(candidate)

    return candidates


def find_node_modules(home: Path, min_size_mb: int = 200) -> list[Candidate]:
    """Find node_modules directories that a package.json can restore."""
    candidates: list[Candidate] = []
    seen: set[Path] = set()

    for root in _search_roots(home):
        for nm_path in _find_dirs(root, "node_modules", maxdepth=5, timeout=60):
            if "node_modules/node_modules" in str(nm_path) or nm_path in seen:
                continue
            seen.add(nm_path)

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


def find_project_cruft(home: Path, min_size_mb: int = 0) -> list[Candidate]:
    """Roll up project-local caches that are numerous rather than large.

    Thousands of ``__pycache__`` directories are individually trivial and
    collectively gigabytes. Reporting them per-directory would bury everything
    else, so each category becomes one candidate covering every member.
    """
    candidates: list[Candidate] = []
    roots = _search_roots(home)

    for name, (category, recovery) in PROJECT_CRUFT_NAMES.items():
        members: list[Path] = []
        total = 0
        for root in roots:
            for path in _find_dirs(root, name, maxdepth=8, timeout=120):
                try:
                    size = get_dir_size(path, timeout=10, use_cache=False)
                except (ScanError, ScanTimeoutError):
                    continue
                if size is None:
                    continue
                members.append(path)
                total += size

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


def find_probed_project_dirs(home: Path, min_size_mb: int = 50) -> list[Candidate]:
    """Find build output directories, and read them before proposing anything.

    ``dist/`` next to a ``pyproject.toml`` is the canonical false positive: the
    structure says build artifact, and the contents sometimes say irreplaceable
    data. Only :func:`~devclean.probes.probe_dist_dir` can tell them apart.
    """
    candidates: list[Candidate] = []
    seen: set[Path] = set()

    for name, (category, recovery) in PROJECT_PROBE_NAMES.items():
        for root in _search_roots(home):
            for path in _find_dirs(root, name, maxdepth=3, timeout=60):
                if path in seen:
                    continue
                seen.add(path)

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


def scan_all(
    home: Path | None = None,
    include_venvs: bool = True,
    include_node_modules: bool = True,
    include_project_cruft: bool = True,
    min_size_mb: int = 100,
) -> ScanResult:
    """Run a full scan for all cruft types.

    Args:
        home: User's home directory (uses Path.home() if None)
        include_venvs: Whether to scan for Python virtual environments
        include_node_modules: Whether to scan for node_modules directories
        include_project_cruft: Whether to scan project-local caches and build output
        min_size_mb: Global size floor, overridable per pattern

    Returns:
        ScanResult containing all found candidates

    """
    from .cache import save_cache

    if home is None:
        home = Path.home()

    result = ScanResult()

    stages: list[tuple[str, object]] = [
        ("known cruft", lambda: scan_known_cruft(home, min_size_mb))
    ]
    if include_venvs:
        stages.append(("virtual environments", lambda: find_venvs(home)))
    if include_node_modules:
        stages.append(("node_modules", lambda: find_node_modules(home)))
    if include_project_cruft:
        stages.append(("project caches", lambda: find_project_cruft(home)))
        stages.append(("build output", lambda: find_probed_project_dirs(home)))

    try:
        for label, stage in stages:
            try:
                result.candidates.extend(stage())  # type: ignore[operator]
            except Exception as e:  # noqa: BLE001 - one bad stage must not sink the scan
                result.errors.append(f"Error scanning {label}: {e}")
        result.sort()
    finally:
        try:
            save_cache()
        except OSError:
            pass

    return result

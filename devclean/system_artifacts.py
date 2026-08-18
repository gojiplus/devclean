"""Detect stale macOS toolchains and package-manager artifacts.

These candidates are intentionally inspect-only.  A version that is not the
current default may still exist for reproducibility, and a package-manager
prefix can contain files installed outside that manager's database.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .candidates import Candidate, Tier
from .locations import temporary_roots

SizeGetter = Callable[[Path], int | None]

_TEX_VERSION = re.compile(r"^[0-9]{4}(basic)?$")
_PYTHON_LIBRARY = re.compile(r"^python(?P<version>[0-9]+\.[0-9]+)$")


@dataclass(frozen=True)
class SystemPaths:
    """Filesystem roots used by the macOS artifact probes."""

    usr_local: Path = Path("/usr/local")
    library: Path = Path("/Library")
    opt: Path = Path("/opt")
    home: Path = field(default_factory=Path.home)
    temp_roots: tuple[Path, ...] = ()

    @classmethod
    def macos(cls) -> SystemPaths:
        """Return the real macOS locations for the current user."""
        return cls(temp_roots=tuple(temporary_roots()))


def _candidate(
    path: Path,
    get_size: SizeGetter,
    min_size_mb: int,
    *,
    category: str,
    description: str,
    recovery: str,
    evidence: list[str],
    concerns: list[str],
) -> Candidate | None:
    try:
        size = get_size(path)
    except Exception:
        return None
    if size is None or size < min_size_mb * 1024 * 1024:
        return None
    return Candidate(
        path=path,
        size_bytes=size,
        category=category,
        description=description,
        tier=Tier.INSPECT,
        recovery=recovery,
        evidence=evidence,
        concerns=concerns,
    )


def _resolved(path: Path) -> Path | None:
    try:
        return path.resolve(strict=True)
    except OSError:
        return None


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _version_directories(parent: Path) -> list[Path]:
    try:
        return sorted(
            path
            for path in parent.iterdir()
            if path.name != "Current" and not path.is_symlink() and path.is_dir()
        )
    except OSError:
        return []


def _find_old_tex(
    paths: SystemPaths, get_size: SizeGetter, min_size_mb: int
) -> list[Candidate]:
    tex_root = paths.usr_local / "texlive"
    active_link = paths.library / "TeX/Distributions/.DefaultTeX/Contents/Root"
    active = _resolved(active_link)
    candidates: list[Candidate] = []
    for version in _version_directories(tex_root):
        if not _TEX_VERSION.fullmatch(version.name):
            continue
        resolved = _resolved(version) or version
        if active is not None and _is_within(active, resolved):
            continue
        evidence = [f"default TeX distribution resolves to {active}"] if active else []
        candidate = _candidate(
            version,
            get_size,
            min_size_mb,
            category="tex",
            description=f"non-default TeX Live distribution {version.name}",
            recovery="Reinstall this release from the MacTeX archive",
            evidence=evidence,
            concerns=[
                "an older TeX release may be retained intentionally for reproducibility"
            ],
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def _find_old_r(
    paths: SystemPaths, get_size: SizeGetter, min_size_mb: int
) -> list[Candidate]:
    versions = paths.library / "Frameworks/R.framework/Versions"
    active = _resolved(versions / "Current")
    candidates: list[Candidate] = []
    for version in _version_directories(versions):
        resolved = _resolved(version) or version
        if active is not None and resolved == active:
            continue
        evidence = (
            [f"R.framework/Versions/Current resolves to {active}"] if active else []
        )
        candidate = _candidate(
            version,
            get_size,
            min_size_mb,
            category="r",
            description=f"non-current R framework {version.name}",
            recovery="Reinstall the matching CRAN macOS package",
            evidence=evidence,
            concerns=[
                "an older R release may be retained intentionally for reproducibility"
            ],
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def _find_inactive_python_frameworks(
    paths: SystemPaths, get_size: SizeGetter, min_size_mb: int
) -> list[Candidate]:
    versions = paths.library / "Frameworks/Python.framework/Versions"
    executable = shutil.which("python3")
    active_python = _resolved(Path(executable)) if executable else None
    candidates: list[Candidate] = []
    for version in _version_directories(versions):
        resolved = _resolved(version) or version
        if active_python is not None and _is_within(active_python, resolved):
            continue
        evidence = [f"python3 resolves to {active_python}"] if active_python else []
        candidate = _candidate(
            version,
            get_size,
            min_size_mb,
            category="python",
            description=f"inactive python.org framework {version.name}",
            recovery="Reinstall the matching python.org macOS package",
            evidence=evidence,
            concerns=[
                "scripts outside the shell PATH may still reference this framework"
            ],
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def _find_global_python_packages(
    paths: SystemPaths, get_size: SizeGetter, min_size_mb: int
) -> list[Candidate]:
    lib = paths.opt / "homebrew/lib"
    candidates: list[Candidate] = []
    try:
        package_dirs = sorted(lib.glob("python*/site-packages"))
    except OSError:
        return []

    for site_packages in package_dirs:
        match = _PYTHON_LIBRARY.fullmatch(site_packages.parent.name)
        if not match or not site_packages.is_dir():
            continue
        version = match.group("version")
        runtime = paths.opt / f"homebrew/Cellar/python@{version}"
        runtime_exists = runtime.is_dir()
        evidence = [
            f"matching Homebrew Python runtime {'exists' if runtime_exists else 'is absent'}: {runtime}"
        ]
        concern = (
            "globally installed packages are live for this Homebrew Python"
            if runtime_exists
            else "no package manifest records how to recreate these globally installed packages"
        )
        candidate = _candidate(
            site_packages,
            get_size,
            min_size_mb,
            category="python",
            description=f"global Homebrew Python {version} packages",
            recovery="Reinstall needed packages into a project environment",
            evidence=evidence,
            concerns=[concern],
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def _find_retained_mactex_installers(
    paths: SystemPaths, get_size: SizeGetter, min_size_mb: int
) -> list[Candidate]:
    cask = paths.opt / "homebrew/Caskroom/mactex"
    candidates: list[Candidate] = []
    try:
        installers = sorted(cask.glob("*/*.pkg"))
    except OSError:
        return []
    for installer in installers:
        candidate = _candidate(
            installer,
            get_size,
            min_size_mb,
            category="tex",
            description="retained MacTeX installer package",
            recovery="Re-download the MacTeX cask installer",
            evidence=[
                "package installer remains in Homebrew's Caskroom after installation"
            ],
            concerns=[
                "removing a current cask artifact may affect a later Homebrew uninstall"
            ],
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def _find_broken_macports(
    paths: SystemPaths, get_size: SizeGetter, min_size_mb: int
) -> list[Candidate]:
    prefix = paths.opt / "local"
    if not prefix.is_dir():
        return []
    port = prefix / "bin/port"
    evidence = ["MacPorts prefix exists"]
    broken = not port.is_file()
    if broken:
        evidence.append("port executable is absent")
    else:
        try:
            result = subprocess.run(
                [str(port), "version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            broken = True
            evidence.append(f"port version failed: {exc}")
        else:
            broken = result.returncode != 0
            if broken:
                message = (result.stderr or result.stdout).splitlines()
                evidence.append(message[0] if message else "port version failed")
    if not broken:
        return []
    candidate = _candidate(
        prefix,
        get_size,
        min_size_mb,
        category="macports",
        description="broken MacPorts installation",
        recovery="Reinstall MacPorts and the requested ports",
        evidence=evidence,
        concerns=[
            "the prefix may contain configuration or files installed outside MacPorts"
        ],
    )
    return [candidate] if candidate else []


def _path_in_use(path: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["lsof", "+D", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return len(result.stdout.splitlines()) > 1


def _find_chrome_clones(
    paths: SystemPaths, get_size: SizeGetter, min_size_mb: int
) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[Path] = set()
    for temp_root in paths.temp_roots:
        x_root = temp_root.parent / "X" if temp_root.name == "T" else temp_root / "X"
        clone_root = x_root / "com.google.Chrome.code_sign_clone"
        try:
            clones = sorted(clone_root.glob("code_sign_clone.*"))
        except OSError:
            continue
        for clone in clones:
            if clone in seen or not clone.is_dir():
                continue
            seen.add(clone)
            in_use = _path_in_use(clone)
            if in_use is True:
                concern = "currently in use by a process; do not delete"
            elif in_use is None:
                concern = "could not determine whether a process is using this clone"
            else:
                concern = "confirm Chrome is closed before deleting"
            candidate = _candidate(
                clone,
                get_size,
                min_size_mb,
                category="browser",
                description="temporary Chrome code-signing clone",
                recovery="Recreated by Chrome during an update",
                evidence=["stored in the per-user temporary X directory"],
                concerns=[concern],
            )
            if candidate:
                candidates.append(candidate)
    return candidates


def _find_obsolete_vscode_extensions(
    paths: SystemPaths, get_size: SizeGetter, min_size_mb: int
) -> list[Candidate]:
    extensions = paths.home / ".vscode/extensions"
    try:
        obsolete = json.loads((extensions / ".obsolete").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(obsolete, dict):
        return []

    measured: list[tuple[Path, int]] = []
    for name, is_obsolete in obsolete.items():
        if not is_obsolete or not isinstance(name, str):
            continue
        path = extensions / name
        if not path.is_dir():
            continue
        try:
            size = get_size(path)
        except Exception:
            continue
        if size is not None:
            measured.append((path, size))

    if sum(size for _, size in measured) < min_size_mb * 1024 * 1024:
        return []

    candidates: list[Candidate] = []
    for path, size in measured:
        candidates.append(
            Candidate(
                path=path,
                size_bytes=size,
                category="editor",
                description="VS Code extension version marked obsolete",
                tier=Tier.INSPECT,
                recovery="Reinstall the extension version from the VS Code Marketplace",
                evidence=["VS Code lists this exact extension directory in .obsolete"],
                concerns=[
                    "confirm no running VS Code process is still using this version"
                ],
            )
        )
    return candidates


def find_system_artifacts(
    get_size: SizeGetter,
    min_size_mb: int = 100,
    paths: SystemPaths | None = None,
) -> list[Candidate]:
    """Return inspect-only candidates for stale macOS development toolchains."""
    layout = paths or SystemPaths.macos()
    candidates: list[Candidate] = []
    for probe in (
        _find_old_tex,
        _find_old_r,
        _find_inactive_python_frameworks,
        _find_global_python_packages,
        _find_retained_mactex_installers,
        _find_broken_macports,
        _find_chrome_clones,
        _find_obsolete_vscode_extensions,
    ):
        candidates.extend(probe(layout, get_size, min_size_mb))
    return candidates

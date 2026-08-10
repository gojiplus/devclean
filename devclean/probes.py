"""Content probes that check whether a directory really is what its name says.

Structure proposes, evidence decides. A directory named ``dist/`` sitting next
to a ``pyproject.toml`` looks like disposable build output by every structural
signal available, and is sometimes the only copy of something expensive. The
only way to tell is to read what is inside.

Every probe returns a list of concerns. Empty means nothing objected; non-empty
means the caller should downgrade the candidate to INSPECT.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# PEP 440: release segment of digits and dots, optional pre/post/dev/local parts.
# Deliberately strict — anything it does not recognize becomes a concern, which
# fails toward asking rather than deleting.
_VERSION_RE = re.compile(
    r"^[0-9]+(\.[0-9]+)*"  # release
    r"((a|b|rc)[0-9]+)?"  # pre-release
    r"(\.post[0-9]+)?"  # post-release
    r"(\.dev[0-9]+)?"  # dev release
    r"(\+[a-zA-Z0-9.]+)?$"  # local version label
)

_SDIST_SUFFIX = ".tar.gz"
_WHEEL_SUFFIX = ".whl"

MANIFESTS = (
    "uv.lock",
    "poetry.lock",
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "environment.yml",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
)


def _looks_like_version(segment: str) -> bool:
    return bool(_VERSION_RE.match(segment))


def _sdist_conforms(stem: str) -> bool:
    """Check a ``{name}-{version}`` sdist stem.

    Distribution names may contain hyphens, so the version is the final
    hyphen-separated segment, not the second one.
    """
    if "-" not in stem:
        return False
    return _looks_like_version(stem.rsplit("-", 1)[1])


def _wheel_conforms(stem: str) -> bool:
    """Check a ``{name}-{version}-{python}-{abi}-{platform}`` wheel stem.

    Parsed from the right, because distribution names may contain hyphens even
    though PEP 427 asks for underscores. The three tags are always last, which
    puts the version at ``-4``, or ``-5`` when an optional build tag is present.
    """
    parts = stem.split("-")
    if len(parts) < 5:
        return False
    return _looks_like_version(parts[-4]) or (len(parts) >= 6 and _looks_like_version(parts[-5]))


def probe_dist_dir(path: Path) -> list[str]:
    """Verify a ``dist/`` holds only Python packaging artifacts.

    A real ``dist/`` is flat and contains nothing but wheels and sdists whose
    names carry a PEP 440 version. Anything else — a subdirectory, a stray
    README, an archive named for its contents rather than a release — means the
    directory is being used for something other than packaging output.
    """
    concerns: list[str] = []
    try:
        entries = sorted(path.iterdir())
    except OSError as exc:
        return [f"could not read directory: {exc}"]

    if not entries:
        return []

    for entry in entries:
        name = entry.name
        if entry.is_dir():
            concerns.append(f"contains a subdirectory ({name}/) — dist/ should be flat")
            continue

        # Dotfiles are never the payload. Real dist/ directories routinely hold
        # a .gitignore, and macOS scatters .DS_Store everywhere; flagging them
        # would push every genuine dist/ to INSPECT and drown the real signal.
        if name.startswith("."):
            continue

        if name.endswith(_WHEEL_SUFFIX):
            if not _wheel_conforms(name[: -len(_WHEEL_SUFFIX)]):
                concerns.append(f"{name} is not a conventionally named wheel")
        elif name.endswith(_SDIST_SUFFIX):
            if not _sdist_conforms(name[: -len(_SDIST_SUFFIX)]):
                concerns.append(
                    f"{name} is a tarball whose name carries no release version "
                    "— it may be data rather than a build artifact"
                )
        else:
            concerns.append(f"{name} is not a wheel or sdist")

    return concerns


def probe_venv(path: Path) -> list[str]:
    """Verify a directory is a real virtualenv and not a package that shares the name.

    ``pyvenv.cfg`` is the marker. Without this check a path such as
    ``node_modules/@next/env`` matches the ``env`` name pattern and would be
    destroyed.
    """
    if not (path / "pyvenv.cfg").is_file():
        return ["no pyvenv.cfg — not a virtualenv"]
    return []


def probe_node_modules(path: Path) -> list[str]:
    """Verify a ``node_modules/`` sits beside something that can restore it."""
    parent = path.parent
    if not (parent / "package.json").is_file():
        return [f"no package.json in {parent} — nothing to reinstall from"]
    return []


def is_gitignored(path: Path) -> bool:
    """Report whether git ignores this path, i.e. no copy exists in history.

    Returns False when the path is not in a git repository or git is
    unavailable, since in that case ignoring tells us nothing.
    """
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=str(path.parent),
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def find_manifest(project_dir: Path) -> str | None:
    """Return the manifest that could rebuild this project's dependencies."""
    for manifest in MANIFESTS:
        if (project_dir / manifest).is_file():
            return manifest
    return None


def recovery_evidence(path: Path, project_dir: Path | None = None) -> tuple[list[str], list[str]]:
    """Collect cross-cutting evidence and concerns about recoverability.

    Two facts matter regardless of category: whether git holds a copy, and
    whether a manifest exists to rebuild from. Together they decide the cost of
    being wrong.
    """
    evidence: list[str] = []
    concerns: list[str] = []

    if is_gitignored(path):
        concerns.append("gitignored — no copy in version control")
    else:
        evidence.append("tracked by git or outside a repo")

    if project_dir is not None:
        manifest = find_manifest(project_dir)
        if manifest:
            evidence.append(f"rebuildable from {manifest}")
        else:
            concerns.append(f"no manifest in {project_dir} to rebuild from")

    return evidence, concerns

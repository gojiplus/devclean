"""Conservative, dependency-free scheduled cleanup of inactive project venvs."""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import shutil
import subprocess
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .exceptions import DevCleanError
from .probes import UV_MACOS_ENTRIES, inspect_environment
from .safety import assert_safe_to_delete
from .settings import load_config

LOG = logging.getLogger(__name__)


def command(args: list[str]) -> str:
    """Run an inspection command, failing closed on errors or timeouts."""
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=60, check=True
    )
    if result.stderr.strip():
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def process_activity() -> str:
    """Read process arguments and open paths, including working directories."""
    return command(["/bin/ps", "-axo", "args="]) + command(
        ["/usr/sbin/lsof", "-nP", "-u", str(os.getuid()), "-Fn"]
    )


def in_use(project: Path, activity: str) -> bool:
    """Check both literal and canonical project paths in the process snapshot."""
    return any(str(path) in activity for path in (project, project.resolve()))


def recent_tree(project: Path, cutoff: float) -> bool:
    """Check all file/directory mtimes, including ignored data and venv updates."""
    if project.stat().st_mtime >= cutoff:
        return True

    def onerror(error: OSError) -> None:
        raise error

    for base, dirs, files in os.walk(project, followlinks=False, onerror=onerror):
        dirs[:] = [name for name in dirs if name != ".git"]
        for name in (*dirs, *files):
            path = Path(base) / name
            if path.lstat().st_mtime >= cutoff:
                return True
    return False


def skip_reason(project: Path, cutoff: float, activity: str) -> str | None:
    """Explain why a project's direct .venv must be retained, if applicable."""
    venv = project / ".venv"
    if project.is_symlink() or venv.is_symlink() or venv.is_mount():
        return "symlink or mount point"
    if venv.stat().st_uid != os.getuid():
        return "environment belongs to another user"
    if (
        not (project / "pyproject.toml").is_file()
        or not (project / "uv.lock").is_file()
    ):
        return "missing pyproject.toml or uv.lock"
    if (project / ".devclean-keep").exists():
        return "project opted out with .devclean-keep"
    _, concerns = inspect_environment(venv, allowed_entries=UV_MACOS_ENTRIES)
    if concerns:
        return ", ".join(concerns)
    if in_use(project, activity):
        return "project referenced by a running process or open file"
    top = command(["git", "-C", str(project), "rev-parse", "--show-toplevel"]).strip()
    if Path(top).resolve() != project.resolve():
        return "not a project repository root"
    committed = command(["git", "-C", str(project), "log", "-1", "--format=%ct"])
    if float(committed.strip()) >= cutoff:
        return "recent Git commit"
    gitdir = Path(
        command(["git", "-C", str(project), "rev-parse", "--absolute-git-dir"]).strip()
    )
    reflog = gitdir / "logs" / "HEAD"
    if reflog.exists() and reflog.stat().st_mtime >= cutoff:
        return "recent checkout or local Git activity"
    if recent_tree(project, cutoff):
        return "recent project or environment changes"
    return None


def clean(root: Path, days: int, *, apply: bool = False) -> int:
    """Inspect immediate child projects and remove only eligible .venv directories."""
    if days < 1:
        raise ValueError("days must be positive")
    root = root.expanduser().resolve(strict=True)
    if not root.is_relative_to(Path.home().resolve()) or root == Path.home().resolve():
        raise ValueError("root must be a project directory below your home")
    protected = load_config().safety.protected_paths
    cutoff = time.time() - days * 86400
    activity = process_activity()
    removed = 0
    for project in sorted(root.iterdir()):
        venv = project / ".venv"
        if not project.is_dir() or not venv.is_dir():
            continue
        try:
            assert_safe_to_delete(venv, protected)
            identity = venv.lstat()
            reason = skip_reason(project, cutoff, activity)
            if reason:
                LOG.info("KEEP %s: %s", venv, reason)
                continue
            if not apply:
                LOG.info("WOULD REMOVE %s; restore with uv sync --locked", venv)
                continue
            # Refresh activity immediately before deletion; inspection failure
            # leaves the environment intact.
            reason = skip_reason(project, cutoff, process_activity())
            if reason:
                LOG.info("KEEP %s: %s", venv, reason)
                continue
            assert_safe_to_delete(venv, protected)
            if not os.path.samestat(identity, venv.lstat()):
                LOG.info("KEEP %s: environment was replaced during inspection", venv)
                continue
            shutil.rmtree(venv)
            removed += 1
            LOG.info("REMOVED %s; restore with uv sync --locked", venv)
        except (
            DevCleanError,
            OSError,
            RuntimeError,
            ValueError,
            subprocess.SubprocessError,
        ) as exc:
            LOG.warning("KEEP %s: inspection failed: %s", venv, exc)
    LOG.info("Finished: removed %s environment(s); dry_run=%s", removed, not apply)
    return removed


def prune_uv(uv: Path, *, apply: bool = False) -> None:
    """Prune unreachable shared-cache entries only when uv is idle."""
    processes = command(["/bin/ps", "-axo", "comm="])
    if any(Path(line.strip()).name == "uv" for line in processes.splitlines()):
        LOG.info("KEEP uv cache: uv is running")
        return
    if not apply:
        LOG.info("WOULD RUN %s cache prune", uv)
        return
    try:
        result = subprocess.run(
            [str(uv), "cache", "prune"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        LOG.info("uv cache prune: %s", (result.stdout + result.stderr).strip())
    except subprocess.TimeoutExpired:
        LOG.warning("uv cache prune timed out; no lock override attempted")


def main() -> None:
    """Run the scheduled cleanup with a single-instance lock and bounded logs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--prune-uv", action="store_true")
    parser.add_argument(
        "--uv",
        type=Path,
        default=Path(shutil.which("uv") or Path.home() / ".local/bin/uv"),
    )
    parser.add_argument(
        "--state-dir", type=Path, default=Path.home() / ".local/state/devclean"
    )
    args = parser.parse_args()
    args.state_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler(
                args.state_dir / "inactive.log", maxBytes=1_000_000, backupCount=2
            ),
        ],
    )
    with (args.state_dir / "inactive.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            LOG.info("Another cleanup is running; skipped")
            return
        try:
            clean(args.root, args.days, apply=args.apply)
            if args.prune_uv:
                prune_uv(args.uv, apply=args.apply)
        except Exception:
            LOG.exception("Cleanup failed; inspect this log before retrying")
            raise


if __name__ == "__main__":
    main()

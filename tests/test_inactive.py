"""Exercise destructive cleanup on isolated repositories and preserve active work."""

import os
import subprocess
import time
from pathlib import Path

import pytest

from devclean import inactive
from devclean.settings import DevCleanConfig, SafetySettings


@pytest.fixture
def project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = home / "projects"
    repo = root / "example"
    venv = repo / ".venv"
    venv.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (venv / "lib").mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "example"\n')
    (repo / "uv.lock").write_text("version = 1\n")
    (repo / ".gitignore").write_text(".venv/\nignored-data/\n")
    env = os.environ | {
        "GIT_AUTHOR_DATE": "2020-01-01T12:00:00+0000",
        "GIT_COMMITTER_DATE": "2020-01-01T12:00:00+0000",
    }
    for args in (
        ["init"],
        ["add", "."],
        [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "init",
        ],
    ):
        subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, env=env
        )
    old = time.time() - 40 * 86400
    for base, dirs, files in os.walk(root):
        for name in (*dirs, *files):
            os.utime(Path(base) / name, (old, old))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(
        inactive,
        "load_config",
        lambda: DevCleanConfig(safety=SafetySettings(protected_paths=[])),
    )
    monkeypatch.setattr(inactive, "process_activity", lambda: "")
    return repo


def test_dry_run_preserves_environment(project):
    assert inactive.clean(project.parent, 14) == 0
    assert (project / ".venv/pyvenv.cfg").exists()


def test_apply_removes_only_environment(project):
    assert inactive.clean(project.parent, 14, apply=True) == 1
    assert not (project / ".venv").exists()
    assert (project / "uv.lock").exists()
    assert (project / "pyproject.toml").exists()
    assert (project / ".git").exists()


@pytest.mark.parametrize(
    "path", ["ignored-data/result.csv", ".venv/lib/new-package.py", "notes.md"]
)
def test_recent_files_preserve_environment(project, path):
    file = project / path
    file.parent.mkdir(exist_ok=True)
    file.write_text("work")
    assert inactive.clean(project.parent, 14, apply=True) == 0
    assert (project / ".venv").exists()


@pytest.mark.parametrize("entry", [".devclean-keep", ".venv/valuable.csv"])
def test_opt_out_and_unexpected_content_preserved(project, entry):
    (project / entry).touch()
    assert inactive.clean(project.parent, 14, apply=True) == 0


def test_missing_lockfile_preserved(project):
    (project / "uv.lock").unlink()
    assert inactive.clean(project.parent, 14, apply=True) == 0


def test_active_process_preserved(project, monkeypatch):
    monkeypatch.setattr(inactive, "process_activity", lambda: f"n{project}/script.py")
    assert inactive.clean(project.parent, 14, apply=True) == 0


def test_process_starting_during_inspection_preserved(project, monkeypatch):
    snapshots = iter(["", f"n{project}/.venv/lib/package.py"])
    monkeypatch.setattr(inactive, "process_activity", lambda: next(snapshots))
    assert inactive.clean(project.parent, 14, apply=True) == 0
    assert (project / ".venv").exists()


def test_process_inspection_failure_preserved(project, monkeypatch):
    def fail():
        raise PermissionError("cannot inspect processes")

    monkeypatch.setattr(inactive, "process_activity", fail)
    with pytest.raises(PermissionError):
        inactive.clean(project.parent, 14, apply=True)
    assert (project / ".venv").exists()


def test_symlink_environment_preserved(project):
    target = project / "saved"
    (project / ".venv").rename(target)
    (project / ".venv").symlink_to(target, target_is_directory=True)
    assert inactive.clean(project.parent, 14, apply=True) == 0
    assert (target / "pyvenv.cfg").exists()


def test_protected_project_preserved(project, monkeypatch):
    config = DevCleanConfig(safety=SafetySettings(protected_paths=[str(project)]))
    monkeypatch.setattr(inactive, "load_config", lambda: config)
    assert inactive.clean(project.parent, 14, apply=True) == 0


def test_invalid_age_preserved(project):
    with pytest.raises(ValueError, match="positive"):
        inactive.clean(project.parent, 0, apply=True)
    assert (project / ".venv").exists()


def test_uv_running_skips_prune(monkeypatch):
    monkeypatch.setattr(inactive, "command", lambda args: "/Users/test/.local/bin/uv\n")

    def forbidden(*args, **kwargs):
        pytest.fail("must not prune while uv is running")

    monkeypatch.setattr(inactive.subprocess, "run", forbidden)
    inactive.prune_uv(Path("/tool/uv"), apply=True)


def test_uv_idle_uses_prune_without_force(monkeypatch):
    monkeypatch.setattr(inactive, "command", lambda args: "/bin/zsh\n")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "Removed unused entries")

    monkeypatch.setattr(inactive.subprocess, "run", run)
    inactive.prune_uv(Path("/tool/uv"), apply=True)
    assert calls == [["/tool/uv", "cache", "prune"]]


def test_active_environment_preserved_without_process_match(project, monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", str(project / ".venv"))
    assert inactive.clean(project.parent, 14, apply=True) == 0
    assert (project / ".venv/pyvenv.cfg").is_file()


def test_tracked_environment_contents_preserved(project):
    subprocess.run(
        ["git", "-C", str(project), "add", "-f", ".venv/pyvenv.cfg"], check=True
    )
    assert inactive.clean(project.parent, 14, apply=True) == 0
    assert (project / ".venv/pyvenv.cfg").is_file()

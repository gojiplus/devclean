"""Codex release cleanup retains active installations and fails closed."""

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from devclean.cli import app
from devclean.codex_releases import unused_codex_releases
from devclean.settings import DevCleanConfig

runner = CliRunner()


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("devclean.cli.load_config", DevCleanConfig)
    package = tmp_path / ".codex/packages/app-server-daemon"
    releases = package / "releases"
    for version in ("0.157.0", "0.162.1", "0.163.0", "0.164.0"):
        binary = releases / f"{version}-aarch64-apple-darwin/bin/codex"
        binary.parent.mkdir(parents=True)
        binary.write_text("binary")
    current = releases / "0.163.0-aarch64-apple-darwin"
    (package / "current").symlink_to(current)
    output = f"p1\nn{current}/bin/codex\n"
    monkeypatch.setattr(
        "devclean.codex_releases.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )
    return tmp_path, releases, current


def test_keeps_current_newer_and_running_versions(installation, monkeypatch):
    home, releases, current = installation
    busy = releases / "0.162.1-aarch64-apple-darwin"
    monkeypatch.setattr(
        "devclean.codex_releases.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, f"p1\nn{busy}/bin/codex\nn{current}/bin/codex\n", ""
        ),
    )
    found_current, eligible, running = unused_codex_releases(home)
    assert found_current == current
    assert eligible == [releases / "0.157.0-aarch64-apple-darwin"]
    assert running == [busy]


def test_unrecognized_and_incomplete_releases_are_preserved(installation):
    home, releases, _ = installation
    (releases / "0.100.0-aarch64-apple-darwin").mkdir()
    (releases / "unrelated/bin").mkdir(parents=True)
    (releases / "unrelated/bin/codex").write_text("not a release")
    (releases / "0.101.0-aarch64-apple-darwin").symlink_to(releases / "unrelated")
    _, eligible, _ = unused_codex_releases(home)
    assert len(eligible) == 2


@pytest.mark.parametrize(
    ("code", "stdout", "stderr"),
    [(1, "", ""), (0, "", ""), (0, "n/bin/tool\n", "permission warning")],
)
def test_failed_or_incomplete_process_check_refuses_cleanup(
    installation, monkeypatch, code, stdout, stderr
):
    home, _, _ = installation
    monkeypatch.setattr(
        "devclean.codex_releases.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, code, stdout, stderr),
    )
    with pytest.raises(ValueError, match="process check"):
        unused_codex_releases(home)


@pytest.mark.parametrize(
    "error", [FileNotFoundError(), subprocess.TimeoutExpired("lsof", 30)]
)
def test_missing_or_timed_out_lsof_refuses_cleanup(installation, monkeypatch, error):
    home, _, _ = installation

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("devclean.codex_releases.subprocess.run", fail)
    with pytest.raises(ValueError, match="Cannot verify"):
        unused_codex_releases(home)


def test_dry_run_preserves_all_files(installation):
    _, releases, _ = installation
    result = runner.invoke(app, ["clean-codex-releases", "--dry-run"])
    assert result.exit_code == 0
    assert "nothing was deleted" in result.stdout
    assert len(list(releases.iterdir())) == 4


def test_force_deletes_only_unused_old_releases(installation):
    home, releases, current = installation
    session = home / ".codex/sessions/keep.jsonl"
    session.parent.mkdir()
    session.write_text("history")
    result = runner.invoke(app, ["clean-codex-releases", "--force"])
    assert result.exit_code == 0, result.stdout
    assert sorted(p.name for p in releases.iterdir()) == [
        current.name,
        "0.164.0-aarch64-apple-darwin",
    ]
    assert session.read_text() == "history"
    assert "free-space change" in result.stdout


def test_missing_current_link_refuses_even_with_force(installation):
    _, releases, _ = installation
    (releases.parent / "current").unlink()
    result = runner.invoke(app, ["clean-codex-releases", "--force"])
    assert result.exit_code == 1
    assert len(list(releases.iterdir())) == 4


def test_changed_current_link_stops_before_deletion(installation, monkeypatch):
    home, releases, current = installation
    initial = unused_codex_releases(home)
    new_current = releases / "0.164.0-aarch64-apple-darwin"
    results = iter([initial, (new_current, initial[1], [])])
    monkeypatch.setattr("devclean.cli.unused_codex_releases", lambda _: next(results))
    result = runner.invoke(app, ["clean-codex-releases", "--force"])
    assert result.exit_code == 1
    assert "state changed" in result.stdout
    assert len(list(releases.iterdir())) == 4
    assert current.exists()


def test_newly_running_release_stops_before_deletion(installation, monkeypatch):
    home, releases, current = installation
    initial = unused_codex_releases(home)
    results = iter([initial, (current, [], initial[1])])
    monkeypatch.setattr("devclean.cli.unused_codex_releases", lambda _: next(results))
    result = runner.invoke(app, ["clean-codex-releases", "--force"])
    assert result.exit_code == 1
    assert len(list(releases.iterdir())) == 4


@pytest.mark.parametrize("protect_parent", [False, True])
def test_configured_protection_prevents_deletion(
    installation, monkeypatch, protect_parent
):
    _, releases, _ = installation
    config = DevCleanConfig()
    protected = (
        releases if protect_parent else releases / "0.157.0-aarch64-apple-darwin"
    )
    config.safety.protected_paths = [str(protected)]
    monkeypatch.setattr("devclean.cli.load_config", lambda: config)
    result = runner.invoke(app, ["clean-codex-releases", "--force"])
    assert result.exit_code == 1
    assert "protected path" in result.stdout
    assert len(list(releases.iterdir())) == 4


def test_permission_error_is_not_reported_as_success(installation, monkeypatch):
    _, releases, _ = installation

    def blocked(*args):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr("devclean.cli._delete", blocked)
    result = runner.invoke(app, ["clean-codex-releases", "--force"])
    assert result.exit_code == 1
    assert "write access" in result.stdout
    assert "Deleted " not in result.stdout
    assert len(list(releases.iterdir())) == 4

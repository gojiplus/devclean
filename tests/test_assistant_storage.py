"""Assistant data is visible without becoming eligible for bulk deletion."""

import pytest

from devclean.assistant_storage import find_assistant_storage
from devclean.candidates import Tier
from devclean.scanner import (
    ProjectInventory,
    ScanResult,
    build_project_inventory,
    find_benchmark_dirs,
    scan_all,
)


def measure(_path):
    return 200 * 1024**2


def test_history_databases_and_caches_are_not_bulk_deletable(tmp_path):
    for name in (".codex/sessions", ".codex/cache", ".claude/projects"):
        (tmp_path / name).mkdir(parents=True)
    for name in ("state_5.sqlite", "state_5.sqlite-wal", "auth.json", "config.toml"):
        (tmp_path / ".codex" / name).write_text("private content")
    candidates = find_assistant_storage(tmp_path, measure)
    assert len(candidates) == 5
    assert {c.category for c in candidates} == {
        "assistant-history",
        "assistant-cache",
        "assistant-database",
    }
    assert all(c.tier == Tier.INSPECT and c.concerns for c in candidates)
    assert ScanResult(candidates=candidates).reclaimable_bytes == 0
    assert not any(c.path.name in {"auth.json", "config.toml"} for c in candidates)


def test_only_non_current_releases_are_reported(tmp_path):
    package = tmp_path / ".codex/packages/app-server-daemon"
    old = package / "releases/0.162.0"
    current = package / "releases/0.163.0"
    old.mkdir(parents=True)
    current.mkdir()
    (package / "current").symlink_to(current)
    candidates = find_assistant_storage(tmp_path, measure)
    assert [c.path for c in candidates] == [old]
    assert not candidates[0].bulk_deletable
    assert any("process" in text for text in candidates[0].evidence)


@pytest.mark.parametrize("target", ["missing", "outside", "cycle"])
def test_uncertain_current_release_prevents_release_candidates(tmp_path, target):
    package = tmp_path / ".codex/packages/app-server-daemon"
    (package / "releases/0.162.0").mkdir(parents=True)
    if target == "outside":
        outside = tmp_path / "other"
        outside.mkdir()
        (package / "current").symlink_to(outside)
    elif target == "cycle":
        (package / "current").symlink_to(package / "current")
    assert find_assistant_storage(tmp_path, measure) == []


@pytest.mark.parametrize("symlink_parent", [False, True])
def test_symlinked_storage_is_not_followed(tmp_path, symlink_parent):
    home = tmp_path / "home"
    home.mkdir()
    outside = tmp_path / "outside"
    (outside / "sessions").mkdir(parents=True)
    if symlink_parent:
        (home / ".codex").symlink_to(outside)
    else:
        (home / ".codex").mkdir()
        (home / ".codex/sessions").symlink_to(outside / "sessions")
    assert find_assistant_storage(home, measure) == []


def test_missing_or_small_measurements_are_not_reported(tmp_path):
    (tmp_path / ".claude/projects").mkdir(parents=True)
    assert find_assistant_storage(tmp_path, lambda _: None) == []
    assert find_assistant_storage(tmp_path, lambda _: 1024) == []


def test_scan_includes_assistant_storage_without_project_scan(tmp_path, monkeypatch):
    (tmp_path / ".claude/projects").mkdir(parents=True)
    monkeypatch.setattr("devclean.scanner.get_dir_size", measure)
    monkeypatch.setattr("devclean.cache.save_cache", lambda: None)
    result = scan_all(
        home=tmp_path,
        include_venvs=False,
        include_node_modules=False,
        include_project_cruft=False,
        include_system_artifacts=False,
        include_temporary_dirs=False,
    )
    assert [c.category for c in result.candidates] == ["assistant-history"]
    assert not result.errors


def test_benchmarks_are_found_and_stay_inspection_only(tmp_path, monkeypatch):
    project = tmp_path / "projects/package"
    working = project / ".benchmarks"
    (working / "corpora/repo/.git").mkdir(parents=True)
    (project / "pyproject.toml").write_text('[project]\nname="package"\n')
    inventory = build_project_inventory(tmp_path)
    assert inventory.paths_named(".benchmarks") == [working]
    monkeypatch.setattr("devclean.scanner.get_dir_size", measure)
    candidates = find_benchmark_dirs(inventory, 100)
    assert len(candidates) == 1
    assert candidates[0].path == working
    assert not candidates[0].bulk_deletable
    assert "Git" in candidates[0].concerns[0]


def test_benchmark_size_floor_and_symlink(tmp_path, monkeypatch):
    working = tmp_path / ".benchmarks"
    working.symlink_to(tmp_path)
    inventory = ProjectInventory()
    inventory.by_name[".benchmarks"] = [working]
    monkeypatch.setattr("devclean.scanner.get_dir_size", measure)
    assert find_benchmark_dirs(inventory, 100) == []
    working.unlink()
    working.mkdir()
    assert find_benchmark_dirs(inventory, 201) == []

"""Tests for the scanner."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devclean.candidates import Candidate, Tier
from devclean.exceptions import ScanError, ScanTimeoutError
from devclean.scanner import (
    ProjectInventory,
    ScanResult,
    _get_dir_sizes,
    _get_dir_sizes_batched,
    _search_roots,
    build_project_inventory,
    check_command_exists,
    find_node_modules,
    find_temporary_dirs,
    find_venvs,
    get_dir_size,
    scan_all,
    scan_known_cruft,
)


def make_candidate(**overrides: object) -> Candidate:
    defaults: dict[str, object] = {
        "path": Path("/tmp/x"),
        "size_bytes": 100 * 1024 * 1024,
        "category": "python",
        "description": "test",
        "tier": Tier.AUTO,
        "recovery": "refetched",
    }
    defaults.update(overrides)
    return Candidate(**defaults)  # type: ignore[arg-type]


class TestCandidate:
    """Tests for the Candidate dataclass."""

    def test_size_human_mb(self):
        assert make_candidate(size_bytes=200 * 1024 * 1024).size_human == "200 MB"

    def test_size_human_gb(self):
        assert make_candidate(size_bytes=2 * 1024**3).size_human == "2.0 GB"

    def test_auto_is_bulk_deletable(self):
        assert make_candidate(tier=Tier.AUTO).bulk_deletable is True

    def test_probe_is_not_bulk_deletable(self):
        """PROBE means nothing objected, not that the contents were understood."""
        assert make_candidate(tier=Tier.PROBE).bulk_deletable is False

    def test_concerns_block_bulk_deletion_even_at_high_tier(self):
        candidate = make_candidate(tier=Tier.VERIFIED)
        candidate.concerns.append("gitignored")
        assert candidate.bulk_deletable is False

    def test_to_dict_round_trips_the_fields_the_skill_reads(self):
        data = make_candidate().to_dict()
        for key in ("path", "size_bytes", "tier", "recovery", "evidence", "concerns"):
            assert key in data


class TestScanResult:
    """Tests for the ScanResult container."""

    def test_empty(self):
        result = ScanResult()
        assert result.candidates == []
        assert result.total_bytes == 0

    def test_totals_and_partitioning(self):
        safe = make_candidate(path=Path("/tmp/a"), size_bytes=1024**3, tier=Tier.AUTO)
        risky = make_candidate(path=Path("/tmp/b"), size_bytes=2 * 1024**3, tier=Tier.INSPECT)
        result = ScanResult(candidates=[safe, risky])

        assert result.total_bytes == 3 * 1024**3
        assert result.reclaimable_bytes == 1024**3
        assert result.bulk_deletable == [safe]
        assert result.needs_review == [risky]

    def test_by_category_groups(self):
        result = ScanResult(
            candidates=[
                make_candidate(category="python"),
                make_candidate(category="node"),
                make_candidate(category="python"),
            ]
        )
        grouped = result.by_category()
        assert len(grouped["python"]) == 2
        assert len(grouped["node"]) == 1

    def test_sort_is_descending_by_size(self):
        result = ScanResult(
            candidates=[
                make_candidate(size_bytes=1),
                make_candidate(size_bytes=100),
                make_candidate(size_bytes=50),
            ]
        )
        result.sort()
        assert [c.size_bytes for c in result.candidates] == [100, 50, 1]

    def test_nested_candidate_is_not_double_counted(self):
        parent = make_candidate(
            path=Path("/private/tmp/job"),
            size_bytes=200 * 1024**2,
            tier=Tier.INSPECT,
        )
        environment = make_candidate(
            path=Path("/private/tmp/job/.venv"),
            size_bytes=100 * 1024**2,
            tier=Tier.VERIFIED,
        )

        result = ScanResult(candidates=[parent, environment])

        assert result.total_bytes == 200 * 1024**2
        assert result.reclaimable_bytes == 100 * 1024**2


class TestGetDirSize:
    """Tests for get_dir_size. All pass use_cache=False so the on-disk cache
    cannot make results depend on prior runs."""

    @patch("devclean.scanner.subprocess.run")
    @patch("pathlib.Path.exists")
    def test_success(self, mock_exists, mock_run):
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="1024\t/tmp/test\n")

        assert get_dir_size(Path("/tmp/test"), use_cache=False) == 1024 * 1024

    @patch("devclean.scanner.subprocess.run")
    @patch("pathlib.Path.exists")
    def test_timeout(self, mock_exists, mock_run):
        from subprocess import TimeoutExpired

        mock_exists.return_value = True
        mock_run.side_effect = TimeoutExpired("du", 30)

        with pytest.raises(ScanTimeoutError):
            get_dir_size(Path("/tmp/test"), timeout=30, use_cache=False)

    @patch("devclean.scanner.subprocess.run")
    @patch("pathlib.Path.exists")
    def test_parse_error(self, mock_exists, mock_run):
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="invalid output")

        with pytest.raises(ScanError):
            get_dir_size(Path("/tmp/test"), use_cache=False)


class TestGetDirSizes:
    @patch("devclean.scanner.subprocess.run")
    def test_measures_multiple_paths_in_one_call(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="1024\t/private/tmp/one\n2048\t/private/tmp/path with spaces\n"
        )
        paths = [Path("/private/tmp/one"), Path("/private/tmp/path with spaces")]

        assert _get_dir_sizes(paths) == {
            paths[0]: 1024 * 1024,
            paths[1]: 2048 * 1024,
        }
        mock_run.assert_called_once_with(
            ["du", "-sk", *(str(path) for path in paths)],
            capture_output=True,
            text=True,
            timeout=60,
        )

    @patch("devclean.scanner.subprocess.run")
    def test_timeout_skips_the_root(self, mock_run):
        from subprocess import TimeoutExpired

        mock_run.side_effect = TimeoutExpired("du", 60)

        assert _get_dir_sizes([Path("/private/tmp/slow")]) == {}

    @patch("devclean.scanner._get_dir_sizes")
    def test_large_inputs_are_measured_in_bounded_batches(self, mock_sizes):
        paths = [Path(f"/tmp/{index}") for index in range(5)]
        mock_sizes.side_effect = lambda batch, _timeout: dict.fromkeys(batch, 1)

        result = _get_dir_sizes_batched(paths, timeout=7, batch_size=2)

        assert result == dict.fromkeys(paths, 1)
        assert [call.args[0] for call in mock_sizes.call_args_list] == [
            paths[:2],
            paths[2:4],
            paths[4:],
        ]


class TestProjectInventory:
    def test_configured_roots_are_used_and_nested_roots_are_collapsed(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        projects = home / "projects"
        nested = projects / "nested"
        extra = tmp_path / "extra"
        nested.mkdir(parents=True)
        extra.mkdir()
        monkeypatch.setattr(
            "devclean.scanner.VENV_SEARCH_DIRS",
            ("{home}/projects", "{home}/projects/nested"),
        )

        home_extra = home / "extra"
        home_extra.mkdir()
        roots = _search_roots(home, [extra, "projects/nested", "~/extra"])
        assert set(roots) == {projects, extra, home_extra}
        assert nested not in roots

    def test_one_walk_finds_project_and_home_level_dependencies(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        project_root = home / "projects"
        project_venv = project_root / "one" / ".venv"
        extra_node = tmp_path / "workspace" / "two" / "node_modules"
        home_venv = home / "analysis-env"
        home_node = home / "node_modules"
        for path in (project_venv, extra_node, home_venv, home_node):
            path.mkdir(parents=True)
        (project_venv / "pyvenv.cfg").touch()
        (home_venv / "pyvenv.cfg").touch()
        monkeypatch.setattr("devclean.scanner.VENV_SEARCH_DIRS", ("{home}/projects",))

        inventory = build_project_inventory(home, [tmp_path / "workspace"])

        assert set(inventory.virtualenvs) == {project_venv, home_venv}
        assert set(inventory.paths_named("node_modules")) == {extra_node, home_node}

    @patch("devclean.scanner._find_named_dirs", return_value=[])
    def test_each_non_overlapping_root_is_walked_once(self, mock_find, tmp_path, monkeypatch):
        home = tmp_path / "home"
        projects = home / "projects"
        nested = projects / "nested"
        nested.mkdir(parents=True)
        monkeypatch.setattr("devclean.scanner.VENV_SEARCH_DIRS", ("{home}/projects",))

        build_project_inventory(home, [nested])

        mock_find.assert_called_once()

    @patch("devclean.scanner.get_dir_size", return_value=100 * 1024 * 1024)
    def test_home_level_directories_are_reported_with_safety_probes(self, _mock_size, tmp_path):
        home = tmp_path / "home"
        venv = home / "custom-env"
        node_modules = home / "node_modules"
        venv.mkdir(parents=True)
        node_modules.mkdir()
        (venv / "pyvenv.cfg").touch()
        inventory = ProjectInventory(by_name={"node_modules": [node_modules]}, virtualenvs=[venv])

        venv_result = find_venvs(home, inventory=inventory)
        node_result = find_node_modules(home, inventory=inventory)

        assert [item.path for item in venv_result] == [venv]
        assert venv_result[0].tier is Tier.INSPECT
        assert [item.path for item in node_result] == [node_modules]
        assert node_result[0].tier is Tier.INSPECT


class TestScanAll:
    @patch("devclean.cache.save_cache")
    @patch("devclean.scanner.find_system_artifacts", return_value=[])
    @patch("devclean.scanner.find_probed_project_dirs", return_value=[])
    @patch("devclean.scanner.find_project_cruft", return_value=[])
    @patch("devclean.scanner.find_node_modules", return_value=[])
    @patch("devclean.scanner.find_venvs", return_value=[])
    @patch("devclean.scanner.scan_known_cruft", return_value=[])
    @patch("devclean.scanner.build_project_inventory")
    def test_project_stages_share_one_inventory(
        self,
        mock_inventory,
        _mock_known,
        mock_venvs,
        mock_node,
        mock_cruft,
        mock_build,
        _mock_system,
        _mock_save,
        tmp_path,
    ):
        inventory = ProjectInventory()
        mock_inventory.return_value = inventory

        result = scan_all(
            tmp_path,
            include_temporary_dirs=False,
            additional_search_paths=[tmp_path / "extra"],
            project_max_depth=9,
            project_scan_timeout=42,
        )

        assert result.errors == []
        mock_inventory.assert_called_once_with(
            tmp_path, [tmp_path / "extra"], maxdepth=9, timeout=42
        )
        assert mock_venvs.call_args.kwargs["inventory"] is inventory
        assert mock_venvs.call_args.args == (tmp_path,)
        assert mock_node.call_args.kwargs["inventory"] is inventory
        assert mock_node.call_args.args == (tmp_path,)
        assert mock_cruft.call_args.kwargs["inventory"] is inventory
        assert mock_build.call_args.kwargs["inventory"] is inventory
        assert mock_build.call_args.args == (tmp_path,)

    @patch("devclean.cache.save_cache")
    @patch("devclean.scanner.find_system_artifacts", return_value=[])
    @patch("devclean.scanner.scan_known_cruft", return_value=[])
    @patch("devclean.scanner.get_dir_size", return_value=100 * 1024**2)
    @patch("devclean.scanner._get_dir_sizes")
    def test_temp_parent_does_not_hide_verified_environment(
        self,
        mock_sizes,
        _mock_size,
        _mock_known,
        _mock_system,
        _mock_save,
        tmp_path,
        monkeypatch,
    ):
        home = tmp_path / "home"
        home.mkdir()
        temporary_root = tmp_path / "private-tmp"
        project = temporary_root / "review-worktree"
        environment = project / ".venv"
        environment.mkdir(parents=True)
        (environment / "pyvenv.cfg").touch()
        (project / "pyproject.toml").touch()
        mock_sizes.return_value = {project: 200 * 1024**2}
        monkeypatch.setattr("devclean.scanner.VENV_SEARCH_DIRS", ())
        monkeypatch.setattr("devclean.scanner.temporary_roots", lambda: [temporary_root])

        result = scan_all(
            home,
            include_node_modules=False,
            include_project_cruft=False,
            include_system_artifacts=False,
            min_size_mb=0,
        )

        assert [(candidate.path, candidate.tier) for candidate in result.candidates] == [
            (project, Tier.INSPECT),
            (environment, Tier.VERIFIED),
        ]
        assert result.total_bytes == 200 * 1024**2
        assert result.reclaimable_bytes == 100 * 1024**2


class TestCheckCommandExists:
    @patch("devclean.scanner.subprocess.run")
    def test_exists(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert check_command_exists("python") is True

    @patch("devclean.scanner.subprocess.run")
    def test_missing(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert check_command_exists("nonexistent-command") is False

    @patch("devclean.scanner.subprocess.run")
    def test_error_is_not_fatal(self, mock_run):
        mock_run.side_effect = OSError("boom")
        assert check_command_exists("python") is False

    def test_strips_version_argument(self):
        assert isinstance(check_command_exists("python --version"), bool)


class TestScanKnownCruft:
    def test_colima_vm_is_never_bulk_deletable(self):
        from devclean.config import CRUFT_PATTERNS

        pattern = next(item for item in CRUFT_PATTERNS if item.path_template.endswith(".colima"))

        assert pattern.safe is False
        assert "volumes are not restored" in pattern.recovery

    @patch("devclean.scanner.get_dir_size")
    @patch("devclean.scanner.check_command_exists")
    def test_nothing_found(self, mock_check_cmd, mock_get_size):
        with patch("pathlib.Path.exists", return_value=False):
            assert scan_known_cruft(Path.home(), min_size_mb=100) == []

    @patch("devclean.scanner.get_dir_size")
    @patch("devclean.scanner.check_command_exists")
    def test_found(self, mock_check_cmd, mock_get_size):
        mock_get_size.return_value = 200 * 1024 * 1024
        mock_check_cmd.return_value = True

        def only_precommit(self):
            return str(self).endswith(".cache/pre-commit")

        with patch("pathlib.Path.exists", only_precommit):
            result = scan_known_cruft(Path.home(), min_size_mb=100)

        assert len(result) == 1
        assert result[0].category == "python"
        assert result[0].size_bytes == 200 * 1024 * 1024

    @patch("devclean.scanner.get_dir_size")
    @patch("devclean.scanner.check_command_exists")
    def test_below_floor_is_skipped(self, mock_check_cmd, mock_get_size):
        mock_get_size.return_value = 50 * 1024 * 1024
        mock_check_cmd.return_value = True

        def only_precommit(self):
            return str(self).endswith(".cache/pre-commit")

        with patch("pathlib.Path.exists", only_precommit):
            assert scan_known_cruft(Path.home(), min_size_mb=100) == []

    @patch("devclean.scanner.get_dir_size")
    @patch("devclean.scanner.check_command_exists")
    def test_purge_command_earns_auto_tier(self, mock_check_cmd, mock_get_size):
        """A tool that documents how to clear its own cache is the evidence."""
        mock_get_size.return_value = 500 * 1024 * 1024
        mock_check_cmd.return_value = True

        def only_uv(self):
            return str(self).endswith(".cache/uv")

        with patch("pathlib.Path.exists", only_uv):
            result = scan_known_cruft(Path.home(), min_size_mb=100)

        assert len(result) == 1
        assert result[0].tier is Tier.AUTO
        assert any("uv cache clean" in e for e in result[0].evidence)

    @patch("devclean.scanner.get_dir_size")
    @patch("devclean.scanner.check_command_exists")
    def test_per_pattern_floor_can_lower_the_global_one(self, mock_check_cmd, mock_get_size):
        """The old code took max(pattern, global), so a pattern floor could only
        ever raise the bar and small-but-numerous categories stayed invisible."""
        from devclean.config import CruftPattern
        from devclean.scanner import _scan_pattern

        mock_get_size.return_value = 20 * 1024 * 1024  # 20 MB
        pattern = CruftPattern(
            "{home}/.cache/tiny",
            "python",
            "small but worth reporting",
            min_size_mb=10,
        )

        with patch("pathlib.Path.exists", return_value=True):
            candidate = _scan_pattern(pattern, Path.home(), min_size_mb=300)

        assert candidate is not None
        assert candidate.size_bytes == 20 * 1024 * 1024

    @patch("devclean.scanner.get_dir_size")
    @patch("devclean.scanner.check_command_exists")
    def test_unsafe_pattern_lands_in_inspect(self, mock_check_cmd, mock_get_size):
        from devclean.config import CruftPattern
        from devclean.scanner import _scan_pattern

        mock_get_size.return_value = 500 * 1024 * 1024
        pattern = CruftPattern("{home}/x", "docker", "running state", safe=False)

        with patch("pathlib.Path.exists", return_value=True):
            candidate = _scan_pattern(pattern, Path.home(), min_size_mb=100)

        assert candidate is not None
        assert candidate.tier is Tier.INSPECT
        assert candidate.bulk_deletable is False


class TestFindTemporaryDirs:
    @patch("devclean.scanner._get_dir_sizes")
    def test_reports_only_direct_user_owned_directories_as_inspect(self, mock_sizes, tmp_path):
        candidate_dir = tmp_path / "large-build"
        candidate_dir.mkdir()
        (candidate_dir / "nested").mkdir()
        (tmp_path / "plain-file").touch()
        mock_sizes.return_value = {candidate_dir: 200 * 1024 * 1024}

        result = find_temporary_dirs(
            min_size_mb=100,
            roots=[tmp_path],
            owner_uid=candidate_dir.stat().st_uid,
        )

        assert [item.path for item in result] == [candidate_dir]
        assert result[0].tier is Tier.INSPECT
        assert result[0].bulk_deletable is False
        assert "current user" in result[0].evidence[1]
        assert result[0].concerns

    @patch("devclean.scanner._get_dir_sizes")
    def test_skips_other_owners_and_items_below_floor(self, mock_sizes, tmp_path):
        candidate_dir = tmp_path / "small-build"
        candidate_dir.mkdir()
        mock_sizes.return_value = {candidate_dir: 50 * 1024 * 1024}

        assert find_temporary_dirs(100, [tmp_path], candidate_dir.stat().st_uid) == []
        assert find_temporary_dirs(1, [tmp_path], candidate_dir.stat().st_uid + 1) == []

    @patch("pathlib.Path.is_mount", return_value=True)
    @patch("devclean.scanner._get_dir_sizes")
    def test_skips_mounted_filesystems(self, mock_sizes, _mock_is_mount, tmp_path):
        candidate_dir = tmp_path / "mounted-volume"
        candidate_dir.mkdir()

        assert find_temporary_dirs(1, [tmp_path], candidate_dir.stat().st_uid) == []
        mock_sizes.assert_called_once_with([])

"""Tests for the scanner."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devclean.candidates import Candidate, Tier
from devclean.exceptions import ScanError, ScanTimeoutError
from devclean.scanner import (
    ScanResult,
    _get_dir_sizes,
    check_command_exists,
    find_temporary_dirs,
    get_dir_size,
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

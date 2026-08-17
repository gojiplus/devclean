"""Tests for the CLI guardrails.

The point of the tier system is that a batch command cannot sweep up a
directory whose contents were never understood. These tests hold that line.
"""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from devclean.candidates import Candidate, Tier
from devclean.cli import app
from devclean.scanner import ScanResult

runner = CliRunner()


def candidate(**overrides: object) -> Candidate:
    defaults: dict[str, object] = {
        "path": Path("/tmp/devclean-test-target"),
        "size_bytes": 500 * 1024 * 1024,
        "category": "python",
        "description": "test",
        "tier": Tier.AUTO,
        "recovery": "uv sync",
    }
    defaults.update(overrides)
    return Candidate(**defaults)  # type: ignore[arg-type]


class TestTierRefusal:
    """--tier must reject anything that was not content-verified."""

    def test_probe_tier_is_refused(self):
        result = runner.invoke(app, ["clean", "--tier", "probe"])
        assert result.exit_code == 1
        assert "cannot be deleted in bulk" in result.stdout

    def test_inspect_tier_is_refused(self):
        result = runner.invoke(app, ["clean", "--tier", "inspect"])
        assert result.exit_code == 1
        assert "cannot be deleted in bulk" in result.stdout

    def test_unknown_tier_is_refused(self):
        result = runner.invoke(app, ["clean", "--tier", "everything"])
        assert result.exit_code == 1
        assert "Unknown tier" in result.stdout

    def test_path_and_tier_together_are_refused(self):
        result = runner.invoke(app, ["clean", "/tmp/x", "--tier", "auto"])
        assert result.exit_code == 1

    def test_neither_path_nor_tier_is_refused(self):
        result = runner.invoke(app, ["clean"])
        assert result.exit_code == 1


class TestDryRun:
    """--dry-run must never reach the deletion call."""

    @patch("devclean.cli._delete")
    @patch("devclean.cli._run_scan")
    def test_tier_dry_run_deletes_nothing(self, mock_scan, mock_delete):
        mock_scan.return_value = ScanResult(candidates=[candidate()])

        result = runner.invoke(app, ["clean", "--tier", "auto", "--dry-run"])

        assert result.exit_code == 0
        assert "nothing was deleted" in result.stdout
        mock_delete.assert_not_called()

    @patch("devclean.cli._delete")
    def test_path_dry_run_deletes_nothing(self, mock_delete, tmp_path):
        target = tmp_path / "victim"
        target.mkdir()

        result = runner.invoke(app, ["clean", str(target), "--dry-run"])

        assert result.exit_code == 0
        assert "would delete" in result.stdout
        mock_delete.assert_not_called()
        assert target.exists()


class TestTierExecution:
    @patch("devclean.cli._delete")
    @patch("devclean.cli._run_scan")
    def test_candidate_with_concerns_is_not_swept_up(self, mock_scan, mock_delete):
        """A concern demotes to INSPECT, which --tier auto must not touch."""
        flagged = candidate(tier=Tier.AUTO)
        flagged.downgrade("holds something unexpected")
        mock_scan.return_value = ScanResult(candidates=[flagged])

        result = runner.invoke(app, ["clean", "--tier", "auto", "--force"])

        assert result.exit_code == 0
        assert "Nothing in tier" in result.stdout
        mock_delete.assert_not_called()

    @patch("devclean.cli._delete")
    @patch("devclean.cli._run_scan")
    def test_rollup_candidates_are_skipped(self, mock_scan, mock_delete):
        """Roll-ups carry a category name, not a real path, and must not be rm -rf'd."""
        rollup = candidate(path=Path("__pycache__"), member_count=7142, tier=Tier.VERIFIED)
        mock_scan.return_value = ScanResult(candidates=[rollup])

        result = runner.invoke(app, ["clean", "--tier", "verified", "--force"])

        assert result.exit_code == 0
        assert "skipping roll-up" in result.stdout
        mock_delete.assert_not_called()


class TestScanIsReadOnly:
    @patch("devclean.cli._delete")
    @patch("devclean.cli._run_scan")
    def test_scan_never_deletes(self, mock_scan, mock_delete):
        mock_scan.return_value = ScanResult(candidates=[candidate()])

        result = runner.invoke(app, ["scan"])

        assert result.exit_code == 0
        mock_delete.assert_not_called()

    @patch("devclean.cli._run_scan")
    def test_json_output_is_parseable(self, mock_scan):
        import json

        mock_scan.return_value = ScanResult(candidates=[candidate()])

        result = runner.invoke(app, ["scan", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["candidates"][0]["tier"] == "auto"
        assert payload["candidates"][0]["recovery"] == "uv sync"

    @patch("devclean.cli._delete")
    @patch("devclean.cli._run_scan")
    def test_plan_never_deletes(self, mock_scan, mock_delete):
        mock_scan.return_value = ScanResult(candidates=[candidate()])

        result = runner.invoke(app, ["plan"])

        assert result.exit_code == 0
        mock_delete.assert_not_called()

    @patch("devclean.cli._run_scan")
    def test_temp_scan_can_be_disabled(self, mock_scan):
        mock_scan.return_value = ScanResult()

        result = runner.invoke(app, ["scan", "--no-temp"])

        assert result.exit_code == 0
        mock_scan.assert_called_once_with(None, False, False, False, True)

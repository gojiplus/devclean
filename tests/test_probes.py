"""Tests for content probes.

The dist/ cases are built from a real near-miss: ``in-rolls/pai`` kept 3.1 GB of
Dataverse upload archives in ``dist/`` next to a ``pyproject.toml``, with
``dist/`` gitignored so git held no copy. Every structural signal said "build
output". Only the contents said otherwise.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from devclean.candidates import BULK_DELETABLE, Candidate, Tier
from devclean.probes import (
    find_manifest,
    probe_dist_dir,
    probe_node_modules,
    probe_venv,
)


class TestProbeDistDir(unittest.TestCase):
    """probe_dist_dir must separate packaging output from everything else."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dist = Path(self._tmp.name) / "dist"
        self.dist.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _touch(self, *names):
        for name in names:
            (self.dist / name).touch()

    def test_real_wheels_and_sdists_pass(self):
        self._touch(
            "naampy-0.9.0-py3-none-any.whl",
            "naampy-0.9.0.tar.gz",
            "lost_years-0.6.0-py3-none-any.whl",
            "ethnicolr-1.1.0.tar.gz",
        )
        assert probe_dist_dir(self.dist) == []

    def test_hyphenated_project_name_passes(self):
        # The version is the LAST hyphen segment, not the second.
        self._touch(
            "rank-preserving-calibration-0.1.0.tar.gz",
            "rank-preserving-calibration-0.1.0-py3-none-any.whl",
        )
        assert probe_dist_dir(self.dist) == []

    def test_pep440_dev_and_local_versions_pass(self):
        # Real filename from indicate/dist.
        self._touch("indicate-0.3.0.post54.dev0+f36e76b.tar.gz")
        assert probe_dist_dir(self.dist) == []

    def test_empty_dist_has_no_concerns(self):
        assert probe_dist_dir(self.dist) == []

    def test_dotfiles_are_ignored(self):
        """Every real dist/ carries a .gitignore, and macOS adds .DS_Store.

        Flagging them would make every genuine dist/ INSPECT, which would train
        the reader to skip the concerns list entirely.
        """
        self._touch(".gitignore", ".DS_Store", "naampy-0.9.0.tar.gz")
        assert probe_dist_dir(self.dist) == []

    def test_dotfiles_do_not_mask_a_real_data_file(self):
        self._touch(".gitignore", "dataverse_hindi_source.tar.gz")
        concerns = probe_dist_dir(self.dist)
        assert len(concerns) == 1
        assert "dataverse_hindi_source.tar.gz" in concerns[0]

    def test_pai_dist_shape_is_flagged(self):
        """The exact contents that a pyproject.toml guard would have deleted."""
        self._touch(
            "pai_2022-2023_html.tar.gz",
            "pai_2023-2024_html.tar.gz",
            "pai_2022-2023_data.tar.gz",
            "pai_2023-2024_data.tar.gz",
            "DATAVERSE_UPLOAD.md",
        )
        (self.dist / "_stage").mkdir()

        concerns = probe_dist_dir(self.dist)

        joined = " ".join(concerns)
        assert "_stage" in joined
        assert "DATAVERSE_UPLOAD.md" in joined
        # All four data tarballs must be called out, not just the first.
        for name in (
            "pai_2022-2023_html.tar.gz",
            "pai_2023-2024_html.tar.gz",
            "pai_2022-2023_data.tar.gz",
            "pai_2023-2024_data.tar.gz",
        ):
            assert name in joined

    def test_year_like_segment_is_not_a_version(self):
        """`pai_2022-2023_html` ends in a digit-leading segment but is not a version.

        A naive "last segment starts with a digit" rule passes this and deletes
        the file. The PEP 440 check is what rejects the underscore.
        """
        self._touch("pai_2022-2023_html.tar.gz")
        assert len(probe_dist_dir(self.dist)) == 1

    def test_candidate_downgrades_to_inspect(self):
        """Concerns must actually move the candidate out of bulk deletion."""
        self._touch("pai_2022-2023_html.tar.gz")
        candidate = Candidate(
            path=self.dist,
            size_bytes=3_100_000_000,
            category="python",
            description="Build artifacts",
            tier=Tier.PROBE,
            recovery="python -m build",
        )
        assert Tier.PROBE not in BULK_DELETABLE

        candidate.downgrade(*probe_dist_dir(self.dist))

        assert candidate.tier == Tier.INSPECT
        assert not candidate.bulk_deletable

    def test_downgrade_is_monotonic(self):
        candidate = Candidate(
            path=self.dist,
            size_bytes=1,
            category="python",
            description="x",
            tier=Tier.VERIFIED,
            recovery="",
        )
        candidate.downgrade("something odd")
        candidate.downgrade()  # no concerns must not restore the tier
        assert candidate.tier == Tier.INSPECT
        assert not candidate.bulk_deletable


class TestProbeVenv(unittest.TestCase):
    """The pyvenv.cfg marker is the only thing separating a venv from a package."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_real_venv_passes(self):
        venv = self.root / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").touch()
        assert probe_venv(venv) == []

    def test_next_env_package_is_rejected(self):
        """node_modules/@next/env matches the `env` name pattern but is a package.

        This path was found on a real machine during a cleanup; without the
        marker check it would have been deleted.
        """
        pkg = self.root / "node_modules" / "@next" / "env"
        pkg.mkdir(parents=True)
        (pkg / "package.json").touch()

        concerns = probe_venv(pkg)

        assert len(concerns) == 1
        assert "pyvenv.cfg" in concerns[0]


class TestProbeNodeModules(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_with_package_json_passes(self):
        (self.root / "package.json").touch()
        nm = self.root / "node_modules"
        nm.mkdir()
        assert probe_node_modules(nm) == []

    def test_orphan_node_modules_is_flagged(self):
        nm = self.root / "node_modules"
        nm.mkdir()
        assert len(probe_node_modules(nm)) == 1


class TestFindManifest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_finds_lockfile(self):
        (self.root / "uv.lock").touch()
        assert find_manifest(self.root) == "uv.lock"

    def test_none_when_absent(self):
        assert find_manifest(self.root) is None


if __name__ == "__main__":
    unittest.main()

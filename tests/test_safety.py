"""Tests for the deletion guard.

Covers the case the previous implementation got wrong: it refused any path with
a protected name anywhere among its components, which ruled out every
virtualenv under ``~/Documents/GitHub`` — the exact thing the tool exists to
delete.
"""

from pathlib import Path

import pytest

from devclean.exceptions import PathNotFoundError, UnsafePathError
from devclean.safety import assert_safe_to_delete, is_safe_to_delete, protected_paths


class TestProtectedPaths:
    def test_includes_home_and_system_roots(self):
        paths = protected_paths()
        assert Path.home() in paths
        assert Path("/") in paths
        assert Path("/System") in paths

    def test_includes_extras_from_config(self, tmp_path):
        assert tmp_path.resolve() in protected_paths([str(tmp_path)])

    def test_invalid_extras_are_skipped_not_fatal(self):
        assert protected_paths(["\x00not-a-path"])


class TestAssertSafeToDelete:
    def test_missing_path_raises(self):
        with pytest.raises(PathNotFoundError):
            assert_safe_to_delete(Path("/this/does/not/exist"))

    def test_home_itself_is_refused(self):
        with pytest.raises(UnsafePathError, match="protected"):
            assert_safe_to_delete(Path.home())

    def test_root_is_refused(self):
        with pytest.raises(UnsafePathError):
            assert_safe_to_delete(Path("/"))

    def test_shared_temp_root_is_refused(self):
        with pytest.raises(UnsafePathError, match="protected"):
            assert_safe_to_delete(Path("/private/tmp"))

    def test_user_owned_child_of_temp_root_is_allowed(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        temp_root = tmp_path / "system-temp"
        candidate = temp_root / "build-output"
        candidate.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        monkeypatch.setattr("devclean.safety.temporary_roots", lambda: [temp_root])

        with pytest.raises(UnsafePathError, match="protected"):
            assert_safe_to_delete(temp_root)
        assert_safe_to_delete(candidate)

    def test_other_paths_outside_home_are_refused(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        outside = tmp_path / "outside" / "candidate"
        fake_home.mkdir()
        outside.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        monkeypatch.setattr(
            "devclean.safety.temporary_roots", lambda: [tmp_path / "elsewhere"]
        )

        with pytest.raises(UnsafePathError, match="outside your home"):
            assert_safe_to_delete(outside)

    def test_mounted_filesystem_is_refused(self, tmp_path, monkeypatch):
        candidate = tmp_path / "mounted-volume"
        candidate.mkdir()
        monkeypatch.setattr(Path, "is_mount", lambda self: self == candidate)

        with pytest.raises(UnsafePathError, match="mounted filesystem"):
            assert_safe_to_delete(candidate)

    def test_documents_itself_is_refused(self):
        documents = Path.home() / "Documents"
        if not documents.exists():
            pytest.skip("no ~/Documents on this machine")
        with pytest.raises(UnsafePathError, match="protected"):
            assert_safe_to_delete(documents)

    def test_nested_path_under_documents_is_allowed(self, tmp_path, monkeypatch):
        """A venv lives at ~/Documents/GitHub/<project>/.venv and must be deletable.

        The old rule rejected any path containing 'Documents' as a component,
        which made the tool unable to clean the directory developers actually
        keep code in.
        """
        fake_home = tmp_path / "home"
        venv = fake_home / "Documents" / "GitHub" / "project" / ".venv"
        venv.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        assert_safe_to_delete(venv)  # must not raise

    def test_shallow_path_needs_explicit_naming(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        shallow = fake_home / ".cache"
        shallow.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        with pytest.raises(UnsafePathError, match="directly under"):
            assert_safe_to_delete(shallow)

        # ...but naming it explicitly is allowed.
        assert_safe_to_delete(shallow, require_depth=False)

    def test_parent_of_home_is_never_deletable(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home" / "user"
        fake_home.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        with pytest.raises(UnsafePathError, match="parent of your home"):
            assert_safe_to_delete(tmp_path / "home", require_depth=False)

    def test_configured_protected_path_is_honored(self, tmp_path, monkeypatch):
        """A deletion caller must not be able to ignore user config."""
        fake_home = tmp_path / "home"
        keep = fake_home / "Documents" / "GitHub" / "keep-me"
        keep.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        assert_safe_to_delete(keep)  # allowed by default

        with pytest.raises(UnsafePathError, match="protected"):
            assert_safe_to_delete(keep, extra_protected=[str(keep)])


class TestIsSafeToDelete:
    def test_boolean_form_swallows_the_exception(self):
        assert is_safe_to_delete(Path.home()) is False
        assert is_safe_to_delete(Path("/does/not/exist")) is False

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

    def test_configured_protected_path_is_honoured(self, tmp_path, monkeypatch):
        """The agent path used to ignore user config entirely."""
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

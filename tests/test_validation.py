"""Tests for validation module."""

import pytest

from devclean.exceptions import UnsafePathError
from devclean.validation import sanitize_path


class TestSanitizePath:
    """Tests for sanitize_path function."""

    def test_sanitize_valid_path(self):
        """Test sanitizing a valid path."""
        path = sanitize_path("~/Documents")
        assert path.is_absolute()
        assert "Documents" in str(path)

    def test_sanitize_empty_path(self):
        """Test sanitizing empty path raises error."""
        with pytest.raises(UnsafePathError, match="Path cannot be empty"):
            sanitize_path("")

        with pytest.raises(UnsafePathError, match="Path cannot be empty"):
            sanitize_path("   ")

    def test_sanitize_dangerous_patterns(self):
        """Test that dangerous patterns are rejected."""
        dangerous_paths = [
            "../../../etc/passwd",
            "/home/user/../../../etc",
            "path;rm -rf /",
            "path|cat /etc/passwd",
            "path&whoami",
            "path$(id)",
            "path`id`",
            "path\nwhoami",
            "path\rls",
        ]

        for dangerous_path in dangerous_paths:
            with pytest.raises(UnsafePathError, match="unsafe pattern"):
                sanitize_path(dangerous_path)

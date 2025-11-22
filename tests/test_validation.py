"""Tests for validation module."""

from pathlib import Path

import pytest

from devclean.exceptions import PathNotFoundError, UnsafePathError
from devclean.validation import (
    is_safe_directory_name,
    sanitize_path,
    validate_api_key,
    validate_directory_for_deletion,
    validate_size_parameter,
    validate_timeout_parameter,
)


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


class TestValidateDirectoryForDeletion:
    """Tests for validate_directory_for_deletion function."""

    def test_validate_nonexistent_path(self):
        """Test validating non-existent path."""
        with pytest.raises(PathNotFoundError):
            validate_directory_for_deletion(Path("/this/does/not/exist"))

    def test_validate_protected_paths(self):
        """Test that protected paths are rejected."""
        home = Path.home()
        protected_paths = [
            home,
            home / "Documents",
            home / "Desktop",
            Path("/"),
            Path("/System"),
        ]

        for protected_path in protected_paths:
            if protected_path.exists():
                with pytest.raises(UnsafePathError, match="protected"):
                    validate_directory_for_deletion(protected_path)


class TestValidateSizeParameter:
    """Tests for validate_size_parameter function."""

    def test_valid_sizes(self):
        """Test valid size parameters."""
        valid_sizes = [0, 1, 100, 1000, 10000]
        for size in valid_sizes:
            validate_size_parameter(size)  # Should not raise

    def test_invalid_sizes(self):
        """Test invalid size parameters."""
        with pytest.raises(ValueError, match="must be an integer"):
            validate_size_parameter("100")

        with pytest.raises(ValueError, match="must be non-negative"):
            validate_size_parameter(-1)

        with pytest.raises(ValueError, match="less than 1TB"):
            validate_size_parameter(2000000)


class TestValidateTimeoutParameter:
    """Tests for validate_timeout_parameter function."""

    def test_valid_timeouts(self):
        """Test valid timeout parameters."""
        valid_timeouts = [1, 30, 60, 300, 3600]
        for timeout in valid_timeouts:
            validate_timeout_parameter(timeout)  # Should not raise

    def test_invalid_timeouts(self):
        """Test invalid timeout parameters."""
        with pytest.raises(ValueError, match="must be an integer"):
            validate_timeout_parameter("30")

        with pytest.raises(ValueError, match="must be positive"):
            validate_timeout_parameter(0)

        with pytest.raises(ValueError, match="less than 1 hour"):
            validate_timeout_parameter(3700)


class TestValidateApiKey:
    """Tests for validate_api_key function."""

    def test_valid_api_key(self):
        """Test valid API key format."""
        valid_key = "sk-ant-1234567890abcdef"
        validate_api_key(valid_key)  # Should not raise

    def test_invalid_api_keys(self):
        """Test invalid API key formats."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_api_key("")

        with pytest.raises(ValueError, match="Invalid API key format"):
            validate_api_key("invalid-key")

        with pytest.raises(ValueError, match="too short"):
            validate_api_key("sk-ant-123")


class TestIsSafeDirectoryName:
    """Tests for is_safe_directory_name function."""

    def test_safe_names(self):
        """Test safe directory names."""
        safe_names = [
            "project",
            "my-project",
            "my_project",
            "Project123",
            "node_modules",
            ".venv",
        ]

        for name in safe_names:
            assert is_safe_directory_name(name)

    def test_unsafe_names(self):
        """Test unsafe directory names."""
        unsafe_names = [
            "",
            " ",
            ".",
            "..",
            "CON",
            "PRN",
            "project/subdir",
            "project\\subdir",
            "project:name",
            "project*",
            "project?",
            'project"name',
            "project<name>",
            "project|name",
            "project\nname",
            "project\tname",
            " project",
            "project ",
        ]

        for name in unsafe_names:
            assert not is_safe_directory_name(name), f"Name should be unsafe: {name}"

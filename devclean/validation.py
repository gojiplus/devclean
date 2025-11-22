"""Input validation and path sanitization for DevClean."""

import os
import re
from pathlib import Path
from typing import List, Optional

from .exceptions import PathNotFoundError, UnsafePathError


def sanitize_path(path_str: str) -> Path:
    """Sanitize and validate a path string.

    Args:
        path_str: Raw path string from user input

    Returns:
        Sanitized Path object

    Raises:
        UnsafePathError: If path contains unsafe elements
        PathNotFoundError: If path doesn't exist when it should

    """
    if not path_str or not path_str.strip():
        raise UnsafePathError("Path cannot be empty")

    # Remove leading/trailing whitespace
    path_str = path_str.strip()

    # Check for dangerous patterns
    dangerous_patterns = [
        r"\.\./",  # Directory traversal
        r"/\.\.",  # Directory traversal
        r"^\.\.",  # Relative traversal
        r";",  # Command injection
        r"\|",  # Command injection
        r"&",  # Command injection
        r"\$\(",  # Command substitution
        r"`",  # Command substitution
        r"\n",  # Newlines
        r"\r",  # Carriage returns
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, path_str):
            raise UnsafePathError(f"Path contains unsafe pattern: {pattern}")

    # Convert to Path and resolve
    try:
        path = Path(path_str).expanduser().resolve()
    except (OSError, RuntimeError) as e:
        raise UnsafePathError(f"Invalid path: {e}") from e

    # Additional safety checks
    if not path.is_absolute():
        raise UnsafePathError("Path must be absolute after resolution")

    return path


def validate_directory_for_scanning(path: Path) -> None:
    """Validate that a directory is safe to scan.

    Args:
        path: Directory path to validate

    Raises:
        PathNotFoundError: If directory doesn't exist
        UnsafePathError: If directory is unsafe to scan

    """
    if not path.exists():
        raise PathNotFoundError(f"Directory does not exist: {path}")

    if not path.is_dir():
        raise UnsafePathError(f"Path is not a directory: {path}")

    # Check if we can read the directory
    if not os.access(path, os.R_OK):
        raise UnsafePathError(f"Cannot read directory: {path}")


def validate_directory_for_deletion(path: Path, protected_paths: list[str] | None = None) -> None:
    """Validate that a directory is safe to delete.

    Args:
        path: Directory path to validate
        protected_paths: Additional protected paths beyond defaults

    Raises:
        UnsafePathError: If directory is unsafe to delete
        PathNotFoundError: If directory doesn't exist

    """
    if not path.exists():
        raise PathNotFoundError(f"Path does not exist: {path}")

    # Default protected paths
    home = Path.home()
    default_protected = [
        home,
        home / "Documents",
        home / "Desktop",
        home / "Downloads",
        home / "Pictures",
        home / "Music",
        home / "Movies",
        Path("/"),
        Path("/System"),
        Path("/Applications"),
        Path("/usr"),
        Path("/bin"),
        Path("/sbin"),
        Path("/lib"),
        Path("/etc"),
    ]

    # Add any additional protected paths
    if protected_paths:
        for pp in protected_paths:
            try:
                default_protected.append(Path(pp).expanduser().resolve())
            except Exception:
                continue  # Skip invalid paths

    # Check if path is protected
    for protected_path in default_protected:
        try:
            if path == protected_path:
                raise UnsafePathError(f"Cannot delete protected path: {path}")

            # Check if path is under a protected directory
            if path.is_relative_to(protected_path):
                # Allow deletion of subdirectories of home that are not special
                if protected_path == home:
                    # Check if it's a special subdirectory
                    special_subdirs = {
                        "Documents",
                        "Desktop",
                        "Downloads",
                        "Pictures",
                        "Music",
                        "Movies",
                    }
                    if path.name in special_subdirs or any(
                        part in special_subdirs for part in path.parts
                    ):
                        raise UnsafePathError(f"Cannot delete special directory: {path}")
                else:
                    raise UnsafePathError(
                        f"Cannot delete path under protected directory {protected_path}: {path}"
                    )

        except ValueError:
            # is_relative_to can raise ValueError on some platforms/path combinations
            continue

    # Check that we're not deleting something that contains the home directory
    try:
        if home.is_relative_to(path):
            raise UnsafePathError(f"Cannot delete path that contains home directory: {path}")
    except ValueError:
        pass


def validate_size_parameter(size_mb: int) -> None:
    """Validate a size parameter.

    Args:
        size_mb: Size in megabytes

    Raises:
        ValueError: If size is invalid

    """
    if not isinstance(size_mb, int):
        raise ValueError("Size must be an integer")

    if size_mb < 0:
        raise ValueError("Size must be non-negative")

    if size_mb > 1000000:  # 1TB limit
        raise ValueError("Size must be less than 1TB")


def validate_timeout_parameter(timeout: int) -> None:
    """Validate a timeout parameter.

    Args:
        timeout: Timeout in seconds

    Raises:
        ValueError: If timeout is invalid

    """
    if not isinstance(timeout, int):
        raise ValueError("Timeout must be an integer")

    if timeout < 1:
        raise ValueError("Timeout must be positive")

    if timeout > 3600:  # 1 hour limit
        raise ValueError("Timeout must be less than 1 hour")


def validate_api_key(api_key: str) -> None:
    """Validate an Anthropic API key format.

    Args:
        api_key: API key to validate

    Raises:
        ValueError: If API key format is invalid

    """
    if not api_key or not api_key.strip():
        raise ValueError("API key cannot be empty")

    # Basic format validation for Anthropic API keys
    if not api_key.startswith("sk-ant-"):
        raise ValueError("Invalid API key format")

    if len(api_key) < 20:
        raise ValueError("API key too short")


def is_safe_directory_name(name: str) -> bool:
    """Check if a directory name is safe.

    Args:
        name: Directory name to check

    Returns:
        True if name is safe, False otherwise

    """
    if not name or not name.strip():
        return False

    # Check for dangerous characters
    dangerous_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|", "\n", "\r", "\t"]
    if any(char in name for char in dangerous_chars):
        return False

    # Check for reserved names on various systems
    reserved_names = {
        "CON",
        "PRN",
        "AUX",
        "NUL",  # Windows reserved
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }

    if name.upper() in reserved_names:
        return False

    # Don't allow names that are just dots or start/end with spaces
    if name in {".", ".."}:
        return False

    if name.startswith(" ") or name.endswith(" "):
        return False

    return True

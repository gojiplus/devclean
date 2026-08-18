"""Input validation and path sanitization for DevClean."""

from __future__ import annotations

import re
from pathlib import Path

from .exceptions import UnsafePathError


def sanitize_path(path_str: str) -> Path:
    """Sanitize and validate a path string.

    Args:
        path_str: Raw path string from user input

    Returns:
        Sanitized Path object

    Raises:
        UnsafePathError: If path contains unsafe elements

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

"""Configuration management for DevClean."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import toml

from .exceptions import ConfigurationError


@dataclass
class ScanSettings:
    """Settings for disk scanning operations."""

    min_size_mb: int = 100
    include_venvs: bool = True
    include_node_modules: bool = True
    timeout_seconds: int = 30
    max_depth: int = 4
    parallel_workers: int = 4


@dataclass
class DisplaySettings:
    """Settings for output display."""

    show_progress: bool = True
    color_output: bool = True
    table_format: str = "rich"
    size_units: str = "auto"  # auto, mb, gb


@dataclass
class SafetySettings:
    """Settings for safety and confirmations."""

    require_confirmation: bool = True
    protected_paths: list[str] = field(
        default_factory=lambda: [
            "~",
            "~/Documents",
            "~/Desktop",
            "~/Downloads",
            "~/Pictures",
            "~/Music",
            "~/Movies",
            "/",
            "/System",
            "/Applications",
        ]
    )
    never_delete_patterns: list[str] = field(default_factory=list)
    always_safe_patterns: list[str] = field(default_factory=list)


@dataclass
class DevCleanConfig:
    """Main configuration for DevClean."""

    scan: ScanSettings = field(default_factory=ScanSettings)
    display: DisplaySettings = field(default_factory=DisplaySettings)
    safety: SafetySettings = field(default_factory=SafetySettings)

    # Additional paths to search for projects
    additional_search_paths: list[str] = field(default_factory=list)

    # Exclusion patterns
    exclude_paths: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)

    # API settings
    anthropic_api_key: str | None = None


def get_config_path() -> Path:
    """Get the path to the configuration file."""
    # Check for config in current directory first
    local_config = Path.cwd() / ".devclean.toml"
    if local_config.exists():
        return local_config

    # Then check user's home directory
    home_config = Path.home() / ".devclean.toml"
    if home_config.exists():
        return home_config

    # Return default location if none exists
    return home_config


def load_config(config_path: Path | None = None) -> DevCleanConfig:
    """Load configuration from file.

    Args:
        config_path: Path to config file. If None, uses default locations.

    Returns:
        DevCleanConfig instance

    Raises:
        ConfigurationError: If config file exists but is invalid

    """
    if config_path is None:
        config_path = get_config_path()

    # Start with defaults
    config = DevCleanConfig()

    if not config_path.exists():
        return config

    try:
        with open(config_path, encoding="utf-8") as f:
            data = toml.load(f)

        # Update config with values from file
        if "scan" in data:
            scan_data = data["scan"]
            config.scan = ScanSettings(
                min_size_mb=scan_data.get("min_size_mb", config.scan.min_size_mb),
                include_venvs=scan_data.get("include_venvs", config.scan.include_venvs),
                include_node_modules=scan_data.get(
                    "include_node_modules", config.scan.include_node_modules
                ),
                timeout_seconds=scan_data.get("timeout_seconds", config.scan.timeout_seconds),
                max_depth=scan_data.get("max_depth", config.scan.max_depth),
                parallel_workers=scan_data.get("parallel_workers", config.scan.parallel_workers),
            )

        if "display" in data:
            display_data = data["display"]
            config.display = DisplaySettings(
                show_progress=display_data.get("show_progress", config.display.show_progress),
                color_output=display_data.get("color_output", config.display.color_output),
                table_format=display_data.get("table_format", config.display.table_format),
                size_units=display_data.get("size_units", config.display.size_units),
            )

        if "safety" in data:
            safety_data = data["safety"]
            config.safety = SafetySettings(
                require_confirmation=safety_data.get(
                    "require_confirmation", config.safety.require_confirmation
                ),
                protected_paths=safety_data.get("protected_paths", config.safety.protected_paths),
                never_delete_patterns=safety_data.get(
                    "never_delete_patterns", config.safety.never_delete_patterns
                ),
                always_safe_patterns=safety_data.get(
                    "always_safe_patterns", config.safety.always_safe_patterns
                ),
            )

        # Top-level settings
        config.additional_search_paths = data.get(
            "additional_search_paths", config.additional_search_paths
        )
        config.exclude_paths = data.get("exclude_paths", config.exclude_paths)
        config.exclude_patterns = data.get("exclude_patterns", config.exclude_patterns)
        config.anthropic_api_key = data.get("anthropic_api_key", config.anthropic_api_key)

        return config

    except Exception as e:
        raise ConfigurationError(f"Failed to load config from {config_path}: {e}") from e


def save_config(config: DevCleanConfig, config_path: Path | None = None) -> None:
    """Save configuration to file.

    Args:
        config: Configuration to save
        config_path: Path to save to. If None, uses default location.

    Raises:
        ConfigurationError: If unable to save config

    """
    if config_path is None:
        config_path = get_config_path()

    try:
        # Convert config to dict for TOML
        data = {
            "scan": {
                "min_size_mb": config.scan.min_size_mb,
                "include_venvs": config.scan.include_venvs,
                "include_node_modules": config.scan.include_node_modules,
                "timeout_seconds": config.scan.timeout_seconds,
                "max_depth": config.scan.max_depth,
                "parallel_workers": config.scan.parallel_workers,
            },
            "display": {
                "show_progress": config.display.show_progress,
                "color_output": config.display.color_output,
                "table_format": config.display.table_format,
                "size_units": config.display.size_units,
            },
            "safety": {
                "require_confirmation": config.safety.require_confirmation,
                "protected_paths": config.safety.protected_paths,
                "never_delete_patterns": config.safety.never_delete_patterns,
                "always_safe_patterns": config.safety.always_safe_patterns,
            },
            "additional_search_paths": config.additional_search_paths,
            "exclude_paths": config.exclude_paths,
            "exclude_patterns": config.exclude_patterns,
        }

        # Don't save API key to file for security
        if config.anthropic_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            # Only save if not already in environment
            pass

        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            toml.dump(data, f)

    except Exception as e:
        raise ConfigurationError(f"Failed to save config to {config_path}: {e}") from e


def create_sample_config(config_path: Path | None = None) -> None:
    """Create a sample configuration file.

    Args:
        config_path: Path to save sample config. If None, uses default location.

    """
    if config_path is None:
        config_path = Path.home() / ".devclean.toml"

    sample_content = """# DevClean Configuration File
# See https://github.com/user/devclean for documentation

[scan]
# Minimum size in MB for items to be reported
min_size_mb = 100

# Whether to scan for Python virtual environments
include_venvs = true

# Whether to scan for node_modules directories
include_node_modules = true

# Timeout in seconds for directory size calculations
timeout_seconds = 30

# Maximum directory depth to search
max_depth = 4

# Number of parallel workers for scanning
parallel_workers = 4

[display]
# Show progress bars during operations
show_progress = true

# Use colored output
color_output = true

# Table format: "rich", "simple", "json"
table_format = "rich"

# Size display units: "auto", "mb", "gb"
size_units = "auto"

[safety]
# Always require confirmation before deletion
require_confirmation = true

# Paths that are never safe to delete
protected_paths = [
    "~", "~/Documents", "~/Desktop", "~/Downloads",
    "~/Pictures", "~/Music", "~/Movies", "/", "/System", "/Applications"
]

# Patterns that should never be deleted
never_delete_patterns = []

# Patterns that are always safe to delete
always_safe_patterns = []

# Additional directories to search for projects
additional_search_paths = [
    "~/workspace",
    "~/coding"
]

# Paths to exclude from scanning
exclude_paths = [
    "~/sensitive-data"
]

# Patterns to exclude from scanning
exclude_patterns = [
    "*.sensitive",
    "private-*"
]
"""

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(sample_content)
    except Exception as e:
        raise ConfigurationError(f"Failed to create sample config at {config_path}: {e}") from e


def get_api_key_from_config_or_env(config: DevCleanConfig) -> str | None:
    """Get API key from config or environment.

    Args:
        config: DevClean configuration

    Returns:
        API key if found, None otherwise

    """
    # Environment variable takes precedence
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return api_key

    # Fall back to config file
    return config.anthropic_api_key

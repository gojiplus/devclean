"""Configuration management for DevClean."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .exceptions import ConfigurationError


@dataclass
class ScanSettings:
    """Settings for disk scanning operations."""

    min_size_mb: int = 100
    include_venvs: bool = True
    include_node_modules: bool = True
    include_system_artifacts: bool = True
    include_temporary_dirs: bool = True
    timeout_seconds: int = 120
    max_depth: int = 8


@dataclass
class SafetySettings:
    """Settings for deletion safety."""

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


@dataclass
class DevCleanConfig:
    """Main configuration for DevClean."""

    scan: ScanSettings = field(default_factory=ScanSettings)
    safety: SafetySettings = field(default_factory=SafetySettings)

    # Additional paths to search for projects
    additional_search_paths: list[str] = field(default_factory=list)


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
        with open(config_path, "rb") as f:
            data = tomllib.load(f)

        # Update config with values from file
        if "scan" in data:
            scan_data = data["scan"]
            config.scan = ScanSettings(
                min_size_mb=scan_data.get("min_size_mb", config.scan.min_size_mb),
                include_venvs=scan_data.get("include_venvs", config.scan.include_venvs),
                include_node_modules=scan_data.get(
                    "include_node_modules", config.scan.include_node_modules
                ),
                include_system_artifacts=scan_data.get(
                    "include_system_artifacts", config.scan.include_system_artifacts
                ),
                include_temporary_dirs=scan_data.get(
                    "include_temporary_dirs", config.scan.include_temporary_dirs
                ),
                timeout_seconds=scan_data.get(
                    "timeout_seconds", config.scan.timeout_seconds
                ),
                max_depth=scan_data.get("max_depth", config.scan.max_depth),
            )

        if "safety" in data:
            safety_data = data["safety"]
            config.safety = SafetySettings(
                protected_paths=safety_data.get(
                    "protected_paths", config.safety.protected_paths
                ),
            )

        # Top-level settings
        config.additional_search_paths = data.get(
            "additional_search_paths", config.additional_search_paths
        )

        return config

    except Exception as e:
        raise ConfigurationError(
            f"Failed to load config from {config_path}: {e}"
        ) from e


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

    # tomllib only reads TOML; tomlkit round-trips it with comments,
    # ordering, and unmanaged keys intact.
    import tomlkit

    try:
        if config_path.exists():
            document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
        else:
            document = tomlkit.document()

        scan = document.setdefault("scan", tomlkit.table())
        scan["min_size_mb"] = config.scan.min_size_mb
        scan["include_venvs"] = config.scan.include_venvs
        scan["include_node_modules"] = config.scan.include_node_modules
        scan["include_system_artifacts"] = config.scan.include_system_artifacts
        scan["include_temporary_dirs"] = config.scan.include_temporary_dirs
        scan["timeout_seconds"] = config.scan.timeout_seconds
        scan["max_depth"] = config.scan.max_depth

        safety = document.setdefault("safety", tomlkit.table())
        safety["protected_paths"] = config.safety.protected_paths

        document["additional_search_paths"] = config.additional_search_paths

        # Serialize before touching the file, and replace atomically, so a
        # serialization error or a crash mid-write cannot leave the user's
        # config truncated.
        serialized = tomlkit.dumps(document)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        staging_path = config_path.with_name(config_path.name + ".tmp")
        staging_path.write_text(serialized, encoding="utf-8")
        staging_path.replace(config_path)

    except Exception as e:
        raise ConfigurationError(f"Failed to save config to {config_path}: {e}") from e


def create_sample_config(config_path: Path | None = None) -> None:
    """Create a sample configuration file.

    Args:
        config_path: Path to save sample config. If None, uses default location.

    Raises:
        ConfigurationError: If the sample config cannot be written.

    """
    if config_path is None:
        config_path = Path.home() / ".devclean.toml"

    sample_content = """# DevClean Configuration File
# See https://github.com/gojiplus/devclean for documentation

# Additional directories to search for projects
additional_search_paths = [
    "~/workspace",
    "~/coding"
]

[scan]
# Minimum size in MB for items to be reported
min_size_mb = 100

# Whether to scan for Python virtual environments
include_venvs = true

# Whether to scan for node_modules directories
include_node_modules = true

# Whether to inspect versioned system toolchains and package-manager leftovers
include_system_artifacts = true

# Whether to scan macOS temporary directories
include_temporary_dirs = true

# Timeout in seconds for directory size calculations
timeout_seconds = 120

# Maximum directory depth to search
max_depth = 8

[safety]
# Paths that are never safe to delete
protected_paths = [
    "~", "~/Documents", "~/Desktop", "~/Downloads",
    "~/Pictures", "~/Music", "~/Movies", "/", "/System", "/Applications"
]
"""

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(sample_content)
    except Exception as e:
        raise ConfigurationError(
            f"Failed to create sample config at {config_path}: {e}"
        ) from e

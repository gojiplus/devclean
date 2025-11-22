"""Custom exceptions for DevClean."""


class DevCleanError(Exception):
    """Base exception for DevClean operations."""

    pass


class ScanError(DevCleanError):
    """Error during disk scanning operations."""

    pass


class PermissionError(DevCleanError):
    """Error due to insufficient permissions."""

    pass


class PathNotFoundError(DevCleanError):
    """Error when a specified path does not exist."""

    pass


class UnsafePathError(DevCleanError):
    """Error when attempting to operate on a protected/unsafe path."""

    pass


class ToolNotFoundError(DevCleanError):
    """Error when a required command-line tool is not found."""

    pass


class ConfigurationError(DevCleanError):
    """Error in configuration file or settings."""

    pass


class DeletionError(DevCleanError):
    """Error during file/directory deletion."""

    def __init__(self, message: str, path: str, error_code: str | None = None) -> None:
        super().__init__(message)
        self.path = path
        self.error_code = error_code


class TimeoutError(DevCleanError):
    """Error when an operation times out."""

    pass

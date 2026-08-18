"""DevClean - evidence-driven disk cleanup for developers on macOS."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("devclean")
except PackageNotFoundError:
    __version__ = "0.0.0"

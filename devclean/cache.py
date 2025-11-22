"""Caching utilities for DevClean operations."""

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .exceptions import ConfigurationError


@dataclass
class CacheEntry:
    """A cached scan result entry."""

    timestamp: float
    size_bytes: int
    exists: bool
    error: str | None = None


class ScanCache:
    """Cache for directory scan results to avoid repeated expensive operations."""

    def __init__(self, cache_file: Path | None = None, ttl_seconds: int = 3600):
        """Initialize the scan cache.

        Args:
            cache_file: Path to cache file. If None, uses default location.
            ttl_seconds: Time-to-live for cache entries in seconds.

        """
        self.ttl_seconds = ttl_seconds
        self.cache_file = cache_file or self._get_default_cache_file()
        self._cache: dict[str, CacheEntry] = {}
        self._load_cache()

    def _get_default_cache_file(self) -> Path:
        """Get the default cache file location."""
        cache_dir = Path.home() / ".cache" / "devclean"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / "scan_cache.json"

    def _load_cache(self) -> None:
        """Load cache from disk."""
        if not self.cache_file.exists():
            return

        try:
            with open(self.cache_file, encoding="utf-8") as f:
                data = json.load(f)

            # Convert dict back to CacheEntry objects
            for key, value in data.items():
                if isinstance(value, dict):
                    self._cache[key] = CacheEntry(**value)

        except Exception as e:
            # If cache is corrupted, start fresh
            self._cache = {}

    def _save_cache(self) -> None:
        """Save cache to disk."""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)

            # Convert CacheEntry objects to dicts for JSON serialization
            data = {}
            for key, entry in self._cache.items():
                data[key] = asdict(entry)

            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        except Exception:
            # Don't fail if we can't save cache
            pass

    def _is_expired(self, entry: CacheEntry) -> bool:
        """Check if a cache entry is expired."""
        return time.time() - entry.timestamp > self.ttl_seconds

    def _clean_expired(self) -> None:
        """Remove expired entries from cache."""
        expired_keys = [key for key, entry in self._cache.items() if self._is_expired(entry)]

        for key in expired_keys:
            del self._cache[key]

    def get(self, path: Path) -> CacheEntry | None:
        """Get cached information for a path.

        Args:
            path: Directory path to check

        Returns:
            CacheEntry if found and not expired, None otherwise

        """
        key = str(path.resolve())
        entry = self._cache.get(key)

        if entry is None:
            return None

        if self._is_expired(entry):
            del self._cache[key]
            return None

        return entry

    def set(self, path: Path, size_bytes: int, exists: bool, error: str | None = None) -> None:
        """Cache information for a path.

        Args:
            path: Directory path
            size_bytes: Size in bytes (0 if error or doesn't exist)
            exists: Whether the path exists
            error: Error message if any

        """
        key = str(path.resolve())

        entry = CacheEntry(
            timestamp=time.time(),
            size_bytes=size_bytes,
            exists=exists,
            error=error,
        )

        self._cache[key] = entry

        # Periodically clean expired entries
        if len(self._cache) % 100 == 0:
            self._clean_expired()

    def invalidate(self, path: Path) -> None:
        """Invalidate cache entry for a path.

        Args:
            path: Path to invalidate

        """
        key = str(path.resolve())
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        self._save_cache()

    def save(self) -> None:
        """Save cache to disk."""
        self._clean_expired()
        self._save_cache()

    def stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics

        """
        total_entries = len(self._cache)

        # Count by status
        exists_count = sum(1 for entry in self._cache.values() if entry.exists)
        error_count = sum(1 for entry in self._cache.values() if entry.error is not None)

        # Calculate total cached size
        total_size = sum(entry.size_bytes for entry in self._cache.values() if entry.exists)

        return {
            "total_entries": total_entries,
            "exists_count": exists_count,
            "error_count": error_count,
            "total_cached_bytes": total_size,
            "cache_file": str(self.cache_file),
            "ttl_seconds": self.ttl_seconds,
        }


# Global cache instance
_global_cache: ScanCache | None = None


def get_cache() -> ScanCache:
    """Get the global cache instance."""
    global _global_cache
    if _global_cache is None:
        _global_cache = ScanCache()
    return _global_cache


def clear_cache() -> None:
    """Clear the global cache."""
    get_cache().clear()


def save_cache() -> None:
    """Save the global cache to disk."""
    get_cache().save()


def cache_stats() -> dict[str, Any]:
    """Get global cache statistics."""
    return get_cache().stats()

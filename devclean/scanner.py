"""Scan filesystem for developer cruft."""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Union

from .config import CRUFT_PATTERNS, VENV_SEARCH_DIRS, VENV_NAMES, CruftPattern
from .exceptions import ScanError, TimeoutError


@dataclass
class CruftItem:
    """A found piece of cruft on disk."""
    
    path: Path
    size_bytes: int
    category: str
    description: str
    safe: bool = True
    tool_installed: Optional[bool] = None  # None = unknown/not checked
    
    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 ** 2)
    
    @property
    def size_gb(self) -> float:
        return self.size_bytes / (1024 ** 3)
    
    @property
    def size_human(self) -> str:
        if self.size_gb >= 1:
            return f"{self.size_gb:.1f} GB"
        return f"{self.size_mb:.0f} MB"


@dataclass
class ScanResult:
    """Results from a disk scan."""
    
    items: List[CruftItem] = field(default_factory=list)
    venvs: List[CruftItem] = field(default_factory=list)
    node_modules: List[CruftItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    @property
    def all_items(self) -> List[CruftItem]:
        return self.items + self.venvs + self.node_modules
    
    @property
    def total_bytes(self) -> int:
        return sum(i.size_bytes for i in self.all_items)
    
    @property
    def total_gb(self) -> float:
        return self.total_bytes / (1024 ** 3)


def get_dir_size(path: Path, timeout: int = 30, use_cache: bool = True) -> Optional[int]:
    """Get directory size in bytes using du.
    
    Args:
        path: Path to directory to measure
        timeout: Timeout in seconds for the du command
        use_cache: Whether to use cached results
        
    Returns:
        Size in bytes, or None if measurement failed
        
    Raises:
        TimeoutError: If the du command times out
    """
    from .cache import get_cache
    
    # Check cache first
    if use_cache:
        cache = get_cache()
        cached_entry = cache.get(path)
        if cached_entry is not None:
            if cached_entry.error:
                return None
            return cached_entry.size_bytes if cached_entry.exists else None
    
    try:
        if not path.exists():
            if use_cache:
                cache.set(path, 0, False)
            return None
            
        result = subprocess.run(
            ["du", "-sk", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            # du -sk returns kilobytes
            size_bytes = int(result.stdout.split()[0]) * 1024
            if use_cache:
                cache.set(path, size_bytes, True)
            return size_bytes
            
    except subprocess.TimeoutExpired as e:
        if use_cache:
            cache.set(path, 0, True, f"Timeout: {e}")
        raise TimeoutError(f"Timeout measuring directory size: {path}") from e
    except (ValueError, IndexError) as e:
        if use_cache:
            cache.set(path, 0, True, f"Parse error: {e}")
        raise ScanError(f"Failed to parse directory size for {path}: {e}") from e
    except Exception as e:
        if use_cache:
            cache.set(path, 0, True, str(e))
        raise ScanError(f"Error measuring directory size for {path}: {e}") from e
    return None


def check_command_exists(command: str) -> bool:
    """Check if a command/tool is installed."""
    try:
        # Extract just the binary name from "binary --version" style commands
        binary = command.split()[0]
        result = subprocess.run(
            ["which", binary],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except:
        return False


def scan_known_cruft(home: Path, min_size_mb: int = 100, max_workers: int = 4) -> List[CruftItem]:
    """Scan known cruft locations in parallel.
    
    Args:
        home: User's home directory path
        min_size_mb: Minimum size in MB to include in results
        max_workers: Maximum number of parallel workers
        
    Returns:
        List of found cruft items
    """
    def scan_pattern(pattern: CruftPattern) -> Optional[CruftItem]:
        """Scan a single cruft pattern."""
        try:
            path = Path(pattern.path_template.format(home=home))
            
            if not path.exists():
                return None
            
            size = get_dir_size(path)
            if size is None:
                return None
            
            effective_min = max(pattern.min_size_mb, min_size_mb)
            if size < effective_min * 1024 * 1024:
                return None
            
            # Check if the tool is installed
            tool_installed = None
            if pattern.check_installed:
                tool_installed = check_command_exists(pattern.check_installed)
            
            return CruftItem(
                path=path,
                size_bytes=size,
                category=pattern.category,
                description=pattern.description,
                safe=pattern.safe,
                tool_installed=tool_installed,
            )
        except Exception:
            # Skip patterns that cause errors
            return None
    
    items = []
    
    # Use ThreadPoolExecutor for parallel processing
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(scan_pattern, pattern): pattern for pattern in CRUFT_PATTERNS}
        
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    items.append(result)
            except Exception:
                # Skip failed patterns
                continue
    
    return items


def find_venvs(home: Path, min_size_mb: int = 50) -> List[CruftItem]:
    """Find Python virtual environments in project directories.
    
    Args:
        home: User's home directory path
        min_size_mb: Minimum size in MB to include in results
        
    Returns:
        List of found virtual environment cruft items
    """
    venvs = []
    seen_paths = set()
    
    for search_template in VENV_SEARCH_DIRS:
        search_dir = Path(search_template.format(home=home))
        
        if not search_dir.exists():
            continue
        
        for venv_name in VENV_NAMES:
            try:
                # Use find command for speed
                result = subprocess.run(
                    ["find", str(search_dir), "-type", "d", "-name", venv_name, "-maxdepth", "4"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                
                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue
                    
                    venv_path = Path(line)
                    
                    # Skip if already seen
                    if venv_path in seen_paths:
                        continue
                    seen_paths.add(venv_path)
                    
                    # Verify it's actually a venv
                    if not (venv_path / "pyvenv.cfg").exists():
                        continue
                    
                    size = get_dir_size(venv_path, timeout=10)
                    if size is None or size < min_size_mb * 1024 * 1024:
                        continue
                    
                    # Get project name from parent
                    project_name = venv_path.parent.name
                    
                    venvs.append(CruftItem(
                        path=venv_path,
                        size_bytes=size,
                        category="python",
                        description=f"venv in {project_name}",
                        safe=True,
                        tool_installed=True,  # If venv exists, python exists
                    ))
                    
            except subprocess.TimeoutExpired:
                continue
    
    return venvs


def find_node_modules(home: Path, min_size_mb: int = 200) -> List[CruftItem]:
    """Find node_modules directories.
    
    Args:
        home: User's home directory path
        min_size_mb: Minimum size in MB to include in results
        
    Returns:
        List of found node_modules cruft items
    """
    modules = []
    
    for search_template in VENV_SEARCH_DIRS:
        search_dir = Path(search_template.format(home=home))
        
        if not search_dir.exists():
            continue
        
        try:
            result = subprocess.run(
                ["find", str(search_dir), "-type", "d", "-name", "node_modules", "-maxdepth", "4"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                
                # Skip nested node_modules
                if "node_modules/node_modules" in line:
                    continue
                
                nm_path = Path(line)
                size = get_dir_size(nm_path, timeout=10)
                
                if size is None or size < min_size_mb * 1024 * 1024:
                    continue
                
                project_name = nm_path.parent.name
                
                modules.append(CruftItem(
                    path=nm_path,
                    size_bytes=size,
                    category="node",
                    description=f"node_modules in {project_name}",
                    safe=True,
                    tool_installed=True,
                ))
                
        except subprocess.TimeoutExpired:
            continue
    
    return modules


def scan_all(
    home: Optional[Path] = None,
    include_venvs: bool = True,
    include_node_modules: bool = True,
    min_size_mb: int = 100,
    max_workers: int = 4,
) -> ScanResult:
    """Run full scan for all cruft types.
    
    Args:
        home: User's home directory (uses Path.home() if None)
        include_venvs: Whether to scan for Python virtual environments
        include_node_modules: Whether to scan for node_modules directories
        min_size_mb: Minimum size in MB to include in results
        max_workers: Maximum number of parallel workers
        
    Returns:
        ScanResult containing all found cruft items
    """
    from .cache import save_cache
    
    if home is None:
        home = Path.home()
    
    result = ScanResult()
    
    try:
        # Scan known cruft locations in parallel
        result.items = scan_known_cruft(home, min_size_mb, max_workers)
        
        # Find venvs
        if include_venvs:
            try:
                result.venvs = find_venvs(home, min_size_mb=50)
            except Exception as e:
                result.errors.append(f"Error scanning virtual environments: {e}")
        
        # Find node_modules
        if include_node_modules:
            try:
                result.node_modules = find_node_modules(home, min_size_mb=200)
            except Exception as e:
                result.errors.append(f"Error scanning node_modules: {e}")
        
        # Sort all by size
        result.items.sort(key=lambda x: x.size_bytes, reverse=True)
        result.venvs.sort(key=lambda x: x.size_bytes, reverse=True)
        result.node_modules.sort(key=lambda x: x.size_bytes, reverse=True)
        
    finally:
        # Save cache after scan completes
        try:
            save_cache()
        except Exception:
            # Don't fail if cache save fails
            pass
    
    return result

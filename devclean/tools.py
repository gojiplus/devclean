"""Tools that the agent can use to interact with the system."""

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import CRUFT_PATTERNS
from .exceptions import DeletionError, PathNotFoundError, UnsafePathError
from .scanner import CruftItem, ScanResult, get_dir_size, scan_all

# Paths that have been "offered" to delete (agent asked about them)
# This provides a code-level guardrail against deletion without discussion
_pending_confirmations: set[str] = set()


def require_confirmation(path: str) -> None:
    """Mark a path as discussed/offered for deletion."""
    _pending_confirmations.add(path)


def check_confirmation(path: str) -> bool:
    """Check if a path was discussed before deletion attempt."""
    return path in _pending_confirmations


def clear_confirmation(path: str) -> None:
    """Clear a path from pending confirmations after deletion."""
    _pending_confirmations.discard(path)


def is_known_cruft_pattern(path: Path) -> bool:
    """Check if a path matches a known safe cruft pattern."""
    home = Path.home()
    path_str = str(path)

    for pattern in CRUFT_PATTERNS:
        expected_path = pattern.path_template.format(home=home)
        if str(path) == expected_path and pattern.safe:
            return True
    return False


# Tool definitions for Claude
TOOL_DEFINITIONS = [
    {
        "name": "scan_disk",
        "description": "Scan the disk for developer cruft like caches, virtual environments, node_modules, etc. Returns a list of items that can potentially be cleaned up.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_venvs": {
                    "type": "boolean",
                    "description": "Whether to scan for Python virtual environments in project directories",
                    "default": True,
                },
                "include_node_modules": {
                    "type": "boolean",
                    "description": "Whether to scan for node_modules directories",
                    "default": True,
                },
                "min_size_mb": {
                    "type": "integer",
                    "description": "Minimum size in MB to include in results",
                    "default": 100,
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_directory_size",
        "description": "Get the size of a specific directory in bytes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the directory",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_directory",
        "description": "List contents of a directory with sizes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the directory",
                },
                "max_items": {
                    "type": "integer",
                    "description": "Maximum number of items to return",
                    "default": 20,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "check_tool_installed",
        "description": "Check if a command-line tool is installed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Name of the tool/command to check (e.g., 'docker', 'python', 'node')",
                },
            },
            "required": ["tool_name"],
        },
    },
    {
        "name": "delete_directory",
        "description": "Delete a directory. Use with caution. Returns success status and any error messages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the directory to delete",
                },
                "use_sudo": {
                    "type": "boolean",
                    "description": "Whether to use sudo for deletion (needed for some protected directories)",
                    "default": False,
                },
                "force": {
                    "type": "boolean",
                    "description": "Bypass protection checks for this deletion (user must explicitly approve)",
                    "default": False,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "get_disk_usage",
        "description": "Get overall disk usage statistics for the system.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "run_cleanup_command",
        "description": "Run a known safe cleanup command like 'brew cleanup', 'pip cache purge', etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": [
                        "brew_cleanup",
                        "pip_cache_purge",
                        "npm_cache_clean",
                        "yarn_cache_clean",
                        "docker_prune",
                    ],
                    "description": "The cleanup command to run",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "approve_path_for_deletion",
        "description": "Mark a custom path (not found in scan) as approved for deletion after inspecting it. Use this when the user asks to delete a specific path that wasn't in the scan results. Always inspect the path with list_directory or get_directory_size first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to approve for deletion",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this path is safe to delete (explain to user)",
                },
            },
            "required": ["path", "reason"],
        },
    },
    {
        "name": "force_delete_cruft",
        "description": "Delete all scanned cruft items regardless of protection status. Use when user confirms they want to delete everything found in scan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "confirm": {
                    "type": "boolean",
                    "description": "User must set this to true to confirm bulk deletion",
                },
                "use_sudo": {
                    "type": "boolean",
                    "description": "Whether to use sudo for deletion",
                    "default": False,
                },
            },
            "required": ["confirm"],
        },
    },
]


def format_scan_result(result: ScanResult) -> str:
    """Format scan results as a string for the agent."""
    lines = []

    # Register all found paths as deletable
    for item in result.all_items:
        require_confirmation(str(item.path))

    if result.items:
        lines.append("## Known Cruft Locations\n")
        for item in result.items:
            orphan_status = ""
            if item.tool_installed is False:
                orphan_status = " [ORPHANED - tool not installed]"
            elif item.tool_installed is True:
                orphan_status = " [tool installed]"

            safe_status = "✓ safe" if item.safe else "⚠ caution"
            lines.append(
                f"- {item.size_human:>8} | {item.description} ({safe_status}){orphan_status}\n"
                f"           {item.path}"
            )
        lines.append("")

    if result.venvs:
        lines.append("## Python Virtual Environments\n")
        for item in result.venvs:
            lines.append(f"- {item.size_human:>8} | {item.description}\n           {item.path}")
        lines.append("")

    if result.node_modules:
        lines.append("## Node Modules\n")
        for item in result.node_modules:
            lines.append(f"- {item.size_human:>8} | {item.description}\n           {item.path}")
        lines.append("")

    lines.append(f"\n**Total: {result.total_gb:.1f} GB** across {len(result.all_items)} items")

    return "\n".join(lines)


def execute_tool(name: str, args: dict[str, Any]) -> str:
    """Execute a tool and return the result as a string.

    Args:
        name: Name of the tool to execute
        args: Arguments to pass to the tool

    Returns:
        String result of the tool execution

    Raises:
        Various exceptions depending on the tool and error conditions

    """

    if name == "scan_disk":
        result = scan_all(
            include_venvs=args.get("include_venvs", True),
            include_node_modules=args.get("include_node_modules", True),
            min_size_mb=args.get("min_size_mb", 100),
        )
        return format_scan_result(result)

    elif name == "get_directory_size":
        path = Path(args["path"])
        if not path.exists():
            return f"Error: Path does not exist: {path}"
        size = get_dir_size(path)
        if size is None:
            return f"Error: Could not get size of {path}"
        size_gb = size / (1024**3)
        size_mb = size / (1024**2)
        if size_gb >= 1:
            return f"{path}: {size_gb:.2f} GB"
        return f"{path}: {size_mb:.0f} MB"

    elif name == "list_directory":
        path = Path(args["path"])
        max_items = args.get("max_items", 20)

        if not path.exists():
            return f"Error: Path does not exist: {path}"

        try:
            # Use du to get sizes of immediate children
            du_result = subprocess.run(
                ["du", "-sk", *[str(p) for p in list(path.iterdir())[:max_items]]],
                capture_output=True,
                text=True,
                timeout=30,
            )

            items = []
            for line in du_result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    size_kb = int(parts[0])
                    item_path = parts[1]
                    size_mb = size_kb / 1024
                    items.append((size_mb, item_path))

            # Sort by size descending
            items.sort(reverse=True)

            lines = [f"Contents of {path}:\n"]
            for size_mb, item_path in items:
                if size_mb >= 1024:
                    lines.append(f"  {size_mb / 1024:.1f} GB  {Path(item_path).name}")
                else:
                    lines.append(f"  {size_mb:.0f} MB  {Path(item_path).name}")

            return "\n".join(lines)

        except Exception as e:
            return f"Error listing directory: {e}"

    elif name == "check_tool_installed":
        tool = args["tool_name"]
        try:
            which_result = subprocess.run(
                ["which", tool],
                capture_output=True,
                timeout=5,
            )
            if which_result.returncode == 0:
                return f"{tool}: INSTALLED at {which_result.stdout.decode().strip()}"
            return f"{tool}: NOT INSTALLED"
        except Exception as e:
            return f"Error checking tool: {e}"

    elif name == "delete_directory":
        path = Path(args["path"])
        use_sudo = args.get("use_sudo", False)
        force = args.get("force", False)

        # Guardrail: only allow deleting paths that were found in a scan
        if not check_confirmation(str(path)):
            return json.dumps(
                {
                    "success": False,
                    "error": "PATH_NOT_SCANNED",
                    "message": f"This path wasn't found in a scan. Run scan_disk first to identify deletable items. Path: {path}",
                    "path": str(path),
                }
            )

        if not path.exists():
            clear_confirmation(str(path))
            return json.dumps(
                {
                    "success": False,
                    "error": "PATH_NOT_FOUND",
                    "message": f"Path does not exist (maybe already deleted?): {path}",
                    "path": str(path),
                }
            )

        # Safety checks (can be bypassed with force=True)
        if not force:
            home = Path.home()
            protected = [
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
            ]

            # Check for protected paths
            try:
                for protected_path in protected:
                    if path == protected_path:
                        return json.dumps(
                            {
                                "success": False,
                                "error": "PROTECTED_PATH",
                                "message": f"Refusing to delete protected path: {path}",
                                "path": str(path),
                                "suggestion": "Use force=true to bypass protection if you're certain this is safe",
                            }
                        )

                    if path.is_relative_to(protected_path):
                        # Allow deletion if it's a known safe cruft pattern
                        if is_known_cruft_pattern(path):
                            break  # Allow deletion
                        else:
                            return json.dumps(
                                {
                                    "success": False,
                                    "error": "PROTECTED_PATH",
                                    "message": f"Path is under protected directory {protected_path}: {path}",
                                    "path": str(path),
                                    "suggestion": "Use force=true to bypass protection, or use_sudo=true if it's a permission issue",
                                }
                            )
            except ValueError:
                # is_relative_to can raise ValueError on some path combinations
                pass

        # Additional safety: don't delete anything that's a parent of home (even with force)
        try:
            home = Path.home()
            home.relative_to(path)
            return json.dumps(
                {
                    "success": False,
                    "error": "PROTECTED_PATH",
                    "message": f"Refusing to delete path that contains home directory: {path}",
                    "path": str(path),
                    "suggestion": "This safety check cannot be bypassed",
                }
            )
        except ValueError:
            pass  # Good, path is not a parent of home

        # Get size before deletion
        size = get_dir_size(path)
        size_str = f"{size / (1024**3):.2f} GB" if size else "unknown size"

        try:
            if use_sudo:
                sudo_result = subprocess.run(
                    ["sudo", "rm", "-rf", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if sudo_result.returncode != 0:
                    error_msg = sudo_result.stderr.strip()
                    if "Operation not permitted" in error_msg:
                        return json.dumps(
                            {
                                "success": False,
                                "error": "FULL_DISK_ACCESS_REQUIRED",
                                "message": "Even sudo can't delete this — macOS sandbox protection. Terminal needs Full Disk Access.",
                                "path": str(path),
                                "suggestion": "Grant Terminal Full Disk Access in System Settings → Privacy & Security → Full Disk Access",
                            }
                        )
                    return json.dumps(
                        {
                            "success": False,
                            "error": "SUDO_FAILED",
                            "message": f"sudo rm failed: {error_msg}",
                            "path": str(path),
                        }
                    )
            else:
                shutil.rmtree(path)

            clear_confirmation(str(path))
            return json.dumps(
                {
                    "success": True,
                    "message": f"Successfully deleted {path}",
                    "path": str(path),
                    "freed_bytes": size,
                    "freed_human": size_str,
                }
            )

        except PermissionError:
            return json.dumps(
                {
                    "success": False,
                    "error": "PERMISSION_DENIED",
                    "message": f"Permission denied deleting {path}",
                    "path": str(path),
                    "suggestion": "Retry with use_sudo=true",
                    "used_sudo": use_sudo,
                }
            )
        except Exception as e:
            return json.dumps(
                {
                    "success": False,
                    "error": "UNKNOWN_ERROR",
                    "message": f"Error deleting {path}: {e}",
                    "path": str(path),
                }
            )

    elif name == "get_disk_usage":
        try:
            df_result = subprocess.run(
                ["df", "-h", "/"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = df_result.stdout.strip().split("\n")
            if len(lines) >= 2:
                # Parse df output
                parts = lines[1].split()
                return (
                    f"Disk Usage:\n"
                    f"  Total: {parts[1]}\n"
                    f"  Used: {parts[2]}\n"
                    f"  Available: {parts[3]}\n"
                    f"  Capacity: {parts[4]}"
                )
            return df_result.stdout
        except Exception as e:
            return f"Error getting disk usage: {e}"

    elif name == "run_cleanup_command":
        command = args["command"]

        commands = {
            "brew_cleanup": ["brew", "cleanup", "--prune=all"],
            "pip_cache_purge": ["pip", "cache", "purge"],
            "npm_cache_clean": ["npm", "cache", "clean", "--force"],
            "yarn_cache_clean": ["yarn", "cache", "clean"],
            "docker_prune": ["docker", "system", "prune", "-a", "-f"],
        }

        if command not in commands:
            return f"Unknown command: {command}"

        cmd = commands[command]

        # Check if tool exists
        tool = cmd[0]
        which_result = subprocess.run(["which", tool], capture_output=True)
        if which_result.returncode != 0:
            return f"{tool} is not installed, skipping {command}"

        try:
            cmd_result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            output = cmd_result.stdout + cmd_result.stderr
            return f"Ran {' '.join(cmd)}:\n{output[:1000]}"
        except subprocess.TimeoutExpired:
            return f"Command timed out: {' '.join(cmd)}"
        except Exception as e:
            return f"Error running command: {e}"

    elif name == "approve_path_for_deletion":
        path = Path(args["path"])
        reason = args.get("reason", "User requested")

        if not path.exists():
            return f"Cannot approve non-existent path: {path}"

        # Safety check even for manual approval
        home = Path.home()
        protected = [
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
        ]
        if path in protected:
            return f"Cannot approve protected system path: {path}"

        require_confirmation(str(path))
        size = get_dir_size(path)
        size_str = f"{size / (1024**3):.2f} GB" if size else "unknown size"

        return f"Path approved for deletion: {path} ({size_str}). Reason: {reason}. You can now call delete_directory on this path after user confirms."

    elif name == "force_delete_cruft":
        if not args.get("confirm", False):
            return "Error: Must set confirm=true to proceed with bulk deletion."

        use_sudo = args.get("use_sudo", False)

        # Get all confirmed paths
        if not _pending_confirmations:
            return "No paths have been scanned/confirmed for deletion. Run scan_disk first."

        deleted_paths = []
        failed_paths = []
        total_freed = 0

        for path_str in list(_pending_confirmations):
            path = Path(path_str)
            if not path.exists():
                clear_confirmation(path_str)
                continue

            # Get size before deletion
            size = get_dir_size(path)

            try:
                if use_sudo:
                    rm_result = subprocess.run(
                        ["sudo", "rm", "-rf", str(path)],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if rm_result.returncode != 0:
                        failed_paths.append(
                            {
                                "path": path_str,
                                "error": rm_result.stderr.strip(),
                                "suggestion": "Grant Terminal Full Disk Access in System Settings if needed",
                            }
                        )
                        continue
                else:
                    shutil.rmtree(path)

                deleted_paths.append(path_str)
                clear_confirmation(path_str)
                if size:
                    total_freed += size

            except PermissionError:
                failed_paths.append(
                    {
                        "path": path_str,
                        "error": "Permission denied",
                        "suggestion": "Retry with use_sudo=true",
                    }
                )
            except Exception as e:
                failed_paths.append(
                    {
                        "path": path_str,
                        "error": str(e),
                        "suggestion": "Check path exists and is accessible",
                    }
                )

        result_lines = []
        if deleted_paths:
            freed_gb = total_freed / (1024**3)
            result_lines.append(
                f"✅ Successfully deleted {len(deleted_paths)} items, freed {freed_gb:.1f} GB:"
            )
            for deleted_path in deleted_paths[:5]:  # Show first 5
                result_lines.append(f"  • {deleted_path}")
            if len(deleted_paths) > 5:
                result_lines.append(f"  • ... and {len(deleted_paths) - 5} more")

        if failed_paths:
            result_lines.append(f"\n❌ Failed to delete {len(failed_paths)} items:")
            for item in failed_paths[:3]:  # Show first 3 failures
                result_lines.append(f"  • {item['path']}: {item['error']}")
                result_lines.append(f"    💡 {item['suggestion']}")

            if any("Permission denied" in item["error"] for item in failed_paths):
                result_lines.append(
                    "\n🔄 To retry failures with sudo: force_delete_cruft(confirm=true, use_sudo=true)"
                )

        return "\n".join(result_lines)

    return f"Unknown tool: {name}"

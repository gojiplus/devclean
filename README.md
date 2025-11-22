# Cleaner

[![CI](https://github.com/gojiplus/devclean/workflows/CI/badge.svg)](https://github.com/gojiplus/devclean/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

AI-powered disk cleanup for developers on macOS.

Cleaner knows where developer cruft hides — Docker orphans, pre-commit caches, torch models, virtual environments, node_modules — and helps you clean it up interactively with AI guidance.

## Installation

```bash
# Install from GitHub (recommended)
pip install git+https://github.com/gojiplus/devclean.git

# Or install locally from source
git clone https://github.com/gojiplus/devclean.git
cd devclean
pip install -e .
```

## Usage

### Quick scan (no AI, no API key needed)

```bash
devclean scan
```

Shows all developer cruft on your system with sizes, categories, and whether items are orphaned (tool uninstalled but data remains).

### Interactive AI-guided cleanup

```bash
export ANTHROPIC_API_KEY=your-key-here
devclean
# or
devclean chat
```

This starts a conversational session where Claude helps you understand what's taking space and guides you through cleanup decisions.

### Configuration

Customize DevClean's behavior with a configuration file:

```bash
# Create a configuration file
devclean config init

# View current settings
devclean config show

# Add protected directories (never deleted)
devclean config add-protected ~/important-project
devclean config add-protected ~/client-work

# Add patterns that are always safe to delete
devclean config add-safe "**/cache"
devclean config add-safe "**/.temp"

# List all configured patterns and paths
devclean config list-patterns

# Edit configuration file directly
devclean config edit

# Validate configuration
devclean config validate
```

Configuration options include:
- **Scan settings**: minimum size, parallel workers, timeouts
- **Display preferences**: colors, progress bars, table format  
- **Safety settings**: protected paths, confirmation requirements
- **API integration**: Anthropic API key storage

Example `.devclean.toml`:
```toml
[scan]
min_size_mb = 100              # Only show items >= 100MB
parallel_workers = 4           # Scan with 4 parallel workers
include_venvs = true          # Scan for Python virtual environments

[safety]
require_confirmation = true    # Always ask before deletion
protected_paths = [           # Never delete these paths
    "~/important-project",
    "~/client-work"
]
always_safe_patterns = [      # These patterns are always safe to delete
    "**/cache",
    "**/.temp"
]

[display]
show_progress = true          # Show progress bars
color_output = true           # Use colored output
table_format = "rich"         # Rich table formatting
```

### Direct deletion

```bash
# Delete specific directories
devclean clean ~/.cache/pre-commit
devclean clean ~/.cache/huggingface --force  # skip confirmation
devclean clean ~/Library/Containers/com.docker.docker --sudo  # use sudo

# Use custom configuration
devclean clean --config ./project.toml ~/some/path
```

### Bulk cleanup

The AI assistant supports bulk operations for cleaning multiple items at once:

```bash
# In AI chat mode, you can say:
# "delete all safe items" - deletes caches, orphaned data, etc.
# "clean up everything except virtual environments"
# "nuke all node_modules directories"
```

The AI will show you exactly what will be deleted and ask for confirmation before proceeding.

## What it finds

**Python**
- `~/.cache/pre-commit` — pre-commit hook environments
- `~/.cache/pip` — pip download cache
- `~/.cache/uv` — uv package cache
- `~/.cache/pypoetry` — Poetry cache
- Virtual environments in your projects

**ML/AI**
- `~/.cache/torch` — PyTorch models
- `~/.cache/huggingface` — HuggingFace models/datasets
- `~/.cache/whisper` — Whisper models

**Node**
- `~/.cache/yarn`, `~/Library/Caches/Yarn`
- `~/.npm`
- `node_modules` in your projects

**Docker**
- `~/Library/Containers/com.docker.docker` — Docker Desktop data (often orphaned!)

**Xcode**
- `~/Library/Developer/Xcode/DerivedData`
- `~/Library/Developer/Xcode/Archives`
- iOS DeviceSupport files

**Testing**
- Playwright browser binaries
- Selenium webdriver cache

**Other**
- Homebrew cache
- Gradle/Maven caches
- Cargo registry
- Go module cache

## How it works

1. **Scan**: Cleaner scans known cruft locations and searches for venvs/node_modules
2. **Detect orphans**: Checks if tools are still installed (e.g., Docker data without Docker)
3. **AI guidance**: Claude explains what each item is and whether it's safe to delete
4. **Confirm & clean**: Nothing is deleted without your explicit confirmation

## Safety Features

- **Configurable Protection**: Add custom protected paths and safe patterns
- **Smart Defaults**: Pre-configured protection for system and user directories  
- **Orphan Detection**: Identifies leftover data from uninstalled tools (safest to delete)
- **Pattern Matching**: Flexible glob patterns for always-safe and never-delete rules
- **Force Override**: Bypass protection for confirmed-safe operations
- **Sudo Support**: Handles permission-protected directories when needed
- **Confirmation Flow**: Respects user-configured confirmation preferences

## Development

```bash
# Clone and setup
git clone https://github.com/gojiplus/devclean.git
cd devclean
make dev-setup

# Run tests
make test

# Run all checks (linting, type checking, security, tests)
make check-all

# Format code
make format

# Local CI testing with Docker
make ci-docker

# See all available commands
make help
```

## Requirements

- macOS (designed for Mac-specific paths)
- Python 3.11+
- Anthropic API key (for AI features; scan works without it)

## Features

- ✅ **Smart Detection**: Finds developer cruft in known locations
- ✅ **AI Guidance**: Claude explains what each item is and whether it's safe to delete
- ✅ **User Configuration**: Customize behavior, protected paths, and safety rules
- ✅ **Pattern Matching**: Flexible glob patterns for safe and protected items
- ✅ **Safety First**: Multiple layers of configurable protection
- ✅ **Bulk Operations**: Delete multiple items at once with AI guidance
- ✅ **Orphan Detection**: Identifies leftover data from uninstalled tools  
- ✅ **Performance**: Parallel scanning and intelligent caching
- ✅ **Modern Python**: Python 3.11+ with tomllib/tomlkit integration
- ✅ **Type Safe**: Comprehensive type hints throughout
- ✅ **Well Tested**: Full test suite with CI/CD

## License

MIT

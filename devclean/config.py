"""Known cruft patterns for macOS developers."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class CruftPattern:
    """A known location that accumulates developer cruft."""

    path_template: str  # Relative to home, supports {home}
    category: str
    description: str
    check_installed: str | None = None  # Command to check if tool is installed
    safe: bool = True  # Safe to delete without breaking running apps
    min_size_mb: int = 100  # Only flag if larger than this


# Known cruft locations on macOS for developers
CRUFT_PATTERNS: list[CruftPattern] = [
    # Python
    CruftPattern(
        "{home}/.cache/pre-commit",
        "python",
        "Pre-commit hook environments",
        check_installed="pre-commit --version",
    ),
    CruftPattern(
        "{home}/.cache/pip",
        "python",
        "pip download cache",
        check_installed="pip --version",
    ),
    CruftPattern(
        "{home}/.cache/uv",
        "python",
        "uv package cache",
        check_installed="uv --version",
    ),
    CruftPattern(
        "{home}/.cache/pypoetry",
        "python",
        "Poetry cache",
        check_installed="poetry --version",
    ),
    CruftPattern(
        "{home}/Library/Caches/pypoetry",
        "python",
        "Poetry cache (Library)",
        check_installed="poetry --version",
    ),
    # ML/AI
    CruftPattern(
        "{home}/.cache/torch",
        "ml",
        "PyTorch downloaded models",
        check_installed=None,  # No single binary
    ),
    CruftPattern(
        "{home}/.cache/huggingface",
        "ml",
        "HuggingFace models and datasets",
        check_installed=None,
    ),
    CruftPattern(
        "{home}/.cache/whisper",
        "ml",
        "OpenAI Whisper models",
        check_installed=None,
    ),
    # Node/JS
    CruftPattern(
        "{home}/.cache/yarn",
        "node",
        "Yarn cache",
        check_installed="yarn --version",
    ),
    CruftPattern(
        "{home}/Library/Caches/Yarn",
        "node",
        "Yarn cache (Library)",
        check_installed="yarn --version",
    ),
    CruftPattern(
        "{home}/.npm",
        "node",
        "npm cache",
        check_installed="npm --version",
    ),
    CruftPattern(
        "{home}/.cache/node-gyp",
        "node",
        "node-gyp build cache",
        check_installed="node --version",
    ),
    CruftPattern(
        "{home}/Library/Caches/node-gyp",
        "node",
        "node-gyp cache (Library)",
        check_installed="node --version",
    ),
    # Docker
    CruftPattern(
        "{home}/Library/Containers/com.docker.docker",
        "docker",
        "Docker Desktop data",
        check_installed="docker --version",
        safe=False,  # Could break running containers
    ),
    CruftPattern(
        "{home}/.docker",
        "docker",
        "Docker config and buildx cache",
        check_installed="docker --version",
    ),
    # Testing
    CruftPattern(
        "{home}/Library/Caches/ms-playwright",
        "testing",
        "Playwright browser binaries",
        check_installed=None,
    ),
    CruftPattern(
        "{home}/.cache/ms-playwright",
        "testing",
        "Playwright browsers (cache)",
        check_installed=None,
    ),
    CruftPattern(
        "{home}/.cache/selenium",
        "testing",
        "Selenium webdriver cache",
        check_installed=None,
    ),
    # R
    CruftPattern(
        "{home}/Library/Caches/org.R-project.R",
        "r",
        "R package cache",
        check_installed="R --version",
    ),
    # Xcode / iOS
    CruftPattern(
        "{home}/Library/Developer/Xcode/DerivedData",
        "xcode",
        "Xcode build cache",
        check_installed="xcodebuild -version",
    ),
    CruftPattern(
        "{home}/Library/Developer/Xcode/Archives",
        "xcode",
        "Xcode app archives",
        check_installed="xcodebuild -version",
        safe=False,  # User might want these
    ),
    CruftPattern(
        "{home}/Library/Developer/Xcode/iOS DeviceSupport",
        "xcode",
        "iOS device support files",
        check_installed="xcodebuild -version",
    ),
    CruftPattern(
        "{home}/Library/Developer/CoreSimulator/Caches",
        "xcode",
        "iOS Simulator caches",
        check_installed="xcodebuild -version",
    ),
    # Homebrew
    CruftPattern(
        "{home}/Library/Caches/Homebrew",
        "homebrew",
        "Homebrew download cache",
        check_installed="brew --version",
    ),
    # Browsers
    CruftPattern(
        "{home}/Library/Caches/Google",
        "browser",
        "Chrome cache",
        check_installed=None,
        min_size_mb=500,
    ),
    CruftPattern(
        "{home}/Library/Caches/Mozilla",
        "browser",
        "Firefox cache",
        check_installed=None,
        min_size_mb=500,
    ),
    # Misc dev tools
    CruftPattern(
        "{home}/.cache/act",
        "ci",
        "act (local GitHub Actions) cache",
        check_installed="act --version",
    ),
    CruftPattern(
        "{home}/.gradle/caches",
        "java",
        "Gradle build cache",
        check_installed="gradle --version",
    ),
    CruftPattern(
        "{home}/.m2/repository",
        "java",
        "Maven local repository",
        check_installed="mvn --version",
    ),
    CruftPattern(
        "{home}/.cargo/registry",
        "rust",
        "Cargo package registry cache",
        check_installed="cargo --version",
    ),
    CruftPattern(
        "{home}/go/pkg/mod",
        "go",
        "Go module cache",
        check_installed="go version",
    ),
]


# Directories to search for virtual environments
VENV_SEARCH_DIRS: list[str] = [
    "{home}/Documents/GitHub",
    "{home}/Documents",
    "{home}/projects",
    "{home}/code",
    "{home}/dev",
    "{home}/src",
    "{home}/repos",
    "{home}/work",
]

# Virtual environment directory names
VENV_NAMES: list[str] = [".venv", "venv", ".env", "env", ".virtualenv", "virtualenv"]

# node_modules search (can be huge)
NODE_MODULES_SEARCH: bool = True

"""Known cruft patterns for macOS developers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CruftPattern:
    """A known location that accumulates developer cruft."""

    path_template: str  # Relative to home, supports {home}
    category: str
    description: str
    check_installed: str | None = None  # Command to check if tool is installed
    safe: bool = True  # Safe to delete without breaking running apps
    min_size_mb: int | None = None
    """Size floor for this pattern, overriding the global one in both directions.

    None means "use the global floor". A number here wins outright, so a
    pattern that matters at 10 MB still surfaces under a global floor of 300.
    """

    recovery: str = "Refetched automatically on next use"
    """How this comes back once deleted."""

    purge_command: str | None = None
    """Official command to clear this cache, where the owning tool provides one.

    Its presence is what earns a pattern the AUTO tier: the tool itself
    declares the directory disposable.
    """


# Known cruft locations on macOS for developers
CRUFT_PATTERNS: list[CruftPattern] = [
    # Python
    CruftPattern(
        "{home}/.cache/pre-commit",
        "python",
        "Pre-commit hook environments",
        check_installed="pre-commit --version",
        purge_command="pre-commit clean",
        recovery="Rebuilt on next `pre-commit run`",
    ),
    CruftPattern(
        "{home}/.cache/pip",
        "python",
        "pip download cache",
        check_installed="pip --version",
        purge_command="pip cache purge",
        recovery="Re-downloaded on next `pip install`",
    ),
    CruftPattern(
        "{home}/Library/Caches/pip",
        "python",
        "pip download cache (macOS default location)",
        check_installed="pip --version",
        purge_command="pip cache purge",
        recovery="Re-downloaded on next `pip install`",
    ),
    CruftPattern(
        "{home}/.cache/uv",
        "python",
        "uv package cache",
        check_installed="uv --version",
        purge_command="uv cache clean",
        recovery="Re-downloaded on next `uv sync`",
    ),
    CruftPattern(
        "{home}/Library/Caches/puccinialin",
        "python",
        "Rust toolchains fetched to build Python extensions",
        check_installed=None,
        recovery="Re-downloaded when a package next needs a Rust build",
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
        purge_command="npm cache clean --force",
        recovery="Re-downloaded on next `npm install`",
    ),
    CruftPattern(
        "{home}/Library/pnpm/store",
        "node",
        "pnpm content-addressable store",
        check_installed="pnpm --version",
        purge_command="pnpm store prune",
        recovery="Re-downloaded on next `pnpm install`",
    ),
    CruftPattern(
        "{home}/.pnpm-store",
        "node",
        "pnpm store (legacy location)",
        check_installed="pnpm --version",
        purge_command="pnpm store prune",
        recovery="Re-downloaded on next `pnpm install`",
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
        "{home}/.colima",
        "docker",
        "Colima virtual machine, images, and volumes",
        check_installed="colima status",
        safe=False,
        recovery="Recreated by `colima start`; images and volumes are not restored",
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
        "{home}/Library/Developer/CoreSimulator/Devices",
        "xcode",
        "iOS Simulator device images (includes unavailable simulators)",
        check_installed="xcodebuild -version",
        safe=False,  # Holds installed apps and their data
        recovery="Recreated by Xcode; `xcrun simctl delete unavailable` prunes safely",
    ),
    # Homebrew
    CruftPattern(
        "{home}/Library/Caches/Homebrew",
        "homebrew",
        "Homebrew download cache",
        check_installed="brew --version",
        purge_command="brew cleanup --prune=all",
        recovery="Re-downloaded on next `brew install`",
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
        recovery="Re-downloaded on next `cargo build`",
    ),
    CruftPattern(
        "{home}/.cargo/git",
        "rust",
        "Cargo git dependency checkouts",
        check_installed="cargo --version",
        recovery="Re-cloned on next `cargo build`",
    ),
    CruftPattern(
        "{home}/go/pkg/mod",
        "go",
        "Go module cache",
        check_installed="go version",
        purge_command="go clean -modcache",
        recovery="Re-downloaded on next `go build`",
    ),
    CruftPattern(
        "{home}/Library/Caches/go-build",
        "go",
        "Go build cache",
        check_installed="go version",
        purge_command="go clean -cache",
        recovery="Rebuilt on next `go build`",
    ),
    # Conda
    CruftPattern(
        "{home}/miniconda3/pkgs",
        "python",
        "Conda package cache (miniconda3)",
        check_installed="conda --version",
        purge_command="conda clean --all --yes",
        recovery="Re-downloaded on next `conda install`",
    ),
    CruftPattern(
        "{home}/anaconda3/pkgs",
        "python",
        "Conda package cache (anaconda3)",
        check_installed="conda --version",
        purge_command="conda clean --all --yes",
        recovery="Re-downloaded on next `conda install`",
    ),
    CruftPattern(
        "{home}/.conda/pkgs",
        "python",
        "Conda package cache (user)",
        check_installed="conda --version",
        purge_command="conda clean --all --yes",
        recovery="Re-downloaded on next `conda install`",
    ),
    # IDEs
    CruftPattern(
        "{home}/Library/Caches/JetBrains",
        "ide",
        "JetBrains IDE caches and indexes",
        check_installed=None,
        recovery="Reindexed on next project open",
    ),
]

# Project-local directories that regenerate from a build or a test run. Many
# small directories rather than one big one, so they are reported as a single
# rolled-up candidate per category instead of thousands of rows.
PROJECT_CRUFT_NAMES: dict[str, tuple[str, str]] = {
    "__pycache__": ("python", "Regenerated on next import"),
    ".pytest_cache": ("testing", "Regenerated on next pytest run"),
    ".mypy_cache": ("python", "Regenerated on next mypy run"),
    ".ruff_cache": ("python", "Regenerated on next ruff run"),
    ".tox": ("testing", "Rebuilt on next tox run"),
    ".ipynb_checkpoints": ("python", "Recreated by Jupyter"),
}

# Project-local directories whose name is suggestive but whose contents must be
# probed before they can be proposed for deletion. See probes.probe_dist_dir.
PROJECT_PROBE_NAMES: dict[str, tuple[str, str]] = {
    "dist": ("python", "Rebuilt by `python -m build`"),
    "build": ("python", "Rebuilt by `python -m build`"),
}


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

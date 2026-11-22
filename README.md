# devclean

[![CI](https://github.com/gojiplus/devclean/actions/workflows/ci.yml/badge.svg)](https://github.com/gojiplus/devclean/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Disk cleanup for macOS developers that tells you *why* something is safe to delete.

Most cleanup tools match directory names. Name matching is how you lose data: a
directory called `dist/` next to a `pyproject.toml` is usually build output and
occasionally the only copy of a dataset. `devclean` reads the contents, and
sorts every candidate by how much evidence actually backs deleting it.

## Install

Download the wheel from [GitHub Releases](https://github.com/gojiplus/devclean/releases/latest)
and run `uv tool install ./devclean-*.whl` from the download directory.
To install the current development version, use Git.

```bash
uv tool install git+https://github.com/gojiplus/devclean.git
```

Or run it without installing:

```bash
uvx --from git+https://github.com/gojiplus/devclean.git devclean scan
```

## Use

```bash
devclean scan          # read-only inventory, never deletes
devclean plan          # the same candidates grouped by tier
devclean clean --tier auto --dry-run
devclean clean --tier auto
```

`scan --json` emits the same data for scripting. The scan reports allocated disk space. A loose
archive and its extracted copy each occupy space. A directory and the files
inside it count once. Display-only groups are excluded from the bulk cleanup
estimate. Hard links, shared APFS blocks, snapshots, and concurrent writes can
make the observed change in free space smaller or larger than the estimate.
Single-path cleanup measures the target filesystem. The batch summary observes
the home filesystem.


For scheduled cleanup of inactive projects, run from this checkout with a
Python interpreter outside the environments being cleaned:

```bash
python3 -m devclean.inactive --root ~/Documents/GitHub --days 14
python3 -m devclean.inactive --root ~/Documents/GitHub --days 14 --apply --prune-uv
```

The first command is a dry run. The second removes only direct-child `.venv`
directories in Git projects with both `pyproject.toml` and `uv.lock`. Recent
commits, checkouts, project files (including ignored data), environment changes,
and running processes protect a project. Inspection errors also preserve it.
Add `.devclean-keep` to opt a project out. Symlinked environments, tracked files,
and unexpected top-level environment contents are preserved.

Restore a removed environment with `uv sync --locked` in its project.
`--prune-uv` runs the installed uv version’s cache prune operation, which can also
remove centrally managed project environments. It skips while uv is running
and respects the cache lock.
Runs cannot overlap; rotating logs live in `~/.local/state/devclean/inactive.log`.
Schedule this command with cron using absolute paths and the checkout as its
working directory. The scheduled interpreter does not need devclean's `.venv`.

Each scan section can be switched off per run: `--no-venvs`, `--no-node`,
`--no-project`, `--no-system`, `--no-temp`. `--min-size N` raises the size
floor for caches, system artifacts, and temporary files and directories.

## Tiers

Every candidate carries a tier, the evidence behind it, and the command that
brings it back.

| Tier | Evidence | Bulk-deletable |
|---|---|---|
| `auto` | An available owner command can target the selected cache | yes |
| `verified` | A dependency directory has supporting recovery evidence | yes |
| `probe` | Name matched a known category; contents passed a shape check | no |
| `inspect` | A probe objected, and says why | no |

`devclean clean --tier` acts only on `auto` and `verified`. For uv, pip, and npm, the
preview shows the command and cache path that will be passed to the owning tool.
If the tool fails, the cleanup reports the failure. Broader cache operations
such as Homebrew cleanup require a separate decision about the tool's scope.
Display-only entries summarize multiple paths and cannot be deleted as a group.

## What the probes catch

A real example. This `dist/` sits next to a `pyproject.toml` and is gitignored. The probe reported the following:

```
$ devclean plan
inspect — 3.1 GiB (needs your decision)
     3.1 GiB  ~/Documents/GitHub/pai/dist
             back via: Rebuilt by `python -m build`
             concern: contains a subdirectory (_stage/) — dist/ should be flat
             concern: DATAVERSE_UPLOAD.md is not a wheel or sdist
             concern: pai_2022-2023_html.tar.gz is a tarball whose name carries
                      no release version — it may be data rather than a build artifact
             concern: gitignored — verify a retained copy before deleting
```

Those archives were a dataset staged for publication. Every structural signal
said "build artifact". Only the contents disagreed.

The same probes clear genuine build output without complaint — a `dist/` holding
`naampy-0.9.0-py3-none-any.whl` and a `.gitignore` reports no concerns.

## Claude Code plugin

The repo ships a skill that drives the CLI through a confirmation flow:
measure, show the list, resolve every concern, confirm per group, then verify
one restore actually works before calling it done.

```
/plugin marketplace add gojiplus/devclean
/plugin install devclean
```

## What it looks for

Per-user caches for uv, pip, npm, pnpm, yarn, Poetry, conda, Homebrew,
pre-commit, Cargo, Go, Gradle, Maven, Playwright, Selenium, JetBrains, Xcode and
the iOS simulator; PyTorch, HuggingFace and Whisper model caches; virtualenvs
and `node_modules` under your project directories or directly under your home
directory; and project-local caches
(`__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.tox`) rolled up
per category rather than listed one directory at a time. One pruned filesystem
walk supplies all project-level checks, including roots from
`additional_search_paths`.

On macOS, `devclean` also reports non-current TeX Live and R installations,
inactive python.org frameworks, Homebrew global Python package trees, retained
MacTeX installers, broken MacPorts prefixes, Chrome code-signing clones, and VS
Code extension directories marked obsolete. These system findings always stay
in `inspect`. A stale version may be intentional, and finding it does not grant
permission to delete it.

The scan also checks direct children of `/private/tmp`, `/var/tmp`, and the
current user's macOS temporary directory. Owned regular files and directories
are reported for inspection. An old
timestamp can come from the original dataset, even in a new scratch folder.
Verified virtualenvs and `node_modules` nested inside those parents are listed
separately. Before bulk removal, the environment checks run again. An unrelated
lockfile or an unexpected top-level virtualenv entry triggers individual review.
Overlapping parent and child candidates are counted only once in the scan total.

The scan also reports Codex and Claude storage by purpose: conversations and
memory, databases, installations, temporary files, and caches. Non-current
Codex daemon releases appear only when the `current` link resolves to a release
inside the expected installation directory. A non-current version may still be
running. These findings are always `inspect`, never bulk-deletable. Credentials
and settings are not scanned.

To remove unused old Codex daemon installations explicitly:

```bash
devclean clean-codex-releases --dry-run
devclean clean-codex-releases
```

This command preserves the current release, newer staged releases, and older
releases whose executables are open in visible processes. It requires a valid
`current` symlink and a successful `lsof` check, honors protected paths, and
rechecks the installation and processes before each deletion. `--force` skips
only the confirmation. It never deletes sessions, databases, settings, or
credentials. Close Codex before cleanup to avoid releases starting or updating
between checks. Permission failures stop cleanup with a nonzero exit status;
bulk tier cleanup also exits nonzero if any selected deletion fails.

Project `.benchmarks` directories are also inspection-only: they can contain
large downloaded corpora, but also unpublished results and Git checkouts. Verify
that unique work is preserved before deleting them. Their sizes participate in
the existing overlap-aware total, not the bulk-reclaimable total.

Model caches and anything a probe flags stay out of the bulk-deletable set.

## Configuration

Optional, at `./.devclean.toml` or `~/.devclean.toml`:

```toml
additional_search_paths = ["~/workspace", "/Volumes/code"]

[scan]
min_size_mb = 100
max_depth = 8
timeout_seconds = 120
include_system_artifacts = true

[safety]
protected_paths = ["~/important-project"]
```

Relative additional paths resolve from your home directory. Overlapping roots
are collapsed so a directory tree is not scanned twice.

`devclean config init` writes a starter file; `devclean config show` prints the
active settings.

## Safety

One guard, in `devclean/safety.py`, used by every deletion path. It refuses your
home directory, its top-level folders, system roots, temporary roots, anything
directly inside a system root, and any parent of your home directory.
Configured `protected_paths` are honored everywhere. Outside your home,
deletion is limited to children of the recognized temporary roots.

System artifact detection is inventory only. The bulk cleanup command cannot
delete system toolchains, package-manager prefixes, installers, Chrome clones,
or obsolete editor extensions.

Deleting a nested path such as `~/Documents/GitHub/project/.venv` is allowed —
that is the point — while `~/Documents` itself is not.

## Development

```bash
make install-dev
make check-all      # ruff, pyright, pydoclint, bandit, pytest
```

## License

MIT

# devclean

[![CI](https://github.com/gojiplus/devclean/workflows/CI/badge.svg)](https://github.com/gojiplus/devclean/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Disk cleanup for macOS developers that tells you *why* something is safe to delete.

Most cleanup tools match directory names. Name matching is how you lose data: a
directory called `dist/` next to a `pyproject.toml` is usually build output and
occasionally the only copy of a dataset. `devclean` reads the contents, and
sorts every candidate by how much evidence actually backs deleting it.

## Install

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

`scan --json` emits the same data for scripting.

## Tiers

Every candidate carries a tier, the evidence behind it, and the command that
brings it back.

| Tier | Evidence | Bulk-deletable |
|---|---|---|
| `auto` | The owning tool documents a purge command (`uv cache clean`, `npm cache clean`) | yes |
| `verified` | A marker file proves it is what its name says — `pyvenv.cfg`, `package.json` | yes |
| `probe` | Name matched a known category; contents passed a shape check | no |
| `inspect` | A probe objected, and says why | no |

`devclean clean --tier` acts only on `auto` and `verified`. Anything else has to
be named explicitly, so a directory whose contents were never understood cannot
be swept up by a batch command.

## What the probes catch

A real example. This `dist/` sits next to a `pyproject.toml` and is gitignored,
so nothing in git holds a copy:

```
$ devclean plan
inspect — 3.1 GB (needs your decision)
     3.1 GB  ~/Documents/GitHub/pai/dist
             back via: Rebuilt by `python -m build`
             concern: contains a subdirectory (_stage/) — dist/ should be flat
             concern: DATAVERSE_UPLOAD.md is not a wheel or sdist
             concern: pai_2022-2023_html.tar.gz is a tarball whose name carries
                      no release version — it may be data rather than a build artifact
             concern: gitignored — no copy in version control
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
and `node_modules` under your project directories; and project-local caches
(`__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.tox`) rolled up
per category rather than listed one directory at a time. It also checks direct
children of `/private/tmp`, `/var/tmp`, and the current user's macOS temporary
directory. Only directories owned by the current user are reported, and these
always stay in `inspect`: being in temporary storage is not proof that a
directory is unused or reproducible.

Model caches and anything a probe flags stay out of the bulk-deletable set.

## Configuration

Optional, at `./.devclean.toml` or `~/.devclean.toml`:

```toml
[scan]
min_size_mb = 100          # global floor; individual patterns may override it

[safety]
protected_paths = ["~/important-project"]
```

`devclean config init` writes a starter file; `devclean config show` prints the
active settings.

## Safety

One guard, in `devclean/safety.py`, used by every deletion path. It refuses your
home directory, its top-level folders, system roots, temporary roots, anything
directly inside a system root, and any parent of your home directory.
Configured `protected_paths` are honoured everywhere. Outside your home,
deletion is limited to children of the recognized temporary roots.

Deleting a nested path such as `~/Documents/GitHub/project/.venv` is allowed —
that is the point — while `~/Documents` itself is not.

## Development

```bash
uv sync --all-extras
make check-all      # ruff, mypy, bandit, pytest
```

## License

MIT

# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

## 0.4.0 - 2026-11-21

- `scan` and `plan` report large temporary files and directories for individual
  review. The cleanup skill explains how to check an archive, a Git remote, or
  a published dataset before deleting a working copy.
- Scheduled cleanup can remove an inactive project's `.venv` when its lockfile
  can rebuild it. A dry run lists eligible projects. Recent activity, tracked
  files, and unexpected environment contents protect the environment.
- Cache cleanup uses the owning package manager when its cache location matches
  the selected path. Space estimates exclude overlapping entries and
  display-only groups. Cleanup reports the observed change in free space.
- An explicitly protected directory now protects every descendant, including
  when the directory is also a built-in protected root. Older configs that list
  `/` block all cleanup until you narrow the list.
- Assistant storage is visible in scans. `clean-codex-releases` can remove old
  Codex installations after checking the current release and running processes.

## [0.3.0] - 2026-08-18

First tagged release.

### Added

- Detection for stale macOS toolchains, retained installers, broken MacPorts,
  Chrome code-signing clones, and obsolete VS Code extensions. These findings
  are always inspect-only; `--no-system` skips them for a run.
- Project scanning for configured roots and dependency directories directly
  under the home directory.

### Changed

- Project checks now share one pruned filesystem walk and batched size probes.
- System findings require individual review and cannot be deleted in bulk.
- Default scan settings changed: `timeout_seconds` rose from 30 to 120 and
  `max_depth` from 4 to 8, so default scans go deeper and are allowed to take
  longer.

### Removed

- Configuration keys that were read but never influenced behavior:
  `exclude_paths`, `exclude_patterns`, `parallel_workers`, `anthropic_api_key`,
  the whole `[display]` section, and the `require_confirmation`,
  `never_delete_patterns`, and `always_safe_patterns` safety keys. Setting any
  of them did nothing; `exclude_paths` in particular suggested a privacy
  guarantee the scanner never provided.
- The `config add-safe`, `config remove-safe`, and `config list-patterns`
  commands, which managed those inert keys.

### Fixed

- `scan` and `plan` now print scan-stage errors even when no candidates are
  found. Previously a scan whose stages all failed reported "Nothing found
  above the size floor." with no hint that anything went wrong, and `plan`
  never showed stage errors at all.

[0.3.0]: https://github.com/gojiplus/devclean/releases/tag/v0.3.0

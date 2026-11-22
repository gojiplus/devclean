---
name: devclean
description: Use when a Mac is low on disk space and needs developer cruft cleaned up — caches, virtualenvs, node_modules, build output — or when deciding whether a specific directory is safe to delete. Drives the devclean CLI, which classifies candidates by how much evidence backs deleting them; this skill supplies the confirmation flow the CLI deliberately does not automate.
---

# devclean

Free disk space without deleting anything that cannot come back.

`devclean` finds and classifies. You inspect, confirm, and verify. The split is
deliberate: the CLI can prove a directory is a virtualenv, but it cannot tell
whether a tarball is a release artifact or the only copy of a dataset. That
judgment is the job this skill exists to do.

## The rule that matters

**Never delete anything whose contents you have not accounted for.**

A directory named `dist/` sitting next to a `pyproject.toml` looks like build
output by every structural signal available. One real case held 3.1 GB of
Dataverse upload archives and was gitignored, so no copy existed in git. The
structure was not wrong — it was insufficient. Only reading the contents
settled it.

When a probe raises a concern, resolve it by finding out what the files
actually are. Do not resolve it by reasoning about what they probably are.

## Command map

- `devclean scan [--json] [-m MB]` — read-only inventory. `--json` for parsing.
- `devclean plan` — the same candidates grouped by tier, with recovery commands
  and concerns. Deletes nothing.
- `devclean clean --tier auto|verified [--dry-run]` — delete a whole tier.
- `devclean clean PATH [--dry-run]` — delete one named path.

Install: `uv tool install devclean` (or `uvx devclean`), or from the repo with
`uv sync && uv run devclean`.

## Tiers

| Tier | Means | Handling |
|---|---|---|
| `auto` | The installed tool supports a purge scoped to this directory | Bulk-deletable |
| `verified` | The dependency directory and its recovery evidence pass inspection | Bulk-deletable |
| `probe` | Name matched, contents passed a shape check | Show the user, get a yes |
| `inspect` | A probe objected, with reasons | **Read the contents. Report what they are. Then ask.** |

`clean --tier` refuses anything below `verified`. That is a guardrail, not an
obstacle to route around — if a candidate needs a per-path command, it needed a
human decision.

## Flow

1. **Measure first.** `df -h /System/Volumes/Data`, then `devclean scan`. Report
   the largest pools and what is regenerable, before proposing anything.
2. **Print the list before proposing a deletion.** Every time, including for
   `auto`. The user should never approve a count without seeing the items.
3. **Resolve every concern on `inspect` candidates.** `ls -lh` the directory,
   read any README inside it, check whether the contents are published
   elsewhere. Say what you found. A concern you cannot resolve is a no.
4. **Confirm per group, not per item.** One question for "the 20 virtualenvs",
   not twenty questions. But `inspect` items are confirmed individually.
5. **Order by yield.** Biggest safe pool first, so the user gets relief early
   and can stop whenever they have enough.
6. **Verify the restore path before claiming success.** Rebuild one deleted
   thing — `uv sync` in the smallest affected repo — and confirm it imports.
   Deleting is only reversible if reversal actually works.
7. **Check for collateral damage.** `git status --porcelain` in each touched
   repo. Files that were committed but should not have been (`.pyc` under
   `__pycache__`, for one real case) show up here as deletions. Restore them
   with `git checkout` and tell the user what happened.

## Inspecting scratch directories

When the user asks about temporary storage, rank individual files as well as
directories by allocated size. Inspect the largest children of mixed folders.
A session folder can hold a disposable environment beside the only copy of
annotations, embeddings, or a Git worktree. Name the smallest path that the
evidence supports deleting.

| Candidate | What to establish before proposing removal |
|---|---|
| Extracted data | Stream the corresponding member from the retained archive and compare its SHA-256 with the extracted file. Keep the archive and report which member restores the file. An archive can contain other unique members. |
| Standalone Git checkout | Find a retained checkout or remote, even if the temporary checkout has no configured remote. Verify its commits are reachable from retained refs. Check local branches, stashes, reflogs, staged and unstaged changes, untracked **and ignored** files, and registered worktrees. A clean status alone misses ignored data. Account for any extra files separately. |
| Linked Git worktree | Identify its owning repository with `git worktree list --porcelain`. Use Git's worktree removal command after checking for unique work, including ignored files. |
| Scratch virtualenv | Inspect `pyvenv.cfg`, the project manifest or lockfile, and unexpected contents. Check which programs have the environment open. Scope the proposal to the environment itself so adjacent scripts, results, and checkpoints survive. |
| Downloaded research dataset | Verify the upstream revision, filenames, sizes, and content IDs. Report the download cost and identify any locally collected data stored nearby. Use the cache owner's controls for shared storage. |

For age-based requests, give the cutoff and distinguish top-level entries from
old files inside newer folders. Extracted files can retain publication dates.
Check the newest descendant before calling a whole tree stale.

Check open files and working directories before removal. An empty process
check is a point-in-time observation. Report inaccessible paths as unmeasured.
For a list of scratch checkouts, show the exact subset that passed inspection
and recheck those paths immediately before an approved cleanup.

For published bundles, compare the local release archive with the publisher's
recorded checksum. Then compare individual members by content. Packaging
changes can produce different ZIP hashes while preserving every source PDF
and table. Check the manifests for acquisition URLs, version IDs, and exceptions
before dismissing unmatched documentation. A Git ignore rule alone tells you
nothing about whether a retained copy exists.

For managed caches, inspect the owning tool's scope. A cache purge can leave
settings and other data in place. Report the measured footprint and the
observed free-space change separately. A shared VM disk may retain its host
allocation even after its guest frees space.

## Reporting

Give per-step yield, not just a total — the user needs to judge whether the
expensive-to-restore steps earned their cost. State what you skipped and why.
If free space moved less than the sizes you deleted, say so rather than
reporting the projected number; on APFS, other processes write concurrently and
snapshots can retain deleted data (`tmutil listlocalsnapshots /`).

## Things that are not cruft

Leave these alone unless the user raises them:

- Model caches (`~/.cache/huggingface`) — recoverable but a slow re-download.
- Temporary-root candidates (`/private/tmp`, `/var/tmp`, and the per-user macOS
  temp directory) — location is not evidence that no process needs them or that
  another copy exists.
- Project-owned caches under `~/.cache/<project-name>` — the user's own data.
- Anything under a repo's data directories, however large.

`devclean` does not propose these for bulk deletion. Do not add them by hand.

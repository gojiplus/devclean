"""Confidence tiers for cleanup candidates.

The scanner finds things that *look* deletable. This module records how much
evidence backs that guess, so the caller can tell the difference between a
package cache with an official purge command and a directory that merely has a
suggestive name.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class Tier(StrEnum):
    """How much evidence backs deleting a candidate."""

    AUTO = "auto"
    """A tool owns this directory and documents a command to purge it."""

    VERIFIED = "verified"
    """A marker file proves the directory is what its name claims."""

    PROBE = "probe"
    """Name matches a known category and the contents passed a shape check."""

    INSPECT = "inspect"
    """A probe found something unexpected. Requires a human decision."""


BULK_DELETABLE = frozenset({Tier.AUTO, Tier.VERIFIED})
"""Tiers that ``devclean clean --tier`` will act on without per-path approval.

PROBE is excluded deliberately: passing a shape check means nothing surprising
was found, not that the contents were understood. INSPECT is excluded because a
probe actively objected.
"""


@dataclass
class Candidate:
    """Something that may be deletable, plus the evidence for and against."""

    path: Path
    size_bytes: int
    category: str
    description: str
    tier: Tier
    recovery: str
    """How this comes back — a command where one exists, prose where none does."""

    evidence: list[str] = field(default_factory=list)
    """Facts that justified the tier."""

    concerns: list[str] = field(default_factory=list)
    """What a probe objected to. Non-empty implies INSPECT."""

    member_count: int = 1
    """Paths rolled up into this candidate, for per-category aggregates."""

    member_sizes: dict[Path, int] = field(default_factory=dict, repr=False)
    """Per-directory measurements behind a display roll-up."""

    def downgrade(self, *concerns: str) -> None:
        """Drop to INSPECT and record why.

        Idempotent and monotonic: a candidate never climbs back up, so the
        order probes run in cannot change the outcome.
        """
        if not concerns:
            return
        self.concerns.extend(concerns)
        self.tier = Tier.INSPECT

    @property
    def bulk_deletable(self) -> bool:
        return (
            self.path.is_absolute()
            and self.tier in BULK_DELETABLE
            and not self.concerns
        )

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024**2)

    @property
    def size_gb(self) -> float:
        return self.size_bytes / (1024**3)

    @property
    def size_human(self) -> str:
        return format_bytes(self.size_bytes)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for ``devclean scan --json``."""
        return {
            "path": str(self.path),
            "size_bytes": self.size_bytes,
            "size_human": self.size_human,
            "category": self.category,
            "description": self.description,
            "tier": self.tier.value,
            "recovery": self.recovery,
            "evidence": list(self.evidence),
            "concerns": list(self.concerns),
            "member_count": self.member_count,
            "bulk_deletable": self.bulk_deletable,
        }


def format_bytes(size_bytes: int) -> str:
    """Format an allocated-space estimate in binary units."""
    if size_bytes >= 1024**3:
        return f"{size_bytes / 1024**3:.1f} GiB"
    return f"{size_bytes / 1024**2:.0f} MiB"


def footprint_bytes(candidates: Iterable[Candidate]) -> int:
    """Count each measured path once, including members of display roll-ups."""
    sizes: dict[Path, int] = {}
    for candidate in candidates:
        for path, size in (
            candidate.member_sizes or {candidate.path: candidate.size_bytes}
        ).items():
            sizes[path] = max(sizes.get(path, 0), size)

    # A fresh set of disjoint children can outweigh a cached parent measurement.
    children: dict[Path, int] = {}
    total = 0
    for path in sorted(sizes, key=lambda p: len(p.parts), reverse=True):
        size = max(sizes[path], children.get(path, 0))
        parent = next((p for p in path.parents if p in sizes), None)
        if parent is None:
            total += size
        else:
            children[parent] = children.get(parent, 0) + size
    return total

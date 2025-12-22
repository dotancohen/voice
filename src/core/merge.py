"""Three-way merge utilities for conflict resolution.

Uses 3-way merge algorithm to combine changes from two sources,
producing conflict markers when automatic merge is not possible.
This ensures no data loss during synchronization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from merge3 import Merge3


@dataclass
class MergeResult:
    """Result of a 3-way merge operation.

    Attributes:
        content: The merged content (may contain conflict markers if conflicted)
        has_conflicts: True if the merge produced conflicts
        conflict_count: Number of conflict regions in the merge
    """

    content: str
    has_conflicts: bool
    conflict_count: int


def merge_content(
    base: str,
    local: str,
    remote: str,
    local_label: str = "LOCAL",
    remote_label: str = "REMOTE",
) -> MergeResult:
    """Perform 3-way merge of text content.

    Merges changes from local and remote versions against a common base.
    When both versions modify the same region differently, conflict markers
    are inserted to preserve both versions.

    Args:
        base: The common ancestor version
        local: The local version (current device's changes)
        remote: The remote version (other device's changes)
        local_label: Label for local version in conflict markers
        remote_label: Label for remote version in conflict markers

    Returns:
        MergeResult with merged content and conflict status

    Examples:
        Clean merge (non-overlapping changes):
        >>> result = merge_content("a\\nb\\nc", "a\\nB\\nc", "a\\nb\\nC")
        >>> result.content
        'a\\nB\\nC'
        >>> result.has_conflicts
        False

        Conflict (overlapping changes):
        >>> result = merge_content("a\\nb\\nc", "a\\nX\\nc", "a\\nY\\nc")
        >>> result.has_conflicts
        True
        >>> "<<<<<<< LOCAL" in result.content
        True
    """
    # Handle edge cases
    if local == remote:
        # Both made same change - no conflict
        return MergeResult(content=local, has_conflicts=False, conflict_count=0)

    if local == base:
        # Only remote changed - use remote
        return MergeResult(content=remote, has_conflicts=False, conflict_count=0)

    if remote == base:
        # Only local changed - use local
        return MergeResult(content=local, has_conflicts=False, conflict_count=0)

    # Perform 3-way merge
    m3 = Merge3(
        base.splitlines(keepends=True),
        local.splitlines(keepends=True),
        remote.splitlines(keepends=True),
    )

    # Count conflicts
    conflict_count = 0
    for group in m3.merge_groups():
        if group[0] == "conflict":
            conflict_count += 1

    # Generate merged content with conflict markers if needed
    merged_lines = list(
        m3.merge_lines(
            name_a=local_label,
            name_b=remote_label,
            start_marker=f"<<<<<<< {local_label}",
            mid_marker="=======",
            end_marker=f">>>>>>> {remote_label}",
        )
    )

    content = "".join(merged_lines)

    return MergeResult(
        content=content,
        has_conflicts=conflict_count > 0,
        conflict_count=conflict_count,
    )


def get_base_version(
    local_content: str,
    remote_content: str,
    stored_base: Optional[str] = None,
) -> str:
    """Get the base version for 3-way merge.

    If a stored base version is available, use it. Otherwise, use empty
    string as base (treats both as new content, which will show full
    conflict if different).

    Args:
        local_content: Current local content
        remote_content: Incoming remote content
        stored_base: Previously stored base version, if available

    Returns:
        Base content for 3-way merge
    """
    if stored_base is not None:
        return stored_base

    # No base available - use empty string
    # This means any differences will be treated as conflicts
    return ""

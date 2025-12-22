"""Merge utilities for conflict resolution.

Uses diff algorithm to combine changes from two sources,
producing conflict markers when content differs.
This ensures no data loss during synchronization.
"""

from __future__ import annotations

from dataclasses import dataclass

from merge3 import Merge3


@dataclass
class MergeResult:
    """Result of a merge operation.

    Attributes:
        content: The merged content (may contain conflict markers if conflicted)
        has_conflicts: True if the merge produced conflicts
        conflict_count: Number of conflict regions in the merge
    """

    content: str
    has_conflicts: bool
    conflict_count: int


def merge_content(
    local: str,
    remote: str,
    local_label: str = "LOCAL",
    remote_label: str = "REMOTE",
) -> MergeResult:
    """Merge two versions of text content.

    Compares local and remote line-by-line. Lines that match are kept as-is.
    Lines that differ get wrapped in conflict markers to preserve both versions.

    Args:
        local: The local version (current device's content)
        remote: The remote version (other device's content)
        local_label: Label for local version in conflict markers
        remote_label: Label for remote version in conflict markers

    Returns:
        MergeResult with merged content and conflict status

    Examples:
        Identical content - no conflict:
        >>> result = merge_content("same", "same")
        >>> result.has_conflicts
        False

        Different content - conflict markers added:
        >>> result = merge_content("local version", "remote version")
        >>> result.has_conflicts
        True
        >>> "<<<<<<< LOCAL" in result.content
        True
    """
    if local == remote:
        return MergeResult(content=local, has_conflicts=False, conflict_count=0)

    # Use merge3 with empty base to do line-by-line diff
    # Lines that match stay as-is, differing lines get conflict markers
    m3 = Merge3(
        "".splitlines(keepends=True),  # empty base
        local.splitlines(keepends=True),
        remote.splitlines(keepends=True),
    )

    conflict_count = 0
    for group in m3.merge_groups():
        if group[0] == "conflict":
            conflict_count += 1

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

"""Merge utilities for Voice.

This module provides text merging functionality with conflict detection.

This is a wrapper around the Rust voicecore extension.

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Import from Rust extension
from voicecore import (
    MergeResult as RustMergeResult,
    merge_content as _rust_merge_content,
)

__all__ = ["MergeResult", "merge_content", "diff3_merge", "auto_merge_if_possible"]


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

    @classmethod
    def from_rust(cls, rust_result: RustMergeResult) -> "MergeResult":
        """Create from Rust MergeResult."""
        return cls(
            content=rust_result.content,
            has_conflicts=rust_result.has_conflicts,
            conflict_count=rust_result.conflict_count,
        )


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
    """
    rust_result = _rust_merge_content(local, remote, local_label, remote_label)
    return MergeResult.from_rust(rust_result)


def diff3_merge(base: str, local: str, remote: str) -> MergeResult:
    """Perform a 3-way merge of text content.

    If both local and remote made the same changes, they're accepted.
    If they made different changes to the same region, conflict markers are added.

    Args:
        base: Original content (common ancestor)
        local: Local version
        remote: Remote version

    Returns:
        MergeResult with merged content and conflict info
    """
    # If no base, use simple merge
    if not base:
        return merge_content(local, remote, "LOCAL", "REMOTE")

    # If local unchanged from base, take remote
    if local == base:
        return MergeResult(content=remote, has_conflicts=False, conflict_count=0)

    # If remote unchanged from base, take local
    if remote == base:
        return MergeResult(content=local, has_conflicts=False, conflict_count=0)

    # If local and remote are the same, no conflict
    if local == remote:
        return MergeResult(content=local, has_conflicts=False, conflict_count=0)

    # Both changed - need to do actual merge
    return merge_content(local, remote, "LOCAL", "REMOTE")


def auto_merge_if_possible(
    local_content: str,
    remote_content: str,
    base_content: Optional[str] = None,
) -> Optional[str]:
    """Attempt automatic merge if possible.

    Returns merged content if successful, None if conflicts exist.
    """
    if local_content == remote_content:
        return local_content

    if base_content is not None:
        result = diff3_merge(base_content, local_content, remote_content)
        if not result.has_conflicts:
            return result.content

    return None

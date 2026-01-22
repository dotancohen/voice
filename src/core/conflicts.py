"""Conflict resolution for Voice sync.

This module handles:
- Listing unresolved conflicts
- Resolving conflicts
- Diff3-style merging for text content

Resolution Choices:
- local: Keep local version (content conflicts)
- remote: Keep remote version (content conflicts)
- merge: Combine with conflict markers (content conflicts)
- restore: Undelete the note (delete conflicts)
- delete: Accept the deletion (delete conflicts)

Conflict Types:
- note_content: Two devices edited the same note simultaneously
- note_delete: One device edited while another deleted
- tag_rename: Two devices renamed the same tag simultaneously

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .database import Database
from .validation import uuid_to_hex

# Import merge functions from Rust
from voicecore import (
    diff3_merge as _rust_diff3_merge,
    auto_merge_if_possible as _rust_auto_merge_if_possible,
    get_diff_preview as _rust_get_diff_preview,
)

logger = logging.getLogger(__name__)


def _convert_row_uuids(row: Dict[str, Any], uuid_fields: List[str]) -> Dict[str, Any]:
    """Convert UUID bytes fields in a row to hex strings.

    Args:
        row: Database row as dict
        uuid_fields: List of field names to convert

    Returns:
        New dict with specified fields converted to hex strings
    """
    result = dict(row)
    for field_name in uuid_fields:
        if field_name in result and result[field_name] is not None:
            result[field_name] = uuid_to_hex(result[field_name])
    return result


class ConflictType(Enum):
    """Types of sync conflicts."""

    NOTE_CONTENT = "note_content"
    NOTE_DELETE = "note_delete"
    TAG_RENAME = "tag_rename"


class ResolutionChoice(Enum):
    """How to resolve a conflict."""

    KEEP_LOCAL = "keep_local"
    KEEP_REMOTE = "keep_remote"
    MERGE = "merge"  # Only for text content
    RESTORE = "restore"  # For delete conflicts - restore the deleted note
    DELETE = "delete"  # For delete conflicts - accept the deletion


@dataclass
class NoteContentConflict:
    """A conflict where two devices edited the same note."""

    id: str  # Conflict ID (UUID hex)
    note_id: str  # Note ID (UUID hex)
    local_content: str
    local_modified_at: int  # Unix timestamp
    local_device_id: str
    local_device_name: Optional[str]
    remote_content: str
    remote_modified_at: int  # Unix timestamp
    remote_device_id: str
    remote_device_name: Optional[str]
    created_at: int  # Unix timestamp
    resolved_at: Optional[int] = None  # Unix timestamp


@dataclass
class NoteDeleteConflict:
    """A conflict where one device edited while another deleted."""

    id: str  # Conflict ID (UUID hex)
    note_id: str  # Note ID (UUID hex)
    surviving_content: str
    surviving_modified_at: int  # Unix timestamp
    surviving_device_id: str
    surviving_device_name: Optional[str]
    deleted_at: int  # Unix timestamp
    deleting_device_id: str
    deleting_device_name: Optional[str]
    created_at: int  # Unix timestamp
    resolved_at: Optional[int] = None  # Unix timestamp


@dataclass
class TagRenameConflict:
    """A conflict where two devices renamed the same tag."""

    id: str  # Conflict ID (UUID hex)
    tag_id: str  # Tag ID (UUID hex)
    local_name: str
    local_modified_at: int  # Unix timestamp
    local_device_id: str
    local_device_name: Optional[str]
    remote_name: str
    remote_modified_at: int  # Unix timestamp
    remote_device_id: str
    remote_device_name: Optional[str]
    created_at: int  # Unix timestamp
    resolved_at: Optional[int] = None  # Unix timestamp


@dataclass
class MergeResult:
    """Result of a diff3-style merge."""

    merged_content: str
    has_conflicts: bool
    conflict_markers: List[Tuple[int, int]] = field(default_factory=list)


class ConflictManager:
    """Manages sync conflicts."""

    def __init__(self, db: Database) -> None:
        """Initialize conflict manager.

        Args:
            db: Database instance
        """
        self.db = db

    def get_unresolved_count(self) -> Dict[str, int]:
        """Get count of unresolved conflicts by type.

        Returns:
            Dict mapping conflict type to count
        """
        return self.db.get_unresolved_conflict_counts()

    def get_note_content_conflicts(
        self, include_resolved: bool = False
    ) -> List[NoteContentConflict]:
        """Get note content conflicts.

        Args:
            include_resolved: If True, include resolved conflicts

        Returns:
            List of NoteContentConflict objects
        """
        rows = self.db.get_note_content_conflicts(include_resolved)
        conflicts = []
        for row in rows:
            conflicts.append(NoteContentConflict(
                id=row["id"],
                note_id=row["note_id"],
                local_content=row["local_content"],
                local_modified_at=row["local_modified_at"],
                local_device_id=row["local_device_id"],
                local_device_name=row.get("local_device_name"),
                remote_content=row["remote_content"],
                remote_modified_at=row["remote_modified_at"],
                remote_device_id=row["remote_device_id"],
                remote_device_name=row.get("remote_device_name"),
                created_at=row["created_at"],
                resolved_at=row.get("resolved_at"),
            ))
        return conflicts

    def get_note_delete_conflicts(
        self, include_resolved: bool = False
    ) -> List[NoteDeleteConflict]:
        """Get note delete conflicts.

        Args:
            include_resolved: If True, include resolved conflicts

        Returns:
            List of NoteDeleteConflict objects
        """
        rows = self.db.get_note_delete_conflicts(include_resolved)
        conflicts = []
        for row in rows:
            conflicts.append(NoteDeleteConflict(
                id=row["id"],
                note_id=row["note_id"],
                surviving_content=row["surviving_content"],
                surviving_modified_at=row["surviving_modified_at"],
                surviving_device_id=row["surviving_device_id"],
                surviving_device_name=row.get("surviving_device_name"),
                deleted_at=row["deleted_at"],
                deleting_device_id=row["deleting_device_id"],
                deleting_device_name=row.get("deleting_device_name"),
                created_at=row["created_at"],
                resolved_at=row.get("resolved_at"),
            ))
        return conflicts

    def get_tag_rename_conflicts(
        self, include_resolved: bool = False
    ) -> List[TagRenameConflict]:
        """Get tag rename conflicts.

        Args:
            include_resolved: If True, include resolved conflicts

        Returns:
            List of TagRenameConflict objects
        """
        rows = self.db.get_tag_rename_conflicts(include_resolved)
        conflicts = []
        for row in rows:
            conflicts.append(TagRenameConflict(
                id=row["id"],
                tag_id=row["tag_id"],
                local_name=row["local_name"],
                local_modified_at=row["local_modified_at"],
                local_device_id=row["local_device_id"],
                local_device_name=row.get("local_device_name"),
                remote_name=row["remote_name"],
                remote_modified_at=row["remote_modified_at"],
                remote_device_id=row["remote_device_id"],
                remote_device_name=row.get("remote_device_name"),
                created_at=row["created_at"],
                resolved_at=row.get("resolved_at"),
            ))
        return conflicts

    def note_has_conflicts(self, note_id: str) -> bool:
        """Check if a note has any unresolved conflicts.

        Args:
            note_id: Note ID (UUID hex, can be partial prefix)

        Returns:
            True if the note has unresolved conflicts
        """
        note_id_lower = note_id.lower()
        for c in self.get_note_content_conflicts():
            if c.note_id.lower().startswith(note_id_lower):
                return True
        for c in self.get_note_delete_conflicts():
            if c.note_id.lower().startswith(note_id_lower):
                return True
        return False

    def get_note_conflict_types(self, note_id: str) -> List[str]:
        """Get the types of unresolved conflicts for a note.

        Args:
            note_id: Note ID (UUID hex, can be partial prefix)

        Returns:
            List of conflict type strings (e.g., ["content", "delete"])
        """
        note_id_lower = note_id.lower()
        types = []
        for c in self.get_note_content_conflicts():
            if c.note_id.lower().startswith(note_id_lower):
                if "content" not in types:
                    types.append("content")
        for c in self.get_note_delete_conflicts():
            if c.note_id.lower().startswith(note_id_lower):
                if "delete" not in types:
                    types.append("delete")
        return types

    def resolve_note_content_conflict(
        self,
        conflict_id: str,
        choice: ResolutionChoice,
        merged_content: Optional[str] = None,
    ) -> bool:
        """Resolve a note content conflict.

        Args:
            conflict_id: Conflict ID (UUID hex)
            choice: How to resolve (KEEP_LOCAL, KEEP_REMOTE, or MERGE)
            merged_content: Merged content (required if choice is MERGE)

        Returns:
            True if resolved successfully
        """
        # Get the conflict to determine content
        conflicts = self.db.get_note_content_conflicts(include_resolved=True)
        conflict = None
        for c in conflicts:
            if c["id"] == conflict_id:
                conflict = c
                break

        if not conflict:
            return False

        # Determine new content
        if choice == ResolutionChoice.KEEP_LOCAL:
            new_content = conflict["local_content"]
        elif choice == ResolutionChoice.KEEP_REMOTE:
            new_content = conflict["remote_content"]
        elif choice == ResolutionChoice.MERGE:
            if merged_content is None:
                raise ValueError("merged_content required for MERGE resolution")
            new_content = merged_content
        else:
            raise ValueError(f"Invalid choice for note content: {choice}")

        result = self.db.resolve_note_content_conflict(conflict_id, new_content)
        if result:
            logger.info(f"Resolved note content conflict {conflict_id} with {choice.value}")
        return result

    def resolve_note_delete_conflict(
        self,
        conflict_id: str,
        choice: ResolutionChoice,
    ) -> bool:
        """Resolve a note delete conflict.

        Args:
            conflict_id: Conflict ID (UUID hex)
            choice: How to resolve (RESTORE to undelete, DELETE to accept deletion)

        Returns:
            True if resolved successfully
        """
        if choice == ResolutionChoice.RESTORE:
            restore_note = True
        elif choice == ResolutionChoice.DELETE:
            restore_note = False
        else:
            raise ValueError(f"Invalid choice for note delete: {choice}")

        result = self.db.resolve_note_delete_conflict(conflict_id, restore_note)
        if result:
            logger.info(f"Resolved note delete conflict {conflict_id} with {choice.value}")
        return result

    def resolve_tag_rename_conflict(
        self,
        conflict_id: str,
        choice: ResolutionChoice,
    ) -> bool:
        """Resolve a tag rename conflict.

        Args:
            conflict_id: Conflict ID (UUID hex)
            choice: How to resolve (KEEP_LOCAL or KEEP_REMOTE)

        Returns:
            True if resolved successfully
        """
        # Get the conflict to determine the name
        conflicts = self.db.get_tag_rename_conflicts(include_resolved=True)
        conflict = None
        for c in conflicts:
            if c["id"] == conflict_id:
                conflict = c
                break

        if not conflict:
            return False

        # Determine new name
        if choice == ResolutionChoice.KEEP_LOCAL:
            new_name = conflict["local_name"]
        elif choice == ResolutionChoice.KEEP_REMOTE:
            new_name = conflict["remote_name"]
        else:
            raise ValueError(f"Invalid choice for tag rename: {choice}")

        result = self.db.resolve_tag_rename_conflict(conflict_id, new_name)
        if result:
            logger.info(f"Resolved tag rename conflict {conflict_id} with {choice.value}")
        return result

    def find_and_resolve_conflict(
        self,
        conflict_id_prefix: str,
        choice: ResolutionChoice,
        merged_content: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """Find a conflict by ID prefix and resolve it.

        This method handles finding the conflict across all types and
        validating that the resolution choice is valid for that type.

        Args:
            conflict_id_prefix: Full or partial conflict ID (UUID hex)
            choice: How to resolve the conflict
            merged_content: Merged content for MERGE resolution (optional)

        Returns:
            Tuple of (success, conflict_type, error_message)
            - success: True if resolved
            - conflict_type: "note_content", "note_delete", "tag_rename", or ""
            - error_message: Error description if not successful, None otherwise
        """
        # Check note content conflicts
        for c in self.get_note_content_conflicts():
            if c.id.startswith(conflict_id_prefix) or c.id == conflict_id_prefix:
                # Validate choice
                if choice not in [
                    ResolutionChoice.KEEP_LOCAL,
                    ResolutionChoice.KEEP_REMOTE,
                    ResolutionChoice.MERGE,
                ]:
                    return False, "note_content", (
                        "Note content conflicts can only be resolved with "
                        "'keep_local', 'keep_remote', or 'merge'"
                    )

                # Handle merge
                actual_merged = merged_content
                if choice == ResolutionChoice.MERGE and actual_merged is None:
                    # Try auto-merge
                    actual_merged = auto_merge_if_possible(
                        c.local_content, c.remote_content
                    )
                    if actual_merged is None:
                        return False, "note_content", (
                            "Cannot auto-merge conflicting content. "
                            "Provide merged_content explicitly."
                        )

                result = self.resolve_note_content_conflict(
                    c.id, choice, actual_merged
                )
                if result:
                    return True, "note_content", None
                return False, "note_content", "Failed to resolve conflict"

        # Check note delete conflicts
        for c in self.get_note_delete_conflicts():
            if c.id.startswith(conflict_id_prefix) or c.id == conflict_id_prefix:
                # Validate choice
                if choice not in [
                    ResolutionChoice.RESTORE,
                    ResolutionChoice.DELETE,
                ]:
                    return False, "note_delete", (
                        "Note delete conflicts can only be resolved with "
                        "'restore' (undelete) or 'delete' (accept deletion)"
                    )

                result = self.resolve_note_delete_conflict(c.id, choice)
                if result:
                    return True, "note_delete", None
                return False, "note_delete", "Failed to resolve conflict"

        # Check tag rename conflicts
        for c in self.get_tag_rename_conflicts():
            if c.id.startswith(conflict_id_prefix) or c.id == conflict_id_prefix:
                # Validate choice
                if choice not in [
                    ResolutionChoice.KEEP_LOCAL,
                    ResolutionChoice.KEEP_REMOTE,
                ]:
                    return False, "tag_rename", (
                        "Tag rename conflicts can only be resolved with "
                        "'keep_local' or 'keep_remote'"
                    )

                result = self.resolve_tag_rename_conflict(c.id, choice)
                if result:
                    return True, "tag_rename", None
                return False, "tag_rename", "Failed to resolve conflict"

        return False, "", f"Conflict with ID starting with '{conflict_id_prefix}' not found"


def diff3_merge(
    base: str,
    local: str,
    remote: str,
) -> MergeResult:
    """Perform a diff3-style merge of text content.

    This is a thin wrapper around the Rust implementation.

    If both local and remote made the same changes, they're accepted.
    If they made different changes to the same region, conflict markers are added.

    Args:
        base: Original content (common ancestor)
        local: Local version
        remote: Remote version

    Returns:
        MergeResult with merged content and conflict info
    """
    result = _rust_diff3_merge(base, local, remote)
    return MergeResult(
        merged_content=result["content"],
        has_conflicts=result["has_conflicts"],
        conflict_markers=[],  # Rust returns conflict_count, not markers
    )


def auto_merge_if_possible(
    local_content: str,
    remote_content: str,
    base_content: Optional[str] = None,
) -> Optional[str]:
    """Attempt automatic merge if possible.

    This is a thin wrapper around the Rust implementation.

    Returns merged content if successful, None if conflicts exist.

    Args:
        local_content: Local version
        remote_content: Remote version
        base_content: Optional common ancestor

    Returns:
        Merged content if no conflicts, None otherwise
    """
    return _rust_auto_merge_if_possible(local_content, remote_content, base_content)


def get_diff_preview(local: str, remote: str) -> str:
    """Get a human-readable diff between two versions.

    This is a thin wrapper around the Rust implementation.

    Args:
        local: Local content
        remote: Remote content

    Returns:
        Unified diff string
    """
    return _rust_get_diff_preview(local, remote)

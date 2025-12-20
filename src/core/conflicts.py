"""Conflict resolution for Voice Rewrite sync.

This module handles:
- Listing unresolved conflicts
- Resolving conflicts (choose local, remote, or merge)
- Diff3-style merging for text content

Conflict Types:
- note_content: Two devices edited the same note simultaneously
- note_delete: One device edited while another deleted
- tag_rename: Two devices renamed the same tag simultaneously

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import difflib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from uuid6 import uuid7

from .database import Database, get_local_device_id
from .validation import uuid_to_hex, validate_uuid_hex

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
    KEEP_BOTH = "keep_both"  # For delete conflicts - keep the note


@dataclass
class NoteContentConflict:
    """A conflict where two devices edited the same note."""

    id: str  # Conflict ID (UUID hex)
    note_id: str  # Note ID (UUID hex)
    local_content: str
    local_modified_at: str
    local_device_id: str
    local_device_name: Optional[str]
    remote_content: str
    remote_modified_at: str
    remote_device_id: str
    remote_device_name: Optional[str]
    created_at: str
    resolved_at: Optional[str] = None


@dataclass
class NoteDeleteConflict:
    """A conflict where one device edited while another deleted."""

    id: str  # Conflict ID (UUID hex)
    note_id: str  # Note ID (UUID hex)
    surviving_content: str
    surviving_modified_at: str
    surviving_device_id: str
    surviving_device_name: Optional[str]
    deleted_at: str
    deleting_device_id: str
    deleting_device_name: Optional[str]
    created_at: str
    resolved_at: Optional[str] = None


@dataclass
class TagRenameConflict:
    """A conflict where two devices renamed the same tag."""

    id: str  # Conflict ID (UUID hex)
    tag_id: str  # Tag ID (UUID hex)
    local_name: str
    local_modified_at: str
    local_device_id: str
    local_device_name: Optional[str]
    remote_name: str
    remote_modified_at: str
    remote_device_id: str
    remote_device_name: Optional[str]
    created_at: str
    resolved_at: Optional[str] = None


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
        counts = {
            "note_content": 0,
            "note_delete": 0,
            "tag_rename": 0,
            "total": 0,
        }

        with self.db.conn:
            cursor = self.db.conn.cursor()

            cursor.execute(
                "SELECT COUNT(*) as count FROM conflicts_note_content WHERE resolved_at IS NULL"
            )
            counts["note_content"] = cursor.fetchone()["count"]

            cursor.execute(
                "SELECT COUNT(*) as count FROM conflicts_note_delete WHERE resolved_at IS NULL"
            )
            counts["note_delete"] = cursor.fetchone()["count"]

            cursor.execute(
                "SELECT COUNT(*) as count FROM conflicts_tag_rename WHERE resolved_at IS NULL"
            )
            counts["tag_rename"] = cursor.fetchone()["count"]

            counts["total"] = (
                counts["note_content"] + counts["note_delete"] + counts["tag_rename"]
            )

        return counts

    def get_note_content_conflicts(
        self, include_resolved: bool = False
    ) -> List[NoteContentConflict]:
        """Get note content conflicts.

        Args:
            include_resolved: If True, include resolved conflicts

        Returns:
            List of NoteContentConflict objects
        """
        query = """
            SELECT id, note_id, local_content, local_modified_at, local_device_id,
                   local_device_name, remote_content, remote_modified_at,
                   remote_device_id, remote_device_name, created_at, resolved_at
            FROM conflicts_note_content
        """
        if not include_resolved:
            query += " WHERE resolved_at IS NULL"
        query += " ORDER BY created_at DESC"

        uuid_fields = ["id", "note_id", "local_device_id", "remote_device_id"]
        conflicts = []
        with self.db.conn:
            cursor = self.db.conn.cursor()
            cursor.execute(query)
            for row in cursor.fetchall():
                converted = _convert_row_uuids(dict(row), uuid_fields)
                conflicts.append(NoteContentConflict(
                    id=converted["id"],
                    note_id=converted["note_id"],
                    local_content=converted["local_content"],
                    local_modified_at=converted["local_modified_at"],
                    local_device_id=converted["local_device_id"],
                    local_device_name=converted.get("local_device_name"),
                    remote_content=converted["remote_content"],
                    remote_modified_at=converted["remote_modified_at"],
                    remote_device_id=converted["remote_device_id"],
                    remote_device_name=converted.get("remote_device_name"),
                    created_at=converted["created_at"],
                    resolved_at=converted.get("resolved_at"),
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
        query = """
            SELECT id, note_id, surviving_content, surviving_modified_at,
                   surviving_device_id, surviving_device_name, deleted_at,
                   deleting_device_id, deleting_device_name, created_at, resolved_at
            FROM conflicts_note_delete
        """
        if not include_resolved:
            query += " WHERE resolved_at IS NULL"
        query += " ORDER BY created_at DESC"

        uuid_fields = ["id", "note_id", "surviving_device_id", "deleting_device_id"]
        conflicts = []
        with self.db.conn:
            cursor = self.db.conn.cursor()
            cursor.execute(query)
            for row in cursor.fetchall():
                converted = _convert_row_uuids(dict(row), uuid_fields)
                conflicts.append(NoteDeleteConflict(
                    id=converted["id"],
                    note_id=converted["note_id"],
                    surviving_content=converted["surviving_content"],
                    surviving_modified_at=converted["surviving_modified_at"],
                    surviving_device_id=converted["surviving_device_id"],
                    surviving_device_name=converted.get("surviving_device_name"),
                    deleted_at=converted["deleted_at"],
                    deleting_device_id=converted["deleting_device_id"],
                    deleting_device_name=converted.get("deleting_device_name"),
                    created_at=converted["created_at"],
                    resolved_at=converted.get("resolved_at"),
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
        query = """
            SELECT id, tag_id, local_name, local_modified_at, local_device_id,
                   local_device_name, remote_name, remote_modified_at,
                   remote_device_id, remote_device_name, created_at, resolved_at
            FROM conflicts_tag_rename
        """
        if not include_resolved:
            query += " WHERE resolved_at IS NULL"
        query += " ORDER BY created_at DESC"

        uuid_fields = ["id", "tag_id", "local_device_id", "remote_device_id"]
        conflicts = []
        with self.db.conn:
            cursor = self.db.conn.cursor()
            cursor.execute(query)
            for row in cursor.fetchall():
                converted = _convert_row_uuids(dict(row), uuid_fields)
                conflicts.append(TagRenameConflict(
                    id=converted["id"],
                    tag_id=converted["tag_id"],
                    local_name=converted["local_name"],
                    local_modified_at=converted["local_modified_at"],
                    local_device_id=converted["local_device_id"],
                    local_device_name=converted.get("local_device_name"),
                    remote_name=converted["remote_name"],
                    remote_modified_at=converted["remote_modified_at"],
                    remote_device_id=converted["remote_device_id"],
                    remote_device_name=converted.get("remote_device_name"),
                    created_at=converted["created_at"],
                    resolved_at=converted.get("resolved_at"),
                ))

        return conflicts

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
        conflict_id_bytes = uuid.UUID(hex=conflict_id).bytes
        device_id = get_local_device_id()

        with self.db.conn:
            cursor = self.db.conn.cursor()

            # Get the conflict
            cursor.execute(
                """SELECT note_id, local_content, remote_content
                   FROM conflicts_note_content WHERE id = ?""",
                (conflict_id_bytes,),
            )
            row = cursor.fetchone()
            if not row:
                return False

            note_id = row["note_id"]

            # Determine new content
            if choice == ResolutionChoice.KEEP_LOCAL:
                new_content = row["local_content"]
            elif choice == ResolutionChoice.KEEP_REMOTE:
                new_content = row["remote_content"]
            elif choice == ResolutionChoice.MERGE:
                if merged_content is None:
                    raise ValueError("merged_content required for MERGE resolution")
                new_content = merged_content
            else:
                raise ValueError(f"Invalid choice for note content: {choice}")

            # Update the note
            cursor.execute(
                """UPDATE notes SET content = ?, modified_at = datetime('now'), device_id = ?
                   WHERE id = ?""",
                (new_content, device_id, note_id),
            )

            # Mark conflict as resolved
            cursor.execute(
                """UPDATE conflicts_note_content SET resolved_at = datetime('now')
                   WHERE id = ?""",
                (conflict_id_bytes,),
            )

            self.db.conn.commit()

        logger.info(f"Resolved note content conflict {conflict_id} with {choice.value}")
        return True

    def resolve_note_delete_conflict(
        self,
        conflict_id: str,
        choice: ResolutionChoice,
    ) -> bool:
        """Resolve a note delete conflict.

        Args:
            conflict_id: Conflict ID (UUID hex)
            choice: How to resolve (KEEP_BOTH to restore, KEEP_REMOTE to accept delete)

        Returns:
            True if resolved successfully
        """
        conflict_id_bytes = uuid.UUID(hex=conflict_id).bytes
        device_id = get_local_device_id()

        with self.db.conn:
            cursor = self.db.conn.cursor()

            # Get the conflict
            cursor.execute(
                """SELECT note_id, surviving_content
                   FROM conflicts_note_delete WHERE id = ?""",
                (conflict_id_bytes,),
            )
            row = cursor.fetchone()
            if not row:
                return False

            note_id = row["note_id"]

            if choice == ResolutionChoice.KEEP_BOTH:
                # Restore the note with surviving content
                cursor.execute(
                    """UPDATE notes SET content = ?, deleted_at = NULL,
                       modified_at = datetime('now'), device_id = ?
                       WHERE id = ?""",
                    (row["surviving_content"], device_id, note_id),
                )
            elif choice == ResolutionChoice.KEEP_REMOTE:
                # Accept the deletion - note stays deleted
                pass
            else:
                raise ValueError(f"Invalid choice for note delete: {choice}")

            # Mark conflict as resolved
            cursor.execute(
                """UPDATE conflicts_note_delete SET resolved_at = datetime('now')
                   WHERE id = ?""",
                (conflict_id_bytes,),
            )

            self.db.conn.commit()

        logger.info(f"Resolved note delete conflict {conflict_id} with {choice.value}")
        return True

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
        conflict_id_bytes = uuid.UUID(hex=conflict_id).bytes
        device_id = get_local_device_id()

        with self.db.conn:
            cursor = self.db.conn.cursor()

            # Get the conflict
            cursor.execute(
                """SELECT tag_id, local_name, remote_name
                   FROM conflicts_tag_rename WHERE id = ?""",
                (conflict_id_bytes,),
            )
            row = cursor.fetchone()
            if not row:
                return False

            tag_id = row["tag_id"]

            # Determine new name
            if choice == ResolutionChoice.KEEP_LOCAL:
                new_name = row["local_name"]
            elif choice == ResolutionChoice.KEEP_REMOTE:
                new_name = row["remote_name"]
            else:
                raise ValueError(f"Invalid choice for tag rename: {choice}")

            # Update the tag
            cursor.execute(
                """UPDATE tags SET name = ?, modified_at = datetime('now'), device_id = ?
                   WHERE id = ?""",
                (new_name, device_id, tag_id),
            )

            # Mark conflict as resolved
            cursor.execute(
                """UPDATE conflicts_tag_rename SET resolved_at = datetime('now')
                   WHERE id = ?""",
                (conflict_id_bytes,),
            )

            self.db.conn.commit()

        logger.info(f"Resolved tag rename conflict {conflict_id} with {choice.value}")
        return True

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
                    ResolutionChoice.KEEP_BOTH,
                    ResolutionChoice.KEEP_REMOTE,
                ]:
                    return False, "note_delete", (
                        "Note delete conflicts can only be resolved with "
                        "'keep_both' (restore) or 'keep_remote' (accept delete)"
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

    If both local and remote made the same changes, they're accepted.
    If they made different changes to the same region, conflict markers are added.

    Args:
        base: Original content (common ancestor)
        local: Local version
        remote: Remote version

    Returns:
        MergeResult with merged content and conflict info
    """
    # Split into lines for merging
    base_lines = base.splitlines(keepends=True)
    local_lines = local.splitlines(keepends=True)
    remote_lines = remote.splitlines(keepends=True)

    # If no base, try simple merge
    if not base_lines:
        return _simple_merge(local_lines, remote_lines)

    # Use difflib to find differences
    local_diff = list(difflib.unified_diff(base_lines, local_lines, n=0))
    remote_diff = list(difflib.unified_diff(base_lines, remote_lines, n=0))

    # Simple case: one side has no changes
    if not local_diff[2:]:  # Skip header lines
        return MergeResult(merged_content=remote, has_conflicts=False)
    if not remote_diff[2:]:
        return MergeResult(merged_content=local, has_conflicts=False)

    # Both sides have changes - use merge3
    return _merge3(base_lines, local_lines, remote_lines)


def _simple_merge(local_lines: List[str], remote_lines: List[str]) -> MergeResult:
    """Simple merge when there's no base version."""
    if local_lines == remote_lines:
        return MergeResult(merged_content="".join(local_lines), has_conflicts=False)

    # Create a merged version with conflict markers
    merged = []
    merged.append("<<<<<<< LOCAL\n")
    merged.extend(local_lines)
    merged.append("=======\n")
    merged.extend(remote_lines)
    merged.append(">>>>>>> REMOTE\n")

    return MergeResult(
        merged_content="".join(merged),
        has_conflicts=True,
        conflict_markers=[(0, len(merged))],
    )


def _merge3(
    base_lines: List[str],
    local_lines: List[str],
    remote_lines: List[str],
) -> MergeResult:
    """Perform 3-way merge using difflib.

    This is a simplified 3-way merge that handles the most common cases.
    """
    import difflib

    # Use SequenceMatcher to find matching blocks
    local_matcher = difflib.SequenceMatcher(None, base_lines, local_lines)
    remote_matcher = difflib.SequenceMatcher(None, base_lines, remote_lines)

    merged = []
    has_conflicts = False
    conflict_markers = []

    # Get all changes from both sides
    local_ops = local_matcher.get_opcodes()
    remote_ops = remote_matcher.get_opcodes()

    # Simple merge: take local changes that don't conflict with remote
    # This is a simplified algorithm that works for non-overlapping edits

    # For now, if both sides changed, use conflict markers
    local_changed = any(op[0] != "equal" for op in local_ops)
    remote_changed = any(op[0] != "equal" for op in remote_ops)

    if local_changed and remote_changed:
        # Check if changes are identical
        if local_lines == remote_lines:
            return MergeResult(merged_content="".join(local_lines), has_conflicts=False)

        # Create conflict markers
        start_line = len(merged)
        merged.append("<<<<<<< LOCAL\n")
        merged.extend(local_lines)
        merged.append("=======\n")
        merged.extend(remote_lines)
        merged.append(">>>>>>> REMOTE\n")
        conflict_markers.append((start_line, len(merged)))
        has_conflicts = True
    elif local_changed:
        merged.extend(local_lines)
    elif remote_changed:
        merged.extend(remote_lines)
    else:
        merged.extend(base_lines)

    return MergeResult(
        merged_content="".join(merged),
        has_conflicts=has_conflicts,
        conflict_markers=conflict_markers,
    )


def auto_merge_if_possible(
    local_content: str,
    remote_content: str,
    base_content: Optional[str] = None,
) -> Optional[str]:
    """Attempt automatic merge if possible.

    Returns merged content if successful, None if conflicts exist.

    Args:
        local_content: Local version
        remote_content: Remote version
        base_content: Optional common ancestor

    Returns:
        Merged content if no conflicts, None otherwise
    """
    if local_content == remote_content:
        return local_content

    if base_content:
        result = diff3_merge(base_content, local_content, remote_content)
        if not result.has_conflicts:
            return result.merged_content

    return None


def get_diff_preview(local: str, remote: str) -> str:
    """Get a human-readable diff between two versions.

    Args:
        local: Local content
        remote: Remote content

    Returns:
        Unified diff string
    """
    local_lines = local.splitlines(keepends=True)
    remote_lines = remote.splitlines(keepends=True)

    diff = difflib.unified_diff(
        local_lines,
        remote_lines,
        fromfile="Local",
        tofile="Remote",
        lineterm="",
    )

    return "".join(diff)

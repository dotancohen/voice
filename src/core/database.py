"""Database operations for Voice.

This module provides all data access functionality using SQLite.
All methods return JSON-serializable types (dicts, lists, primitives)
to support future CLI and web server modes.

This is a wrapper around the Rust voice_core extension.

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Import Database from the Rust extension
from voice_core import Database as RustDatabase
from voice_core import set_local_device_id as _rust_set_local_device_id
import uuid as uuid_module

logger = logging.getLogger(__name__)


def set_local_device_id(device_id: Union[bytes, str]) -> None:
    """Set the local device ID for database operations.

    Args:
        device_id: UUID7 bytes or hex string of this device
    """
    if isinstance(device_id, bytes):
        device_id = uuid_module.UUID(bytes=device_id).hex
    _rust_set_local_device_id(device_id)


__all__ = ["Database", "set_local_device_id"]


class Database:
    """Wrapper around the Rust Database for backward compatibility.

    This class provides the same interface as the original Python Database
    but delegates to the Rust implementation.
    """

    def __init__(self, db_path: Union[Path, str]) -> None:
        """Initialize database connection.

        Args:
            db_path: Path to the SQLite database file, or ':memory:' for in-memory
        """
        path_str = str(db_path) if isinstance(db_path, Path) else db_path
        self._rust_db = RustDatabase(path_str)
        logger.info(f"Opened Rust database at {path_str}")

    def get_all_notes(self) -> List[Dict[str, Any]]:
        """Get all non-deleted notes."""
        return self._rust_db.get_all_notes()

    def get_note(self, note_id: Union[bytes, str]) -> Optional[Dict[str, Any]]:
        """Get a specific note by ID."""
        if isinstance(note_id, bytes):
            import uuid
            note_id = uuid.UUID(bytes=note_id).hex
        return self._rust_db.get_note(note_id)

    def create_note(self, content: str = "") -> str:
        """Create a new note."""
        return self._rust_db.create_note(content)

    def update_note(self, note_id: Union[bytes, str], content: str) -> bool:
        """Update a note's content."""
        if isinstance(note_id, bytes):
            import uuid
            note_id = uuid.UUID(bytes=note_id).hex
        return self._rust_db.update_note(note_id, content)

    def delete_note(self, note_id: Union[bytes, str]) -> bool:
        """Soft delete a note."""
        if isinstance(note_id, bytes):
            import uuid
            note_id = uuid.UUID(bytes=note_id).hex
        return self._rust_db.delete_note(note_id)

    def get_all_tags(self) -> List[Dict[str, Any]]:
        """Get all non-deleted tags."""
        return self._rust_db.get_all_tags()

    def get_tag_descendants(self, tag_id: Union[bytes, str]) -> List[bytes]:
        """Get all descendant tag IDs for a tag."""
        if isinstance(tag_id, bytes):
            tag_id = uuid_module.UUID(bytes=tag_id).hex
        hex_ids = self._rust_db.get_tag_descendants(tag_id)
        # Convert hex strings back to bytes for backward compatibility
        return [uuid_module.UUID(hex=h).bytes for h in hex_ids]

    def filter_notes(self, tag_ids: List[Union[bytes, str]]) -> List[Dict[str, Any]]:
        """Filter notes by tag IDs."""
        # Convert bytes to hex strings
        hex_ids = []
        for tid in tag_ids:
            if isinstance(tid, bytes):
                import uuid
                hex_ids.append(uuid.UUID(bytes=tid).hex)
            else:
                hex_ids.append(tid)
        return self._rust_db.filter_notes(hex_ids)

    def get_tag(self, tag_id: Union[bytes, str]) -> Optional[Dict[str, Any]]:
        """Get a specific tag by ID."""
        if isinstance(tag_id, bytes):
            import uuid
            tag_id = uuid.UUID(bytes=tag_id).hex
        return self._rust_db.get_tag(tag_id)

    def get_tags_by_name(self, name: str) -> List[Dict[str, Any]]:
        """Get all tags with a specific name."""
        return self._rust_db.get_tags_by_name(name)

    def get_tag_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        """Get a tag by its hierarchical path."""
        return self._rust_db.get_tag_by_path(path)

    def get_all_tags_by_path(self, path: str) -> List[Dict[str, Any]]:
        """Get all tags matching a path (for ambiguous names)."""
        return self._rust_db.get_all_tags_by_path(path)

    def is_tag_name_ambiguous(self, name: str) -> bool:
        """Check if a tag name exists multiple times."""
        return self._rust_db.is_tag_name_ambiguous(name)

    def search_notes(
        self,
        text_query: Optional[str] = None,
        tag_id_groups: Optional[List[List[Union[bytes, str]]]] = None,
    ) -> List[Dict[str, Any]]:
        """Search notes by text and/or tags."""
        # Convert bytes to hex strings in tag_id_groups
        converted_groups = None
        if tag_id_groups is not None:
            converted_groups = []
            for group in tag_id_groups:
                converted_group = []
                for tid in group:
                    if isinstance(tid, bytes):
                        import uuid
                        converted_group.append(uuid.UUID(bytes=tid).hex)
                    else:
                        converted_group.append(tid)
                converted_groups.append(converted_group)
        return self._rust_db.search_notes(text_query, converted_groups)

    def create_tag(
        self, name: str, parent_id: Optional[Union[bytes, str]] = None
    ) -> str:
        """Create a new tag."""
        if isinstance(parent_id, bytes):
            import uuid
            parent_id = uuid.UUID(bytes=parent_id).hex
        return self._rust_db.create_tag(name, parent_id)

    def rename_tag(self, tag_id: Union[bytes, str], new_name: str) -> bool:
        """Rename a tag."""
        if isinstance(tag_id, bytes):
            import uuid
            tag_id = uuid.UUID(bytes=tag_id).hex
        return self._rust_db.rename_tag(tag_id, new_name)

    def add_tag_to_note(
        self, note_id: Union[bytes, str], tag_id: Union[bytes, str]
    ) -> bool:
        """Add a tag to a note."""
        if isinstance(note_id, bytes):
            import uuid
            note_id = uuid.UUID(bytes=note_id).hex
        if isinstance(tag_id, bytes):
            import uuid
            tag_id = uuid.UUID(bytes=tag_id).hex
        return self._rust_db.add_tag_to_note(note_id, tag_id)

    def remove_tag_from_note(
        self, note_id: Union[bytes, str], tag_id: Union[bytes, str]
    ) -> bool:
        """Remove a tag from a note."""
        if isinstance(note_id, bytes):
            import uuid
            note_id = uuid.UUID(bytes=note_id).hex
        if isinstance(tag_id, bytes):
            import uuid
            tag_id = uuid.UUID(bytes=tag_id).hex
        return self._rust_db.remove_tag_from_note(note_id, tag_id)

    def get_note_tags(self, note_id: Union[bytes, str]) -> List[Dict[str, Any]]:
        """Get all tags for a note."""
        if isinstance(note_id, bytes):
            import uuid
            note_id = uuid.UUID(bytes=note_id).hex
        return self._rust_db.get_note_tags(note_id)

    def close(self) -> None:
        """Close the database connection."""
        self._rust_db.close()
        logger.info("Closed Rust database connection")

    # ============================================================================
    # Sync methods
    # ============================================================================

    def get_peer_last_sync(self, peer_device_id: str) -> Optional[str]:
        """Get the last sync timestamp for a peer.

        Args:
            peer_device_id: Peer's device UUID hex string

        Returns:
            ISO timestamp of last sync, or None if never synced.
        """
        return self._rust_db.get_peer_last_sync(peer_device_id)

    def update_peer_sync_time(
        self, peer_device_id: str, peer_name: Optional[str] = None
    ) -> None:
        """Update or create peer's last sync timestamp.

        Args:
            peer_device_id: Peer's device UUID hex string
            peer_name: Peer's human-readable name
        """
        self._rust_db.update_peer_sync_time(peer_device_id, peer_name)

    def get_changes_since(
        self, since: Optional[str] = None, limit: int = 1000
    ) -> Dict[str, Any]:
        """Get all changes since a timestamp.

        Args:
            since: ISO timestamp to get changes after (None for all)
            limit: Maximum number of changes to return

        Returns:
            Dict with 'changes' list and 'latest_timestamp'
        """
        return self._rust_db.get_changes_since(since, limit)

    def get_full_dataset(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get the full dataset for initial sync.

        Returns:
            Dictionary with notes, tags, and note_tags lists.
        """
        return self._rust_db.get_full_dataset()

    # ============================================================================
    # Sync apply methods
    # ============================================================================

    def apply_sync_note(
        self,
        note_id: str,
        created_at: str,
        content: str,
        modified_at: Optional[str] = None,
        deleted_at: Optional[str] = None,
    ) -> bool:
        """Apply a sync note change."""
        return self._rust_db.apply_sync_note(note_id, created_at, content, modified_at, deleted_at)

    def apply_sync_tag(
        self,
        tag_id: str,
        name: str,
        parent_id: Optional[str] = None,
        created_at: str = "",
        modified_at: Optional[str] = None,
    ) -> bool:
        """Apply a sync tag change."""
        return self._rust_db.apply_sync_tag(tag_id, name, parent_id, created_at, modified_at)

    def apply_sync_note_tag(
        self,
        note_id: str,
        tag_id: str,
        created_at: str,
        modified_at: Optional[str] = None,
        deleted_at: Optional[str] = None,
    ) -> bool:
        """Apply a sync note_tag change."""
        return self._rust_db.apply_sync_note_tag(note_id, tag_id, created_at, modified_at, deleted_at)

    def get_note_raw(self, note_id: str) -> Optional[Dict[str, Any]]:
        """Get raw note data by ID (including deleted, for sync)."""
        return self._rust_db.get_note_raw(note_id)

    def get_tag_raw(self, tag_id: str) -> Optional[Dict[str, Any]]:
        """Get raw tag data by ID (for sync)."""
        return self._rust_db.get_tag_raw(tag_id)

    def get_note_tag_raw(self, note_id: str, tag_id: str) -> Optional[Dict[str, Any]]:
        """Get raw note_tag data (for sync)."""
        return self._rust_db.get_note_tag_raw(note_id, tag_id)

    def create_note_content_conflict(
        self,
        note_id: str,
        local_content: str,
        local_modified_at: str,
        remote_content: str,
        remote_modified_at: str,
        remote_device_id: Optional[str] = None,
        remote_device_name: Optional[str] = None,
    ) -> str:
        """Create a note content conflict record."""
        return self._rust_db.create_note_content_conflict(
            note_id, local_content, local_modified_at,
            remote_content, remote_modified_at,
            remote_device_id, remote_device_name,
        )

    def create_note_delete_conflict(
        self,
        note_id: str,
        surviving_content: str,
        surviving_modified_at: str,
        surviving_device_id: Optional[str] = None,
        deleted_content: Optional[str] = None,
        deleted_at: str = "",
        deleting_device_id: Optional[str] = None,
        deleting_device_name: Optional[str] = None,
    ) -> str:
        """Create a note delete conflict record."""
        return self._rust_db.create_note_delete_conflict(
            note_id, surviving_content, surviving_modified_at,
            surviving_device_id, deleted_content, deleted_at,
            deleting_device_id, deleting_device_name,
        )

    def create_tag_rename_conflict(
        self,
        tag_id: str,
        local_name: str,
        local_modified_at: str,
        remote_name: str,
        remote_modified_at: str,
        remote_device_id: Optional[str] = None,
        remote_device_name: Optional[str] = None,
    ) -> str:
        """Create a tag rename conflict record."""
        return self._rust_db.create_tag_rename_conflict(
            tag_id, local_name, local_modified_at,
            remote_name, remote_modified_at,
            remote_device_id, remote_device_name,
        )

    def create_note_tag_conflict(
        self,
        note_id: str,
        tag_id: str,
        local_created_at: Optional[str] = None,
        local_modified_at: Optional[str] = None,
        local_deleted_at: Optional[str] = None,
        remote_created_at: Optional[str] = None,
        remote_modified_at: Optional[str] = None,
        remote_deleted_at: Optional[str] = None,
        remote_device_id: Optional[str] = None,
        remote_device_name: Optional[str] = None,
    ) -> str:
        """Create a note_tag conflict record."""
        return self._rust_db.create_note_tag_conflict(
            note_id, tag_id,
            local_created_at, local_modified_at, local_deleted_at,
            remote_created_at, remote_modified_at, remote_deleted_at,
            remote_device_id, remote_device_name,
        )

    def create_tag_parent_conflict(
        self,
        tag_id: str,
        local_parent_id: Optional[str],
        local_modified_at: str,
        remote_parent_id: Optional[str],
        remote_modified_at: str,
        remote_device_id: Optional[str] = None,
        remote_device_name: Optional[str] = None,
    ) -> str:
        """Create a tag parent_id conflict record."""
        return self._rust_db.create_tag_parent_conflict(
            tag_id, local_parent_id, local_modified_at,
            remote_parent_id, remote_modified_at,
            remote_device_id, remote_device_name,
        )

    def create_tag_delete_conflict(
        self,
        tag_id: str,
        surviving_name: str,
        surviving_parent_id: Optional[str],
        surviving_modified_at: str,
        surviving_device_id: Optional[str] = None,
        surviving_device_name: Optional[str] = None,
        deleted_at: str = "",
        deleting_device_id: Optional[str] = None,
        deleting_device_name: Optional[str] = None,
    ) -> str:
        """Create a tag delete conflict record (rename vs delete)."""
        return self._rust_db.create_tag_delete_conflict(
            tag_id, surviving_name, surviving_parent_id, surviving_modified_at,
            surviving_device_id, surviving_device_name,
            deleted_at, deleting_device_id, deleting_device_name,
        )

    # ============================================================================
    # Conflict query and resolution methods
    # ============================================================================

    def get_unresolved_conflict_counts(self) -> Dict[str, int]:
        """Get counts of unresolved conflicts by type."""
        return self._rust_db.get_unresolved_conflict_counts()

    def get_note_content_conflicts(
        self, include_resolved: bool = False
    ) -> List[Dict[str, Any]]:
        """Get note content conflicts."""
        return self._rust_db.get_note_content_conflicts(include_resolved)

    def get_note_delete_conflicts(
        self, include_resolved: bool = False
    ) -> List[Dict[str, Any]]:
        """Get note delete conflicts."""
        return self._rust_db.get_note_delete_conflicts(include_resolved)

    def get_tag_rename_conflicts(
        self, include_resolved: bool = False
    ) -> List[Dict[str, Any]]:
        """Get tag rename conflicts."""
        return self._rust_db.get_tag_rename_conflicts(include_resolved)

    def get_tag_parent_conflicts(
        self, include_resolved: bool = False
    ) -> List[Dict[str, Any]]:
        """Get tag parent_id conflicts."""
        return self._rust_db.get_tag_parent_conflicts(include_resolved)

    def get_tag_delete_conflicts(
        self, include_resolved: bool = False
    ) -> List[Dict[str, Any]]:
        """Get tag delete conflicts (rename vs delete)."""
        return self._rust_db.get_tag_delete_conflicts(include_resolved)

    def resolve_note_content_conflict(
        self, conflict_id: str, new_content: str
    ) -> bool:
        """Resolve a note content conflict."""
        return self._rust_db.resolve_note_content_conflict(conflict_id, new_content)

    def resolve_note_delete_conflict(
        self, conflict_id: str, restore_note: bool
    ) -> bool:
        """Resolve a note delete conflict."""
        return self._rust_db.resolve_note_delete_conflict(conflict_id, restore_note)

    def resolve_tag_rename_conflict(
        self, conflict_id: str, new_name: str
    ) -> bool:
        """Resolve a tag rename conflict."""
        return self._rust_db.resolve_tag_rename_conflict(conflict_id, new_name)

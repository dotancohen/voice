"""Database operations for Voice.

This module provides all data access functionality using SQLite.
All methods return JSON-serializable types (dicts, lists, primitives)
to support future CLI and web server modes.

This is a wrapper around the Rust voicecore extension.

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Import Database from the Rust extension
from voicecore import Database as RustDatabase
from voicecore import set_local_device_id as _rust_set_local_device_id
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

    def merge_notes(self, note_id_1: Union[bytes, str], note_id_2: Union[bytes, str]) -> str:
        """Merge two notes into one.

        - Keeps the note with the earliest created_at timestamp
        - Concatenates content with separator (if both non-empty)
        - Moves tags from victim to survivor (deduplicates)
        - Moves attachments from victim to survivor
        - Soft-deletes the victim note

        Returns the surviving note ID (hex string).
        """
        if isinstance(note_id_1, bytes):
            import uuid
            note_id_1 = uuid.UUID(bytes=note_id_1).hex
        if isinstance(note_id_2, bytes):
            import uuid
            note_id_2 = uuid.UUID(bytes=note_id_2).hex
        return self._rust_db.merge_notes(note_id_1, note_id_2)

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

    def reparent_tag(
        self, tag_id: Union[bytes, str], new_parent_id: Optional[Union[bytes, str]] = None
    ) -> bool:
        """Move a tag to a different parent (or make it a root tag).

        Args:
            tag_id: UUID of the tag to move (bytes or hex string)
            new_parent_id: UUID of new parent, or None to make it a root tag

        Returns:
            True if the tag was moved, False if not found
        """
        if isinstance(tag_id, bytes):
            import uuid
            tag_id = uuid.UUID(bytes=tag_id).hex
        if isinstance(new_parent_id, bytes):
            import uuid
            new_parent_id = uuid.UUID(bytes=new_parent_id).hex
        return self._rust_db.reparent_tag(tag_id, new_parent_id)

    def delete_tag(self, tag_id: Union[bytes, str]) -> bool:
        """Soft delete a tag.

        Args:
            tag_id: UUID of the tag to delete (bytes or hex string)

        Returns:
            True if a tag was deleted, False if not found
        """
        if isinstance(tag_id, bytes):
            import uuid
            tag_id = uuid.UUID(bytes=tag_id).hex
        return self._rust_db.delete_tag(tag_id)

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

    def reset_sync_timestamps(self) -> None:
        """Reset sync timestamps to force re-fetching all data from peers.

        This sets last_sync_at to NULL for all peers, causing the next sync
        to exchange all data. Unlike clearing sync peers, this preserves
        peer configuration.
        """
        self._rust_db.reset_sync_timestamps()

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

    # ============================================================================
    # AudioFile and NoteAttachment methods
    # ============================================================================

    def create_audio_file(
        self,
        filename: str,
        file_created_at: Optional[str] = None,
    ) -> str:
        """Create a new audio file record.

        Args:
            filename: Original filename
            file_created_at: Optional file creation timestamp

        Returns:
            Audio file ID (hex string)
        """
        return self._rust_db.create_audio_file(filename, file_created_at)

    def get_audio_file(self, audio_id: str) -> Optional[Dict[str, Any]]:
        """Get an audio file by ID.

        Args:
            audio_id: Audio file UUID hex string

        Returns:
            Audio file dict or None if not found
        """
        return self._rust_db.get_audio_file(audio_id)

    def get_audio_files_for_note(self, note_id: str) -> List[Dict[str, Any]]:
        """Get all audio files attached to a note.

        Args:
            note_id: Note UUID hex string

        Returns:
            List of audio file dicts
        """
        return self._rust_db.get_audio_files_for_note(note_id)

    def get_all_audio_files(self) -> List[Dict[str, Any]]:
        """Get all audio files in the database.

        Returns:
            List of audio file dicts
        """
        return self._rust_db.get_all_audio_files()

    def update_audio_file_summary(self, audio_id: str, summary: str) -> bool:
        """Update an audio file's summary.

        Args:
            audio_id: Audio file UUID hex string
            summary: New summary text

        Returns:
            True if updated, False if not found
        """
        return self._rust_db.update_audio_file_summary(audio_id, summary)

    def delete_audio_file(self, audio_id: str) -> bool:
        """Soft delete an audio file.

        Args:
            audio_id: Audio file UUID hex string

        Returns:
            True if deleted, False if not found
        """
        return self._rust_db.delete_audio_file(audio_id)

    def attach_to_note(
        self,
        note_id: str,
        attachment_id: str,
        attachment_type: str,
    ) -> str:
        """Attach an item to a note.

        Args:
            note_id: Note UUID hex string
            attachment_id: Attachment UUID hex string
            attachment_type: Type of attachment (e.g., "audio_file")

        Returns:
            Association ID (hex string)
        """
        return self._rust_db.attach_to_note(note_id, attachment_id, attachment_type)

    def detach_from_note(self, association_id: str) -> bool:
        """Detach an item from a note (soft delete).

        Args:
            association_id: Association UUID hex string

        Returns:
            True if detached, False if not found
        """
        return self._rust_db.detach_from_note(association_id)

    def get_attachments_for_note(self, note_id: str) -> List[Dict[str, Any]]:
        """Get all attachments for a note.

        Args:
            note_id: Note UUID hex string

        Returns:
            List of attachment dicts
        """
        return self._rust_db.get_attachments_for_note(note_id)

    def get_attachment(self, association_id: str) -> Optional[Dict[str, Any]]:
        """Get an attachment by association ID.

        Args:
            association_id: Association UUID hex string

        Returns:
            Attachment dict or None if not found
        """
        return self._rust_db.get_attachment(association_id)

    # ============================================================================
    # AudioFile and NoteAttachment sync methods
    # ============================================================================

    def get_audio_file_raw(self, audio_id: str) -> Optional[Dict[str, Any]]:
        """Get raw audio file data by ID (including deleted, for sync)."""
        return self._rust_db.get_audio_file_raw(audio_id)

    def apply_sync_audio_file(
        self,
        audio_id: str,
        imported_at: str,
        filename: str,
        file_created_at: Optional[str] = None,
        summary: Optional[str] = None,
        modified_at: Optional[str] = None,
        deleted_at: Optional[str] = None,
    ) -> bool:
        """Apply a sync audio file change."""
        return self._rust_db.apply_sync_audio_file(
            audio_id, imported_at, filename,
            file_created_at, summary, modified_at, deleted_at
        )

    def get_note_attachment_raw(
        self, association_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get raw note attachment data by ID (including deleted, for sync)."""
        return self._rust_db.get_note_attachment_raw(association_id)

    def apply_sync_note_attachment(
        self,
        association_id: str,
        note_id: str,
        attachment_id: str,
        attachment_type: str,
        created_at: str,
        modified_at: Optional[str] = None,
        deleted_at: Optional[str] = None,
    ) -> bool:
        """Apply a sync note attachment change."""
        return self._rust_db.apply_sync_note_attachment(
            association_id, note_id, attachment_id, attachment_type,
            created_at, modified_at, deleted_at
        )

    # ============================================================================
    # Maintenance methods
    # ============================================================================

    def normalize_database(self) -> None:
        """Normalize database data for consistency.

        This includes:
        - Timestamp normalization (ISO 8601 to SQLite format)
        - Future: Unicode normalization
        """
        self._rust_db.normalize_database()

    # ============================================================================
    # Transcription methods
    # ============================================================================

    def create_transcription(
        self,
        audio_file_id: str,
        content: str,
        service: str,
        content_segments: Optional[str] = None,
        service_arguments: Optional[str] = None,
        service_response: Optional[str] = None,
        state: Optional[str] = None,
    ) -> str:
        """Create a new transcription record.

        Args:
            audio_file_id: Audio file UUID hex string
            content: Full transcribed text
            service: Transcription service used (e.g., "whisper", "google")
            content_segments: Optional JSON string with segment-level data
            service_arguments: Optional JSON string with service arguments
            service_response: Optional JSON string with service response metadata
            state: Optional state string (default: "original !verified !verbatim !cleaned !polished")

        Returns:
            Transcription ID (hex string)
        """
        return self._rust_db.create_transcription(
            audio_file_id, content, service,
            content_segments, service_arguments, service_response, state
        )

    def get_transcription(self, transcription_id: str) -> Optional[Dict[str, Any]]:
        """Get a transcription by ID.

        Args:
            transcription_id: Transcription UUID hex string

        Returns:
            Transcription dict or None if not found
        """
        return self._rust_db.get_transcription(transcription_id)

    def get_transcriptions_for_audio_file(
        self, audio_file_id: str
    ) -> List[Dict[str, Any]]:
        """Get all transcriptions for an audio file.

        Args:
            audio_file_id: Audio file UUID hex string

        Returns:
            List of transcription dicts
        """
        return self._rust_db.get_transcriptions_for_audio_file(audio_file_id)

    def delete_transcription(self, transcription_id: str) -> bool:
        """Soft delete a transcription.

        Args:
            transcription_id: Transcription UUID hex string

        Returns:
            True if deleted, False if not found
        """
        return self._rust_db.delete_transcription(transcription_id)

    def update_transcription(
        self,
        transcription_id: str,
        content: str,
        content_segments: Optional[str] = None,
        service_response: Optional[str] = None,
        state: Optional[str] = None,
    ) -> bool:
        """Update a transcription's content, state, and service response.

        Used to update a pending transcription after the transcription completes,
        or when the user edits the transcription content or state.

        Args:
            transcription_id: Transcription UUID hex string
            content: Full transcribed text
            content_segments: Optional JSON string with segment-level data
            service_response: Optional JSON string with service response metadata
            state: Optional state string (e.g., "cleaned verified")

        Returns:
            True if updated, False if not found
        """
        return self._rust_db.update_transcription(
            transcription_id, content, content_segments, service_response, state
        )

    # ============================================================================
    # Note Display Cache methods
    # ============================================================================

    def rebuild_note_cache(self, note_id: Union[bytes, str]) -> None:
        """Rebuild the display cache for a single note.

        The cache stores pre-computed data for the Note pane display:
        - Tags with full hierarchical paths
        - Conflict types
        - Attachments with audio files and transcriptions (metadata only)

        Args:
            note_id: Note UUID (bytes or hex string)
        """
        if isinstance(note_id, bytes):
            note_id = uuid_module.UUID(bytes=note_id).hex
        self._rust_db.rebuild_note_cache(note_id)

    def rebuild_all_note_caches(self) -> int:
        """Rebuild the display cache for all notes.

        Returns:
            Number of notes processed
        """
        return self._rust_db.rebuild_all_note_caches()

    def get_transcription_content(self, transcription_id: Union[bytes, str]) -> Optional[str]:
        """Get full transcription content by ID.

        Used for lazy-loading full content when displaying transcription.
        The cache only stores a 100-character preview.

        Args:
            transcription_id: Transcription UUID (bytes or hex string)

        Returns:
            Full transcription content, or None if not found
        """
        if isinstance(transcription_id, bytes):
            transcription_id = uuid_module.UUID(bytes=transcription_id).hex
        return self._rust_db.get_transcription_content(transcription_id)

    def update_cache_waveform(
        self,
        note_id: Union[bytes, str],
        audio_id: Union[bytes, str],
        waveform: List[int]
    ) -> bool:
        """Update the waveform data in a note's display cache.

        The waveform is an array of amplitude values (0-255) for visualization.
        This is called after extracting the waveform with ffmpeg.

        Args:
            note_id: Note UUID (bytes or hex string)
            audio_id: Audio file UUID (bytes or hex string)
            waveform: List of amplitude values (0-255), typically 150 values

        Returns:
            True if the cache was updated, False if note or audio not found
        """
        if isinstance(note_id, bytes):
            note_id = uuid_module.UUID(bytes=note_id).hex
        if isinstance(audio_id, bytes):
            audio_id = uuid_module.UUID(bytes=audio_id).hex
        # Convert to bytes for Rust
        waveform_bytes = bytes(waveform)
        return self._rust_db.update_cache_waveform(note_id, audio_id, list(waveform_bytes))

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
from typing import Any, Dict, List, Optional, TypedDict, Union


class TagChangeResult(TypedDict):
    """Result of a tag change operation (add/remove tag from note)."""
    changed: bool
    note_id: str
    list_cache_rebuilt: bool

# Import Database from the Rust extension
from voicecore import Database as RustDatabase
from voicecore import set_local_device_id as _rust_set_local_device_id
from voicecore import set_local_timezone as _rust_set_local_timezone

from .timestamp_utils import local_timezone
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

    def __init__(self, db_path: Union[Path, str], account_id: Optional[str] = None) -> None:
        """Initialize database connection.

        Args:
            db_path: Path to the SQLite database file, or ':memory:' for in-memory
            account_id: The account this database belongs to. A fresh database
                takes it; one that belongs to another account is refused.
        """
        path_str = str(db_path) if isinstance(db_path, Path) else db_path
        # Every timestamp written from here records the clock this computer
        # reads, so the time survives a journey to another timezone
        offset, zone = local_timezone()
        _rust_set_local_timezone(offset, zone)
        self._rust_db = RustDatabase(path_str, account_id)
        logger.info(f"Opened Rust database at {path_str} (timezone {zone or offset})")

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

    def get_deleted_notes(self) -> List[Dict[str, Any]]:
        """The notes in the trash: deleted, still here, newest deletion first.

        Deleting a note has always been a soft delete, so every note that was
        ever deleted is still in the database with its history and its
        recordings. This is what the trash bin shows.
        """
        return self._rust_db.get_deleted_notes()

    def undelete_note(self, note_id: Union[bytes, str]) -> bool:
        """Take a note out of the trash. False when it was not in there.

        The recovery is a version like any other, so it reaches the other
        devices by the ordinary route.
        """
        if isinstance(note_id, bytes):
            import uuid
            note_id = uuid.UUID(bytes=note_id).hex
        return self._rust_db.undelete_note(note_id)

    def purge_note(self, note_id: Union[bytes, str]) -> List[str]:
        """Empty one note out of the trash for good, on every device.

        The note, its history, its tag links, its attachments and the
        recordings that hung on this note alone are removed, here and on
        every device this one syncs with. It cannot be undone.

        Returns the ids of the audio files that were removed, so the caller
        can delete the files from disk.
        """
        if isinstance(note_id, bytes):
            import uuid
            note_id = uuid.UUID(bytes=note_id).hex
        return self._rust_db.purge_note(note_id)

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
    ) -> TagChangeResult:
        """Add a tag to a note.

        Returns:
            TagChangeResult with:
            - changed: True if tag was added (False if already present)
            - note_id: The resolved note ID
            - list_cache_rebuilt: True if the list pane cache was rebuilt
        """
        if isinstance(note_id, bytes):
            import uuid
            note_id = uuid.UUID(bytes=note_id).hex
        if isinstance(tag_id, bytes):
            import uuid
            tag_id = uuid.UUID(bytes=tag_id).hex
        return self._rust_db.add_tag_to_note(note_id, tag_id)

    def remove_tag_from_note(
        self, note_id: Union[bytes, str], tag_id: Union[bytes, str]
    ) -> TagChangeResult:
        """Remove a tag from a note.

        Returns:
            TagChangeResult with:
            - changed: True if tag was removed (False if not present)
            - note_id: The resolved note ID
            - list_cache_rebuilt: True if the list pane cache was rebuilt
        """
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

    def get_peer_last_sync(self, peer_device_id: str) -> Optional[int]:
        """Get the last sync timestamp for a peer.

        Args:
            peer_device_id: Peer's device UUID hex string

        Returns:
            Unix timestamp of last sync, or None if never synced.
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
        self, since: Optional[int] = None, limit: int = 1000
    ) -> Dict[str, Any]:
        """Get all changes since a timestamp.

        Args:
            since: Unix timestamp to get changes after (None for all)
            limit: Maximum number of changes to return

        Returns:
            Dict with 'changes' list and 'latest_timestamp'
        """
        return self._rust_db.get_changes_since(since, limit)

    def get_changes_after_seq(
        self, cursor: int = 0, upto: Optional[int] = None, limit: int = 1000
    ) -> Dict[str, Any]:
        """Write-order feed (the primary sync feed).

        Args:
            cursor: Return changes with seq greater than this
            upto: Optional upper bound on seq
            limit: Maximum number of changes in this page

        Returns:
            Dict with 'changes', 'next_cursor' (pass back to continue),
            'is_complete' and 'latest_timestamp'
        """
        return self._rust_db.get_changes_after_seq(cursor, upto, limit)

    def current_seq(self) -> int:
        """End of this database's write-order feed."""
        return self._rust_db.current_seq()

    def database_id(self) -> str:
        """Identity of this database; peers reset their cursors when it changes."""
        return self._rust_db.database_id()

    def account_id(self) -> str:
        """The account this database belongs to: 32 hex characters."""
        return self._rust_db.account_id()

    def move_to_account(self, account_id: str) -> None:
        """Move this database, notes and all, to another account.

        A snapshot is taken first; every peer is forgotten so the next sync
        exchanges everything. This is the deliberate way to merge accounts.
        """
        self._rust_db.move_to_account(account_id)

    def list_devices(self) -> List[Dict[str, Any]]:
        """Every device of the account, as its card says."""
        return self._rust_db.list_devices()

    def not_duplicated(self, audio_dir: Optional[str]) -> Dict[str, int]:
        """What is on this device only: {"notes": n, "recordings": m} (Stage 10)."""
        return self._rust_db.not_duplicated(audio_dir)

    def copies_of(self, audio_id: str) -> List[Dict[str, Any]]:
        """The peers known to hold a copy of a recording, with when that was learnt."""
        return self._rust_db.copies_of(audio_id)

    def peer_summaries(self) -> List[Dict[str, Any]]:
        """Every peer dealt with: when it was last reached and by which operation."""
        return self._rust_db.peer_summaries()

    def admit_device(self, device_id: str, name: str, key_hash: str, certificate_fingerprint: str = "") -> None:
        """Let a device into the account: its card, with the hash of its key."""
        self._rust_db.admit_device(device_id, name, key_hash, certificate_fingerprint)

    def revoke_device(self, device_id: str) -> None:
        """Revoke a device of the account. One way, and it travels to every peer."""
        self._rust_db.revoke_device(device_id)

    def snapshot(self) -> str:
        """Copy the database into its snapshot directory; returns the path."""
        return self._rust_db.snapshot()

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """Every snapshot beside this database, newest first."""
        return self._rust_db.list_snapshots()

    def restore_snapshot(self, name: str) -> None:
        """Replace the database's contents with a snapshot's; the state replaced is snapshotted first."""
        self._rust_db.restore_snapshot(name)

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
        created_at: int,
        content: str,
        modified_at: Optional[int] = None,
        deleted_at: Optional[int] = None,
        sync_received_at: Optional[int] = None,
    ) -> bool:
        """Apply a sync note change."""
        return self._rust_db.apply_sync_note(note_id, created_at, content, modified_at, deleted_at, sync_received_at)

    def apply_sync_tag(
        self,
        tag_id: str,
        name: str,
        parent_id: Optional[str] = None,
        created_at: int = 0,
        modified_at: Optional[int] = None,
        deleted_at: Optional[int] = None,
        sync_received_at: Optional[int] = None,
    ) -> bool:
        """Apply a sync tag change."""
        return self._rust_db.apply_sync_tag(tag_id, name, parent_id, created_at, modified_at, deleted_at, sync_received_at)

    def apply_sync_note_tag(
        self,
        note_id: str,
        tag_id: str,
        created_at: int,
        modified_at: Optional[int] = None,
        deleted_at: Optional[int] = None,
        sync_received_at: Optional[int] = None,
    ) -> bool:
        """Apply a sync note_tag change."""
        return self._rust_db.apply_sync_note_tag(note_id, tag_id, created_at, modified_at, deleted_at, sync_received_at)

    def get_note_raw(self, note_id: str) -> Optional[Dict[str, Any]]:
        """Get raw note data by ID (including deleted, for sync)."""
        return self._rust_db.get_note_raw(note_id)

    def get_tag_raw(self, tag_id: str) -> Optional[Dict[str, Any]]:
        """Get raw tag data by ID (for sync)."""
        return self._rust_db.get_tag_raw(tag_id)

    def get_note_tag_raw(self, note_id: str, tag_id: str) -> Optional[Dict[str, Any]]:
        """Get raw note_tag data (for sync)."""
        return self._rust_db.get_note_tag_raw(note_id, tag_id)

    # ============================================================================
    # Versioned fields, conflicts and synced settings (voicecore versions.rs)
    # ============================================================================

    def get_unresolved_conflict_counts(self) -> Dict[str, int]:
        """Counts of unresolved conflicts keyed by kind, plus "total"."""
        return self._rust_db.get_unresolved_conflict_counts()

    def get_conflicts(self, include_resolved: bool = False) -> List[Dict[str, Any]]:
        """All conflicts, newest first (unresolved only unless include_resolved)."""
        return self._rust_db.get_conflicts(include_resolved)

    def get_entity_conflicts(self, entity_type: str, entity_id: str) -> List[Dict[str, Any]]:
        """Unresolved conflicts of one entity, e.g. ("note", note_id)."""
        return self._rust_db.get_entity_conflicts(entity_type, entity_id)

    def get_conflict(self, id_or_prefix: str) -> Optional[Dict[str, Any]]:
        """One conflict by id or unique prefix; None when nothing matches."""
        return self._rust_db.get_conflict(id_or_prefix)

    def get_note_conflicts(self, note_id: str) -> List[Dict[str, Any]]:
        """Unresolved conflicts touching a note: its fields, tag links, attachments, transcriptions."""
        return self._rust_db.get_note_conflicts(note_id)

    def get_note_conflict_types(self, note_id: str) -> List[str]:
        """Kinds of unresolved conflict touching a note (content, delete, tag, ...)."""
        return self._rust_db.get_note_conflict_types(note_id)

    def accept_conflict(self, conflict_id: str) -> bool:
        """Accept the merged value as it stands. Propagates to every peer."""
        return self._rust_db.accept_conflict(conflict_id)

    def resolve_conflict_with_content(self, conflict_id: str, content: str) -> bool:
        """Resolve a conflict by writing a new value for the field."""
        return self._rust_db.resolve_conflict_with_content(conflict_id, content)

    def get_field_history(self, entity_type: str, entity_id: str, field: str) -> List[Dict[str, Any]]:
        """Every version of one field, oldest first."""
        return self._rust_db.get_field_history(entity_type, entity_id, field)

    def get_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        """One field version by hex id."""
        return self._rust_db.get_version(version_id)

    def get_setting(self, key: str) -> Optional[str]:
        """A synced setting value (shared by every device), or None."""
        return self._rust_db.get_setting(key)

    def set_setting(self, key: str, value: str) -> None:
        """Set a synced setting. Concurrent changes are merged and flagged."""
        self._rust_db.set_setting(key, value)

    def get_all_settings(self) -> Dict[str, str]:
        """All synced settings as a dict."""
        return self._rust_db.get_all_settings()

    # ============================================================================
    # AudioFile and NoteAttachment methods
    # ============================================================================

    def create_audio_file(
        self,
        filename: str,
        file_created_at: Optional[int] = None,
        audio_dir: "Path | str | None" = None,
    ) -> str:
        """Create the record of an imported file.

        Args:
            filename: The file's own name; it keeps it in the audio folder, with
                " (2)" and so on before the extension when the name is taken
            file_created_at: Optional Unix timestamp for file creation time
            audio_dir: The audio folder, so a file already there takes its name too

        Returns:
            Audio file ID (hex string)
        """
        return self._rust_db.create_audio_file(filename, file_created_at, str(audio_dir) if audio_dir else None)

    def settle_file_names(self, audio_dir: "Path | str") -> int:
        """Resolve names two recordings share and rename on disk the files of
        recordings renamed by a sync or a collision (FILE-15). Returns how
        many files were renamed."""
        return self._rust_db.settle_file_names(str(audio_dir))

    def store_content_hash(self, audio_id: str, audio_dir: "Path | str") -> str:
        """Compute and store the recording's content hash from its file under
        ``audio_dir`` (Stage 13); call it after the file is copied there."""
        return self._rust_db.store_content_hash(audio_id, str(audio_dir))

    def set_waveform_levels(self, audio_id: str, levels: List[int]) -> None:
        """Keep the levels a recording's waveform is drawn from (FILE-20);
        they sync with the recording to every device."""
        self._rust_db.set_waveform_levels(audio_id, list(levels))

    def waveform_levels(self, audio_id: str) -> Optional[List[int]]:
        """The levels a device kept for this recording, or None."""
        levels = self._rust_db.waveform_levels(audio_id)
        return list(levels) if levels is not None else None

    def waveform_bars(self, audio_id: str, bar_count: int) -> Optional[List[float]]:
        """The recording's waveform bars from its kept levels, without reading
        the audio (FILE-20); None when no device kept levels yet."""
        return self._rust_db.waveform_bars(audio_id, bar_count)

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
        imported_at: int,
        filename: str,
        file_created_at: Optional[int] = None,
        duration_seconds: Optional[int] = None,
        summary: Optional[str] = None,
        modified_at: Optional[int] = None,
        deleted_at: Optional[int] = None,
        sync_received_at: Optional[int] = None,
    ) -> bool:
        """Apply a sync audio file change."""
        return self._rust_db.apply_sync_audio_file(
            audio_id, imported_at, filename,
            file_created_at, duration_seconds, summary, modified_at, deleted_at, sync_received_at
        )

    def get_audio_files_missing_duration(self) -> List[Dict[str, Any]]:
        """Get all audio files that have no duration set."""
        return self._rust_db.get_audio_files_missing_duration()

    def update_audio_file_duration(self, audio_id: str, duration_seconds: int) -> bool:
        """Update an audio file's duration."""
        return self._rust_db.update_audio_file_duration(audio_id, duration_seconds)

    def update_audio_file_created_at(self, audio_id: str, file_created_at: int) -> bool:
        """Set when a recording was made, for a row that never had it.

        Read off the file or its name by whichever device holds the file; see
        `core.missing_data`. A repair, not an edit by the user.

        Args:
            audio_id: Audio file UUID hex string
            file_created_at: Unix timestamp of when the recording was made

        Returns:
            True if updated, False if the audio file was not found
        """
        return self._rust_db.update_audio_file_created_at(audio_id, file_created_at)

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
        created_at: int,
        modified_at: Optional[int] = None,
        deleted_at: Optional[int] = None,
        sync_received_at: Optional[int] = None,
    ) -> bool:
        """Apply a sync note attachment change."""
        return self._rust_db.apply_sync_note_attachment(
            association_id, note_id, attachment_id, attachment_type,
            created_at, modified_at, deleted_at, sync_received_at
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

    def get_recent_transcriptions(
        self, service: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """The most recent transcriptions, newest first.

        What the transcription queue shows once the work is done; the
        `service_response` of each row carries what that work cost.

        Args:
            service: Only this transcription service, or every service if None.
            limit: At most this many rows. A queue view is a screenful of recent
                work, not a history.

        Returns:
            List of transcription dicts, newest first.
        """
        return self._rust_db.get_recent_transcriptions(service, limit)

    def get_notes_for_audio_file(self, audio_file_id: str) -> List[str]:
        """The notes a recording is attached to, as hex ids. Normally one.

        The queue view uses it to say which note each transcription belongs to.
        """
        return self._rust_db.get_notes_for_audio_file(audio_file_id)

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

    def rebuild_note_list_cache(self, note_id: Union[bytes, str]) -> None:
        """Rebuild the list pane display cache for a single note.

        The cache stores pre-computed data for the Notes List pane:
        - Date (created_at timestamp)
        - Marked status (has _system/_marked tag)
        - Content preview (first 100 characters)

        Args:
            note_id: Note UUID (bytes or hex string)
        """
        if isinstance(note_id, bytes):
            note_id = uuid_module.UUID(bytes=note_id).hex
        self._rust_db.rebuild_note_list_cache(note_id)

    def rebuild_all_note_list_caches(self) -> int:
        """Rebuild the list pane display cache for all notes.

        Returns:
            Number of notes processed
        """
        return self._rust_db.rebuild_all_note_list_caches()

    def rebuild_all_caches_for_note(self, note_id: Union[bytes, str]) -> None:
        """Rebuild ALL cache fields for a single note.

        This rebuilds every cache column (note pane display, list pane display)
        for the given note.

        Args:
            note_id: Note UUID (bytes or hex string)
        """
        if isinstance(note_id, bytes):
            note_id = uuid_module.UUID(bytes=note_id).hex
        self._rust_db.rebuild_all_caches_for_note(note_id)

    def rebuild_all_database_caches(self) -> Dict[str, Any]:
        """Rebuild ALL cache fields for all notes in the database.

        Returns:
            Summary dict with:
            - notes_processed: Number of notes processed
            - cache_fields_rebuilt: Number of cache fields per note
            - errors: List of error messages (if any)
        """
        notes, fields, errors = self._rust_db.rebuild_all_database_caches()
        return {
            "notes_processed": notes,
            "cache_fields_rebuilt": fields,
            "errors": errors,
        }

    def get_cache_registry_info(self) -> List[Dict[str, str]]:
        """Get information about all registered cache fields.

        Returns:
            List of dicts with table, column, and description for each cache field.
        """
        info_list = self._rust_db.get_cache_registry_info()
        return [
            {"table": table, "column": column, "description": desc}
            for table, column, desc in info_list
        ]

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

    # ============================================================================
    # Note marking (star/bookmark) methods
    # ============================================================================

    def is_note_marked(self, note_id: Union[bytes, str]) -> bool:
        """Check if a note is marked (starred/bookmarked).

        Args:
            note_id: Note UUID (bytes or hex string)

        Returns:
            True if the note is marked, False otherwise
        """
        if isinstance(note_id, bytes):
            note_id = uuid_module.UUID(bytes=note_id).hex
        return self._rust_db.is_note_marked(note_id)

    def mark_note(self, note_id: Union[bytes, str]) -> bool:
        """Mark a note (add the _system/_marked tag).

        Args:
            note_id: Note UUID (bytes or hex string)

        Returns:
            True if the note was marked, False if already marked
        """
        if isinstance(note_id, bytes):
            note_id = uuid_module.UUID(bytes=note_id).hex
        return self._rust_db.mark_note(note_id)

    def unmark_note(self, note_id: Union[bytes, str]) -> bool:
        """Unmark a note (remove the _system/_marked tag).

        Args:
            note_id: Note UUID (bytes or hex string)

        Returns:
            True if the note was unmarked, False if not marked
        """
        if isinstance(note_id, bytes):
            note_id = uuid_module.UUID(bytes=note_id).hex
        return self._rust_db.unmark_note(note_id)

    def toggle_note_marked(self, note_id: Union[bytes, str]) -> bool:
        """Toggle a note's marked state.

        Args:
            note_id: Note UUID (bytes or hex string)

        Returns:
            The new marked state (True if now marked, False if now unmarked)
        """
        if isinstance(note_id, bytes):
            note_id = uuid_module.UUID(bytes=note_id).hex
        return self._rust_db.toggle_note_marked(note_id)

    def get_system_tag_id_hex(self) -> str:
        """Get the _system tag ID as a hex string.

        Used for filtering system tags from UI display.

        Returns:
            System tag ID hex string
        """
        return self._rust_db.get_system_tag_id_hex()

    # ========================================================================
    # File Storage Configuration
    # ========================================================================

    def get_file_storage_config(self) -> Optional[Dict[str, Any]]:
        """Get the file storage configuration from the database.

        Returns:
            Configuration dict with 'provider' and 'config' keys, or None if not set.
            Example: {"provider": "s3", "config": {"bucket": "my-bucket", ...}}
        """
        return self._rust_db.get_file_storage_config()

    def set_file_storage_config(self, provider: str, config: Optional[str] = None) -> None:
        """Set the file storage configuration in the database.

        Args:
            provider: Storage provider name ("s3", "none", etc.)
            config: Optional JSON string with provider-specific configuration
        """
        self._rust_db.set_file_storage_config(provider, config)

    def get_file_storage_provider(self) -> str:
        """Get the file storage provider name.

        Returns:
            Provider name ("s3", "none", etc.)
        """
        return self._rust_db.get_file_storage_provider()

    def is_file_storage_enabled(self) -> bool:
        """Check if file storage is enabled.

        Returns:
            True if a cloud storage provider is configured.
        """
        return self._rust_db.is_file_storage_enabled()

    # ========================================================================
    # Audio File Storage Methods
    # ========================================================================

    def get_audio_files_pending_upload(self) -> List[Dict[str, Any]]:
        """Get all audio files that need to be uploaded to cloud storage.

        Returns:
            List of audio file dicts with storage_provider=None.
        """
        return self._rust_db.get_audio_files_pending_upload()

    def update_audio_file_storage(
        self,
        audio_file_id: str,
        storage_provider: str,
        storage_key: str,
    ) -> bool:
        """Update an audio file's cloud storage information after successful upload.

        Args:
            audio_file_id: Audio file UUID
            storage_provider: Provider name ("s3", etc.)
            storage_key: Object key/path in cloud storage

        Returns:
            True if the audio file was updated.
        """
        return self._rust_db.update_audio_file_storage(audio_file_id, storage_provider, storage_key)

    def clear_audio_file_storage(self, audio_file_id: str) -> bool:
        """Clear an audio file's cloud storage information.

        Args:
            audio_file_id: Audio file UUID

        Returns:
            True if the audio file was updated.
        """
        return self._rust_db.clear_audio_file_storage(audio_file_id)

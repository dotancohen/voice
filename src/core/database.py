"""Database operations for Voice Rewrite.

This module provides all data access functionality using SQLite.
All methods return JSON-serializable types (dicts, lists, primitives)
to support future CLI and web server modes.

UUIDs are stored as BLOB (16 bytes) and converted to hex strings for JSON output.

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, cast

from uuid6 import uuid7

from .validation import (
    ValidationError,
    validate_note_id,
    validate_tag_id,
    validate_tag_ids,
    validate_tag_path,
    validate_search_query,
    validate_tag_id_groups,
    uuid_to_hex,
)

logger = logging.getLogger(__name__)

# Placeholder device ID for local operations (will be replaced with real device ID from config)
_local_device_id: Optional[bytes] = None


def set_local_device_id(device_id: bytes) -> None:
    """Set the local device ID for database operations.

    Args:
        device_id: UUID7 bytes of this device
    """
    global _local_device_id
    _local_device_id = device_id


def get_local_device_id() -> bytes:
    """Get the local device ID, generating one if not set.

    Returns:
        UUID7 bytes of this device
    """
    global _local_device_id
    if _local_device_id is None:
        _local_device_id = uuid7().bytes
    return _local_device_id


def _uuid_to_hex(value: Optional[bytes]) -> Optional[str]:
    """Convert UUID bytes to hex string, handling None."""
    if value is None:
        return None
    return uuid.UUID(bytes=value).hex


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a database row dict, converting BLOB UUIDs to hex strings.

    Args:
        row: Database row as dict

    Returns:
        Dict with UUIDs converted to hex strings
    """
    result = {}
    for key, value in row.items():
        if isinstance(value, bytes) and len(value) == 16:
            # Assume 16-byte values are UUIDs
            result[key] = uuid.UUID(bytes=value).hex
        else:
            result[key] = value
    return result


def dict_factory(cursor: sqlite3.Cursor, row: sqlite3.Row) -> Dict[str, Any]:
    """Convert database row to dictionary.

    Args:
        cursor: Database cursor
        row: Database row

    Returns:
        Dictionary with column names as keys.
    """
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


class Database:
    """Manages SQLite database operations for notes and tags.

    This class provides a clean interface for all database operations.
    All methods return JSON-serializable data structures.

    Attributes:
        db_path: Path to the SQLite database file
        conn: Database connection (created on init)
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize database connection and create schema if needed.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = dict_factory
        self.init_database()
        logger.info(f"Database initialized at {db_path}")

    def init_database(self) -> None:
        """Create database schema if it doesn't exist.

        Creates tables: notes, tags, note_tags, sync_peers, conflicts, and all indexes.
        """
        with self.conn:
            cursor = self.conn.cursor()

            # Create notes table with UUID7 BLOB primary key
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id BLOB PRIMARY KEY,
                    created_at DATETIME NOT NULL,
                    content TEXT NOT NULL,
                    modified_at DATETIME,
                    deleted_at DATETIME,
                    device_id BLOB NOT NULL
                )
            """)

            # Create tags table with UUID7 BLOB primary key
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id BLOB PRIMARY KEY,
                    name TEXT NOT NULL,
                    parent_id BLOB,
                    created_at DATETIME NOT NULL,
                    modified_at DATETIME,
                    device_id BLOB NOT NULL,
                    FOREIGN KEY (parent_id) REFERENCES tags (id) ON DELETE CASCADE
                )
            """)

            # Create note_tags junction table with timestamps for sync
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS note_tags (
                    note_id BLOB NOT NULL,
                    tag_id BLOB NOT NULL,
                    created_at DATETIME NOT NULL,
                    deleted_at DATETIME,
                    device_id BLOB NOT NULL,
                    FOREIGN KEY (note_id) REFERENCES notes (id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE,
                    PRIMARY KEY (note_id, tag_id)
                )
            """)

            # Create sync_peers table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_peers (
                    peer_id BLOB PRIMARY KEY,
                    peer_name TEXT,
                    peer_url TEXT NOT NULL,
                    last_sync_at DATETIME,
                    last_received_timestamp DATETIME,
                    last_sent_timestamp DATETIME,
                    certificate_fingerprint BLOB
                )
            """)

            # Create conflicts_note_content table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conflicts_note_content (
                    id BLOB PRIMARY KEY,
                    note_id BLOB NOT NULL,
                    local_content TEXT NOT NULL,
                    local_modified_at DATETIME NOT NULL,
                    local_device_id BLOB NOT NULL,
                    local_device_name TEXT,
                    remote_content TEXT NOT NULL,
                    remote_modified_at DATETIME NOT NULL,
                    remote_device_id BLOB NOT NULL,
                    remote_device_name TEXT,
                    created_at DATETIME NOT NULL,
                    resolved_at DATETIME,
                    FOREIGN KEY (note_id) REFERENCES notes(id)
                )
            """)

            # Create conflicts_note_delete table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conflicts_note_delete (
                    id BLOB PRIMARY KEY,
                    note_id BLOB NOT NULL,
                    surviving_content TEXT NOT NULL,
                    surviving_modified_at DATETIME NOT NULL,
                    surviving_device_id BLOB NOT NULL,
                    surviving_device_name TEXT,
                    deleted_at DATETIME NOT NULL,
                    deleting_device_id BLOB NOT NULL,
                    deleting_device_name TEXT,
                    created_at DATETIME NOT NULL,
                    resolved_at DATETIME,
                    FOREIGN KEY (note_id) REFERENCES notes(id)
                )
            """)

            # Create conflicts_tag_rename table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conflicts_tag_rename (
                    id BLOB PRIMARY KEY,
                    tag_id BLOB NOT NULL,
                    local_name TEXT NOT NULL,
                    local_modified_at DATETIME NOT NULL,
                    local_device_id BLOB NOT NULL,
                    local_device_name TEXT,
                    remote_name TEXT NOT NULL,
                    remote_modified_at DATETIME NOT NULL,
                    remote_device_id BLOB NOT NULL,
                    remote_device_name TEXT,
                    created_at DATETIME NOT NULL,
                    resolved_at DATETIME,
                    FOREIGN KEY (tag_id) REFERENCES tags(id)
                )
            """)

            # Create sync_failures table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_failures (
                    id BLOB PRIMARY KEY,
                    peer_id BLOB NOT NULL,
                    peer_name TEXT,
                    entity_type TEXT NOT NULL,
                    entity_id BLOB,
                    operation TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    resolved_at DATETIME,
                    FOREIGN KEY (peer_id) REFERENCES sync_peers(peer_id)
                )
            """)

            # Create indexes
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_notes_created_at ON notes(created_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_notes_deleted_at ON notes(deleted_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_notes_modified_at ON notes(modified_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_tags_parent_id ON tags(parent_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(LOWER(name))"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_tags_modified_at ON tags(modified_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_note_tags_note ON note_tags(note_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags(tag_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_note_tags_created_at ON note_tags(created_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_note_tags_deleted_at ON note_tags(deleted_at)"
            )

            self.conn.commit()
            logger.info("Database schema created successfully")

    def get_all_notes(self) -> List[Dict[str, Any]]:
        """Get all non-deleted notes with their associated tag names.

        Returns:
            List of note dictionaries, each containing id (hex), created_at, content,
            modified_at, deleted_at, device_id (hex), and tag_names (comma-separated string).
        """
        query = """
            SELECT
                n.id,
                n.created_at,
                n.content,
                n.modified_at,
                n.deleted_at,
                n.device_id,
                GROUP_CONCAT(t.name, ', ') as tag_names
            FROM notes n
            LEFT JOIN note_tags nt ON n.id = nt.note_id AND nt.deleted_at IS NULL
            LEFT JOIN tags t ON nt.tag_id = t.id
            WHERE n.deleted_at IS NULL
            GROUP BY n.id
            ORDER BY n.created_at DESC
        """
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query)
            return [_row_to_dict(row) for row in cursor.fetchall()]

    def get_note(self, note_id: Union[bytes, str]) -> Optional[Dict[str, Any]]:
        """Retrieve a note by ID with its associated tags.

        Args:
            note_id: The ID of the note to retrieve (bytes or hex string)

        Returns:
            Dictionary containing note data and associated tags, or None if not found.

        Raises:
            ValidationError: If note_id is invalid.
            sqlite3.DatabaseError: If database query fails.
        """
        note_id_bytes = validate_note_id(note_id)
        query = """
            SELECT
                n.id,
                n.created_at,
                n.content,
                n.modified_at,
                n.deleted_at,
                n.device_id,
                GROUP_CONCAT(t.name, ', ') as tag_names
            FROM notes n
            LEFT JOIN note_tags nt ON n.id = nt.note_id AND nt.deleted_at IS NULL
            LEFT JOIN tags t ON nt.tag_id = t.id
            WHERE n.id = ?
            GROUP BY n.id
        """
        try:
            with self.conn:
                cursor = self.conn.cursor()
                cursor.execute(query, (note_id_bytes,))
                row = cursor.fetchone()
                return _row_to_dict(row) if row else None
        except sqlite3.DatabaseError as e:
            logger.error(f"Database error retrieving note {uuid_to_hex(note_id_bytes)}: {e}")
            raise

    def create_note(self, content: str = "") -> str:
        """Create a new note.

        Args:
            content: The content for the new note (can be empty)

        Returns:
            The hex ID of the newly created note.

        Raises:
            sqlite3.DatabaseError: If database insert fails.
        """
        note_id = uuid7().bytes
        device_id = get_local_device_id()

        query = """
            INSERT INTO notes (id, content, created_at, device_id)
            VALUES (?, ?, datetime('now'), ?)
        """
        try:
            with self.conn:
                cursor = self.conn.cursor()
                cursor.execute(query, (note_id, content, device_id))
                self.conn.commit()
                note_id_hex = uuid_to_hex(note_id)
                logger.info(f"Created note {note_id_hex}")
                return note_id_hex
        except sqlite3.DatabaseError as e:
            logger.error(f"Database error creating note: {e}")
            raise

    def update_note(self, note_id: Union[bytes, str], content: str) -> bool:
        """Update a note's content.

        Args:
            note_id: The ID of the note to update (bytes or hex string)
            content: The new content for the note

        Returns:
            True if the note was updated, False if note not found.

        Raises:
            ValidationError: If note_id or content is invalid.
            sqlite3.DatabaseError: If database update fails.
        """
        note_id_bytes = validate_note_id(note_id)
        if not content or not content.strip():
            raise ValidationError("content", "Note content cannot be empty")

        device_id = get_local_device_id()

        query = """
            UPDATE notes
            SET content = ?, modified_at = datetime('now'), device_id = ?
            WHERE id = ? AND deleted_at IS NULL
        """
        try:
            with self.conn:
                cursor = self.conn.cursor()
                cursor.execute(query, (content, device_id, note_id_bytes))
                self.conn.commit()
                updated = cursor.rowcount > 0
                if updated:
                    logger.info(f"Updated note {uuid_to_hex(note_id_bytes)}")
                else:
                    logger.warning(f"Note {uuid_to_hex(note_id_bytes)} not found or deleted")
                return updated
        except sqlite3.DatabaseError as e:
            logger.error(f"Database error updating note {uuid_to_hex(note_id_bytes)}: {e}")
            raise

    def delete_note(self, note_id: Union[bytes, str]) -> bool:
        """Soft-delete a note.

        Args:
            note_id: The ID of the note to delete (bytes or hex string)

        Returns:
            True if the note was deleted, False if note not found.

        Raises:
            ValidationError: If note_id is invalid.
            sqlite3.DatabaseError: If database update fails.
        """
        note_id_bytes = validate_note_id(note_id)
        device_id = get_local_device_id()

        query = """
            UPDATE notes
            SET deleted_at = datetime('now'), modified_at = datetime('now'), device_id = ?
            WHERE id = ? AND deleted_at IS NULL
        """
        try:
            with self.conn:
                cursor = self.conn.cursor()
                cursor.execute(query, (device_id, note_id_bytes))
                self.conn.commit()
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info(f"Deleted note {uuid_to_hex(note_id_bytes)}")
                return deleted
        except sqlite3.DatabaseError as e:
            logger.error(f"Database error deleting note {uuid_to_hex(note_id_bytes)}: {e}")
            raise

    def get_all_tags(self) -> List[Dict[str, Any]]:
        """Get all tags with their hierarchy information.

        Returns:
            List of tag dictionaries, each containing id (hex), name, parent_id (hex),
            created_at, modified_at, and device_id (hex). Ordered by name for display.
        """
        query = """
            SELECT id, name, parent_id, created_at, modified_at, device_id
            FROM tags
            ORDER BY name
        """
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query)
            return [_row_to_dict(row) for row in cursor.fetchall()]

    def get_tag_descendants(self, tag_id: Union[bytes, str]) -> List[bytes]:
        """Get all descendant tag IDs for a given tag using recursive CTE.

        This returns the tag itself plus all its children, grandchildren, etc.

        Args:
            tag_id: The ID of the root tag (bytes or hex string)

        Returns:
            List of tag IDs (as bytes) including the root tag and all descendants.

        Raises:
            ValidationError: If tag_id is invalid.
        """
        tag_id_bytes = validate_tag_id(tag_id)
        query = """
            WITH RECURSIVE tag_tree AS (
                SELECT id FROM tags WHERE id = ?
                UNION ALL
                SELECT t.id FROM tags t
                JOIN tag_tree tt ON t.parent_id = tt.id
            )
            SELECT id FROM tag_tree
        """
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query, (tag_id_bytes,))
            results = cursor.fetchall()
            return [row["id"] for row in results]

    def filter_notes(self, tag_ids: List[Union[bytes, str]]) -> List[Dict[str, Any]]:
        """Filter notes by tag IDs (including descendants).

        Args:
            tag_ids: List of tag IDs to filter by (bytes or hex strings)

        Returns:
            List of note dictionaries matching any of the specified tags.

        Raises:
            ValidationError: If any tag_id is invalid.
        """
        if not tag_ids:
            return self.get_all_notes()

        tag_ids_bytes = validate_tag_ids(tag_ids)

        # Build placeholders for SQL IN clause
        placeholders = ",".join("?" * len(tag_ids_bytes))

        query = f"""
            SELECT DISTINCT
                n.id,
                n.created_at,
                n.content,
                n.modified_at,
                n.deleted_at,
                n.device_id,
                GROUP_CONCAT(t.name, ', ') as tag_names
            FROM notes n
            INNER JOIN note_tags nt ON n.id = nt.note_id AND nt.deleted_at IS NULL
            LEFT JOIN tags t ON nt.tag_id = t.id
            WHERE n.deleted_at IS NULL
              AND n.id IN (
                  SELECT note_id FROM note_tags
                  WHERE tag_id IN ({placeholders}) AND deleted_at IS NULL
              )
            GROUP BY n.id
            ORDER BY n.created_at DESC
        """
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query, tag_ids_bytes)
            return [_row_to_dict(row) for row in cursor.fetchall()]

    def get_tag(self, tag_id: Union[bytes, str]) -> Optional[Dict[str, Any]]:
        """Get a single tag by ID.

        Args:
            tag_id: Tag ID to retrieve (bytes or hex string)

        Returns:
            Dictionary with tag data (id as hex), or None if not found.

        Raises:
            ValidationError: If tag_id is invalid.
        """
        tag_id_bytes = validate_tag_id(tag_id)
        query = "SELECT id, name, parent_id, created_at, modified_at, device_id FROM tags WHERE id = ?"
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query, (tag_id_bytes,))
            row = cursor.fetchone()
            return _row_to_dict(row) if row else None

    def get_tags_by_name(self, name: str) -> List[Dict[str, Any]]:
        """Get all tags with a given name (case-insensitive).

        Args:
            name: Tag name to search for

        Returns:
            List of tag dictionaries matching the name (ids as hex).
        """
        query = "SELECT id, name, parent_id, created_at, modified_at, device_id FROM tags WHERE LOWER(name) = LOWER(?)"
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query, (name,))
            return [_row_to_dict(row) for row in cursor.fetchall()]

    def get_tag_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        """Get a tag by hierarchical path (case-insensitive).

        Args:
            path: Tag path like "Europe/France/Paris" or just "Work"

        Returns:
            Dictionary with tag data (id as hex), or None if path not found.

        Raises:
            ValidationError: If path is invalid.
        """
        validate_tag_path(path)
        parts = path.split("/")
        current_parent_id: Optional[bytes] = None

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Find tag with this name and current parent
            if current_parent_id is None:
                query = "SELECT id, name, parent_id, created_at, modified_at, device_id FROM tags WHERE LOWER(name) = LOWER(?) AND parent_id IS NULL"
                params: Tuple[Any, ...] = (part,)
            else:
                query = "SELECT id, name, parent_id, created_at, modified_at, device_id FROM tags WHERE LOWER(name) = LOWER(?) AND parent_id = ?"
                params = (part, current_parent_id)

            with self.conn:
                cursor = self.conn.cursor()
                cursor.execute(query, params)
                result = cursor.fetchone()

                if result is None:
                    return None

                current_parent_id = result["id"]

        # Return the final tag
        if current_parent_id is not None:
            return self.get_tag(current_parent_id)

        return None

    def get_all_tags_by_path(self, path: str) -> List[Dict[str, Any]]:
        """Get all tags matching a path (case-insensitive).

        This is similar to get_tag_by_path but returns ALL matching tags.
        For simple names (no '/'), returns all tags with that name.
        For full paths, returns the specific tag if unique, or all matches if ambiguous.

        Args:
            path: Tag path like "bar" (could match Foo/bar and Boom/bar) or "Foo/bar" (specific)

        Returns:
            List of tag dictionaries matching the path (ids as hex). Empty if not found.

        Raises:
            ValidationError: If path is invalid.
        """
        validate_tag_path(path)
        parts = path.split("/")

        # If just a simple name (no slashes), return all tags with that name
        if len(parts) == 1:
            return self.get_tags_by_name(parts[0].strip())

        # For full paths, navigate through hierarchy
        # Start with all root tags matching the first part
        current_tags: List[Dict[str, Any]] = []
        first_part = parts[0].strip()

        query = "SELECT id, name, parent_id, created_at, modified_at, device_id FROM tags WHERE LOWER(name) = LOWER(?) AND parent_id IS NULL"
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query, (first_part,))
            current_tags = [_row_to_dict(row) for row in cursor.fetchall()]

        if not current_tags:
            return []

        # Navigate through remaining parts
        for part in parts[1:]:
            part = part.strip()
            if not part:
                continue

            next_tags: List[Dict[str, Any]] = []
            for tag in current_tags:
                # Convert hex back to bytes for query
                tag_id_bytes = uuid.UUID(hex=tag["id"]).bytes
                query = "SELECT id, name, parent_id, created_at, modified_at, device_id FROM tags WHERE LOWER(name) = LOWER(?) AND parent_id = ?"
                with self.conn:
                    cursor = self.conn.cursor()
                    cursor.execute(query, (part, tag_id_bytes))
                    matches = [_row_to_dict(row) for row in cursor.fetchall()]
                    next_tags.extend(matches)

            current_tags = next_tags
            if not current_tags:
                return []

        return current_tags

    def is_tag_name_ambiguous(self, name: str) -> bool:
        """Check if a tag name is ambiguous (appears more than once).

        Args:
            name: Tag name to check (without path)

        Returns:
            True if multiple tags have this name, False otherwise.
        """
        tags = self.get_tags_by_name(name)
        return len(tags) > 1

    def search_notes(
        self, text_query: Optional[str] = None, tag_id_groups: Optional[List[List[Union[bytes, str]]]] = None
    ) -> List[Dict[str, Any]]:
        """Search notes by text content and/or tags using AND logic.

        All search criteria are combined with AND logic:
        - The text query (if provided) AND
        - Each tag group (note must have at least one tag from each group)

        Tag groups represent hierarchical searches. For example:
        - tag:Foo expands to [1,2,3] (Foo and descendants)
        - tag:bar expands to [2] (just bar)
        - Note must have (1 OR 2 OR 3) AND (2)

        Args:
            text_query: Text to search in note content (case-insensitive)
            tag_id_groups: List of tag ID groups - note must have at least one tag from EACH group

        Returns:
            List of note dictionaries matching ALL criteria (ids as hex).

        Raises:
            ValidationError: If text_query or tag_id_groups are invalid.
        """
        validate_search_query(text_query)
        validated_groups = validate_tag_id_groups(tag_id_groups)

        query = """
            SELECT DISTINCT
                n.id,
                n.created_at,
                n.content,
                n.modified_at,
                n.deleted_at,
                n.device_id,
                GROUP_CONCAT(t.name, ', ') as tag_names
            FROM notes n
            LEFT JOIN note_tags nt ON n.id = nt.note_id AND nt.deleted_at IS NULL
            LEFT JOIN tags t ON nt.tag_id = t.id
            WHERE n.deleted_at IS NULL
        """

        params: List[Any] = []

        # Add text search condition
        if text_query and text_query.strip():
            query += " AND LOWER(n.content) LIKE LOWER(?)"
            params.append(f"%{text_query}%")

        # Add tag filter condition (AND logic - note must have at least one tag from EACH group)
        if validated_groups:
            for tag_group in validated_groups:
                if tag_group:  # Skip empty groups
                    placeholders = ",".join("?" * len(tag_group))
                    query += f"""
                        AND EXISTS (
                            SELECT 1 FROM note_tags
                            WHERE note_id = n.id AND tag_id IN ({placeholders}) AND deleted_at IS NULL
                        )
                    """
                    params.extend(tag_group)

        query += """
            GROUP BY n.id
            ORDER BY n.created_at DESC
        """

        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            return [_row_to_dict(row) for row in cursor.fetchall()]

    def create_tag(self, name: str, parent_id: Optional[Union[bytes, str]] = None) -> str:
        """Create a new tag.

        Args:
            name: Tag name
            parent_id: Parent tag ID (bytes or hex string), or None for root tag

        Returns:
            The hex ID of the newly created tag.

        Raises:
            ValidationError: If name or parent_id is invalid.
            sqlite3.DatabaseError: If database insert fails.
        """
        tag_id = uuid7().bytes
        device_id = get_local_device_id()
        parent_id_bytes = None
        if parent_id is not None:
            parent_id_bytes = validate_tag_id(parent_id)

        query = """
            INSERT INTO tags (id, name, parent_id, created_at, device_id)
            VALUES (?, ?, ?, datetime('now'), ?)
        """
        try:
            with self.conn:
                cursor = self.conn.cursor()
                cursor.execute(query, (tag_id, name, parent_id_bytes, device_id))
                self.conn.commit()
                tag_id_hex = uuid_to_hex(tag_id)
                logger.info(f"Created tag {tag_id_hex}: {name}")
                return tag_id_hex
        except sqlite3.DatabaseError as e:
            logger.error(f"Database error creating tag: {e}")
            raise

    def add_tag_to_note(self, note_id: Union[bytes, str], tag_id: Union[bytes, str]) -> bool:
        """Add a tag to a note.

        Args:
            note_id: Note ID (bytes or hex string)
            tag_id: Tag ID (bytes or hex string)

        Returns:
            True if the tag was added, False if already exists.

        Raises:
            ValidationError: If note_id or tag_id is invalid.
            sqlite3.DatabaseError: If database insert fails.
        """
        note_id_bytes = validate_note_id(note_id)
        tag_id_bytes = validate_tag_id(tag_id)
        device_id = get_local_device_id()

        # Check if association exists (including soft-deleted)
        check_query = "SELECT deleted_at FROM note_tags WHERE note_id = ? AND tag_id = ?"
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(check_query, (note_id_bytes, tag_id_bytes))
            existing = cursor.fetchone()

            if existing:
                if existing["deleted_at"] is not None:
                    # Reactivate soft-deleted association
                    update_query = """
                        UPDATE note_tags
                        SET deleted_at = NULL, device_id = ?
                        WHERE note_id = ? AND tag_id = ?
                    """
                    cursor.execute(update_query, (device_id, note_id_bytes, tag_id_bytes))
                    self.conn.commit()
                    return True
                else:
                    # Already active
                    return False

            # Create new association
            insert_query = """
                INSERT INTO note_tags (note_id, tag_id, created_at, device_id)
                VALUES (?, ?, datetime('now'), ?)
            """
            try:
                cursor.execute(insert_query, (note_id_bytes, tag_id_bytes, device_id))
                self.conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def remove_tag_from_note(self, note_id: Union[bytes, str], tag_id: Union[bytes, str]) -> bool:
        """Remove a tag from a note (soft delete).

        Args:
            note_id: Note ID (bytes or hex string)
            tag_id: Tag ID (bytes or hex string)

        Returns:
            True if the tag was removed, False if not found.

        Raises:
            ValidationError: If note_id or tag_id is invalid.
            sqlite3.DatabaseError: If database update fails.
        """
        note_id_bytes = validate_note_id(note_id)
        tag_id_bytes = validate_tag_id(tag_id)
        device_id = get_local_device_id()

        query = """
            UPDATE note_tags
            SET deleted_at = datetime('now'), device_id = ?
            WHERE note_id = ? AND tag_id = ? AND deleted_at IS NULL
        """
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query, (device_id, note_id_bytes, tag_id_bytes))
            self.conn.commit()
            return cursor.rowcount > 0

    def get_note_tags(self, note_id: Union[bytes, str]) -> List[Dict[str, Any]]:
        """Get all active tags for a note.

        Args:
            note_id: Note ID (bytes or hex string)

        Returns:
            List of tag dictionaries (ids as hex).

        Raises:
            ValidationError: If note_id is invalid.
        """
        note_id_bytes = validate_note_id(note_id)
        query = """
            SELECT t.id, t.name, t.parent_id, t.created_at, t.modified_at, t.device_id
            FROM tags t
            INNER JOIN note_tags nt ON t.id = nt.tag_id
            WHERE nt.note_id = ? AND nt.deleted_at IS NULL
            ORDER BY t.name
        """
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query, (note_id_bytes,))
            return [_row_to_dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")

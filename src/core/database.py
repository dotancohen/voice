"""Database operations for Voice Rewrite.

This module provides all data access functionality using SQLite.
All methods return JSON-serializable types (dicts, lists, primitives)
to support future CLI and web server modes.

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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

        Creates tables: notes, tags, note_tags and all indexes.
        """
        with self.conn:
            cursor = self.conn.cursor()

            # Create notes table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at DATETIME NOT NULL,
                    content TEXT NOT NULL,
                    modified_at DATETIME,
                    deleted_at DATETIME,
                    CHECK (datetime(created_at) IS NOT NULL),
                    CHECK (datetime(modified_at) IS NULL OR datetime(modified_at) IS NOT NULL),
                    CHECK (datetime(deleted_at) IS NULL OR datetime(deleted_at) IS NOT NULL)
                )
            """)

            # Create tags table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    parent_id INTEGER,
                    FOREIGN KEY (parent_id) REFERENCES tags (id) ON DELETE CASCADE,
                    CHECK (parent_id IS NULL OR parent_id != id)
                )
            """)

            # Create note_tags junction table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS note_tags (
                    note_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    FOREIGN KEY (note_id) REFERENCES notes (id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE,
                    PRIMARY KEY (note_id, tag_id)
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
                "CREATE INDEX IF NOT EXISTS idx_tags_parent_id ON tags(parent_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(LOWER(name))"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_note_tags_note ON note_tags(note_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags(tag_id)"
            )

            self.conn.commit()
            logger.info("Database schema created successfully")

    def get_all_notes(self) -> List[Dict[str, Any]]:
        """Get all non-deleted notes with their associated tag names.

        Returns:
            List of note dictionaries, each containing id, created_at, content,
            modified_at, deleted_at, and tag_names (comma-separated string).
        """
        query = """
            SELECT
                n.id,
                n.created_at,
                n.content,
                n.modified_at,
                n.deleted_at,
                GROUP_CONCAT(t.name, ', ') as tag_names
            FROM notes n
            LEFT JOIN note_tags nt ON n.id = nt.note_id
            LEFT JOIN tags t ON nt.tag_id = t.id
            WHERE n.deleted_at IS NULL
            GROUP BY n.id
            ORDER BY n.created_at DESC
        """
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query)
            return cursor.fetchall()

    def get_note(self, note_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a note by ID with its associated tags.

        Args:
            note_id: The ID of the note to retrieve

        Returns:
            Dictionary containing note data and associated tags, or None if not found.

        Raises:
            sqlite3.DatabaseError: If database query fails.
        """
        query = """
            SELECT
                n.id,
                n.created_at,
                n.content,
                n.modified_at,
                n.deleted_at,
                GROUP_CONCAT(t.name, ', ') as tag_names
            FROM notes n
            LEFT JOIN note_tags nt ON n.id = nt.note_id
            LEFT JOIN tags t ON nt.tag_id = t.id
            WHERE n.id = ?
            GROUP BY n.id
        """
        try:
            with self.conn:
                cursor = self.conn.cursor()
                cursor.execute(query, (note_id,))
                result = cursor.fetchone()
                return result
        except sqlite3.DatabaseError as e:
            logger.error(f"Database error retrieving note {note_id}: {e}")
            raise

    def get_all_tags(self) -> List[Dict[str, Any]]:
        """Get all tags with their hierarchy information.

        Returns:
            List of tag dictionaries, each containing id, name, and parent_id.
            Ordered by name for display purposes.
        """
        query = """
            SELECT id, name, parent_id
            FROM tags
            ORDER BY name
        """
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query)
            return cursor.fetchall()

    def get_tag_descendants(self, tag_id: int) -> List[int]:
        """Get all descendant tag IDs for a given tag using recursive CTE.

        This returns the tag itself plus all its children, grandchildren, etc.

        Args:
            tag_id: The ID of the root tag

        Returns:
            List of tag IDs including the root tag and all descendants.
        """
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
            cursor.execute(query, (tag_id,))
            results = cursor.fetchall()
            return [row["id"] for row in results]

    def filter_notes(self, tag_ids: List[int]) -> List[Dict[str, Any]]:
        """Filter notes by tag IDs (including descendants).

        Args:
            tag_ids: List of tag IDs to filter by

        Returns:
            List of note dictionaries matching any of the specified tags.
        """
        if not tag_ids:
            return self.get_all_notes()

        # Build placeholders for SQL IN clause
        placeholders = ",".join("?" * len(tag_ids))

        query = f"""
            SELECT DISTINCT
                n.id,
                n.created_at,
                n.content,
                n.modified_at,
                n.deleted_at,
                GROUP_CONCAT(t.name, ', ') as tag_names
            FROM notes n
            INNER JOIN note_tags nt ON n.id = nt.note_id
            LEFT JOIN tags t ON nt.tag_id = t.id
            WHERE n.deleted_at IS NULL
              AND n.id IN (
                  SELECT note_id FROM note_tags
                  WHERE tag_id IN ({placeholders})
              )
            GROUP BY n.id
            ORDER BY n.created_at DESC
        """
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query, tag_ids)
            return cursor.fetchall()

    def get_tag(self, tag_id: int) -> Optional[Dict[str, Any]]:
        """Get a single tag by ID.

        Args:
            tag_id: Tag ID to retrieve

        Returns:
            Dictionary with tag data, or None if not found.
        """
        query = "SELECT id, name, parent_id FROM tags WHERE id = ?"
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query, (tag_id,))
            return cursor.fetchone()

    def get_tags_by_name(self, name: str) -> List[Dict[str, Any]]:
        """Get all tags with a given name (case-insensitive).

        Args:
            name: Tag name to search for

        Returns:
            List of tag dictionaries matching the name.
        """
        query = "SELECT id, name, parent_id FROM tags WHERE LOWER(name) = LOWER(?)"
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query, (name,))
            return cursor.fetchall()

    def get_tag_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        """Get a tag by hierarchical path (case-insensitive).

        Args:
            path: Tag path like "Europe/France/Paris" or just "Work"

        Returns:
            Dictionary with tag data, or None if path not found.
        """
        parts = path.split("/")
        current_parent_id: Optional[int] = None

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Find tag with this name and current parent
            if current_parent_id is None:
                query = "SELECT id, name, parent_id FROM tags WHERE LOWER(name) = LOWER(?) AND parent_id IS NULL"
                params = (part,)
            else:
                query = "SELECT id, name, parent_id FROM tags WHERE LOWER(name) = LOWER(?) AND parent_id = ?"
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
            List of tag dictionaries matching the path. Empty if not found.
        """
        parts = path.split("/")

        # If just a simple name (no slashes), return all tags with that name
        if len(parts) == 1:
            return self.get_tags_by_name(parts[0].strip())

        # For full paths, navigate through hierarchy
        # Start with all root tags matching the first part
        current_tags = []
        first_part = parts[0].strip()

        query = "SELECT id, name, parent_id FROM tags WHERE LOWER(name) = LOWER(?) AND parent_id IS NULL"
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(query, (first_part,))
            current_tags = cursor.fetchall()

        if not current_tags:
            return []

        # Navigate through remaining parts
        for part in parts[1:]:
            part = part.strip()
            if not part:
                continue

            next_tags = []
            for tag in current_tags:
                query = "SELECT id, name, parent_id FROM tags WHERE LOWER(name) = LOWER(?) AND parent_id = ?"
                with self.conn:
                    cursor = self.conn.cursor()
                    cursor.execute(query, (part, tag["id"]))
                    matches = cursor.fetchall()
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
        self, text_query: Optional[str] = None, tag_id_groups: Optional[List[List[int]]] = None
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
            List of note dictionaries matching ALL criteria.
        """
        query = """
            SELECT DISTINCT
                n.id,
                n.created_at,
                n.content,
                n.modified_at,
                n.deleted_at,
                GROUP_CONCAT(t.name, ', ') as tag_names
            FROM notes n
            LEFT JOIN note_tags nt ON n.id = nt.note_id
            LEFT JOIN tags t ON nt.tag_id = t.id
            WHERE n.deleted_at IS NULL
        """

        params: List[Any] = []

        # Add text search condition
        if text_query and text_query.strip():
            query += " AND LOWER(n.content) LIKE LOWER(?)"
            params.append(f"%{text_query}%")

        # Add tag filter condition (AND logic - note must have at least one tag from EACH group)
        if tag_id_groups:
            for tag_group in tag_id_groups:
                if tag_group:  # Skip empty groups
                    placeholders = ",".join("?" * len(tag_group))
                    query += f"""
                        AND EXISTS (
                            SELECT 1 FROM note_tags
                            WHERE note_id = n.id AND tag_id IN ({placeholders})
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
            return cursor.fetchall()

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")

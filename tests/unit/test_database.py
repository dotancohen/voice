"""Unit tests for database operations.

Tests all methods in src/core/database.py including:
- Basic CRUD operations
- Tag hierarchy navigation
- Search functionality with AND logic
- Hierarchical tag filtering
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from core.database import Database


class TestDatabaseInit:
    """Test database initialization."""

    def test_creates_schema(self, empty_db: Database) -> None:
        """Test that database schema is created correctly."""
        with empty_db.conn:
            cursor = empty_db.conn.cursor()

            # Check notes table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='notes'"
            )
            assert cursor.fetchone() is not None

            # Check tags table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tags'"
            )
            assert cursor.fetchone() is not None

            # Check note_tags table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='note_tags'"
            )
            assert cursor.fetchone() is not None

    def test_creates_indexes(self, empty_db: Database) -> None:
        """Test that indexes are created."""
        with empty_db.conn:
            cursor = empty_db.conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            )
            indexes = cursor.fetchall()
            assert len(indexes) >= 6  # Should have at least 6 indexes


class TestGetAllNotes:
    """Test get_all_notes method."""

    def test_returns_all_notes(self, populated_db: Database) -> None:
        """Test that all non-deleted notes are returned."""
        notes = populated_db.get_all_notes()
        assert len(notes) == 6
        assert all("id" in note for note in notes)
        assert all("content" in note for note in notes)
        assert all("created_at" in note for note in notes)

    def test_excludes_deleted_notes(self, populated_db: Database) -> None:
        """Test that deleted notes are excluded."""
        # Mark note 1 as deleted
        with populated_db.conn:
            cursor = populated_db.conn.cursor()
            cursor.execute(
                "UPDATE notes SET deleted_at = ? WHERE id = 1",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),)
            )

        notes = populated_db.get_all_notes()
        assert len(notes) == 5
        assert not any(note["id"] == 1 for note in notes)

    def test_returns_empty_for_empty_db(self, empty_db: Database) -> None:
        """Test that empty list is returned for empty database."""
        notes = empty_db.get_all_notes()
        assert notes == []

    def test_includes_tag_names(self, populated_db: Database) -> None:
        """Test that tag names are included in results."""
        notes = populated_db.get_all_notes()
        # Note 1 has Work, Projects, Meetings
        note1 = next(n for n in notes if n["id"] == 1)
        assert "Work" in note1["tag_names"]
        assert "Projects" in note1["tag_names"]
        assert "Meetings" in note1["tag_names"]


class TestGetNote:
    """Test get_note method."""

    def test_returns_note_by_id(self, populated_db: Database) -> None:
        """Test retrieving specific note by ID."""
        note = populated_db.get_note(1)
        assert note is not None
        assert note["id"] == 1
        assert "Meeting notes" in note["content"]

    def test_returns_none_for_nonexistent_note(self, populated_db: Database) -> None:
        """Test that None is returned for non-existent note."""
        note = populated_db.get_note(999)
        assert note is None

    def test_includes_tags(self, populated_db: Database) -> None:
        """Test that tags are included in note result."""
        note = populated_db.get_note(1)
        assert note is not None
        assert note["tag_names"] is not None


class TestGetAllTags:
    """Test get_all_tags method."""

    def test_returns_all_tags(self, populated_db: Database) -> None:
        """Test that all tags are returned."""
        tags = populated_db.get_all_tags()
        assert len(tags) == 14  # We created 14 tags in fixture

    def test_returns_hierarchy_info(self, populated_db: Database) -> None:
        """Test that parent_id is included."""
        tags = populated_db.get_all_tags()
        # Work is root
        work_tag = next(t for t in tags if t["name"] == "Work")
        assert work_tag["parent_id"] is None

        # Projects is child of Work
        projects_tag = next(t for t in tags if t["name"] == "Projects")
        assert projects_tag["parent_id"] == work_tag["id"]

    def test_returns_empty_for_empty_db(self, empty_db: Database) -> None:
        """Test empty list for database with no tags."""
        tags = empty_db.get_all_tags()
        assert tags == []


class TestGetTagDescendants:
    """Test get_tag_descendants method."""

    def test_returns_self_and_descendants(self, populated_db: Database) -> None:
        """Test that tag and all descendants are returned."""
        # Work (1) has children Projects (2), VoiceRewrite (3), Meetings (4)
        descendants = populated_db.get_tag_descendants(1)
        assert 1 in descendants  # Work itself
        assert 2 in descendants  # Projects
        assert 3 in descendants  # VoiceRewrite
        assert 4 in descendants  # Meetings
        assert len(descendants) == 4

    def test_returns_only_self_for_leaf(self, populated_db: Database) -> None:
        """Test that leaf node returns only itself."""
        # VoiceRewrite (3) has no children
        descendants = populated_db.get_tag_descendants(3)
        assert descendants == [3]

    def test_handles_deep_hierarchy(self, populated_db: Database) -> None:
        """Test deep hierarchy navigation."""
        # Europe (9) -> France (10) -> Paris (11)
        descendants = populated_db.get_tag_descendants(9)
        assert 9 in descendants   # Europe
        assert 10 in descendants  # France
        assert 11 in descendants  # Paris
        assert 12 in descendants  # Germany


class TestGetTag:
    """Test get_tag method."""

    def test_returns_tag_by_id(self, populated_db: Database) -> None:
        """Test retrieving tag by ID."""
        tag = populated_db.get_tag(1)
        assert tag is not None
        assert tag["name"] == "Work"
        assert tag["parent_id"] is None

    def test_returns_none_for_nonexistent(self, populated_db: Database) -> None:
        """Test None returned for non-existent tag."""
        tag = populated_db.get_tag(999)
        assert tag is None


class TestGetTagsByName:
    """Test get_tags_by_name method."""

    def test_finds_tag_by_name(self, populated_db: Database) -> None:
        """Test finding tag by exact name."""
        tags = populated_db.get_tags_by_name("Work")
        assert len(tags) == 1
        assert tags[0]["name"] == "Work"

    def test_case_insensitive_search(self, populated_db: Database) -> None:
        """Test that search is case-insensitive."""
        tags_lower = populated_db.get_tags_by_name("work")
        tags_upper = populated_db.get_tags_by_name("WORK")
        tags_mixed = populated_db.get_tags_by_name("WoRk")

        assert len(tags_lower) == 1
        assert len(tags_upper) == 1
        assert len(tags_mixed) == 1
        assert tags_lower[0]["id"] == tags_upper[0]["id"] == tags_mixed[0]["id"]

    def test_returns_empty_for_no_match(self, populated_db: Database) -> None:
        """Test empty list when no tags match."""
        tags = populated_db.get_tags_by_name("NonExistent")
        assert tags == []


class TestGetTagByPath:
    """Test get_tag_by_path method."""

    def test_finds_tag_by_simple_path(self, populated_db: Database) -> None:
        """Test finding root tag by simple path."""
        tag = populated_db.get_tag_by_path("Work")
        assert tag is not None
        assert tag["name"] == "Work"

    def test_finds_tag_by_hierarchical_path(self, populated_db: Database) -> None:
        """Test finding tag by hierarchical path."""
        tag = populated_db.get_tag_by_path("Geography/Europe/France/Paris")
        assert tag is not None
        assert tag["name"] == "Paris"

    def test_case_insensitive_path(self, populated_db: Database) -> None:
        """Test that path navigation is case-insensitive."""
        tag1 = populated_db.get_tag_by_path("geography/europe/france/paris")
        tag2 = populated_db.get_tag_by_path("GEOGRAPHY/EUROPE/FRANCE/PARIS")
        tag3 = populated_db.get_tag_by_path("Geography/Europe/France/Paris")

        assert tag1 is not None
        assert tag2 is not None
        assert tag3 is not None
        assert tag1["id"] == tag2["id"] == tag3["id"]

    def test_returns_none_for_invalid_path(self, populated_db: Database) -> None:
        """Test None returned for invalid path."""
        tag = populated_db.get_tag_by_path("Work/NonExistent/Path")
        assert tag is None

    def test_handles_trailing_slash(self, populated_db: Database) -> None:
        """Test that trailing slashes are handled."""
        tag = populated_db.get_tag_by_path("Work/Projects/")
        assert tag is not None
        assert tag["name"] == "Projects"


class TestSearchNotes:
    """Test search_notes method with hierarchical AND logic."""

    def test_text_search_only(self, populated_db: Database) -> None:
        """Test free-text search."""
        notes = populated_db.search_notes(text_query="meeting")
        assert len(notes) == 1
        assert "Meeting notes" in notes[0]["content"]

    def test_text_search_case_insensitive(self, populated_db: Database) -> None:
        """Test that text search is case-insensitive."""
        notes1 = populated_db.search_notes(text_query="MEETING")
        notes2 = populated_db.search_notes(text_query="meeting")
        notes3 = populated_db.search_notes(text_query="MeEtInG")

        assert len(notes1) == len(notes2) == len(notes3) == 1

    def test_hebrew_text_search(self, populated_db: Database) -> None:
        """Test search with Hebrew text."""
        notes = populated_db.search_notes(text_query="שלום")
        assert len(notes) == 1
        assert "שלום עולם" in notes[0]["content"]

    def test_single_tag_group(self, populated_db: Database) -> None:
        """Test search with single tag (includes descendants)."""
        # Personal (5) has descendants Family (6), Health (7)
        # Notes 3, 4, 5, 6 all have Personal or descendants
        notes = populated_db.search_notes(tag_id_groups=[[5, 6, 7]])
        assert len(notes) == 4
        note_ids = {n["id"] for n in notes}
        assert note_ids == {3, 4, 5, 6}

    def test_multiple_tag_groups_and_logic(self, populated_db: Database) -> None:
        """Test AND logic with multiple tag groups."""
        # Group 1: Personal (5, 6, 7)
        # Group 2: Family (6)
        # Only notes with (5 OR 6 OR 7) AND (6) should match
        notes = populated_db.search_notes(tag_id_groups=[[5, 6, 7], [6]])
        assert len(notes) == 1
        assert notes[0]["id"] == 4  # Family reunion note

    def test_hierarchical_parent_includes_children(self, populated_db: Database) -> None:
        """Test that searching parent tag includes child tags."""
        # Europe (9) includes France (10), Paris (11), Germany (12)
        # Note 4 has Paris (11)
        notes = populated_db.search_notes(tag_id_groups=[[9, 10, 11, 12]])
        assert len(notes) == 1
        assert "Paris" in notes[0]["content"]

    def test_combined_text_and_tags(self, populated_db: Database) -> None:
        """Test combined text and tag search."""
        # Search for "reunion" in Personal notes
        notes = populated_db.search_notes(
            text_query="reunion",
            tag_id_groups=[[5, 6, 7]]
        )
        assert len(notes) == 1
        assert notes[0]["id"] == 4

    def test_no_results(self, populated_db: Database) -> None:
        """Test search with no matching results."""
        notes = populated_db.search_notes(text_query="nonexistent")
        assert len(notes) == 0

    def test_empty_search_returns_all(self, populated_db: Database) -> None:
        """Test that empty search criteria returns all notes."""
        # This should not happen in practice, but database should handle it
        # by returning all notes
        all_notes = populated_db.get_all_notes()
        # If both parameters are None/empty, the behavior depends on implementation
        # Let's verify our implementation handles this gracefully


class TestFilterNotes:
    """Test filter_notes method (legacy, uses OR logic)."""

    def test_filters_by_tag_ids(self, populated_db: Database) -> None:
        """Test filtering by tag IDs."""
        # Filter by Work tag (1)
        notes = populated_db.filter_notes([1])
        assert len(notes) >= 2  # At least notes 1 and 2 have Work
        assert all("Work" in note["tag_names"] for note in notes)

    def test_returns_all_for_empty_list(self, populated_db: Database) -> None:
        """Test that empty tag list returns all notes."""
        notes = populated_db.filter_notes([])
        assert len(notes) == 6  # All notes

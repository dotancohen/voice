"""Unit tests for database operations.

Tests all methods in src/core/database.py including:
- Basic CRUD operations
- Tag hierarchy navigation
- Search functionality with AND logic
- Hierarchical tag filtering
"""

from __future__ import annotations

from datetime import datetime

import pytest

from core.database import Database
from tests.conftest import (
    get_tag_uuid_hex, get_note_uuid_hex, TAG_UUIDS, NOTE_UUIDS, uuid_to_hex
)


class TestDatabaseInit:
    """Test database initialization."""

    def test_creates_schema(self, empty_db: Database) -> None:
        """Test that database schema is created correctly.

        The Rust Database creates schema automatically. We verify by testing
        that CRUD operations work correctly.
        """
        # Schema is verified by successful CRUD operations
        # Create a note and tag to verify schema exists
        note_id = empty_db.create_note("Test note for schema verification")
        assert note_id is not None
        assert len(note_id) == 32  # UUID hex

        tag_id = empty_db.create_tag("TestTag")
        assert tag_id is not None
        assert len(tag_id) == 32  # UUID hex

        # If we get here without errors, schema is correctly created

    def test_creates_indexes(self, empty_db: Database) -> None:
        """Test that indexes are created.

        Indexes are created by the Rust Database automatically during initialization.
        We verify by testing that queries perform correctly (indirectly testing indexes).
        """
        # Create multiple notes
        for i in range(10):
            empty_db.create_note(f"Test note {i}")

        # Verify search works (uses FTS index)
        results = empty_db.search_notes(text_query="Test note")
        assert len(results) == 10

        # If we get here without errors, indexes are working


class TestGetAllNotes:
    """Test get_all_notes method."""

    def test_returns_all_notes(self, populated_db: Database) -> None:
        """Test that all non-deleted notes are returned."""
        notes = populated_db.get_all_notes()
        assert len(notes) == 9
        assert all("id" in note for note in notes)
        assert all("content" in note for note in notes)
        assert all("created_at" in note for note in notes)
        # IDs should be hex strings
        assert all(len(note["id"]) == 32 for note in notes)

    def test_excludes_deleted_notes(self, populated_db: Database) -> None:
        """Test that deleted notes are excluded."""
        # Mark note 1 as deleted using the delete_note method
        note_1_hex = get_note_uuid_hex(1)
        result = populated_db.delete_note(note_1_hex)
        assert result is True

        notes = populated_db.get_all_notes()
        assert len(notes) == 8  # 9 notes - 1 deleted
        assert not any(note["id"] == note_1_hex for note in notes)

    def test_returns_empty_for_empty_db(self, empty_db: Database) -> None:
        """Test that empty list is returned for empty database."""
        notes = empty_db.get_all_notes()
        assert notes == []

    def test_includes_tag_names(self, populated_db: Database) -> None:
        """Test that tag names are included in results."""
        notes = populated_db.get_all_notes()
        note_1_hex = get_note_uuid_hex(1)
        # Note 1 has Work, Projects, Meetings
        note1 = next(n for n in notes if n["id"] == note_1_hex)
        assert "Work" in note1["tag_names"]
        assert "Projects" in note1["tag_names"]
        assert "Meetings" in note1["tag_names"]


class TestGetNote:
    """Test get_note method."""

    def test_returns_note_by_id(self, populated_db: Database) -> None:
        """Test retrieving specific note by ID."""
        note_1_hex = get_note_uuid_hex(1)
        note = populated_db.get_note(note_1_hex)
        assert note is not None
        assert note["id"] == note_1_hex
        assert "Meeting notes" in note["content"]

    def test_returns_none_for_nonexistent_note(self, populated_db: Database) -> None:
        """Test that None is returned for non-existent note."""
        fake_id = "00000000000070008000999999999999"
        note = populated_db.get_note(fake_id)
        assert note is None

    def test_includes_tags(self, populated_db: Database) -> None:
        """Test that tags are included in note result."""
        note_1_hex = get_note_uuid_hex(1)
        note = populated_db.get_note(note_1_hex)
        assert note is not None
        assert note["tag_names"] is not None


class TestGetAllTags:
    """Test get_all_tags method."""

    def test_returns_all_tags(self, populated_db: Database) -> None:
        """Test that all tags are returned."""
        tags = populated_db.get_all_tags()
        assert len(tags) == 21  # We created 21 tags in fixture

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
        # Work has children Projects, Voice, Meetings
        work_hex = get_tag_uuid_hex("Work")
        descendants = populated_db.get_tag_descendants(work_hex)
        assert TAG_UUIDS["Work"] in descendants  # Work itself
        assert TAG_UUIDS["Projects"] in descendants  # Projects
        assert TAG_UUIDS["Voice"] in descendants  # Voice
        assert TAG_UUIDS["Meetings"] in descendants  # Meetings
        assert len(descendants) == 4

    def test_returns_only_self_for_leaf(self, populated_db: Database) -> None:
        """Test that leaf node returns only itself."""
        # Voice has no children
        voice_hex = get_tag_uuid_hex("Voice")
        descendants = populated_db.get_tag_descendants(voice_hex)
        assert descendants == [TAG_UUIDS["Voice"]]

    def test_handles_deep_hierarchy(self, populated_db: Database) -> None:
        """Test deep hierarchy navigation."""
        # Europe -> France -> Paris, Germany
        europe_hex = get_tag_uuid_hex("Europe")
        descendants = populated_db.get_tag_descendants(europe_hex)
        assert TAG_UUIDS["Europe"] in descendants   # Europe
        assert TAG_UUIDS["France"] in descendants  # France
        assert TAG_UUIDS["Paris_France"] in descendants  # Paris
        assert TAG_UUIDS["Germany"] in descendants  # Germany


class TestGetTag:
    """Test get_tag method."""

    def test_returns_tag_by_id(self, populated_db: Database) -> None:
        """Test retrieving tag by ID."""
        work_hex = get_tag_uuid_hex("Work")
        tag = populated_db.get_tag(work_hex)
        assert tag is not None
        assert tag["name"] == "Work"
        assert tag["parent_id"] is None

    def test_returns_none_for_nonexistent(self, populated_db: Database) -> None:
        """Test None returned for non-existent tag."""
        fake_id = "00000000000070008000999999999999"
        tag = populated_db.get_tag(fake_id)
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
        # Personal has descendants Family, Health
        # Notes 3, 4, 5, 6 all have Personal or descendants
        personal_descendants = [
            TAG_UUIDS["Personal"], TAG_UUIDS["Family"], TAG_UUIDS["Health"]
        ]
        notes = populated_db.search_notes(tag_id_groups=[personal_descendants])
        assert len(notes) == 4
        note_ids = {n["id"] for n in notes}
        expected_ids = {get_note_uuid_hex(3), get_note_uuid_hex(4),
                       get_note_uuid_hex(5), get_note_uuid_hex(6)}
        assert note_ids == expected_ids

    def test_multiple_tag_groups_and_logic(self, populated_db: Database) -> None:
        """Test AND logic with multiple tag groups."""
        # Group 1: Personal and descendants
        # Group 2: Family only
        # Only notes with (Personal OR Family OR Health) AND (Family) should match
        group1 = [TAG_UUIDS["Personal"], TAG_UUIDS["Family"], TAG_UUIDS["Health"]]
        group2 = [TAG_UUIDS["Family"]]
        notes = populated_db.search_notes(tag_id_groups=[group1, group2])
        assert len(notes) == 1
        assert notes[0]["id"] == get_note_uuid_hex(4)  # Family reunion note

    def test_hierarchical_parent_includes_children(self, populated_db: Database) -> None:
        """Test that searching parent tag includes child tags."""
        # Europe includes France, Paris, Germany
        # Note 4 has Paris
        europe_descendants = [
            TAG_UUIDS["Europe"], TAG_UUIDS["France"],
            TAG_UUIDS["Paris_France"], TAG_UUIDS["Germany"]
        ]
        notes = populated_db.search_notes(tag_id_groups=[europe_descendants])
        assert len(notes) == 1
        assert "Paris" in notes[0]["content"]

    def test_combined_text_and_tags(self, populated_db: Database) -> None:
        """Test combined text and tag search."""
        # Search for "reunion" in Personal notes
        personal_descendants = [
            TAG_UUIDS["Personal"], TAG_UUIDS["Family"], TAG_UUIDS["Health"]
        ]
        notes = populated_db.search_notes(
            text_query="reunion",
            tag_id_groups=[personal_descendants]
        )
        assert len(notes) == 1
        assert notes[0]["id"] == get_note_uuid_hex(4)

    def test_no_results(self, populated_db: Database) -> None:
        """Test search with no matching results."""
        notes = populated_db.search_notes(text_query="nonexistent")
        assert len(notes) == 0

    def test_empty_search_returns_all(self, populated_db: Database) -> None:
        """Test that empty search criteria returns all notes."""
        all_notes = populated_db.get_all_notes()
        search_notes = populated_db.search_notes()
        assert len(search_notes) == len(all_notes)


class TestFilterNotes:
    """Test filter_notes method (legacy, uses OR logic)."""

    def test_filters_by_tag_ids(self, populated_db: Database) -> None:
        """Test filtering by tag IDs."""
        # Filter by Work tag
        notes = populated_db.filter_notes([TAG_UUIDS["Work"]])
        assert len(notes) >= 2  # At least notes 1 and 2 have Work
        assert all("Work" in note["tag_names"] for note in notes)

    def test_returns_all_for_empty_list(self, populated_db: Database) -> None:
        """Test that empty tag list returns all notes."""
        notes = populated_db.filter_notes([])
        assert len(notes) == 9  # All notes


class TestAmbiguousTagHandling:
    """Test handling of ambiguous tag names (same name, different hierarchy)."""

    def test_get_tags_by_name_finds_multiple_paris(self, populated_db: Database) -> None:
        """Test that get_tags_by_name finds both Paris tags."""
        tags = populated_db.get_tags_by_name("Paris")
        assert len(tags) == 2

        # Should find both Paris tags
        tag_ids_bytes = {uuid_to_hex(TAG_UUIDS["Paris_France"]),
                        uuid_to_hex(TAG_UUIDS["Paris_Texas"])}
        actual_ids = {tag["id"] for tag in tags}
        assert actual_ids == tag_ids_bytes

    def test_get_tags_by_name_finds_multiple_bar(self, populated_db: Database) -> None:
        """Test that get_tags_by_name finds both bar tags."""
        tags = populated_db.get_tags_by_name("bar")
        assert len(tags) == 2

        tag_ids_bytes = {uuid_to_hex(TAG_UUIDS["bar_Foo"]),
                        uuid_to_hex(TAG_UUIDS["bar_Boom"])}
        actual_ids = {tag["id"] for tag in tags}
        assert actual_ids == tag_ids_bytes

    def test_get_all_tags_by_path_with_ambiguous_paris(self, populated_db: Database) -> None:
        """Test get_all_tags_by_path returns both Paris tags when searching for 'Paris'."""
        tags = populated_db.get_all_tags_by_path("Paris")
        assert len(tags) == 2

        tag_ids_bytes = {uuid_to_hex(TAG_UUIDS["Paris_France"]),
                        uuid_to_hex(TAG_UUIDS["Paris_Texas"])}
        actual_ids = {tag["id"] for tag in tags}
        assert actual_ids == tag_ids_bytes

    def test_get_all_tags_by_path_with_full_path_france_paris(self, populated_db: Database) -> None:
        """Test get_all_tags_by_path with full path returns only France/Paris."""
        tags = populated_db.get_all_tags_by_path("Geography/Europe/France/Paris")
        assert len(tags) == 1
        assert tags[0]["id"] == get_tag_uuid_hex("Paris_France")
        assert tags[0]["name"] == "Paris"

    def test_get_all_tags_by_path_with_full_path_texas_paris(self, populated_db: Database) -> None:
        """Test get_all_tags_by_path with full path returns only Texas/Paris."""
        tags = populated_db.get_all_tags_by_path("Geography/US/Texas/Paris")
        assert len(tags) == 1
        assert tags[0]["id"] == get_tag_uuid_hex("Paris_Texas")
        assert tags[0]["name"] == "Paris"

    def test_search_with_ambiguous_paris_uses_or_logic(self, populated_db: Database) -> None:
        """Test that searching for ambiguous 'Paris' finds notes from both hierarchies."""
        # Get descendants for both Paris tags
        france_paris_descendants = populated_db.get_tag_descendants(
            get_tag_uuid_hex("Paris_France")
        )
        texas_paris_descendants = populated_db.get_tag_descendants(
            get_tag_uuid_hex("Paris_Texas")
        )

        # Search with just "Paris" - should use OR logic
        notes = populated_db.search_notes(
            tag_id_groups=[france_paris_descendants + texas_paris_descendants]
        )

        # Should find note 4 (France/Paris) and note 9 (Texas/Paris)
        assert len(notes) == 2
        note_ids = {n["id"] for n in notes}
        assert get_note_uuid_hex(4) in note_ids  # Family reunion in Paris (France)
        assert get_note_uuid_hex(9) in note_ids  # Cowboys in Paris, Texas

    def test_search_with_specific_france_paris_path(self, populated_db: Database) -> None:
        """Test searching with full France/Paris path finds only French Paris note."""
        # Get the specific France/Paris tag
        tags = populated_db.get_all_tags_by_path("Geography/Europe/France/Paris")
        assert len(tags) == 1
        france_paris_id = tags[0]["id"]

        # Search with this specific tag
        descendants = populated_db.get_tag_descendants(france_paris_id)
        notes = populated_db.search_notes(tag_id_groups=[descendants])

        # Should find only note 4
        assert len(notes) == 1
        assert notes[0]["id"] == get_note_uuid_hex(4)
        assert "Family reunion" in notes[0]["content"]

    def test_search_with_specific_texas_paris_path(self, populated_db: Database) -> None:
        """Test searching with full Texas/Paris path finds only Texas Paris note."""
        tags = populated_db.get_all_tags_by_path("Geography/US/Texas/Paris")
        assert len(tags) == 1
        texas_paris_id = tags[0]["id"]

        descendants = populated_db.get_tag_descendants(texas_paris_id)
        notes = populated_db.search_notes(tag_id_groups=[descendants])

        # Should find only note 9
        assert len(notes) == 1
        assert notes[0]["id"] == get_note_uuid_hex(9)
        assert "Cowboys" in notes[0]["content"]


class TestCreateNote:
    """Test create_note method."""

    def test_creates_note_with_content(self, empty_db: Database) -> None:
        """Test creating a note with content."""
        note_id = empty_db.create_note("Test note content")
        assert len(note_id) == 32  # UUID hex string

        note = empty_db.get_note(note_id)
        assert note is not None
        assert note["content"] == "Test note content"

    def test_creates_note_with_empty_content(self, empty_db: Database) -> None:
        """Test creating a note with empty content."""
        note_id = empty_db.create_note("")
        assert len(note_id) == 32

        note = empty_db.get_note(note_id)
        assert note is not None
        assert note["content"] == ""


class TestUpdateNote:
    """Test update_note method."""

    def test_updates_note_content(self, populated_db: Database) -> None:
        """Test updating a note's content."""
        note_1_hex = get_note_uuid_hex(1)
        result = populated_db.update_note(note_1_hex, "Updated content")
        assert result is True

        note = populated_db.get_note(note_1_hex)
        assert note["content"] == "Updated content"
        assert note["modified_at"] is not None

    def test_returns_false_for_nonexistent_note(self, populated_db: Database) -> None:
        """Test that False is returned for non-existent note."""
        fake_id = "00000000000070008000999999999999"
        result = populated_db.update_note(fake_id, "New content")
        assert result is False


class TestDeleteNote:
    """Test delete_note method."""

    def test_soft_deletes_note(self, populated_db: Database) -> None:
        """Test soft-deleting a note."""
        note_1_hex = get_note_uuid_hex(1)
        result = populated_db.delete_note(note_1_hex)
        assert result is True

        # Note should still exist but be excluded from get_all_notes
        notes = populated_db.get_all_notes()
        assert not any(n["id"] == note_1_hex for n in notes)

    def test_returns_false_for_nonexistent_note(self, populated_db: Database) -> None:
        """Test that False is returned for non-existent note."""
        fake_id = "00000000000070008000999999999999"
        result = populated_db.delete_note(fake_id)
        assert result is False


class TestMergeNotes:
    """Test merge_notes method."""

    def test_merges_content_with_separator(self, empty_db: Database) -> None:
        """Test that content is merged with separator."""
        import time
        note1_id = empty_db.create_note("First note content")
        time.sleep(0.01)  # Ensure different timestamps
        note2_id = empty_db.create_note("Second note content")

        survivor_id = empty_db.merge_notes(note1_id, note2_id)

        # First note (earlier) should survive
        assert survivor_id == note1_id

        note = empty_db.get_note(survivor_id)
        assert note is not None
        assert "First note content" in note["content"]
        assert "----------------" in note["content"]
        assert "Second note content" in note["content"]

    def test_preserves_earlier_note(self, empty_db: Database) -> None:
        """Test that note with earlier created_at survives."""
        import time
        note1_id = empty_db.create_note("First")
        time.sleep(1.1)  # Sleep > 1s to ensure different second-precision timestamps
        note2_id = empty_db.create_note("Second")

        # Merge with second note first in args - should still keep first
        survivor_id = empty_db.merge_notes(note2_id, note1_id)
        assert survivor_id == note1_id

    def test_soft_deletes_later_note(self, empty_db: Database) -> None:
        """Test that later note is soft-deleted."""
        import time
        note1_id = empty_db.create_note("First")
        time.sleep(0.01)
        note2_id = empty_db.create_note("Second")

        empty_db.merge_notes(note1_id, note2_id)

        # Second note should be deleted
        note = empty_db.get_note(note2_id)
        assert note is None

        # All notes should only include first
        notes = empty_db.get_all_notes()
        assert len(notes) == 1
        assert notes[0]["id"] == note1_id

    def test_no_separator_when_survivor_empty(self, empty_db: Database) -> None:
        """Test no separator when survivor content is empty."""
        import time
        note1_id = empty_db.create_note("")
        time.sleep(0.01)
        note2_id = empty_db.create_note("Content from second")

        survivor_id = empty_db.merge_notes(note1_id, note2_id)
        note = empty_db.get_note(survivor_id)

        assert note["content"] == "Content from second"
        assert "----------------" not in note["content"]

    def test_no_separator_when_victim_empty(self, empty_db: Database) -> None:
        """Test no separator when victim content is empty."""
        import time
        note1_id = empty_db.create_note("Content from first")
        time.sleep(0.01)
        note2_id = empty_db.create_note("")

        survivor_id = empty_db.merge_notes(note1_id, note2_id)
        note = empty_db.get_note(survivor_id)

        assert note["content"] == "Content from first"
        assert "----------------" not in note["content"]

    def test_both_contents_empty(self, empty_db: Database) -> None:
        """Test merging two notes with empty content."""
        import time
        note1_id = empty_db.create_note("")
        time.sleep(0.01)
        note2_id = empty_db.create_note("")

        survivor_id = empty_db.merge_notes(note1_id, note2_id)
        note = empty_db.get_note(survivor_id)

        assert note["content"] == ""

    def test_moves_tags_from_victim(self, empty_db: Database) -> None:
        """Test that tags are moved from victim to survivor."""
        import time
        note1_id = empty_db.create_note("First")
        time.sleep(0.01)
        note2_id = empty_db.create_note("Second")

        tag_id = empty_db.create_tag("TestTag")
        empty_db.add_tag_to_note(note2_id, tag_id)

        empty_db.merge_notes(note1_id, note2_id)

        # Survivor should have the tag
        note = empty_db.get_note(note1_id)
        assert "TestTag" in note["tag_names"]

    def test_deduplicates_tags(self, empty_db: Database) -> None:
        """Test that duplicate tags are not created."""
        import time
        note1_id = empty_db.create_note("First")
        time.sleep(0.01)
        note2_id = empty_db.create_note("Second")

        tag_id = empty_db.create_tag("SharedTag")
        empty_db.add_tag_to_note(note1_id, tag_id)
        empty_db.add_tag_to_note(note2_id, tag_id)

        empty_db.merge_notes(note1_id, note2_id)

        # Survivor should have tag only once
        note = empty_db.get_note(note1_id)
        assert note["tag_names"].count("SharedTag") == 1

    def test_moves_multiple_tags(self, empty_db: Database) -> None:
        """Test moving multiple tags from victim."""
        import time
        note1_id = empty_db.create_note("First")
        time.sleep(0.01)
        note2_id = empty_db.create_note("Second")

        tag1_id = empty_db.create_tag("Tag1")
        tag2_id = empty_db.create_tag("Tag2")
        tag3_id = empty_db.create_tag("Tag3")

        empty_db.add_tag_to_note(note1_id, tag1_id)
        empty_db.add_tag_to_note(note2_id, tag2_id)
        empty_db.add_tag_to_note(note2_id, tag3_id)

        empty_db.merge_notes(note1_id, note2_id)

        note = empty_db.get_note(note1_id)
        assert "Tag1" in note["tag_names"]
        assert "Tag2" in note["tag_names"]
        assert "Tag3" in note["tag_names"]

    def test_moves_attachments(self, empty_db: Database) -> None:
        """Test that attachments are moved from victim to survivor."""
        import time
        note1_id = empty_db.create_note("First")
        time.sleep(0.01)
        note2_id = empty_db.create_note("Second")

        # Create an audio file and attach to note2
        audio_id = empty_db.create_audio_file("test.wav")
        empty_db.attach_to_note(note2_id, audio_id, "audio_file")

        empty_db.merge_notes(note1_id, note2_id)

        # Survivor should have the attachment
        attachments = empty_db.get_attachments_for_note(note1_id)
        assert len(attachments) == 1
        assert attachments[0]["attachment_id"] == audio_id

    def test_error_same_note_id(self, empty_db: Database) -> None:
        """Test error when merging note with itself."""
        note_id = empty_db.create_note("Test")

        with pytest.raises(Exception) as exc_info:
            empty_db.merge_notes(note_id, note_id)
        assert "itself" in str(exc_info.value).lower()

    def test_error_nonexistent_note(self, empty_db: Database) -> None:
        """Test error when note doesn't exist."""
        note_id = empty_db.create_note("Test")
        fake_id = "00000000000070008000999999999999"

        with pytest.raises(Exception) as exc_info:
            empty_db.merge_notes(note_id, fake_id)
        assert "not found" in str(exc_info.value).lower()

    def test_error_deleted_note(self, empty_db: Database) -> None:
        """Test error when merging with deleted note."""
        import time
        note1_id = empty_db.create_note("First")
        time.sleep(0.01)
        note2_id = empty_db.create_note("Second")

        empty_db.delete_note(note2_id)

        with pytest.raises(Exception) as exc_info:
            empty_db.merge_notes(note1_id, note2_id)
        assert "deleted" in str(exc_info.value).lower()

    def test_updates_modified_at(self, empty_db: Database) -> None:
        """Test that survivor's modified_at is updated."""
        import time
        note1_id = empty_db.create_note("First")

        # Get initial modified_at (should be None)
        note_before = empty_db.get_note(note1_id)
        initial_modified = note_before.get("modified_at")

        time.sleep(0.01)
        note2_id = empty_db.create_note("Second")

        time.sleep(0.01)
        empty_db.merge_notes(note1_id, note2_id)

        note_after = empty_db.get_note(note1_id)
        assert note_after["modified_at"] is not None
        if initial_modified:
            assert note_after["modified_at"] > initial_modified

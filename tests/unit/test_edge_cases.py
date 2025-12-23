"""Edge case tests for Voice.

Tests boundary conditions, special characters, and unusual inputs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest

from tests.helpers import get_tag_uuid, get_tag_uuid_hex, get_note_uuid

from core.database import Database
from core.search import parse_search_input, execute_search, get_tag_full_path
from core.validation import (
    ValidationError,
    validate_tag_name,
    validate_tag_path,
    validate_note_content,
    validate_search_query,
    validate_note_id,
    MAX_TAG_NAME_LENGTH,
    MAX_TAG_PATH_LENGTH,
    MAX_TAG_PATH_DEPTH,
    MAX_NOTE_CONTENT_LENGTH,
    MAX_SEARCH_QUERY_LENGTH,
)


# Test UUIDs
TEST_UUID_1 = uuid.UUID("00000000-0000-7000-8000-000000000001").bytes
TEST_UUID_2 = uuid.UUID("00000000-0000-7000-8000-000000000002").bytes
NONEXISTENT_UUID = uuid.UUID("00000000-0000-7000-8000-000000009999").bytes


@pytest.mark.unit
class TestLongContentEdgeCases:
    """Test handling of very long content."""

    def test_note_content_at_max_length(self) -> None:
        """Content at exactly max length is valid."""
        content = "x" * MAX_NOTE_CONTENT_LENGTH
        validate_note_content(content)  # Should not raise

    def test_note_content_one_over_max(self) -> None:
        """Content one character over max is invalid."""
        content = "x" * (MAX_NOTE_CONTENT_LENGTH + 1)
        with pytest.raises(ValidationError):
            validate_note_content(content)

    def test_tag_name_at_max_length(self) -> None:
        """Tag name at exactly max length is valid."""
        name = "x" * MAX_TAG_NAME_LENGTH
        validate_tag_name(name)  # Should not raise

    def test_tag_name_one_over_max(self) -> None:
        """Tag name one character over max is invalid."""
        name = "x" * (MAX_TAG_NAME_LENGTH + 1)
        with pytest.raises(ValidationError):
            validate_tag_name(name)

    def test_search_query_at_max_length(self) -> None:
        """Search query at exactly max length is valid."""
        query = "x" * MAX_SEARCH_QUERY_LENGTH
        validate_search_query(query)  # Should not raise

    def test_search_query_one_over_max(self) -> None:
        """Search query one character over max is invalid."""
        query = "x" * (MAX_SEARCH_QUERY_LENGTH + 1)
        with pytest.raises(ValidationError):
            validate_search_query(query)

    def test_tag_path_at_max_depth(self) -> None:
        """Tag path at exactly max depth is valid."""
        path = "/".join(["t"] * MAX_TAG_PATH_DEPTH)
        validate_tag_path(path)  # Should not raise

    def test_tag_path_one_over_max_depth(self) -> None:
        """Tag path one level over max depth is invalid."""
        path = "/".join(["t"] * (MAX_TAG_PATH_DEPTH + 1))
        with pytest.raises(ValidationError):
            validate_tag_path(path)


@pytest.mark.unit
class TestSpecialCharacterEdgeCases:
    """Test handling of special characters."""

    def test_tag_name_with_unicode(self) -> None:
        """Tag names with various Unicode are valid."""
        valid_names = [
            "שלום",  # Hebrew
            "日本語",  # Japanese
            "émoji",  # Accented
            "Ωmega",  # Greek
            "🏷️",  # Emoji (if supported)
        ]
        for name in valid_names:
            validate_tag_name(name)

    def test_tag_name_with_special_chars(self) -> None:
        """Tag names with allowed special characters."""
        valid_names = [
            "work-project",
            "work_project",
            "work.project",
            "work@home",
            "100%",
            "C++",
            "Q&A",
        ]
        for name in valid_names:
            validate_tag_name(name)

    def test_tag_name_with_slash_invalid(self) -> None:
        """Tag names with slash are invalid (reserved for paths)."""
        with pytest.raises(ValidationError):
            validate_tag_name("parent/child")

    def test_search_with_quotes(self) -> None:
        """Search parsing handles quoted strings."""
        result = parse_search_input('"hello world"')
        assert result.free_text == '"hello world"'

    def test_search_with_backslashes(self) -> None:
        """Search parsing handles backslashes."""
        result = parse_search_input("path\\to\\file")
        assert result.free_text == "path\\to\\file"

    def test_search_with_sql_injection_attempt(self) -> None:
        """Search safely handles SQL-like input."""
        result = parse_search_input("'; DROP TABLE notes; --")
        assert result.free_text == "'; DROP TABLE notes; --"
        assert result.tag_terms == []


@pytest.mark.unit
class TestWhitespaceEdgeCases:
    """Test handling of whitespace."""

    def test_tag_name_only_spaces_invalid(self) -> None:
        """Tag name with only spaces is invalid."""
        with pytest.raises(ValidationError):
            validate_tag_name("   ")

    def test_tag_name_with_leading_trailing_spaces(self) -> None:
        """Tag name with leading/trailing spaces is trimmed."""
        validate_tag_name("  valid  ")  # Should not raise

    def test_content_only_whitespace_invalid(self) -> None:
        """Content with only whitespace is invalid."""
        with pytest.raises(ValidationError):
            validate_note_content("   \n\t   ")

    def test_search_only_spaces(self) -> None:
        """Search with only spaces returns empty."""
        result = parse_search_input("   ")
        assert result.tag_terms == []
        assert result.free_text == ""

    def test_search_with_multiple_spaces_between_words(self) -> None:
        """Search collapses multiple spaces."""
        result = parse_search_input("hello    world")
        # Words are split and rejoined
        assert "hello" in result.free_text
        assert "world" in result.free_text

    def test_tag_path_with_empty_segments(self) -> None:
        """Tag path with empty segments (double slashes)."""
        # Should still work - empty segments are skipped
        validate_tag_path("parent//child")


@pytest.mark.unit
class TestBoundaryConditions:
    """Test boundary conditions."""

    def test_note_id_wrong_type_invalid(self) -> None:
        """Note ID of wrong type is invalid."""
        with pytest.raises(ValidationError):
            validate_note_id(0)  # Integer, not bytes

    def test_note_id_wrong_length_invalid(self) -> None:
        """Note ID of wrong length is invalid."""
        with pytest.raises(ValidationError):
            validate_note_id(b"short")

    def test_note_id_valid_bytes(self) -> None:
        """Valid UUID bytes are accepted."""
        result = validate_note_id(TEST_UUID_1)
        assert result == TEST_UUID_1

    def test_note_id_valid_hex_string(self) -> None:
        """Valid hex string is accepted and converted."""
        result = validate_note_id("00000000000070008000000000000001")
        assert result == TEST_UUID_1

    def test_empty_tag_prefix(self) -> None:
        """Empty tag: prefix is ignored."""
        result = parse_search_input("tag:")
        assert result.tag_terms == []

    def test_tag_with_colon_in_name(self) -> None:
        """Tag search with colon in tag name."""
        result = parse_search_input("tag:time:12:00")
        # Everything after first "tag:" is the tag name
        assert result.tag_terms == ["time:12:00"]


@pytest.mark.unit
class TestDatabaseEdgeCases:
    """Test database edge cases."""

    def test_search_empty_database(self, empty_db: Database) -> None:
        """Search on empty database returns empty list."""
        result = execute_search(empty_db, "anything")
        assert result.notes == []

    def test_get_nonexistent_note(self, empty_db: Database) -> None:
        """Getting nonexistent note returns None."""
        note = empty_db.get_note(NONEXISTENT_UUID)
        assert note is None

    def test_get_nonexistent_tag(self, empty_db: Database) -> None:
        """Getting nonexistent tag returns None."""
        tag = empty_db.get_tag(NONEXISTENT_UUID)
        assert tag is None

    def test_tag_descendants_of_leaf(self, populated_db: Database) -> None:
        """Getting descendants of leaf tag returns just that tag."""
        # Voice is a leaf tag
        voice_uuid = get_tag_uuid("Voice")
        descendants = populated_db.get_tag_descendants(voice_uuid)
        assert descendants == [voice_uuid]

    def test_filter_notes_empty_list(self, populated_db: Database) -> None:
        """Filtering with empty tag list returns all notes."""
        notes = populated_db.filter_notes([])
        all_notes = populated_db.get_all_notes()
        assert len(notes) == len(all_notes)


@pytest.mark.unit
class TestSearchEdgeCases:
    """Test search functionality edge cases."""

    def test_search_case_insensitive_text(self, populated_db: Database) -> None:
        """Text search is case-insensitive."""
        result1 = execute_search(populated_db, "doctor")
        result2 = execute_search(populated_db, "DOCTOR")
        result3 = execute_search(populated_db, "Doctor")

        assert len(result1.notes) == len(result2.notes) == len(result3.notes)

    def test_search_case_insensitive_tag(self, populated_db: Database) -> None:
        """Tag search is case-insensitive."""
        result1 = execute_search(populated_db, "tag:work")
        result2 = execute_search(populated_db, "tag:WORK")
        result3 = execute_search(populated_db, "tag:Work")

        assert len(result1.notes) == len(result2.notes) == len(result3.notes)

    def test_search_partial_word_match(self, populated_db: Database) -> None:
        """Partial word matches in content."""
        # "Doctor" should match "Doctor appointment"
        result = execute_search(populated_db, "Doc")
        assert len(result.notes) >= 1

    def test_search_multiple_text_words(self, populated_db: Database) -> None:
        """Multiple words must all match."""
        result = execute_search(populated_db, "Family reunion")
        assert len(result.notes) == 1
        assert "Family reunion" in result.notes[0]["content"]

    def test_search_tag_not_in_text(self, populated_db: Database) -> None:
        """tag: prefix is not treated as text search."""
        result = execute_search(populated_db, "tag:Work")
        # Should find Work-tagged notes, not notes containing "tag:Work"
        assert len(result.notes) >= 1

    def test_ambiguous_tag_all_matches_returned(self, populated_db: Database) -> None:
        """Ambiguous tag returns notes from all matching tags."""
        result = execute_search(populated_db, "tag:bar")
        # bar exists under both Foo and Boom
        assert len(result.notes) == 2
        assert "tag:bar" in result.ambiguous_tags


@pytest.mark.unit
class TestTagHierarchyEdgeCases:
    """Test tag hierarchy edge cases."""

    def test_root_tag_has_no_parent(self, populated_db: Database) -> None:
        """Root tags have parent_id None."""
        tag = populated_db.get_tag(get_tag_uuid("Work"))
        assert tag["parent_id"] is None

    def test_child_tag_has_parent(self, populated_db: Database) -> None:
        """Child tags have valid parent_id."""
        tag = populated_db.get_tag(get_tag_uuid("Projects"))  # Projects under Work
        assert tag["parent_id"] == get_tag_uuid_hex("Work")

    def test_tag_path_traversal(self, populated_db: Database) -> None:
        """Full path correctly traverses hierarchy."""
        path = get_tag_full_path(populated_db, get_tag_uuid("Paris_France"))
        assert path == "Geography/Europe/France/Paris"

    def test_search_parent_includes_deep_children(self, populated_db: Database) -> None:
        """Searching parent finds notes tagged with deep descendants."""
        result = execute_search(populated_db, "tag:Geography")
        # Should find notes with France/Paris, Israel, Texas/Paris
        assert len(result.notes) >= 3


@pytest.mark.unit
class TestUnicodeEdgeCases:
    """Test Unicode handling edge cases."""

    def test_hebrew_in_search(self, populated_db: Database) -> None:
        """Hebrew text search works correctly."""
        result = execute_search(populated_db, "שלום")
        assert len(result.notes) == 1
        assert "שלום" in result.notes[0]["content"]

    def test_mixed_hebrew_english_search(self, populated_db: Database) -> None:
        """Mixed Hebrew/English content can be found."""
        # Search for phrase that appears in the note
        result = execute_search(populated_db, "Hebrew text")
        assert len(result.notes) == 1
        assert "שלום" in result.notes[0]["content"]

    def test_unicode_normalization(self) -> None:
        """Unicode normalization in tag names."""
        # These should both be valid
        validate_tag_name("café")  # Composed form
        validate_tag_name("café")  # Decomposed form (if different)

    def test_rtl_text_in_tag_name(self) -> None:
        """Right-to-left text in tag names."""
        validate_tag_name("עברית")
        validate_tag_name("العربية")

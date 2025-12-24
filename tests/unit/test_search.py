"""Unit tests for search functionality.

Tests the search parsing and execution logic in core/search.py.
"""

from __future__ import annotations

import pytest

from tests.helpers import get_tag_uuid, get_tag_uuid_hex

from core.search import (
    ParsedSearch,
    SearchResult,
    parse_search_input,
    get_tag_full_path,
    resolve_tag_term,
    find_ambiguous_tags,
    execute_search,
    build_tag_search_term,
)
from core.database import Database


@pytest.mark.unit
class TestParseSearchInput:
    """Tests for parse_search_input."""

    def test_empty_input(self) -> None:
        """Empty input returns empty result."""
        result = parse_search_input("")
        assert result.tag_terms == []
        assert result.free_text == ""

    def test_whitespace_only(self) -> None:
        """Whitespace-only input returns empty result."""
        result = parse_search_input("   ")
        assert result.tag_terms == []
        assert result.free_text == ""

    def test_free_text_only(self) -> None:
        """Input without tags returns free text."""
        result = parse_search_input("hello world")
        assert result.tag_terms == []
        assert result.free_text == "hello world"

    def test_single_tag(self) -> None:
        """Single tag term is extracted."""
        result = parse_search_input("tag:Work")
        assert result.tag_terms == ["Work"]
        assert result.free_text == ""

    def test_multiple_tags(self) -> None:
        """Multiple tag terms are extracted."""
        result = parse_search_input("tag:Work tag:Personal")
        assert result.tag_terms == ["Work", "Personal"]
        assert result.free_text == ""

    def test_tag_with_path(self) -> None:
        """Hierarchical tag paths are extracted."""
        result = parse_search_input("tag:Europe/France/Paris")
        assert result.tag_terms == ["Europe/France/Paris"]
        assert result.free_text == ""

    def test_mixed_tags_and_text(self) -> None:
        """Tags and free text are properly separated."""
        result = parse_search_input("hello tag:Work world tag:Personal")
        assert result.tag_terms == ["Work", "Personal"]
        assert result.free_text == "hello world"

    def test_case_insensitive_tag_prefix(self) -> None:
        """Tag prefix is case-insensitive."""
        result = parse_search_input("TAG:Work Tag:Personal")
        assert result.tag_terms == ["Work", "Personal"]

    def test_empty_tag_ignored(self) -> None:
        """Empty tag: prefix is ignored."""
        result = parse_search_input("tag: hello")
        assert result.tag_terms == []
        assert result.free_text == "hello"


@pytest.mark.unit
class TestGetTagFullPath:
    """Tests for get_tag_full_path."""

    def test_root_tag(self, populated_db: Database) -> None:
        """Root tag returns just its name."""
        path = get_tag_full_path(populated_db, get_tag_uuid("Work"))
        assert path == "Work"

    def test_nested_tag(self, populated_db: Database) -> None:
        """Nested tag returns full path."""
        path = get_tag_full_path(populated_db, get_tag_uuid("Paris_France"))
        assert path == "Geography/Europe/France/Paris"

    def test_nonexistent_tag(self, populated_db: Database) -> None:
        """Nonexistent tag returns empty string."""
        import uuid
        nonexistent = uuid.UUID("00000000-0000-7000-8000-000000009999").bytes
        path = get_tag_full_path(populated_db, nonexistent)
        assert path == ""


@pytest.mark.unit
class TestResolveTagTerm:
    """Tests for resolve_tag_term."""

    def test_simple_tag_name(self, populated_db: Database) -> None:
        """Simple tag name is resolved."""
        tag_ids, is_ambiguous, not_found = resolve_tag_term(populated_db, "Work")
        assert not not_found
        assert not is_ambiguous
        assert get_tag_uuid_hex("Work") in tag_ids

    def test_hierarchical_path(self, populated_db: Database) -> None:
        """Hierarchical path is resolved."""
        tag_ids, is_ambiguous, not_found = resolve_tag_term(
            populated_db, "Geography/Europe/France"
        )
        assert not not_found
        assert not is_ambiguous
        assert get_tag_uuid_hex("France") in tag_ids
        assert get_tag_uuid_hex("Paris_France") in tag_ids  # Paris (descendant)

    def test_ambiguous_tag(self, populated_db: Database) -> None:
        """Ambiguous tag name returns all matches."""
        tag_ids, is_ambiguous, not_found = resolve_tag_term(populated_db, "Paris")
        assert not not_found
        assert is_ambiguous  # Paris exists under both France and Texas
        assert get_tag_uuid_hex("Paris_France") in tag_ids
        assert get_tag_uuid_hex("Paris_Texas") in tag_ids

    def test_not_found_tag(self, populated_db: Database) -> None:
        """Nonexistent tag returns not found."""
        tag_ids, is_ambiguous, not_found = resolve_tag_term(
            populated_db, "NonexistentTag"
        )
        assert not_found
        assert tag_ids == []


@pytest.mark.unit
class TestFindAmbiguousTags:
    """Tests for find_ambiguous_tags."""

    def test_no_ambiguous_tags(self, populated_db: Database) -> None:
        """No ambiguous tags returns empty list."""
        result = find_ambiguous_tags(populated_db, ["Work", "Personal"])
        assert result == []

    def test_with_ambiguous_tag(self, populated_db: Database) -> None:
        """Ambiguous tags are returned with prefix."""
        result = find_ambiguous_tags(populated_db, ["Work", "Paris"])
        assert result == ["tag:Paris"]

    def test_multiple_ambiguous_tags(self, populated_db: Database) -> None:
        """Multiple ambiguous tags are all returned."""
        result = find_ambiguous_tags(populated_db, ["Paris", "bar"])
        assert "tag:Paris" in result
        assert "tag:bar" in result


@pytest.mark.unit
class TestExecuteSearch:
    """Tests for execute_search."""

    def test_empty_search(self, populated_db: Database) -> None:
        """Empty search returns all notes."""
        result = execute_search(populated_db, "")
        assert len(result.notes) > 0
        assert result.ambiguous_tags == []
        assert result.not_found_tags == []

    def test_text_search(self, populated_db: Database) -> None:
        """Text search finds matching notes."""
        result = execute_search(populated_db, "Doctor")
        assert len(result.notes) == 1
        assert "Doctor" in result.notes[0]["content"]

    def test_tag_search(self, populated_db: Database) -> None:
        """Tag search finds notes with that tag."""
        result = execute_search(populated_db, "tag:Work")
        assert len(result.notes) >= 1
        assert result.ambiguous_tags == []

    def test_combined_search(self, populated_db: Database) -> None:
        """Combined tag and text search."""
        result = execute_search(populated_db, "tag:Personal Doctor")
        assert len(result.notes) == 1
        assert "Doctor" in result.notes[0]["content"]

    def test_not_found_tag(self, populated_db: Database) -> None:
        """Not found tag returns empty notes."""
        result = execute_search(populated_db, "tag:NonexistentTag")
        assert result.notes == []
        assert "NonexistentTag" in result.not_found_tags

    def test_ambiguous_tag_reported(self, populated_db: Database) -> None:
        """Ambiguous tags are reported in result."""
        result = execute_search(populated_db, "tag:Paris")
        assert "tag:Paris" in result.ambiguous_tags


@pytest.mark.unit
class TestBuildTagSearchTerm:
    """Tests for build_tag_search_term."""

    def test_non_ambiguous_tag(self, populated_db: Database) -> None:
        """Non-ambiguous tag uses simple name."""
        term = build_tag_search_term(populated_db, get_tag_uuid("Work"))
        assert term == "tag:Work"

    def test_ambiguous_tag(self, populated_db: Database) -> None:
        """Ambiguous tag uses full path."""
        term = build_tag_search_term(populated_db, get_tag_uuid("Paris_France"))
        assert term == "tag:Geography/Europe/France/Paris"

    def test_force_full_path(self, populated_db: Database) -> None:
        """Full path can be forced."""
        term = build_tag_search_term(populated_db, get_tag_uuid("Work"), use_full_path=True)
        assert term == "tag:Work"  # Work is a root tag, so path is just "Work"

    def test_nonexistent_tag(self, populated_db: Database) -> None:
        """Nonexistent tag returns empty string."""
        import uuid
        nonexistent = uuid.UUID("00000000-0000-7000-8000-000000009999").bytes
        term = build_tag_search_term(populated_db, nonexistent)
        assert term == ""

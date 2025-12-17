"""Unit tests for input validation.

Tests all validation functions in core/validation.py.
"""

from __future__ import annotations

import pytest

from core.validation import (
    ValidationError,
    validate_note_id,
    validate_tag_id,
    validate_tag_ids,
    validate_tag_name,
    validate_tag_path,
    validate_note_content,
    validate_search_query,
    validate_parent_tag_id,
    validate_tag_id_groups,
    MAX_TAG_NAME_LENGTH,
    MAX_NOTE_CONTENT_LENGTH,
    MAX_SEARCH_QUERY_LENGTH,
    MAX_TAG_PATH_LENGTH,
    MAX_TAG_PATH_DEPTH,
)


@pytest.mark.unit
class TestValidateNoteId:
    """Tests for validate_note_id."""

    def test_valid_note_id(self) -> None:
        """Valid positive integer should pass."""
        validate_note_id(1)
        validate_note_id(100)
        validate_note_id(999999)

    def test_zero_note_id_raises(self) -> None:
        """Zero should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_note_id(0)
        assert exc.value.field == "note_id"
        assert "positive" in exc.value.message

    def test_negative_note_id_raises(self) -> None:
        """Negative number should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_note_id(-1)
        assert exc.value.field == "note_id"

    def test_non_integer_raises(self) -> None:
        """Non-integer types should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_note_id("1")  # type: ignore
        assert exc.value.field == "note_id"
        assert "integer" in exc.value.message

        with pytest.raises(ValidationError):
            validate_note_id(1.5)  # type: ignore


@pytest.mark.unit
class TestValidateTagId:
    """Tests for validate_tag_id."""

    def test_valid_tag_id(self) -> None:
        """Valid positive integer should pass."""
        validate_tag_id(1)
        validate_tag_id(50)

    def test_zero_tag_id_raises(self) -> None:
        """Zero should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_tag_id(0)
        assert exc.value.field == "tag_id"

    def test_negative_tag_id_raises(self) -> None:
        """Negative number should raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_tag_id(-5)

    def test_non_integer_raises(self) -> None:
        """Non-integer types should raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_tag_id(None)  # type: ignore


@pytest.mark.unit
class TestValidateTagIds:
    """Tests for validate_tag_ids."""

    def test_valid_tag_ids(self) -> None:
        """Valid list of positive integers should pass."""
        validate_tag_ids([1, 2, 3])
        validate_tag_ids([1])
        validate_tag_ids([])

    def test_non_list_raises(self) -> None:
        """Non-list types should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_tag_ids((1, 2, 3))  # type: ignore
        assert exc.value.field == "tag_ids"
        assert "list" in exc.value.message

    def test_invalid_item_raises(self) -> None:
        """Invalid items in list should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_tag_ids([1, 0, 3])
        assert exc.value.field == "tag_ids"
        assert "item 1" in exc.value.message

    def test_non_integer_item_raises(self) -> None:
        """Non-integer items should raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_tag_ids([1, "2", 3])  # type: ignore


@pytest.mark.unit
class TestValidateTagName:
    """Tests for validate_tag_name."""

    def test_valid_tag_names(self) -> None:
        """Valid tag names should pass."""
        validate_tag_name("Work")
        validate_tag_name("Personal")
        validate_tag_name("Project-X")
        validate_tag_name("  Trimmed  ")  # Whitespace is stripped
        validate_tag_name("שלום")  # Hebrew
        validate_tag_name("日本語")  # Japanese

    def test_empty_name_raises(self) -> None:
        """Empty string should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_tag_name("")
        assert exc.value.field == "tag_name"
        assert "empty" in exc.value.message

    def test_whitespace_only_raises(self) -> None:
        """Whitespace-only string should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_tag_name("   ")
        assert "empty" in exc.value.message or "whitespace" in exc.value.message

    def test_too_long_raises(self) -> None:
        """Names exceeding max length should raise ValidationError."""
        long_name = "a" * (MAX_TAG_NAME_LENGTH + 1)
        with pytest.raises(ValidationError) as exc:
            validate_tag_name(long_name)
        assert "exceed" in exc.value.message or str(MAX_TAG_NAME_LENGTH) in exc.value.message

    def test_slash_in_name_raises(self) -> None:
        """Names containing '/' should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_tag_name("Parent/Child")
        assert "/" in exc.value.message or "path" in exc.value.message.lower()

    def test_non_string_raises(self) -> None:
        """Non-string types should raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_tag_name(123)  # type: ignore


@pytest.mark.unit
class TestValidateTagPath:
    """Tests for validate_tag_path."""

    def test_valid_paths(self) -> None:
        """Valid tag paths should pass."""
        validate_tag_path("Work")
        validate_tag_path("Europe/France/Paris")
        validate_tag_path("A/B/C/D")

    def test_empty_path_raises(self) -> None:
        """Empty path should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_tag_path("")
        assert exc.value.field == "tag_path"

    def test_whitespace_only_raises(self) -> None:
        """Whitespace-only path should raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_tag_path("   ")

    def test_too_long_path_raises(self) -> None:
        """Path exceeding max length should raise ValidationError."""
        long_path = "/".join(["tag"] * 100)
        with pytest.raises(ValidationError) as exc:
            validate_tag_path(long_path)
        assert "exceed" in exc.value.message

    def test_too_deep_path_raises(self) -> None:
        """Path exceeding max depth should raise ValidationError."""
        deep_path = "/".join(["t"] * (MAX_TAG_PATH_DEPTH + 1))
        with pytest.raises(ValidationError) as exc:
            validate_tag_path(deep_path)
        assert "level" in exc.value.message or "depth" in exc.value.message.lower()

    def test_segment_too_long_raises(self) -> None:
        """Path segment exceeding max name length should raise ValidationError."""
        long_segment = "a" * (MAX_TAG_NAME_LENGTH + 1)
        with pytest.raises(ValidationError):
            validate_tag_path(f"Valid/{long_segment}/Also")


@pytest.mark.unit
class TestValidateNoteContent:
    """Tests for validate_note_content."""

    def test_valid_content(self) -> None:
        """Valid content should pass."""
        validate_note_content("Hello, world!")
        validate_note_content("A" * 1000)
        validate_note_content("שלום עולם")

    def test_empty_content_raises(self) -> None:
        """Empty content should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_note_content("")
        assert exc.value.field == "content"

    def test_whitespace_only_raises(self) -> None:
        """Whitespace-only content should raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_note_content("   \n\t   ")

    def test_too_long_content_raises(self) -> None:
        """Content exceeding max length should raise ValidationError."""
        long_content = "a" * (MAX_NOTE_CONTENT_LENGTH + 1)
        with pytest.raises(ValidationError) as exc:
            validate_note_content(long_content)
        assert "exceed" in exc.value.message

    def test_non_string_raises(self) -> None:
        """Non-string types should raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_note_content(12345)  # type: ignore


@pytest.mark.unit
class TestValidateSearchQuery:
    """Tests for validate_search_query."""

    def test_valid_queries(self) -> None:
        """Valid search queries should pass."""
        validate_search_query("hello")
        validate_search_query("meeting notes")
        validate_search_query("")  # Empty is valid (no filter)
        validate_search_query(None)  # None is valid (no filter)

    def test_too_long_query_raises(self) -> None:
        """Query exceeding max length should raise ValidationError."""
        long_query = "a" * (MAX_SEARCH_QUERY_LENGTH + 1)
        with pytest.raises(ValidationError) as exc:
            validate_search_query(long_query)
        assert exc.value.field == "search_query"

    def test_non_string_raises(self) -> None:
        """Non-string, non-None types should raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_search_query(123)  # type: ignore


@pytest.mark.unit
class TestValidateParentTagId:
    """Tests for validate_parent_tag_id."""

    def test_valid_parent_id(self) -> None:
        """Valid parent IDs should pass."""
        validate_parent_tag_id(None)  # Root tag
        validate_parent_tag_id(1)
        validate_parent_tag_id(100, tag_id=50)

    def test_self_reference_raises(self) -> None:
        """Tag cannot be its own parent."""
        with pytest.raises(ValidationError) as exc:
            validate_parent_tag_id(5, tag_id=5)
        assert exc.value.field == "parent_id"
        assert "own parent" in exc.value.message

    def test_invalid_parent_id_raises(self) -> None:
        """Invalid parent IDs should raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_parent_tag_id(0)

        with pytest.raises(ValidationError):
            validate_parent_tag_id(-1)


@pytest.mark.unit
class TestValidateTagIdGroups:
    """Tests for validate_tag_id_groups."""

    def test_valid_groups(self) -> None:
        """Valid tag ID groups should pass."""
        validate_tag_id_groups(None)
        validate_tag_id_groups([])
        validate_tag_id_groups([[1, 2, 3]])
        validate_tag_id_groups([[1], [2, 3], [4, 5, 6]])

    def test_non_list_raises(self) -> None:
        """Non-list types should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_tag_id_groups("invalid")  # type: ignore
        assert exc.value.field == "tag_id_groups"

    def test_non_list_group_raises(self) -> None:
        """Non-list groups should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_tag_id_groups([[1, 2], (3, 4)])  # type: ignore
        assert "group 1" in exc.value.message

    def test_invalid_id_in_group_raises(self) -> None:
        """Invalid IDs within groups should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_tag_id_groups([[1, 2], [3, 0]])
        assert "group 1" in exc.value.message


@pytest.mark.unit
class TestValidationErrorFormat:
    """Tests for ValidationError formatting."""

    def test_error_string_format(self) -> None:
        """Error string should contain field and message."""
        error = ValidationError("test_field", "test message")
        assert "test_field" in str(error)
        assert "test message" in str(error)

    def test_error_attributes(self) -> None:
        """Error should have correct attributes."""
        error = ValidationError("my_field", "something went wrong")
        assert error.field == "my_field"
        assert error.message == "something went wrong"

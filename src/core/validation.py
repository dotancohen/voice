"""Input validation for Voice Rewrite.

This module provides validation functions for all user inputs.
All validators raise ValidationError with descriptive messages.

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import re
from typing import List, Optional


class ValidationError(Exception):
    """Raised when input validation fails.

    Attributes:
        field: Name of the field that failed validation
        message: Human-readable error message
    """

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


# Limits
MAX_TAG_NAME_LENGTH = 100
MAX_NOTE_CONTENT_LENGTH = 100_000  # 100KB of text
MAX_SEARCH_QUERY_LENGTH = 500
MAX_TAG_PATH_LENGTH = 500
MAX_TAG_PATH_DEPTH = 50


def validate_note_id(note_id: int) -> None:
    """Validate a note ID.

    Args:
        note_id: The note ID to validate

    Raises:
        ValidationError: If note_id is invalid
    """
    if not isinstance(note_id, int):
        raise ValidationError("note_id", f"must be an integer, got {type(note_id).__name__}")
    if note_id < 1:
        raise ValidationError("note_id", "must be a positive integer")


def validate_tag_id(tag_id: int) -> None:
    """Validate a tag ID.

    Args:
        tag_id: The tag ID to validate

    Raises:
        ValidationError: If tag_id is invalid
    """
    if not isinstance(tag_id, int):
        raise ValidationError("tag_id", f"must be an integer, got {type(tag_id).__name__}")
    if tag_id < 1:
        raise ValidationError("tag_id", "must be a positive integer")


def validate_tag_ids(tag_ids: List[int]) -> None:
    """Validate a list of tag IDs.

    Args:
        tag_ids: List of tag IDs to validate

    Raises:
        ValidationError: If any tag_id is invalid
    """
    if not isinstance(tag_ids, list):
        raise ValidationError("tag_ids", f"must be a list, got {type(tag_ids).__name__}")
    for i, tag_id in enumerate(tag_ids):
        try:
            validate_tag_id(tag_id)
        except ValidationError as e:
            raise ValidationError("tag_ids", f"item {i}: {e.message}")


def validate_tag_name(name: str) -> None:
    """Validate a tag name.

    Tag names must be:
    - Non-empty after stripping whitespace
    - No longer than MAX_TAG_NAME_LENGTH characters
    - Not contain path separator (/)
    - Not be only whitespace

    Args:
        name: The tag name to validate

    Raises:
        ValidationError: If name is invalid
    """
    if not isinstance(name, str):
        raise ValidationError("tag_name", f"must be a string, got {type(name).__name__}")

    stripped = name.strip()

    if not stripped:
        raise ValidationError("tag_name", "cannot be empty or whitespace only")

    if len(stripped) > MAX_TAG_NAME_LENGTH:
        raise ValidationError(
            "tag_name", f"cannot exceed {MAX_TAG_NAME_LENGTH} characters (got {len(stripped)})"
        )

    if "/" in stripped:
        raise ValidationError("tag_name", "cannot contain '/' character (reserved for paths)")


def validate_tag_path(path: str) -> None:
    """Validate a tag path.

    Tag paths are slash-separated tag names like "Europe/France/Paris".

    Args:
        path: The tag path to validate

    Raises:
        ValidationError: If path is invalid
    """
    if not isinstance(path, str):
        raise ValidationError("tag_path", f"must be a string, got {type(path).__name__}")

    stripped = path.strip()

    if not stripped:
        raise ValidationError("tag_path", "cannot be empty or whitespace only")

    if len(stripped) > MAX_TAG_PATH_LENGTH:
        raise ValidationError(
            "tag_path", f"cannot exceed {MAX_TAG_PATH_LENGTH} characters (got {len(stripped)})"
        )

    parts = stripped.split("/")

    if len(parts) > MAX_TAG_PATH_DEPTH:
        raise ValidationError(
            "tag_path", f"cannot exceed {MAX_TAG_PATH_DEPTH} levels (got {len(parts)})"
        )

    # Validate each part as a tag name (but allow empty parts from leading/trailing slashes)
    non_empty_parts = [p.strip() for p in parts if p.strip()]

    if not non_empty_parts:
        raise ValidationError("tag_path", "must contain at least one valid tag name")

    for part in non_empty_parts:
        if len(part) > MAX_TAG_NAME_LENGTH:
            raise ValidationError(
                "tag_path",
                f"tag name '{part[:20]}...' exceeds {MAX_TAG_NAME_LENGTH} characters",
            )


def validate_note_content(content: str) -> None:
    """Validate note content.

    Note content must be:
    - A string
    - Non-empty after stripping whitespace
    - No longer than MAX_NOTE_CONTENT_LENGTH characters

    Args:
        content: The note content to validate

    Raises:
        ValidationError: If content is invalid
    """
    if not isinstance(content, str):
        raise ValidationError("content", f"must be a string, got {type(content).__name__}")

    if not content.strip():
        raise ValidationError("content", "cannot be empty or whitespace only")

    if len(content) > MAX_NOTE_CONTENT_LENGTH:
        raise ValidationError(
            "content",
            f"cannot exceed {MAX_NOTE_CONTENT_LENGTH} characters (got {len(content)})",
        )


def validate_search_query(query: Optional[str]) -> None:
    """Validate a search query.

    Search queries can be None/empty (meaning no text filter).
    If provided, must not exceed MAX_SEARCH_QUERY_LENGTH.

    Args:
        query: The search query to validate (can be None)

    Raises:
        ValidationError: If query is invalid
    """
    if query is None:
        return

    if not isinstance(query, str):
        raise ValidationError("search_query", f"must be a string, got {type(query).__name__}")

    if len(query) > MAX_SEARCH_QUERY_LENGTH:
        raise ValidationError(
            "search_query",
            f"cannot exceed {MAX_SEARCH_QUERY_LENGTH} characters (got {len(query)})",
        )


def validate_parent_tag_id(parent_id: Optional[int], tag_id: Optional[int] = None) -> None:
    """Validate a parent tag ID for tag creation/update.

    Args:
        parent_id: The parent tag ID (None for root tags)
        tag_id: The tag's own ID (for circular reference check during updates)

    Raises:
        ValidationError: If parent_id is invalid
    """
    if parent_id is None:
        return

    validate_tag_id(parent_id)

    if tag_id is not None and parent_id == tag_id:
        raise ValidationError("parent_id", "tag cannot be its own parent")


def validate_tag_id_groups(tag_id_groups: Optional[List[List[int]]]) -> None:
    """Validate tag ID groups for search.

    Args:
        tag_id_groups: List of lists of tag IDs (can be None)

    Raises:
        ValidationError: If any tag ID is invalid
    """
    if tag_id_groups is None:
        return

    if not isinstance(tag_id_groups, list):
        raise ValidationError(
            "tag_id_groups", f"must be a list, got {type(tag_id_groups).__name__}"
        )

    for i, group in enumerate(tag_id_groups):
        if not isinstance(group, list):
            raise ValidationError(
                "tag_id_groups", f"group {i} must be a list, got {type(group).__name__}"
            )
        for j, tag_id in enumerate(group):
            try:
                validate_tag_id(tag_id)
            except ValidationError as e:
                raise ValidationError("tag_id_groups", f"group {i}, item {j}: {e.message}")

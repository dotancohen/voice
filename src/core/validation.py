"""Input validation for Voice Rewrite.

This module provides validation functions for all user inputs.
All validators raise ValidationError with descriptive messages.

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import re
import uuid
from typing import List, Optional, Union


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
UUID_BYTES_LENGTH = 16


def validate_uuid(value: bytes, field_name: str = "id") -> None:
    """Validate a UUID value (must be 16 bytes).

    Args:
        value: The UUID bytes to validate
        field_name: Name of the field for error messages

    Raises:
        ValidationError: If value is not valid UUID bytes
    """
    if not isinstance(value, bytes):
        raise ValidationError(
            field_name, f"must be bytes, got {type(value).__name__}"
        )
    if len(value) != UUID_BYTES_LENGTH:
        raise ValidationError(
            field_name, f"must be {UUID_BYTES_LENGTH} bytes, got {len(value)}"
        )


def validate_uuid_hex(value: str, field_name: str = "id") -> bytes:
    """Validate and convert a UUID hex string to bytes.

    Args:
        value: The UUID hex string (32 chars, no hyphens)
        field_name: Name of the field for error messages

    Returns:
        UUID as bytes (16 bytes)

    Raises:
        ValidationError: If value is not a valid UUID hex string
    """
    if not isinstance(value, str):
        raise ValidationError(
            field_name, f"must be a string, got {type(value).__name__}"
        )
    try:
        # Accept both hyphenated and non-hyphenated formats
        return uuid.UUID(hex=value.replace("-", "")).bytes
    except ValueError as e:
        raise ValidationError(field_name, f"invalid UUID format: {e}")


def uuid_to_hex(value: bytes) -> str:
    """Convert UUID bytes to hex string (32 chars, no hyphens).

    Args:
        value: UUID as bytes (16 bytes)

    Returns:
        UUID as hex string
    """
    return uuid.UUID(bytes=value).hex


def validate_entity_id(entity_id: Union[bytes, str], field_name: str = "id") -> bytes:
    """Validate a UUID entity ID (note, tag, device, etc.).

    Args:
        entity_id: The entity ID to validate (bytes or hex string)
        field_name: Name of the field for error messages

    Returns:
        entity_id as bytes

    Raises:
        ValidationError: If entity_id is invalid
    """
    if isinstance(entity_id, str):
        return validate_uuid_hex(entity_id, field_name)
    validate_uuid(entity_id, field_name)
    return entity_id


def validate_note_id(note_id: Union[bytes, str]) -> bytes:
    """Validate a note ID."""
    return validate_entity_id(note_id, "note_id")


def validate_tag_id(tag_id: Union[bytes, str]) -> bytes:
    """Validate a tag ID."""
    return validate_entity_id(tag_id, "tag_id")


def validate_tag_ids(tag_ids: List[Union[bytes, str]]) -> List[bytes]:
    """Validate a list of tag IDs.

    Args:
        tag_ids: List of tag IDs to validate

    Returns:
        List of tag_ids as bytes

    Raises:
        ValidationError: If any tag_id is invalid
    """
    if not isinstance(tag_ids, list):
        raise ValidationError("tag_ids", f"must be a list, got {type(tag_ids).__name__}")
    result = []
    for i, tag_id in enumerate(tag_ids):
        try:
            result.append(validate_tag_id(tag_id))
        except ValidationError as e:
            raise ValidationError("tag_ids", f"item {i}: {e.message}")
    return result


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


def validate_parent_tag_id(
    parent_id: Optional[Union[bytes, str]], tag_id: Optional[Union[bytes, str]] = None
) -> Optional[bytes]:
    """Validate a parent tag ID for tag creation/update.

    Args:
        parent_id: The parent tag ID (None for root tags)
        tag_id: The tag's own ID (for circular reference check during updates)

    Returns:
        parent_id as bytes, or None

    Raises:
        ValidationError: If parent_id is invalid
    """
    if parent_id is None:
        return None

    parent_bytes = validate_tag_id(parent_id)

    if tag_id is not None:
        tag_bytes = validate_tag_id(tag_id)
        if parent_bytes == tag_bytes:
            raise ValidationError("parent_id", "tag cannot be its own parent")

    return parent_bytes


def validate_tag_id_groups(
    tag_id_groups: Optional[List[List[Union[bytes, str]]]]
) -> Optional[List[List[bytes]]]:
    """Validate tag ID groups for search.

    Args:
        tag_id_groups: List of lists of tag IDs (can be None)

    Returns:
        tag_id_groups with all IDs as bytes, or None

    Raises:
        ValidationError: If any tag ID is invalid
    """
    if tag_id_groups is None:
        return None

    if not isinstance(tag_id_groups, list):
        raise ValidationError(
            "tag_id_groups", f"must be a list, got {type(tag_id_groups).__name__}"
        )

    result = []
    for i, group in enumerate(tag_id_groups):
        if not isinstance(group, list):
            raise ValidationError(
                "tag_id_groups", f"group {i} must be a list, got {type(group).__name__}"
            )
        group_result = []
        for j, tag_id in enumerate(group):
            try:
                group_result.append(validate_tag_id(tag_id))
            except ValidationError as e:
                raise ValidationError("tag_id_groups", f"group {i}, item {j}: {e.message}")
        result.append(group_result)
    return result


def validate_device_id(device_id: Union[bytes, str]) -> bytes:
    """Validate a device ID."""
    return validate_entity_id(device_id, "device_id")

"""Input validation for Voice.

This module provides validation functions for all user inputs.
All validators raise ValidationError with descriptive messages.

This is a wrapper around the Rust voice_core extension.

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import uuid
from typing import List, Optional, Union

# Import from Rust extension
from voice_core import (
    ValidationError as _RustValidationError,
    validate_uuid_hex as _rust_validate_uuid_hex,
    validate_note_id as _rust_validate_note_id,
    validate_tag_id as _rust_validate_tag_id,
    validate_tag_name as _rust_validate_tag_name,
    validate_note_content as _rust_validate_note_content,
    validate_search_query as _rust_validate_search_query,
    uuid_to_hex as _rust_uuid_to_hex,
)


class ValidationError(ValueError):
    """Validation error with field and message attributes.

    This class wraps the Rust ValidationError to provide a Pythonic interface
    with .field and .message attributes.
    """

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"

    def __repr__(self) -> str:
        return f"ValidationError(field='{self.field}', message='{self.message}')"

    @classmethod
    def from_rust(cls, rust_err: _RustValidationError) -> "ValidationError":
        """Create from a Rust ValidationError exception."""
        # The Rust exception message is formatted as "field:message"
        msg = str(rust_err)
        if ":" in msg:
            field, message = msg.split(":", 1)
            return cls(field.strip(), message.strip())
        return cls("unknown", msg)


# Re-export ValidationError
__all__ = [
    "ValidationError",
    "validate_uuid",
    "validate_uuid_hex",
    "uuid_to_hex",
    "validate_entity_id",
    "validate_note_id",
    "validate_tag_id",
    "validate_tag_ids",
    "validate_tag_name",
    "validate_tag_path",
    "validate_note_content",
    "validate_search_query",
    "validate_parent_tag_id",
    "validate_tag_id_groups",
    "validate_device_id",
]

# Limits (keep for backward compatibility)
MAX_TAG_NAME_LENGTH = 100
MAX_NOTE_CONTENT_LENGTH = 100_000
MAX_SEARCH_QUERY_LENGTH = 500
MAX_TAG_PATH_LENGTH = 500
MAX_TAG_PATH_DEPTH = 50
UUID_BYTES_LENGTH = 16


def validate_uuid(value: bytes, field_name: str = "id") -> None:
    """Validate a UUID value (must be 16 bytes)."""
    if not isinstance(value, bytes):
        raise ValidationError(
            field_name, f"must be bytes, got {type(value).__name__}"
        )
    if len(value) != UUID_BYTES_LENGTH:
        raise ValidationError(
            field_name, f"must be {UUID_BYTES_LENGTH} bytes, got {len(value)}"
        )


def validate_uuid_hex(value: str, field_name: str = "id") -> bytes:
    """Validate and convert a UUID hex string to bytes."""
    if not isinstance(value, str):
        raise ValidationError(
            field_name, f"must be a string, got {type(value).__name__}"
        )
    try:
        # Use Rust validation, then convert to bytes
        _rust_validate_uuid_hex(value.replace("-", ""), field_name)
        return uuid.UUID(hex=value.replace("-", "")).bytes
    except _RustValidationError as e:
        raise ValidationError.from_rust(e) from None
    except ValueError as e:
        raise ValidationError(field_name, f"invalid UUID format: {e}") from None


def uuid_to_hex(value: bytes) -> str:
    """Convert UUID bytes to hex string (32 chars, no hyphens)."""
    return uuid.UUID(bytes=value).hex


def validate_entity_id(entity_id: Union[bytes, str], field_name: str = "id") -> bytes:
    """Validate a UUID entity ID (note, tag, device, etc.)."""
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
    """Validate a list of tag IDs."""
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
    """Validate a tag name."""
    if not isinstance(name, str):
        raise ValidationError(
            "tag_name", f"must be a string, got {type(name).__name__}"
        )
    try:
        _rust_validate_tag_name(name)
    except _RustValidationError as e:
        raise ValidationError.from_rust(e) from None


def validate_tag_path(path: str) -> None:
    """Validate a tag path."""
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
    """Validate note content."""
    if not isinstance(content, str):
        raise ValidationError(
            "content", f"must be a string, got {type(content).__name__}"
        )
    try:
        _rust_validate_note_content(content)
    except _RustValidationError as e:
        raise ValidationError.from_rust(e) from None


def validate_search_query(query: Optional[str]) -> None:
    """Validate a search query."""
    if query is not None and not isinstance(query, str):
        raise ValidationError(
            "search_query", f"must be a string or None, got {type(query).__name__}"
        )
    try:
        _rust_validate_search_query(query)
    except _RustValidationError as e:
        raise ValidationError.from_rust(e) from None


def validate_parent_tag_id(
    parent_id: Optional[Union[bytes, str]], tag_id: Optional[Union[bytes, str]] = None
) -> Optional[bytes]:
    """Validate a parent tag ID for tag creation/update."""
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
    """Validate tag ID groups for search."""
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

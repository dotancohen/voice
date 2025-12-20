"""Data models for the Voice Rewrite application.

This module defines immutable dataclasses representing the core entities:
Note and Tag.

All IDs are UUID7 stored as bytes (16 bytes).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Note:
    """Represents a note in the system.

    Notes contain text content and metadata about creation, modification,
    and deletion times. All timestamps are accurate to the second.

    Attributes:
        id: Unique identifier for the note (UUID7 as bytes)
        created_at: When the note was created (never NULL)
        content: The note text content
        device_id: UUID7 of the device that last modified this note
        modified_at: When the note was last modified (None if never modified)
        deleted_at: When the note was deleted (None if not deleted, soft delete)
    """

    id: bytes
    created_at: datetime
    content: str
    device_id: bytes
    modified_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


@dataclass(frozen=True)
class Tag:
    """Represents a tag in the hierarchical tag system.

    Tags can have parent-child relationships, forming a tree structure.
    A tag with parent_id=None is a root-level tag.

    Attributes:
        id: Unique identifier for the tag (UUID7 as bytes)
        name: Display name of the tag (must be unique within parent)
        device_id: UUID7 of the device that last modified this tag
        parent_id: ID of the parent tag (None for root tags)
        created_at: When the tag was created
        modified_at: When the tag was last modified (None if never modified)
    """

    id: bytes
    name: str
    device_id: bytes
    parent_id: Optional[bytes] = None
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None


@dataclass(frozen=True)
class NoteTag:
    """Represents the association between a note and a tag.

    This is used for syncing note-tag relationships.

    Attributes:
        note_id: UUID7 of the note
        tag_id: UUID7 of the tag
        created_at: When the association was created
        device_id: UUID7 of the device that created this association
        deleted_at: When the association was removed (None if active)
    """

    note_id: bytes
    tag_id: bytes
    created_at: datetime
    device_id: bytes
    deleted_at: Optional[datetime] = None

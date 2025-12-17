"""Data models for the Voice Rewrite application.

This module defines immutable dataclasses representing the core entities:
Note and Tag.
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
        id: Unique identifier for the note
        created_at: When the note was created (never NULL)
        content: The note text content
        modified_at: When the note was last modified (None if never modified)
        deleted_at: When the note was deleted (None if not deleted, soft delete)
    """

    id: int
    created_at: datetime
    content: str
    modified_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


@dataclass(frozen=True)
class Tag:
    """Represents a tag in the hierarchical tag system.

    Tags can have parent-child relationships, forming a tree structure.
    A tag with parent_id=None is a root-level tag.

    Attributes:
        id: Unique identifier for the tag
        name: Display name of the tag (must be unique)
        parent_id: ID of the parent tag (None for root tags)
    """

    id: int
    name: str
    parent_id: Optional[int] = None

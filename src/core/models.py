"""Data models for the Voice application.

This module defines immutable dataclasses representing the core entities:
Note, Tag, NoteAttachment, and AudioFile.

All IDs are UUID7 stored as bytes (16 bytes).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class AttachmentType(Enum):
    """Types of attachments that can be associated with notes."""

    AUDIO_FILE = "audio_file"
    SUMMARY = "summary"  # Future


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


@dataclass(frozen=True)
class NoteAttachment:
    """Represents the association between a note and an attachment.

    This is a junction table record that links notes to their attachments
    (audio files, summaries, etc.). An attachment can be linked to multiple notes.

    Attributes:
        id: Unique identifier for this association (UUID7 as bytes)
        note_id: UUID7 of the note
        attachment_id: UUID7 of the attachment (audio_file, summary, etc.)
        attachment_type: Type of the attachment
        created_at: When the association was created
        device_id: UUID7 of the device that created this association
        modified_at: When the association was modified (for sync tracking)
        deleted_at: When the association was removed (None if active)
    """

    id: bytes
    note_id: bytes
    attachment_id: bytes
    attachment_type: AttachmentType
    created_at: datetime
    device_id: bytes
    modified_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


@dataclass(frozen=True)
class AudioFile:
    """Represents an audio file entity.

    Audio files are stored on disk and can be attached to notes via NoteAttachment.
    The actual file is stored at `{audiofile_directory}/{id}.{extension}`.

    Attributes:
        id: Unique identifier for the audio file (UUID7 as bytes)
        imported_at: When the file was imported into the system
        filename: Original filename from import
        device_id: UUID7 of the device that created/last modified this record
        file_created_at: When the file was originally created (from filesystem metadata)
        summary: Quick text summary of the audio content
        modified_at: When the record was last modified
        deleted_at: When the file was soft-deleted (None if active)
    """

    id: bytes
    imported_at: datetime
    filename: str
    device_id: bytes
    file_created_at: Optional[datetime] = None
    summary: Optional[str] = None
    modified_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


# Supported audio file formats for import
AUDIO_FILE_FORMATS = frozenset(["mp3", "wav", "flac", "ogg", "opus", "m4a"])

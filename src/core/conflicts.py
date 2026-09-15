"""Conflict handling for Voice sync.

Every editable field (note content, tag name and parent, transcription text
and state, note-tag links, attachments, deletions, synced settings) is
versioned in voicecore like a Git history. When two devices change the same
field concurrently the sync merges them three-way:

- text is merged line by line; overlapping edits stay in the text between
  ``<<<<<<< VERSION A`` / ``>>>>>>> VERSION B`` markers, so nothing is lost;
- links and deletions keep the value that preserves data (attached, alive);
- scalars keep the later value.

Whenever a merge could not be decided automatically a conflict record is
created on every device. Conflicts are resolved by:

- **editing** the field (saving a note with the markers cleaned up); or
- **accepting** the merged value as it stands.

Both produce a new version that descends from the merge, so the resolution
propagates to every device. Nothing is ever picked by "last write wins".

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .database import Database

# Merge functions from Rust
from voicecore import (
    diff3_merge as _rust_diff3_merge,
    auto_merge_if_possible as _rust_auto_merge_if_possible,
    get_diff_preview as _rust_get_diff_preview,
)

logger = logging.getLogger(__name__)

# Conflict marker labels produced by the merge (symmetric: every device shows
# the same text)
MARKER_A = "<<<<<<< VERSION A"
MARKER_SEP = "======="
MARKER_B = ">>>>>>> VERSION B"

# Conflict kinds as stored in field_conflicts.kind
KIND_TEXT = "text"
KIND_SCALAR = "scalar"
KIND_FLAGS = "flags"
KIND_MEMBERSHIP = "membership"
KIND_DELETE = "delete"

ENTITY_NOTE = "note"
ENTITY_TAG = "tag"
ENTITY_NOTE_TAG = "note_tag"
ENTITY_NOTE_ATTACHMENT = "note_attachment"
ENTITY_TRANSCRIPTION = "transcription"
ENTITY_AUDIO_FILE = "audio_file"
ENTITY_SETTING = "setting"

_ENTITY_LABELS = {
    ENTITY_NOTE: "Note",
    ENTITY_TAG: "Tag",
    ENTITY_NOTE_TAG: "Note tag",
    ENTITY_NOTE_ATTACHMENT: "Attachment",
    ENTITY_TRANSCRIPTION: "Transcription",
    ENTITY_AUDIO_FILE: "Audio file",
    ENTITY_SETTING: "Setting",
}


def has_conflict_markers(text: str) -> bool:
    """Whether a text still contains unresolved merge markers."""
    return MARKER_A in text or MARKER_B in text


@dataclass
class Conflict:
    """A recorded disagreement between two versions of one field."""

    id: str
    entity_type: str
    entity_id: str
    field: str
    kind: str
    base_version_id: Optional[str]
    version_a_id: str
    version_b_id: str
    merge_version_id: str
    device_a_id: Optional[str]
    device_a_name: Optional[str]
    device_b_id: Optional[str]
    device_b_name: Optional[str]
    created_at: int
    resolved_at: Optional[int] = None

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Conflict":
        return cls(
            id=row["id"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            field=row["field"],
            kind=row["kind"],
            base_version_id=row.get("base_version_id"),
            version_a_id=row["version_a_id"],
            version_b_id=row["version_b_id"],
            merge_version_id=row["merge_version_id"],
            device_a_id=row.get("device_a_id"),
            device_a_name=row.get("device_a_name"),
            device_b_id=row.get("device_b_id"),
            device_b_name=row.get("device_b_name"),
            created_at=row["created_at"],
            resolved_at=row.get("resolved_at"),
        )

    @property
    def is_resolved(self) -> bool:
        return self.resolved_at is not None

    @property
    def device_a_label(self) -> str:
        return _device_label(self.device_a_name, self.device_a_id)

    @property
    def device_b_label(self) -> str:
        return _device_label(self.device_b_name, self.device_b_id)

    @property
    def note_id(self) -> Optional[str]:
        """The note this conflict belongs to, when it is a note or note-tag conflict."""
        if self.entity_type == ENTITY_NOTE:
            return self.entity_id
        if self.entity_type == ENTITY_NOTE_TAG:
            return self.entity_id.split(":", 1)[0]
        return None

    @property
    def display_kind(self) -> str:
        """Kind as shown to the user: "content" for text, otherwise the field."""
        if self.kind == KIND_DELETE:
            return "delete"
        if self.entity_type == ENTITY_NOTE_TAG:
            return "tag"
        if self.entity_type == ENTITY_NOTE_ATTACHMENT:
            return "attachment"
        if self.kind == KIND_TEXT:
            return "content"
        return self.field

    def describe(self) -> str:
        """One line for lists: what disagreed and which devices did it."""
        entity = _ENTITY_LABELS.get(self.entity_type, self.entity_type)
        what = {
            KIND_TEXT: f"{entity} {self.field} edited on both",
            KIND_DELETE: f"{entity} deleted on one, changed on the other",
            KIND_MEMBERSHIP: f"{entity} removed on one, kept on the other",
            KIND_SCALAR: f"{entity} {self.field} changed on both",
            KIND_FLAGS: f"{entity} {self.field} changed on both",
        }.get(self.kind, f"{entity} {self.field}")
        return f"{what}: {self.device_a_label} vs {self.device_b_label}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "field": self.field,
            "kind": self.kind,
            "display_kind": self.display_kind,
            "description": self.describe(),
            "note_id": self.note_id,
            "base_version_id": self.base_version_id,
            "version_a_id": self.version_a_id,
            "version_b_id": self.version_b_id,
            "merge_version_id": self.merge_version_id,
            "device_a": self.device_a_label,
            "device_b": self.device_b_label,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


@dataclass
class FieldVersion:
    """One immutable version of a field."""

    id: str
    entity_type: str
    entity_id: str
    field: str
    parent_id: Optional[str]
    merge_parent_id: Optional[str]
    content: Optional[str]
    context: Optional[str]
    conflict_kind: Optional[str]
    device_id: Optional[str]
    device_name: Optional[str]
    created_at: int
    #: Seconds east of UTC on the device that wrote it, when it reported one
    created_at_offset: Optional[int] = None
    created_at_zone: Optional[str] = None

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "FieldVersion":
        return cls(
            id=row["id"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            field=row["field"],
            parent_id=row.get("parent_id"),
            merge_parent_id=row.get("merge_parent_id"),
            content=row.get("content"),
            context=row.get("context"),
            conflict_kind=row.get("conflict_kind"),
            device_id=row.get("device_id"),
            device_name=row.get("device_name"),
            created_at_offset=row.get("created_at_offset"),
            created_at_zone=row.get("created_at_zone"),
            created_at=row["created_at"],
        )

    @property
    def device_label(self) -> str:
        return _device_label(self.device_name, self.device_id)


@dataclass
class ConflictVersions:
    """The versions a conflict was built from."""

    base: Optional[FieldVersion]
    version_a: Optional[FieldVersion]
    version_b: Optional[FieldVersion]
    merge: Optional[FieldVersion]


@dataclass
class MergeResult:
    """Result of a diff3-style merge."""

    merged_content: str
    has_conflicts: bool
    conflict_markers: List[Tuple[int, int]] = field(default_factory=list)


def _device_label(name: Optional[str], device_id: Optional[str]) -> str:
    if name:
        return name
    if device_id:
        return device_id[:8]
    return "unknown device"


class ConflictManager:
    """Lists, describes and resolves sync conflicts."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ----- queries -----

    def get_unresolved_count(self) -> Dict[str, int]:
        """Unresolved conflict counts keyed by kind plus "total"."""
        return self.db.get_unresolved_conflict_counts()

    def get_conflicts(self, include_resolved: bool = False) -> List[Conflict]:
        """All conflicts, newest first."""
        return [Conflict.from_row(r) for r in self.db.get_conflicts(include_resolved)]

    def get_entity_conflicts(self, entity_type: str, entity_id: str) -> List[Conflict]:
        """Unresolved conflicts of one entity."""
        return [Conflict.from_row(r) for r in self.db.get_entity_conflicts(entity_type, entity_id)]

    def get_conflict(self, id_or_prefix: str) -> Optional[Conflict]:
        """One conflict by id or unique prefix."""
        row = self.db.get_conflict(id_or_prefix)
        return Conflict.from_row(row) if row else None

    def get_note_conflicts(self, note_id: str) -> List[Conflict]:
        """Unresolved conflicts that concern a note: its own fields, its tag
        links, its attachments and the transcriptions attached to it."""
        return [Conflict.from_row(r) for r in self.db.get_note_conflicts(note_id)]

    def get_note_conflict_types(self, note_id: str) -> List[str]:
        """Kinds of unresolved conflict for a note (e.g. ["content", "tag"])."""
        return self.db.get_note_conflict_types(note_id)

    def describe_note_conflicts(self, note_id: str) -> str:
        """Warning text for editors: kinds and the devices involved."""
        conflicts = self.get_note_conflicts(note_id)
        if not conflicts:
            return ""
        kinds = []
        devices = []
        for c in conflicts:
            if c.display_kind not in kinds:
                kinds.append(c.display_kind)
            for d in (c.device_a_label, c.device_b_label):
                if d not in devices:
                    devices.append(d)
        return (
            f"CONFLICT ({', '.join(kinds)}): changed on {' and '.join(devices)}. "
            "Both versions are kept. Edit and save to resolve, or accept the merge as it is."
        )

    def get_conflict_versions(self, conflict: Conflict) -> ConflictVersions:
        """The base, the two sides and the merge of a conflict."""

        def load(vid: Optional[str]) -> Optional[FieldVersion]:
            if not vid:
                return None
            row = self.db.get_version(vid)
            return FieldVersion.from_row(row) if row else None

        return ConflictVersions(
            base=load(conflict.base_version_id),
            version_a=load(conflict.version_a_id),
            version_b=load(conflict.version_b_id),
            merge=load(conflict.merge_version_id),
        )

    def get_field_history(self, entity_type: str, entity_id: str, field_name: str) -> List[FieldVersion]:
        """Every version of one field, oldest first."""
        return [FieldVersion.from_row(r) for r in self.db.get_field_history(entity_type, entity_id, field_name)]

    # ----- resolution -----

    def accept(self, conflict_id: str) -> bool:
        """Accept the merged value as it stands (markers included, if any)."""
        ok = self.db.accept_conflict(conflict_id)
        if ok:
            logger.info(f"Accepted merge for conflict {conflict_id}")
        return ok

    def resolve_with_content(self, conflict_id: str, content: str) -> bool:
        """Resolve a conflict by writing a new value for its field."""
        ok = self.db.resolve_conflict_with_content(conflict_id, content)
        if ok:
            logger.info(f"Resolved conflict {conflict_id} with new content")
        return ok

    def accept_note_conflicts(self, note_id: str) -> int:
        """Accept every unresolved conflict of a note. Returns how many."""
        n = 0
        for c in self.get_note_conflicts(note_id):
            if self.accept(c.id):
                n += 1
        return n

    def find_and_resolve_conflict(
        self,
        conflict_id_prefix: str,
        content: Optional[str] = None,
    ) -> Tuple[bool, Optional[Conflict], Optional[str]]:
        """Find a conflict by id prefix and accept it, or resolve it with content.

        Returns (success, conflict, error_message).
        """
        try:
            conflict = self.get_conflict(conflict_id_prefix)
        except Exception as e:
            return False, None, str(e)
        if conflict is None:
            return False, None, f"Conflict with ID starting with '{conflict_id_prefix}' not found"
        if conflict.is_resolved:
            return False, conflict, f"Conflict {conflict.id[:8]} is already resolved"
        if content is None:
            ok = self.accept(conflict.id)
        else:
            ok = self.resolve_with_content(conflict.id, content)
        if not ok:
            return False, conflict, "Failed to resolve conflict"
        return True, conflict, None


def diff3_merge(base: str, local: str, remote: str) -> MergeResult:
    """Three-way merge of text (thin wrapper around the Rust implementation)."""
    result = _rust_diff3_merge(base, local, remote)
    return MergeResult(
        merged_content=result["content"],
        has_conflicts=result["has_conflicts"],
        conflict_markers=[],
    )


def auto_merge_if_possible(
    local_content: str,
    remote_content: str,
    base_content: Optional[str] = None,
) -> Optional[str]:
    """Merged content when the merge is clean, None when it conflicts."""
    return _rust_auto_merge_if_possible(local_content, remote_content, base_content)


def get_diff_preview(local: str, remote: str) -> str:
    """Unified diff between two versions."""
    return _rust_get_diff_preview(local, remote)

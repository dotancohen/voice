"""Unit tests for conflict resolution.

Tests conflict detection, resolution, and diff3 merging.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Generator

import pytest
from uuid6 import uuid7

from core.config import Config
from core.conflicts import (
    ConflictManager,
    ConflictType,
    MergeResult,
    NoteContentConflict,
    NoteDeleteConflict,
    ResolutionChoice,
    TagRenameConflict,
    auto_merge_if_possible,
    diff3_merge,
    get_diff_preview,
)
from core.database import Database, set_local_device_id
from core.validation import uuid_to_hex


@pytest.fixture
def conflict_db(test_config_dir: Path) -> Generator[Database, None, None]:
    """Create a database for conflict testing."""
    device_id = uuid.UUID("00000000-0000-7000-8000-000000000003").bytes
    set_local_device_id(device_id)

    db_path = test_config_dir / "conflict_test.db"
    db = Database(db_path)
    yield db
    db.close()


@pytest.fixture
def conflict_manager(conflict_db: Database) -> ConflictManager:
    """Create a conflict manager instance."""
    return ConflictManager(conflict_db)


@pytest.fixture
def sample_note(conflict_db: Database) -> str:
    """Create a sample note and return its ID hex."""
    note_id = conflict_db.create_note("Original content")
    return note_id


@pytest.fixture
def sample_tag(conflict_db: Database) -> str:
    """Create a sample tag and return its ID hex."""
    tag_id = conflict_db.create_tag("original_tag")
    return tag_id


class TestConflictDataclasses:
    """Test conflict dataclass creation."""

    def test_note_content_conflict(self) -> None:
        """NoteContentConflict has all required fields."""
        conflict = NoteContentConflict(
            id="abc123",
            note_id="note123",
            local_content="Local text",
            local_modified_at="2024-01-01T00:00:00",
            local_device_id="device1",
            local_device_name="My Device",
            remote_content="Remote text",
            remote_modified_at="2024-01-01T00:01:00",
            remote_device_id="device2",
            remote_device_name="Other Device",
            created_at="2024-01-01T00:02:00",
        )
        assert conflict.id == "abc123"
        assert conflict.local_content == "Local text"
        assert conflict.remote_content == "Remote text"
        assert conflict.resolved_at is None

    def test_note_delete_conflict(self) -> None:
        """NoteDeleteConflict has all required fields."""
        conflict = NoteDeleteConflict(
            id="def456",
            note_id="note456",
            surviving_content="Content that survived",
            surviving_modified_at="2024-01-01T00:00:00",
            surviving_device_id="device1",
            surviving_device_name="Editing Device",
            deleted_at="2024-01-01T00:01:00",
            deleting_device_id="device2",
            deleting_device_name="Deleting Device",
            created_at="2024-01-01T00:02:00",
        )
        assert conflict.id == "def456"
        assert conflict.surviving_content == "Content that survived"
        assert conflict.resolved_at is None

    def test_tag_rename_conflict(self) -> None:
        """TagRenameConflict has all required fields."""
        conflict = TagRenameConflict(
            id="ghi789",
            tag_id="tag789",
            local_name="local_name",
            local_modified_at="2024-01-01T00:00:00",
            local_device_id="device1",
            local_device_name="My Device",
            remote_name="remote_name",
            remote_modified_at="2024-01-01T00:01:00",
            remote_device_id="device2",
            remote_device_name="Other Device",
            created_at="2024-01-01T00:02:00",
        )
        assert conflict.id == "ghi789"
        assert conflict.local_name == "local_name"
        assert conflict.remote_name == "remote_name"


class TestMergeResult:
    """Test MergeResult dataclass."""

    def test_successful_merge(self) -> None:
        """MergeResult for clean merge."""
        result = MergeResult(merged_content="Merged text", has_conflicts=False)
        assert result.merged_content == "Merged text"
        assert result.has_conflicts is False
        assert result.conflict_markers == []

    def test_merge_with_conflicts(self) -> None:
        """MergeResult with conflict markers."""
        result = MergeResult(
            merged_content="<<<<<<< LOCAL\ntext\n=======\nother\n>>>>>>> REMOTE\n",
            has_conflicts=True,
            conflict_markers=[(0, 5)],
        )
        assert result.has_conflicts is True
        assert len(result.conflict_markers) == 1


class TestResolutionChoice:
    """Test ResolutionChoice enum."""

    def test_enum_values(self) -> None:
        """ResolutionChoice has expected values."""
        assert ResolutionChoice.KEEP_LOCAL.value == "keep_local"
        assert ResolutionChoice.KEEP_REMOTE.value == "keep_remote"
        assert ResolutionChoice.MERGE.value == "merge"
        assert ResolutionChoice.KEEP_BOTH.value == "keep_both"


class TestConflictType:
    """Test ConflictType enum."""

    def test_enum_values(self) -> None:
        """ConflictType has expected values."""
        assert ConflictType.NOTE_CONTENT.value == "note_content"
        assert ConflictType.NOTE_DELETE.value == "note_delete"
        assert ConflictType.TAG_RENAME.value == "tag_rename"


class TestConflictManagerInit:
    """Test ConflictManager initialization."""

    def test_creates_manager(self, conflict_manager: ConflictManager) -> None:
        """Manager is created with database."""
        assert conflict_manager.db is not None


class TestGetUnresolvedCount:
    """Test counting unresolved conflicts."""

    def test_empty_counts(self, conflict_manager: ConflictManager) -> None:
        """Empty database has zero conflicts."""
        counts = conflict_manager.get_unresolved_count()
        assert counts["note_content"] == 0
        assert counts["note_delete"] == 0
        assert counts["tag_rename"] == 0
        assert counts["total"] == 0

    def test_counts_with_conflicts(
        self,
        conflict_manager: ConflictManager,
        conflict_db: Database,
        sample_note: str,
    ) -> None:
        """Counts reflect inserted conflicts."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        remote_device_id = "00000000000070008000000000000002"

        # Create a note content conflict using Database method
        conflict_db.create_note_content_conflict(
            note_id=sample_note,
            local_content="Local content",
            local_modified_at=now,
            remote_content="Remote content",
            remote_modified_at=now,
            remote_device_id=remote_device_id,
        )

        counts = conflict_manager.get_unresolved_count()
        assert counts["note_content"] == 1
        assert counts["total"] == 1


class TestGetNoteContentConflicts:
    """Test retrieving note content conflicts."""

    def test_empty_list(self, conflict_manager: ConflictManager) -> None:
        """Empty database returns empty list."""
        conflicts = conflict_manager.get_note_content_conflicts()
        assert conflicts == []

    def test_retrieves_unresolved(
        self,
        conflict_manager: ConflictManager,
        conflict_db: Database,
        sample_note: str,
    ) -> None:
        """Retrieves unresolved conflicts."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        remote_device_id = "00000000000070008000000000000002"

        conflict_db.create_note_content_conflict(
            note_id=sample_note,
            local_content="Local version",
            local_modified_at=now,
            remote_content="Remote version",
            remote_modified_at=now,
            remote_device_id=remote_device_id,
        )

        conflicts = conflict_manager.get_note_content_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0].local_content == "Local version"
        assert conflicts[0].remote_content == "Remote version"

    def test_excludes_resolved(
        self,
        conflict_manager: ConflictManager,
        conflict_db: Database,
        sample_note: str,
    ) -> None:
        """Excludes resolved conflicts by default."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        remote_device_id = "00000000000070008000000000000002"

        # Create a conflict, then resolve it
        conflict_id = conflict_db.create_note_content_conflict(
            note_id=sample_note,
            local_content="Local version",
            local_modified_at=now,
            remote_content="Remote version",
            remote_modified_at=now,
            remote_device_id=remote_device_id,
        )
        # Resolve the conflict immediately
        conflict_db.resolve_note_content_conflict(conflict_id, "Local version")

        conflicts = conflict_manager.get_note_content_conflicts()
        assert len(conflicts) == 0

        # Include resolved
        conflicts = conflict_manager.get_note_content_conflicts(include_resolved=True)
        assert len(conflicts) == 1


class TestGetNoteDeleteConflicts:
    """Test retrieving note delete conflicts."""

    def test_empty_list(self, conflict_manager: ConflictManager) -> None:
        """Empty database returns empty list."""
        conflicts = conflict_manager.get_note_delete_conflicts()
        assert conflicts == []

    def test_retrieves_unresolved(
        self,
        conflict_manager: ConflictManager,
        conflict_db: Database,
        sample_note: str,
    ) -> None:
        """Retrieves unresolved delete conflicts."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        surviving_device_id = "00000000000070008000000000000001"
        deleting_device_id = "00000000000070008000000000000002"

        conflict_db.create_note_delete_conflict(
            note_id=sample_note,
            surviving_content="Surviving content",
            surviving_modified_at=now,
            surviving_device_id=surviving_device_id,
            deleted_at=now,
            deleting_device_id=deleting_device_id,
        )

        conflicts = conflict_manager.get_note_delete_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0].surviving_content == "Surviving content"


class TestGetTagRenameConflicts:
    """Test retrieving tag rename conflicts."""

    def test_empty_list(self, conflict_manager: ConflictManager) -> None:
        """Empty database returns empty list."""
        conflicts = conflict_manager.get_tag_rename_conflicts()
        assert conflicts == []

    def test_retrieves_unresolved(
        self,
        conflict_manager: ConflictManager,
        conflict_db: Database,
        sample_tag: str,
    ) -> None:
        """Retrieves unresolved tag rename conflicts."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        remote_device_id = "00000000000070008000000000000002"

        conflict_db.create_tag_rename_conflict(
            tag_id=sample_tag,
            local_name="local_tag_name",
            local_modified_at=now,
            remote_name="remote_tag_name",
            remote_modified_at=now,
            remote_device_id=remote_device_id,
        )

        conflicts = conflict_manager.get_tag_rename_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0].local_name == "local_tag_name"
        assert conflicts[0].remote_name == "remote_tag_name"


class TestResolveNoteContentConflict:
    """Test resolving note content conflicts."""

    def test_keep_local(
        self,
        conflict_manager: ConflictManager,
        conflict_db: Database,
        sample_note: str,
    ) -> None:
        """Keep local resolution updates note with local content."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        remote_device_id = "00000000000070008000000000000002"

        conflict_id = conflict_db.create_note_content_conflict(
            note_id=sample_note,
            local_content="Local content wins",
            local_modified_at=now,
            remote_content="Remote content loses",
            remote_modified_at=now,
            remote_device_id=remote_device_id,
        )

        result = conflict_manager.resolve_note_content_conflict(
            conflict_id, ResolutionChoice.KEEP_LOCAL
        )
        assert result is True

        # Check note was updated
        note = conflict_db.get_note_raw(sample_note)
        assert note is not None
        assert note["content"] == "Local content wins"

        # Check conflict was marked resolved
        conflicts = conflict_manager.get_note_content_conflicts()
        assert len(conflicts) == 0

    def test_keep_remote(
        self,
        conflict_manager: ConflictManager,
        conflict_db: Database,
        sample_note: str,
    ) -> None:
        """Keep remote resolution updates note with remote content."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        remote_device_id = "00000000000070008000000000000002"

        conflict_id = conflict_db.create_note_content_conflict(
            note_id=sample_note,
            local_content="Local content loses",
            local_modified_at=now,
            remote_content="Remote content wins",
            remote_modified_at=now,
            remote_device_id=remote_device_id,
        )

        result = conflict_manager.resolve_note_content_conflict(
            conflict_id, ResolutionChoice.KEEP_REMOTE
        )
        assert result is True

        # Check note was updated
        note = conflict_db.get_note_raw(sample_note)
        assert note is not None
        assert note["content"] == "Remote content wins"

    def test_merge_resolution(
        self,
        conflict_manager: ConflictManager,
        conflict_db: Database,
        sample_note: str,
    ) -> None:
        """Merge resolution updates note with merged content."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        remote_device_id = "00000000000070008000000000000002"

        conflict_id = conflict_db.create_note_content_conflict(
            note_id=sample_note,
            local_content="Local content",
            local_modified_at=now,
            remote_content="Remote content",
            remote_modified_at=now,
            remote_device_id=remote_device_id,
        )

        result = conflict_manager.resolve_note_content_conflict(
            conflict_id, ResolutionChoice.MERGE, merged_content="Merged content"
        )
        assert result is True

        # Check note was updated with merged content
        note = conflict_db.get_note_raw(sample_note)
        assert note is not None
        assert note["content"] == "Merged content"

    def test_merge_requires_content(
        self,
        conflict_manager: ConflictManager,
        conflict_db: Database,
        sample_note: str,
    ) -> None:
        """Merge resolution requires merged_content parameter."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        remote_device_id = "00000000000070008000000000000002"

        conflict_id = conflict_db.create_note_content_conflict(
            note_id=sample_note,
            local_content="Local content",
            local_modified_at=now,
            remote_content="Remote content",
            remote_modified_at=now,
            remote_device_id=remote_device_id,
        )

        with pytest.raises(ValueError, match="merged_content required"):
            conflict_manager.resolve_note_content_conflict(
                conflict_id, ResolutionChoice.MERGE
            )

    def test_nonexistent_conflict(self, conflict_manager: ConflictManager) -> None:
        """Resolving nonexistent conflict returns False."""
        fake_id = uuid7().hex
        result = conflict_manager.resolve_note_content_conflict(
            fake_id, ResolutionChoice.KEEP_LOCAL
        )
        assert result is False


class TestResolveNoteDeleteConflict:
    """Test resolving note delete conflicts."""

    def test_keep_both_restores_note(
        self,
        conflict_manager: ConflictManager,
        conflict_db: Database,
    ) -> None:
        """Keep both resolution restores the deleted note."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()

        # Create a note and then delete it
        note_id = conflict_db.create_note("Deleted content")
        conflict_db.delete_note(note_id)

        # Create delete conflict
        surviving_device_id = "00000000000070008000000000000001"
        deleting_device_id = "00000000000070008000000000000002"

        conflict_id = conflict_db.create_note_delete_conflict(
            note_id=note_id,
            surviving_content="Surviving content to restore",
            surviving_modified_at=now,
            surviving_device_id=surviving_device_id,
            deleted_at=now,
            deleting_device_id=deleting_device_id,
        )

        result = conflict_manager.resolve_note_delete_conflict(
            conflict_id, ResolutionChoice.KEEP_BOTH
        )
        assert result is True

        # Check note was restored
        note = conflict_db.get_note_raw(note_id)
        assert note is not None
        assert note["content"] == "Surviving content to restore"
        assert note["deleted_at"] is None

    def test_keep_remote_accepts_deletion(
        self,
        conflict_manager: ConflictManager,
        conflict_db: Database,
    ) -> None:
        """Keep remote resolution accepts the deletion."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()

        # Create a note and then delete it
        note_id = conflict_db.create_note("Deleted content")
        conflict_db.delete_note(note_id)

        # Create delete conflict
        surviving_device_id = "00000000000070008000000000000001"
        deleting_device_id = "00000000000070008000000000000002"

        conflict_id = conflict_db.create_note_delete_conflict(
            note_id=note_id,
            surviving_content="This content stays deleted",
            surviving_modified_at=now,
            surviving_device_id=surviving_device_id,
            deleted_at=now,
            deleting_device_id=deleting_device_id,
        )

        result = conflict_manager.resolve_note_delete_conflict(
            conflict_id, ResolutionChoice.KEEP_REMOTE
        )
        assert result is True

        # Check note stays deleted
        note = conflict_db.get_note_raw(note_id)
        assert note is not None
        assert note["deleted_at"] is not None


class TestResolveTagRenameConflict:
    """Test resolving tag rename conflicts."""

    def test_keep_local(
        self,
        conflict_manager: ConflictManager,
        conflict_db: Database,
        sample_tag: str,
    ) -> None:
        """Keep local resolution updates tag with local name."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        remote_device_id = "00000000000070008000000000000002"

        conflict_id = conflict_db.create_tag_rename_conflict(
            tag_id=sample_tag,
            local_name="local_name_wins",
            local_modified_at=now,
            remote_name="remote_name_loses",
            remote_modified_at=now,
            remote_device_id=remote_device_id,
        )

        result = conflict_manager.resolve_tag_rename_conflict(
            conflict_id, ResolutionChoice.KEEP_LOCAL
        )
        assert result is True

        # Check tag was updated
        tag = conflict_db.get_tag_raw(sample_tag)
        assert tag is not None
        assert tag["name"] == "local_name_wins"

    def test_keep_remote(
        self,
        conflict_manager: ConflictManager,
        conflict_db: Database,
        sample_tag: str,
    ) -> None:
        """Keep remote resolution updates tag with remote name."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        remote_device_id = "00000000000070008000000000000002"

        conflict_id = conflict_db.create_tag_rename_conflict(
            tag_id=sample_tag,
            local_name="local_name_loses",
            local_modified_at=now,
            remote_name="remote_name_wins",
            remote_modified_at=now,
            remote_device_id=remote_device_id,
        )

        result = conflict_manager.resolve_tag_rename_conflict(
            conflict_id, ResolutionChoice.KEEP_REMOTE
        )
        assert result is True

        # Check tag was updated
        tag = conflict_db.get_tag_raw(sample_tag)
        assert tag is not None
        assert tag["name"] == "remote_name_wins"


class TestDiff3Merge:
    """Test diff3-style merging."""

    def test_identical_changes(self) -> None:
        """Same changes on both sides merge cleanly."""
        base = "Line 1\nLine 2\nLine 3\n"
        local = "Line 1\nModified Line 2\nLine 3\n"
        remote = "Line 1\nModified Line 2\nLine 3\n"

        result = diff3_merge(base, local, remote)
        assert result.has_conflicts is False
        assert "Modified Line 2" in result.merged_content

    def test_one_side_unchanged(self) -> None:
        """One side unchanged merges cleanly."""
        base = "Line 1\nLine 2\nLine 3\n"
        local = base
        remote = "Line 1\nModified Line 2\nLine 3\n"

        result = diff3_merge(base, local, remote)
        assert result.has_conflicts is False
        assert result.merged_content == remote

    def test_conflicting_changes(self) -> None:
        """Different changes create conflict markers."""
        base = "Line 1\nLine 2\nLine 3\n"
        local = "Line 1\nLocal change\nLine 3\n"
        remote = "Line 1\nRemote change\nLine 3\n"

        result = diff3_merge(base, local, remote)
        assert result.has_conflicts is True
        assert "<<<<<<< LOCAL" in result.merged_content
        assert "=======" in result.merged_content
        assert ">>>>>>> REMOTE" in result.merged_content

    def test_empty_base(self) -> None:
        """Empty base with different content creates conflict."""
        base = ""
        local = "Local content\n"
        remote = "Remote content\n"

        result = diff3_merge(base, local, remote)
        assert result.has_conflicts is True

    def test_empty_base_same_content(self) -> None:
        """Empty base with same content merges cleanly."""
        base = ""
        local = "Same content\n"
        remote = "Same content\n"

        result = diff3_merge(base, local, remote)
        assert result.has_conflicts is False
        assert result.merged_content == "Same content\n"


class TestAutoMergeIfPossible:
    """Test automatic merging."""

    def test_identical_content(self) -> None:
        """Identical content returns the content."""
        result = auto_merge_if_possible("Same text", "Same text")
        assert result == "Same text"

    def test_clean_merge_with_base(self) -> None:
        """Clean merge returns merged content."""
        base = "Original\n"
        local = "Original\n"
        remote = "Modified\n"

        result = auto_merge_if_possible(local, remote, base)
        assert result == "Modified\n"

    def test_conflict_returns_none(self) -> None:
        """Conflicting changes return None."""
        base = "Original\n"
        local = "Local change\n"
        remote = "Remote change\n"

        result = auto_merge_if_possible(local, remote, base)
        assert result is None

    def test_no_base_different_content(self) -> None:
        """Different content without base returns None."""
        result = auto_merge_if_possible("Local text", "Remote text")
        assert result is None


class TestGetDiffPreview:
    """Test diff preview generation."""

    def test_generates_unified_diff(self) -> None:
        """Generates unified diff format."""
        local = "Line 1\nLine 2\nLine 3\n"
        remote = "Line 1\nModified Line 2\nLine 3\n"

        diff = get_diff_preview(local, remote)
        assert "--- Local" in diff
        assert "+++ Remote" in diff
        assert "-Line 2" in diff
        assert "+Modified Line 2" in diff

    def test_identical_content(self) -> None:
        """Identical content produces empty diff."""
        local = "Same content\n"
        remote = "Same content\n"

        diff = get_diff_preview(local, remote)
        # Empty diff for identical content
        assert diff == "" or "---" not in diff

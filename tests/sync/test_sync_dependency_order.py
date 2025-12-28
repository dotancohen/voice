"""Tests for sync dependency ordering.

Ensures that sync changes are applied in correct order to satisfy
foreign key constraints (parents before children).
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestSyncDependencyOrder:
    """Test that sync applies changes in correct dependency order."""

    def test_apply_sync_changes_handles_out_of_order_entities(
        self, tmp_path: Path
    ) -> None:
        """Test that note_attachment can sync even if it comes before its parents."""
        from core.database import Database, set_local_device_id
        from core.sync import SyncChange, apply_sync_changes

        set_local_device_id("00000000000070008000000000000001")
        db = Database(tmp_path / "notes.db")

        # Simulate changes arriving in WRONG order:
        # note_attachment first, then audio_file, then note
        # This is the order that would cause FOREIGN KEY failures without sorting
        changes = [
            # note_attachment comes FIRST (wrong - depends on note and audio_file)
            SyncChange(
                entity_type="note_attachment",
                entity_id="aaaa0000000000000000000000000001",
                operation="create",
                data={
                    "id": "aaaa0000000000000000000000000001",
                    "note_id": "bbbb0000000000000000000000000001",
                    "attachment_id": "cccc0000000000000000000000000001",
                    "attachment_type": "audio_file",
                    "created_at": "2025-01-01 10:00:00",
                },
                timestamp="2025-01-01 10:00:03",
                device_id="00000000000070008000000000000002",
            ),
            # audio_file comes SECOND
            SyncChange(
                entity_type="audio_file",
                entity_id="cccc0000000000000000000000000001",
                operation="create",
                data={
                    "id": "cccc0000000000000000000000000001",
                    "imported_at": "2025-01-01 10:00:00",
                    "filename": "recording.mp3",
                    "file_created_at": "2024-12-15 08:30:00",
                },
                timestamp="2025-01-01 10:00:02",
                device_id="00000000000070008000000000000002",
            ),
            # note comes LAST (wrong - should be first)
            SyncChange(
                entity_type="note",
                entity_id="bbbb0000000000000000000000000001",
                operation="create",
                data={
                    "id": "bbbb0000000000000000000000000001",
                    "created_at": "2025-01-01 10:00:00",
                    "content": "Test note with audio",
                },
                timestamp="2025-01-01 10:00:01",
                device_id="00000000000070008000000000000002",
            ),
        ]

        # This should NOT fail with FOREIGN KEY constraint
        applied, conflicts, errors = apply_sync_changes(
            db, changes, "00000000000070008000000000000002", "TestPeer"
        )

        # All should be applied successfully
        assert len(errors) == 0, f"Expected no errors, got: {errors}"
        assert applied == 3, f"Expected 3 applied, got {applied}"

        # Verify all entities exist
        note = db.get_note("bbbb0000000000000000000000000001")
        assert note is not None, "Note should exist"

        audio = db.get_audio_file("cccc0000000000000000000000000001")
        assert audio is not None, "Audio file should exist"

        attachments = db.get_attachments_for_note("bbbb0000000000000000000000000001")
        assert len(attachments) == 1, "Note should have one attachment"

    def test_apply_sync_changes_handles_note_tag_before_tag(
        self, tmp_path: Path
    ) -> None:
        """Test that note_tag can sync even if it comes before the tag."""
        from core.database import Database, set_local_device_id
        from core.sync import SyncChange, apply_sync_changes

        set_local_device_id("00000000000070008000000000000001")
        db = Database(tmp_path / "notes.db")

        # Wrong order: note_tag, then note, then tag
        # Note: note_tag entity_id format is "note_id:tag_id"
        note_id = "eeee0000000000000000000000000001"
        tag_id = "ffff0000000000000000000000000001"
        changes = [
            SyncChange(
                entity_type="note_tag",
                entity_id=f"{note_id}:{tag_id}",
                operation="create",
                data={
                    "note_id": note_id,
                    "tag_id": tag_id,
                    "created_at": "2025-01-01 10:00:00",
                },
                timestamp="2025-01-01 10:00:03",
                device_id="00000000000070008000000000000002",
            ),
            SyncChange(
                entity_type="note",
                entity_id=note_id,
                operation="create",
                data={
                    "id": note_id,
                    "created_at": "2025-01-01 10:00:00",
                    "content": "Tagged note",
                },
                timestamp="2025-01-01 10:00:01",
                device_id="00000000000070008000000000000002",
            ),
            SyncChange(
                entity_type="tag",
                entity_id=tag_id,
                operation="create",
                data={
                    "id": tag_id,
                    "name": "important",
                    "created_at": "2025-01-01 10:00:00",
                },
                timestamp="2025-01-01 10:00:02",
                device_id="00000000000070008000000000000002",
            ),
        ]

        applied, conflicts, errors = apply_sync_changes(
            db, changes, "00000000000070008000000000000002", "TestPeer"
        )

        assert len(errors) == 0, f"Expected no errors, got: {errors}"
        assert applied == 3

        # Verify note has the tag
        note = db.get_note(note_id)
        assert note is not None
        assert "important" in (note.get("tag_names") or "")

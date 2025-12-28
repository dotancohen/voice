"""Sync tests for AudioFile and NoteAttachment entities.

Tests sync operations including:
- Syncing audio file metadata between devices
- Syncing note attachments
- Conflict detection and handling
- Edge cases during sync
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.database import Database, set_local_device_id


# Device IDs for testing
DEVICE_A = "00000000000070008000000000000001"
DEVICE_B = "00000000000070008000000000000002"


@pytest.fixture
def device_a_db(tmp_path: Path) -> Database:
    """Create database for device A."""
    set_local_device_id(DEVICE_A)
    db_path = tmp_path / "device_a.db"
    db = Database(db_path)
    return db


@pytest.fixture
def device_b_db(tmp_path: Path) -> Database:
    """Create database for device B."""
    set_local_device_id(DEVICE_B)
    db_path = tmp_path / "device_b.db"
    db = Database(db_path)
    return db


class TestAudioFileSyncBasic:
    """Test basic audio file sync operations."""

    def test_sync_audio_file_to_new_device(
        self, device_a_db: Database, device_b_db: Database
    ) -> None:
        """Test syncing an audio file from device A to device B."""
        # Create audio file on device A
        set_local_device_id(DEVICE_A)
        audio_id = device_a_db.create_audio_file(
            "recording.mp3",
            file_created_at="2024-06-15 10:30:00"
        )

        # Get raw data for sync
        raw = device_a_db.get_audio_file_raw(audio_id)
        assert raw is not None

        # Apply to device B
        set_local_device_id(DEVICE_B)
        # apply_sync_audio_file returns None on success (no exception raised)
        device_b_db.apply_sync_audio_file(
            raw["id"],
            raw["imported_at"],
            raw["filename"],
            raw.get("file_created_at"),
            raw.get("summary"),
            raw.get("modified_at"),
            raw.get("deleted_at"),
        )

        # Verify on device B
        audio_file = device_b_db.get_audio_file(audio_id)
        assert audio_file is not None
        assert audio_file["filename"] == "recording.mp3"

    def test_sync_audio_file_with_summary(
        self, device_a_db: Database, device_b_db: Database
    ) -> None:
        """Test syncing an audio file with summary."""
        set_local_device_id(DEVICE_A)
        audio_id = device_a_db.create_audio_file("recording.mp3")
        device_a_db.update_audio_file_summary(audio_id, "Meeting notes summary")

        raw = device_a_db.get_audio_file_raw(audio_id)

        set_local_device_id(DEVICE_B)
        device_b_db.apply_sync_audio_file(
            raw["id"],
            raw["imported_at"],
            raw["filename"],
            raw.get("file_created_at"),
            raw.get("summary"),
            raw.get("modified_at"),
            raw.get("deleted_at"),
        )

        audio_file = device_b_db.get_audio_file(audio_id)
        assert audio_file["summary"] == "Meeting notes summary"

    def test_sync_deleted_audio_file(
        self, device_a_db: Database, device_b_db: Database
    ) -> None:
        """Test syncing a deleted audio file."""
        set_local_device_id(DEVICE_A)
        audio_id = device_a_db.create_audio_file("recording.mp3")
        device_a_db.delete_audio_file(audio_id)

        raw = device_a_db.get_audio_file_raw(audio_id)
        assert raw["deleted_at"] is not None

        set_local_device_id(DEVICE_B)
        device_b_db.apply_sync_audio_file(
            raw["id"],
            raw["imported_at"],
            raw["filename"],
            raw.get("file_created_at"),
            raw.get("summary"),
            raw.get("modified_at"),
            raw.get("deleted_at"),
        )

        # The audio file should exist but be marked as deleted
        audio_file = device_b_db.get_audio_file(audio_id)
        assert audio_file is not None
        assert audio_file["deleted_at"] is not None


class TestNoteAttachmentSyncBasic:
    """Test basic note attachment sync operations."""

    def test_sync_note_attachment(
        self, device_a_db: Database, device_b_db: Database
    ) -> None:
        """Test syncing a note attachment from device A to device B."""
        set_local_device_id(DEVICE_A)

        # Create note and audio file on device A
        note_id = device_a_db.create_note("Test note")
        audio_id = device_a_db.create_audio_file("recording.mp3")
        assoc_id = device_a_db.attach_to_note(note_id, audio_id, "audio_file")

        # Get raw data for sync
        raw_note = device_a_db.get_note_raw(note_id)
        raw_audio = device_a_db.get_audio_file_raw(audio_id)
        raw_attachment = device_a_db.get_note_attachment_raw(assoc_id)

        assert raw_attachment is not None

        # Apply to device B (note and audio first)
        set_local_device_id(DEVICE_B)

        device_b_db.apply_sync_note(
            raw_note["id"],
            raw_note["created_at"],
            raw_note["content"],
            raw_note.get("modified_at"),
            raw_note.get("deleted_at"),
        )

        device_b_db.apply_sync_audio_file(
            raw_audio["id"],
            raw_audio["imported_at"],
            raw_audio["filename"],
            raw_audio.get("file_created_at"),
            raw_audio.get("summary"),
            raw_audio.get("modified_at"),
            raw_audio.get("deleted_at"),
        )

        # Apply the attachment
        device_b_db.apply_sync_note_attachment(
            raw_attachment["id"],
            raw_attachment["note_id"],
            raw_attachment["attachment_id"],
            raw_attachment["attachment_type"],
            raw_attachment["created_at"],
            raw_attachment.get("modified_at"),
            raw_attachment.get("deleted_at"),
        )

        # Verify attachment exists on device B
        attachments = device_b_db.get_attachments_for_note(note_id)
        assert len(attachments) == 1
        assert attachments[0]["attachment_id"] == audio_id

    def test_sync_detached_attachment(
        self, device_a_db: Database, device_b_db: Database
    ) -> None:
        """Test syncing a detached (soft-deleted) attachment."""
        set_local_device_id(DEVICE_A)

        note_id = device_a_db.create_note("Test note")
        audio_id = device_a_db.create_audio_file("recording.mp3")
        assoc_id = device_a_db.attach_to_note(note_id, audio_id, "audio_file")

        # Detach on device A
        device_a_db.detach_from_note(assoc_id)

        # Get raw data
        raw_note = device_a_db.get_note_raw(note_id)
        raw_audio = device_a_db.get_audio_file_raw(audio_id)
        raw_attachment = device_a_db.get_note_attachment_raw(assoc_id)

        assert raw_attachment["deleted_at"] is not None

        # Apply to device B
        set_local_device_id(DEVICE_B)

        device_b_db.apply_sync_note(
            raw_note["id"],
            raw_note["created_at"],
            raw_note["content"],
        )

        device_b_db.apply_sync_audio_file(
            raw_audio["id"],
            raw_audio["imported_at"],
            raw_audio["filename"],
        )

        device_b_db.apply_sync_note_attachment(
            raw_attachment["id"],
            raw_attachment["note_id"],
            raw_attachment["attachment_id"],
            raw_attachment["attachment_type"],
            raw_attachment["created_at"],
            raw_attachment.get("modified_at"),
            raw_attachment.get("deleted_at"),
        )

        # Attachment should not appear in normal query
        attachments = device_b_db.get_attachments_for_note(note_id)
        assert len(attachments) == 0


class TestAudioFileSyncUpdates:
    """Test audio file sync with updates."""

    def test_sync_summary_update(
        self, device_a_db: Database, device_b_db: Database
    ) -> None:
        """Test syncing a summary update."""
        set_local_device_id(DEVICE_A)
        audio_id = device_a_db.create_audio_file("recording.mp3")

        # Sync initial version to device B
        raw1 = device_a_db.get_audio_file_raw(audio_id)
        set_local_device_id(DEVICE_B)
        device_b_db.apply_sync_audio_file(
            raw1["id"],
            raw1["imported_at"],
            raw1["filename"],
        )

        # Update summary on device A
        set_local_device_id(DEVICE_A)
        device_a_db.update_audio_file_summary(audio_id, "Updated summary")

        # Sync update to device B
        raw2 = device_a_db.get_audio_file_raw(audio_id)
        set_local_device_id(DEVICE_B)
        device_b_db.apply_sync_audio_file(
            raw2["id"],
            raw2["imported_at"],
            raw2["filename"],
            raw2.get("file_created_at"),
            raw2.get("summary"),
            raw2.get("modified_at"),
            raw2.get("deleted_at"),
        )

        audio_file = device_b_db.get_audio_file(audio_id)
        assert audio_file["summary"] == "Updated summary"

    def test_sync_delete_after_create(
        self, device_a_db: Database, device_b_db: Database
    ) -> None:
        """Test syncing deletion after initial sync."""
        set_local_device_id(DEVICE_A)
        audio_id = device_a_db.create_audio_file("recording.mp3")

        # Sync initial version
        raw1 = device_a_db.get_audio_file_raw(audio_id)
        set_local_device_id(DEVICE_B)
        device_b_db.apply_sync_audio_file(
            raw1["id"],
            raw1["imported_at"],
            raw1["filename"],
        )

        # Delete on device A
        set_local_device_id(DEVICE_A)
        device_a_db.delete_audio_file(audio_id)

        # Sync deletion
        raw2 = device_a_db.get_audio_file_raw(audio_id)
        set_local_device_id(DEVICE_B)
        device_b_db.apply_sync_audio_file(
            raw2["id"],
            raw2["imported_at"],
            raw2["filename"],
            raw2.get("file_created_at"),
            raw2.get("summary"),
            raw2.get("modified_at"),
            raw2.get("deleted_at"),
        )

        audio_file = device_b_db.get_audio_file(audio_id)
        assert audio_file["deleted_at"] is not None


class TestSyncManyItems:
    """Test syncing many audio files and attachments."""

    def test_sync_many_audio_files(
        self, device_a_db: Database, device_b_db: Database
    ) -> None:
        """Test syncing 50 audio files."""
        set_local_device_id(DEVICE_A)

        # Create 50 audio files on device A
        audio_ids = []
        for i in range(50):
            audio_id = device_a_db.create_audio_file(f"recording_{i}.mp3")
            audio_ids.append(audio_id)

        # Sync all to device B
        set_local_device_id(DEVICE_B)
        for audio_id in audio_ids:
            set_local_device_id(DEVICE_A)
            raw = device_a_db.get_audio_file_raw(audio_id)
            set_local_device_id(DEVICE_B)
            device_b_db.apply_sync_audio_file(
                raw["id"],
                raw["imported_at"],
                raw["filename"],
            )

        # Verify all exist on device B
        for i, audio_id in enumerate(audio_ids):
            audio_file = device_b_db.get_audio_file(audio_id)
            assert audio_file is not None
            assert audio_file["filename"] == f"recording_{i}.mp3"

    def test_sync_note_with_many_attachments(
        self, device_a_db: Database, device_b_db: Database
    ) -> None:
        """Test syncing a note with 20 attachments."""
        set_local_device_id(DEVICE_A)

        note_id = device_a_db.create_note("Note with many attachments")
        assoc_ids = []

        for i in range(20):
            audio_id = device_a_db.create_audio_file(f"attachment_{i}.mp3")
            assoc_id = device_a_db.attach_to_note(note_id, audio_id, "audio_file")
            assoc_ids.append((audio_id, assoc_id))

        # Sync note
        raw_note = device_a_db.get_note_raw(note_id)
        set_local_device_id(DEVICE_B)
        device_b_db.apply_sync_note(
            raw_note["id"],
            raw_note["created_at"],
            raw_note["content"],
        )

        # Sync all audio files and attachments
        for audio_id, assoc_id in assoc_ids:
            set_local_device_id(DEVICE_A)
            raw_audio = device_a_db.get_audio_file_raw(audio_id)
            raw_attach = device_a_db.get_note_attachment_raw(assoc_id)

            set_local_device_id(DEVICE_B)
            device_b_db.apply_sync_audio_file(
                raw_audio["id"],
                raw_audio["imported_at"],
                raw_audio["filename"],
            )
            device_b_db.apply_sync_note_attachment(
                raw_attach["id"],
                raw_attach["note_id"],
                raw_attach["attachment_id"],
                raw_attach["attachment_type"],
                raw_attach["created_at"],
            )

        # Verify all attachments on device B
        audio_files = device_b_db.get_audio_files_for_note(note_id)
        assert len(audio_files) == 20


class TestSyncEdgeCases:
    """Test edge cases in sync operations."""

    def test_sync_unicode_filename(
        self, device_a_db: Database, device_b_db: Database
    ) -> None:
        """Test syncing audio file with Unicode filename."""
        set_local_device_id(DEVICE_A)
        audio_id = device_a_db.create_audio_file("שיר_יפה_🎵.mp3")

        raw = device_a_db.get_audio_file_raw(audio_id)

        set_local_device_id(DEVICE_B)
        device_b_db.apply_sync_audio_file(
            raw["id"],
            raw["imported_at"],
            raw["filename"],
        )

        audio_file = device_b_db.get_audio_file(audio_id)
        assert audio_file["filename"] == "שיר_יפה_🎵.mp3"

    def test_sync_unicode_summary(
        self, device_a_db: Database, device_b_db: Database
    ) -> None:
        """Test syncing audio file with Unicode summary."""
        set_local_device_id(DEVICE_A)
        audio_id = device_a_db.create_audio_file("recording.mp3")
        device_a_db.update_audio_file_summary(audio_id, "תקציר בעברית 音乐摘要")

        raw = device_a_db.get_audio_file_raw(audio_id)

        set_local_device_id(DEVICE_B)
        device_b_db.apply_sync_audio_file(
            raw["id"],
            raw["imported_at"],
            raw["filename"],
            raw.get("file_created_at"),
            raw.get("summary"),
            raw.get("modified_at"),
        )

        audio_file = device_b_db.get_audio_file(audio_id)
        assert audio_file["summary"] == "תקציר בעברית 音乐摘要"

    def test_sync_very_long_summary(
        self, device_a_db: Database, device_b_db: Database
    ) -> None:
        """Test syncing audio file with very long summary."""
        set_local_device_id(DEVICE_A)
        audio_id = device_a_db.create_audio_file("recording.mp3")
        long_summary = "x" * 10000
        device_a_db.update_audio_file_summary(audio_id, long_summary)

        raw = device_a_db.get_audio_file_raw(audio_id)

        set_local_device_id(DEVICE_B)
        device_b_db.apply_sync_audio_file(
            raw["id"],
            raw["imported_at"],
            raw["filename"],
            raw.get("file_created_at"),
            raw.get("summary"),
            raw.get("modified_at"),
        )

        audio_file = device_b_db.get_audio_file(audio_id)
        assert audio_file["summary"] == long_summary

    def test_sync_same_audio_to_multiple_notes_different_devices(
        self, device_a_db: Database, device_b_db: Database
    ) -> None:
        """Test syncing one audio attached to multiple notes."""
        set_local_device_id(DEVICE_A)

        audio_id = device_a_db.create_audio_file("shared.mp3")
        note1_id = device_a_db.create_note("Note 1")
        note2_id = device_a_db.create_note("Note 2")

        assoc1_id = device_a_db.attach_to_note(note1_id, audio_id, "audio_file")
        assoc2_id = device_a_db.attach_to_note(note2_id, audio_id, "audio_file")

        # Sync to device B
        set_local_device_id(DEVICE_B)

        # Sync audio
        raw_audio = device_a_db.get_audio_file_raw(audio_id)
        device_b_db.apply_sync_audio_file(
            raw_audio["id"],
            raw_audio["imported_at"],
            raw_audio["filename"],
        )

        # Sync notes
        for note_id in [note1_id, note2_id]:
            set_local_device_id(DEVICE_A)
            raw_note = device_a_db.get_note_raw(note_id)
            set_local_device_id(DEVICE_B)
            device_b_db.apply_sync_note(
                raw_note["id"],
                raw_note["created_at"],
                raw_note["content"],
            )

        # Sync attachments
        for assoc_id in [assoc1_id, assoc2_id]:
            set_local_device_id(DEVICE_A)
            raw_attach = device_a_db.get_note_attachment_raw(assoc_id)
            set_local_device_id(DEVICE_B)
            device_b_db.apply_sync_note_attachment(
                raw_attach["id"],
                raw_attach["note_id"],
                raw_attach["attachment_id"],
                raw_attach["attachment_type"],
                raw_attach["created_at"],
            )

        # Verify both notes have the audio
        audio_files1 = device_b_db.get_audio_files_for_note(note1_id)
        audio_files2 = device_b_db.get_audio_files_for_note(note2_id)

        assert len(audio_files1) == 1
        assert len(audio_files2) == 1
        assert audio_files1[0]["id"] == audio_id
        assert audio_files2[0]["id"] == audio_id

    def test_sync_reapply_same_data(
        self, device_a_db: Database, device_b_db: Database
    ) -> None:
        """Test applying the same sync data multiple times (idempotency)."""
        set_local_device_id(DEVICE_A)
        audio_id = device_a_db.create_audio_file("recording.mp3")

        raw = device_a_db.get_audio_file_raw(audio_id)

        set_local_device_id(DEVICE_B)

        # Apply same data 3 times - no exception should be raised
        for _ in range(3):
            device_b_db.apply_sync_audio_file(
                raw["id"],
                raw["imported_at"],
                raw["filename"],
            )

        # Should still have exactly one audio file
        audio_file = device_b_db.get_audio_file(audio_id)
        assert audio_file is not None
        assert audio_file["filename"] == "recording.mp3"


class TestGetChangesSince:
    """Test getting changes for sync."""

    def test_get_audio_file_changes(self, device_a_db: Database) -> None:
        """Test that audio file changes appear in get_changes_since."""
        set_local_device_id(DEVICE_A)

        # Create audio file
        audio_id = device_a_db.create_audio_file("recording.mp3")

        # Get changes
        changes = device_a_db.get_changes_since(None, 1000)

        # Should include the audio file
        audio_changes = [
            c for c in changes.get("changes", [])
            if c.get("entity_type") == "audio_file"
        ]
        assert len(audio_changes) >= 1

    def test_get_note_attachment_changes(self, device_a_db: Database) -> None:
        """Test that note attachment changes appear in get_changes_since."""
        set_local_device_id(DEVICE_A)

        note_id = device_a_db.create_note("Test note")
        audio_id = device_a_db.create_audio_file("recording.mp3")
        device_a_db.attach_to_note(note_id, audio_id, "audio_file")

        changes = device_a_db.get_changes_since(None, 1000)

        attachment_changes = [
            c for c in changes.get("changes", [])
            if c.get("entity_type") == "note_attachment"
        ]
        assert len(attachment_changes) >= 1

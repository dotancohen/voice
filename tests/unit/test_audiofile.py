"""Unit tests for AudioFile database operations.

Tests all AudioFile methods in the Database including:
- Creating audio files
- Attaching audio files to notes
- Retrieving audio files
- Updating audio file summary
- Soft deleting audio files
"""

from __future__ import annotations

from datetime import datetime

import pytest

from core.database import Database


class TestCreateAudioFile:
    """Test create_audio_file method."""

    def test_creates_audio_file_with_filename(self, empty_db: Database) -> None:
        """Test creating an audio file with a filename."""
        audio_id = empty_db.create_audio_file("test_recording.mp3")
        assert len(audio_id) == 32  # UUID hex string

        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file is not None
        assert audio_file["filename"] == "test_recording.mp3"
        assert audio_file["imported_at"] is not None

    def test_creates_audio_file_with_file_created_at(self, empty_db: Database) -> None:
        """Test creating an audio file with file_created_at timestamp."""
        file_created = "2024-06-15 10:30:00"
        audio_id = empty_db.create_audio_file("recording.wav", file_created_at=file_created)

        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file is not None
        # Rust returns ISO format with T separator
        assert "2024-06-15" in audio_file["file_created_at"]
        assert "10:30:00" in audio_file["file_created_at"]

    def test_creates_audio_file_without_file_created_at(self, empty_db: Database) -> None:
        """Test creating an audio file without file_created_at."""
        audio_id = empty_db.create_audio_file("recording.flac")

        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file is not None
        assert audio_file["file_created_at"] is None


class TestGetAudioFile:
    """Test get_audio_file method."""

    def test_returns_audio_file_by_id(self, empty_db: Database) -> None:
        """Test retrieving audio file by ID."""
        audio_id = empty_db.create_audio_file("test.mp3")
        audio_file = empty_db.get_audio_file(audio_id)

        assert audio_file is not None
        assert audio_file["id"] == audio_id
        assert audio_file["filename"] == "test.mp3"

    def test_returns_none_for_nonexistent(self, empty_db: Database) -> None:
        """Test None returned for non-existent audio file."""
        fake_id = "00000000000070008000999999999999"
        audio_file = empty_db.get_audio_file(fake_id)
        assert audio_file is None


class TestAttachToNote:
    """Test attach_to_note method."""

    def test_attaches_audio_file_to_note(self, empty_db: Database) -> None:
        """Test attaching an audio file to a note."""
        note_id = empty_db.create_note("Test note")
        audio_id = empty_db.create_audio_file("recording.mp3")

        assoc_id = empty_db.attach_to_note(note_id, audio_id, "audio_file")
        assert len(assoc_id) == 32  # UUID hex string

        # Verify attachment exists
        attachments = empty_db.get_attachments_for_note(note_id)
        assert len(attachments) == 1
        assert attachments[0]["attachment_id"] == audio_id
        assert attachments[0]["attachment_type"] == "audio_file"

    def test_attaches_same_audio_to_multiple_notes(self, empty_db: Database) -> None:
        """Test attaching same audio file to multiple notes."""
        note1_id = empty_db.create_note("Note 1")
        note2_id = empty_db.create_note("Note 2")
        audio_id = empty_db.create_audio_file("shared_recording.mp3")

        assoc1_id = empty_db.attach_to_note(note1_id, audio_id, "audio_file")
        assoc2_id = empty_db.attach_to_note(note2_id, audio_id, "audio_file")

        # Different association IDs
        assert assoc1_id != assoc2_id

        # Both notes have the attachment
        attachments1 = empty_db.get_attachments_for_note(note1_id)
        attachments2 = empty_db.get_attachments_for_note(note2_id)

        assert len(attachments1) == 1
        assert len(attachments2) == 1
        assert attachments1[0]["attachment_id"] == audio_id
        assert attachments2[0]["attachment_id"] == audio_id


class TestDetachFromNote:
    """Test detach_from_note method."""

    def test_detaches_audio_file_from_note(self, empty_db: Database) -> None:
        """Test soft-deleting an attachment."""
        note_id = empty_db.create_note("Test note")
        audio_id = empty_db.create_audio_file("recording.mp3")
        assoc_id = empty_db.attach_to_note(note_id, audio_id, "audio_file")

        result = empty_db.detach_from_note(assoc_id)
        assert result is True

        # Attachment should not appear in list
        attachments = empty_db.get_attachments_for_note(note_id)
        assert len(attachments) == 0

    def test_returns_false_for_nonexistent_attachment(self, empty_db: Database) -> None:
        """Test False returned for non-existent attachment."""
        fake_id = "00000000000070008000999999999999"
        result = empty_db.detach_from_note(fake_id)
        assert result is False


class TestGetAudioFilesForNote:
    """Test get_audio_files_for_note method."""

    def test_returns_audio_files_for_note(self, empty_db: Database) -> None:
        """Test getting all audio files attached to a note."""
        note_id = empty_db.create_note("Test note")
        audio1_id = empty_db.create_audio_file("recording1.mp3")
        audio2_id = empty_db.create_audio_file("recording2.wav")

        empty_db.attach_to_note(note_id, audio1_id, "audio_file")
        empty_db.attach_to_note(note_id, audio2_id, "audio_file")

        audio_files = empty_db.get_audio_files_for_note(note_id)
        assert len(audio_files) == 2

        filenames = {af["filename"] for af in audio_files}
        assert filenames == {"recording1.mp3", "recording2.wav"}

    def test_returns_empty_for_note_without_attachments(self, empty_db: Database) -> None:
        """Test empty list for note without attachments."""
        note_id = empty_db.create_note("Note without attachments")
        audio_files = empty_db.get_audio_files_for_note(note_id)
        assert audio_files == []

    def test_excludes_detached_audio_files(self, empty_db: Database) -> None:
        """Test that detached audio files are excluded."""
        note_id = empty_db.create_note("Test note")
        audio1_id = empty_db.create_audio_file("keep.mp3")
        audio2_id = empty_db.create_audio_file("remove.mp3")

        empty_db.attach_to_note(note_id, audio1_id, "audio_file")
        assoc2_id = empty_db.attach_to_note(note_id, audio2_id, "audio_file")

        # Detach second audio file
        empty_db.detach_from_note(assoc2_id)

        audio_files = empty_db.get_audio_files_for_note(note_id)
        assert len(audio_files) == 1
        assert audio_files[0]["filename"] == "keep.mp3"


class TestUpdateAudioFileSummary:
    """Test update_audio_file_summary method."""

    def test_updates_summary(self, empty_db: Database) -> None:
        """Test updating audio file summary."""
        audio_id = empty_db.create_audio_file("recording.mp3")

        result = empty_db.update_audio_file_summary(audio_id, "Meeting notes summary")
        assert result is True

        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["summary"] == "Meeting notes summary"
        assert audio_file["modified_at"] is not None

    def test_returns_false_for_nonexistent(self, empty_db: Database) -> None:
        """Test False returned for non-existent audio file."""
        fake_id = "00000000000070008000999999999999"
        result = empty_db.update_audio_file_summary(fake_id, "Summary")
        assert result is False


class TestDeleteAudioFile:
    """Test delete_audio_file method."""

    def test_soft_deletes_audio_file(self, empty_db: Database) -> None:
        """Test soft-deleting an audio file."""
        audio_id = empty_db.create_audio_file("recording.mp3")

        result = empty_db.delete_audio_file(audio_id)
        assert result is True

        # Audio file should still exist but have deleted_at set
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file is not None
        assert audio_file["deleted_at"] is not None

    def test_returns_false_for_nonexistent(self, empty_db: Database) -> None:
        """Test False returned for non-existent audio file."""
        fake_id = "00000000000070008000999999999999"
        result = empty_db.delete_audio_file(fake_id)
        assert result is False


class TestGetAttachment:
    """Test get_attachment method."""

    def test_returns_attachment_by_id(self, empty_db: Database) -> None:
        """Test retrieving attachment by association ID."""
        note_id = empty_db.create_note("Test note")
        audio_id = empty_db.create_audio_file("recording.mp3")
        assoc_id = empty_db.attach_to_note(note_id, audio_id, "audio_file")

        attachment = empty_db.get_attachment(assoc_id)
        assert attachment is not None
        assert attachment["id"] == assoc_id
        assert attachment["note_id"] == note_id
        assert attachment["attachment_id"] == audio_id
        assert attachment["attachment_type"] == "audio_file"

    def test_returns_none_for_nonexistent(self, empty_db: Database) -> None:
        """Test None returned for non-existent attachment."""
        fake_id = "00000000000070008000999999999999"
        attachment = empty_db.get_attachment(fake_id)
        assert attachment is None

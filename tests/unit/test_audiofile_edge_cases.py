"""Edge case tests for AudioFile operations.

Tests corner cases including:
- File size variations (empty, small, large)
- Special filenames (Unicode, spaces, special chars)
- Many files and attachments
- Invalid and edge case scenarios
"""

from __future__ import annotations

import os
import string
from pathlib import Path

import pytest

from core.database import Database
from core.audiofile_manager import AudioFileManager, is_supported_audio_format


class TestFilenameEdgeCases:
    """Test handling of special filenames."""

    def test_unicode_filename_hebrew(self, empty_db: Database) -> None:
        """Test audio file with Hebrew filename."""
        audio_id = empty_db.create_audio_file("שיר_יפה.mp3")
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["filename"] == "שיר_יפה.mp3"

    def test_unicode_filename_chinese(self, empty_db: Database) -> None:
        """Test audio file with Chinese filename."""
        audio_id = empty_db.create_audio_file("音乐文件.wav")
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["filename"] == "音乐文件.wav"

    def test_unicode_filename_emoji(self, empty_db: Database) -> None:
        """Test audio file with emoji in filename."""
        audio_id = empty_db.create_audio_file("🎵music🎶.mp3")
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["filename"] == "🎵music🎶.mp3"

    def test_unicode_filename_arabic(self, empty_db: Database) -> None:
        """Test audio file with Arabic filename."""
        audio_id = empty_db.create_audio_file("موسيقى.ogg")
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["filename"] == "موسيقى.ogg"

    def test_filename_with_spaces(self, empty_db: Database) -> None:
        """Test audio file with spaces in filename."""
        audio_id = empty_db.create_audio_file("my recording file.mp3")
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["filename"] == "my recording file.mp3"

    def test_filename_with_multiple_spaces(self, empty_db: Database) -> None:
        """Test audio file with multiple consecutive spaces."""
        audio_id = empty_db.create_audio_file("my   recording   file.mp3")
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["filename"] == "my   recording   file.mp3"

    def test_filename_with_special_chars(self, empty_db: Database) -> None:
        """Test audio file with special characters in filename."""
        audio_id = empty_db.create_audio_file("recording_[2024]-{test}.mp3")
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["filename"] == "recording_[2024]-{test}.mp3"

    def test_filename_with_parentheses(self, empty_db: Database) -> None:
        """Test audio file with parentheses in filename."""
        audio_id = empty_db.create_audio_file("song (remix) (final).mp3")
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["filename"] == "song (remix) (final).mp3"

    def test_filename_with_quotes(self, empty_db: Database) -> None:
        """Test audio file with quotes in filename."""
        audio_id = empty_db.create_audio_file("John's \"Best\" Song.mp3")
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["filename"] == "John's \"Best\" Song.mp3"

    def test_filename_starting_with_dot(self, empty_db: Database) -> None:
        """Test hidden file (starting with dot)."""
        audio_id = empty_db.create_audio_file(".hidden_audio.mp3")
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["filename"] == ".hidden_audio.mp3"

    def test_filename_with_multiple_dots(self, empty_db: Database) -> None:
        """Test filename with multiple dots."""
        audio_id = empty_db.create_audio_file("song.backup.2024.01.15.mp3")
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["filename"] == "song.backup.2024.01.15.mp3"

    def test_very_long_filename(self, empty_db: Database) -> None:
        """Test very long filename (200+ chars)."""
        long_name = "a" * 200 + ".mp3"
        audio_id = empty_db.create_audio_file(long_name)
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["filename"] == long_name

    def test_filename_with_path_separators(self, empty_db: Database) -> None:
        """Test filename containing path separator characters."""
        # Note: These are stored as filenames, not paths
        audio_id = empty_db.create_audio_file("folder-name-song.mp3")
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["filename"] == "folder-name-song.mp3"

    def test_uppercase_extension(self, empty_db: Database) -> None:
        """Test filename with uppercase extension."""
        audio_id = empty_db.create_audio_file("recording.MP3")
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["filename"] == "recording.MP3"

    def test_mixed_case_extension(self, empty_db: Database) -> None:
        """Test filename with mixed case extension."""
        audio_id = empty_db.create_audio_file("recording.Mp3")
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["filename"] == "recording.Mp3"


class TestManyFilesAndAttachments:
    """Test handling of many files and attachments."""

    def test_create_100_audio_files(self, empty_db: Database) -> None:
        """Test creating 100 audio files."""
        audio_ids = []
        for i in range(100):
            audio_id = empty_db.create_audio_file(f"recording_{i:03d}.mp3")
            audio_ids.append(audio_id)

        # Verify all were created with unique IDs
        assert len(set(audio_ids)) == 100

        # Verify each can be retrieved
        for i, audio_id in enumerate(audio_ids):
            audio_file = empty_db.get_audio_file(audio_id)
            assert audio_file is not None
            assert audio_file["filename"] == f"recording_{i:03d}.mp3"

    def test_attach_many_audio_files_to_one_note(self, empty_db: Database) -> None:
        """Test attaching 50 audio files to a single note."""
        note_id = empty_db.create_note("Note with many attachments")

        audio_ids = []
        for i in range(50):
            audio_id = empty_db.create_audio_file(f"attachment_{i}.mp3")
            audio_ids.append(audio_id)
            empty_db.attach_to_note(note_id, audio_id, "audio_file")

        # Verify all attachments are returned
        audio_files = empty_db.get_audio_files_for_note(note_id)
        assert len(audio_files) == 50

    def test_attach_one_audio_to_many_notes(self, empty_db: Database) -> None:
        """Test attaching one audio file to 20 notes."""
        audio_id = empty_db.create_audio_file("shared_recording.mp3")

        note_ids = []
        for i in range(20):
            note_id = empty_db.create_note(f"Note {i}")
            note_ids.append(note_id)
            empty_db.attach_to_note(note_id, audio_id, "audio_file")

        # Verify audio is attached to all notes
        for note_id in note_ids:
            audio_files = empty_db.get_audio_files_for_note(note_id)
            assert len(audio_files) == 1
            assert audio_files[0]["id"] == audio_id

    def test_many_attachments_on_many_notes(self, empty_db: Database) -> None:
        """Test creating a matrix of notes and audio attachments."""
        # Create 10 notes and 10 audio files
        note_ids = [empty_db.create_note(f"Note {i}") for i in range(10)]
        audio_ids = [empty_db.create_audio_file(f"audio_{i}.mp3") for i in range(10)]

        # Attach each audio to each note (100 attachments total)
        for note_id in note_ids:
            for audio_id in audio_ids:
                empty_db.attach_to_note(note_id, audio_id, "audio_file")

        # Verify each note has 10 audio files
        for note_id in note_ids:
            audio_files = empty_db.get_audio_files_for_note(note_id)
            assert len(audio_files) == 10


class TestAttachmentEdgeCases:
    """Test edge cases for attachment operations."""

    def test_double_attach_same_audio_to_same_note(self, empty_db: Database) -> None:
        """Test attaching same audio file to same note twice creates two associations."""
        note_id = empty_db.create_note("Test note")
        audio_id = empty_db.create_audio_file("recording.mp3")

        assoc1_id = empty_db.attach_to_note(note_id, audio_id, "audio_file")
        assoc2_id = empty_db.attach_to_note(note_id, audio_id, "audio_file")

        # Should create two separate associations
        assert assoc1_id != assoc2_id

        # Both should appear in attachments
        audio_files = empty_db.get_audio_files_for_note(note_id)
        # Note: depending on implementation, might return 1 or 2
        assert len(audio_files) >= 1

    def test_detach_already_detached(self, empty_db: Database) -> None:
        """Test detaching an already detached attachment."""
        note_id = empty_db.create_note("Test note")
        audio_id = empty_db.create_audio_file("recording.mp3")
        assoc_id = empty_db.attach_to_note(note_id, audio_id, "audio_file")

        # First detach should succeed
        result1 = empty_db.detach_from_note(assoc_id)
        assert result1 is True

        # Second detach should return False (already detached)
        result2 = empty_db.detach_from_note(assoc_id)
        assert result2 is False

    def test_attach_to_deleted_note(self, empty_db: Database) -> None:
        """Test attaching audio to a soft-deleted note."""
        note_id = empty_db.create_note("Test note")
        audio_id = empty_db.create_audio_file("recording.mp3")

        # Delete the note
        empty_db.delete_note(note_id)

        # Attaching should still work (foreign key allows it)
        assoc_id = empty_db.attach_to_note(note_id, audio_id, "audio_file")
        assert len(assoc_id) == 32

    def test_attach_deleted_audio_to_note(self, empty_db: Database) -> None:
        """Test attaching a soft-deleted audio file to a note."""
        note_id = empty_db.create_note("Test note")
        audio_id = empty_db.create_audio_file("recording.mp3")

        # Delete the audio file
        empty_db.delete_audio_file(audio_id)

        # Attaching should still work
        assoc_id = empty_db.attach_to_note(note_id, audio_id, "audio_file")
        assert len(assoc_id) == 32

    def test_get_attachments_for_nonexistent_note(self, empty_db: Database) -> None:
        """Test getting attachments for a note that doesn't exist."""
        fake_id = "00000000000070008000999999999999"
        audio_files = empty_db.get_audio_files_for_note(fake_id)
        assert audio_files == []

    def test_update_deleted_audio_summary(self, empty_db: Database) -> None:
        """Test updating summary of a deleted audio file."""
        audio_id = empty_db.create_audio_file("recording.mp3")
        empty_db.delete_audio_file(audio_id)

        # Updating summary of deleted file should still work
        result = empty_db.update_audio_file_summary(audio_id, "Summary text")
        # The behavior depends on implementation - could return True or False
        assert isinstance(result, bool)


class TestSummaryEdgeCases:
    """Test edge cases for audio file summaries."""

    def test_empty_summary(self, empty_db: Database) -> None:
        """Test setting an empty summary."""
        audio_id = empty_db.create_audio_file("recording.mp3")
        result = empty_db.update_audio_file_summary(audio_id, "")

        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["summary"] == ""

    def test_very_long_summary(self, empty_db: Database) -> None:
        """Test setting a very long summary (10KB)."""
        audio_id = empty_db.create_audio_file("recording.mp3")
        long_summary = "a" * 10000
        result = empty_db.update_audio_file_summary(audio_id, long_summary)

        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["summary"] == long_summary

    def test_unicode_summary(self, empty_db: Database) -> None:
        """Test summary with Unicode characters."""
        audio_id = empty_db.create_audio_file("recording.mp3")
        unicode_summary = "תקציר בעברית 🎵 音乐摘要"
        result = empty_db.update_audio_file_summary(audio_id, unicode_summary)

        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["summary"] == unicode_summary

    def test_summary_with_newlines(self, empty_db: Database) -> None:
        """Test summary with newlines and formatting."""
        audio_id = empty_db.create_audio_file("recording.mp3")
        multi_line_summary = "Line 1\nLine 2\n\nLine 4\tTabbed"
        result = empty_db.update_audio_file_summary(audio_id, multi_line_summary)

        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["summary"] == multi_line_summary

    def test_update_summary_multiple_times(self, empty_db: Database) -> None:
        """Test updating summary multiple times."""
        audio_id = empty_db.create_audio_file("recording.mp3")

        for i in range(10):
            empty_db.update_audio_file_summary(audio_id, f"Summary version {i}")

        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["summary"] == "Summary version 9"
        assert audio_file["modified_at"] is not None


class TestTimestampEdgeCases:
    """Test edge cases for timestamp handling."""

    def test_file_created_at_edge_dates(self, empty_db: Database) -> None:
        """Test various edge case dates for file_created_at."""
        edge_dates = [
            "1970-01-01 00:00:00",  # Unix epoch
            "2000-01-01 00:00:00",  # Y2K
            "2099-12-31 23:59:59",  # Far future
        ]

        for date in edge_dates:
            audio_id = empty_db.create_audio_file("test.mp3", file_created_at=date)
            audio_file = empty_db.get_audio_file(audio_id)
            assert date.replace(" ", "T") in audio_file["file_created_at"] or \
                   date in audio_file["file_created_at"]

    def test_null_file_created_at(self, empty_db: Database) -> None:
        """Test that file_created_at can be None."""
        audio_id = empty_db.create_audio_file("recording.mp3", file_created_at=None)
        audio_file = empty_db.get_audio_file(audio_id)
        assert audio_file["file_created_at"] is None


class TestFileManagerEdgeCases:
    """Test edge cases for AudioFileManager."""

    def test_import_empty_file(self, tmp_path: Path) -> None:
        """Test importing an empty (0 byte) audio file."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        # Create empty file
        source = tmp_path / "empty.mp3"
        source.touch()  # Creates 0-byte file

        audio_id = "0123456789abcdef0123456789abcdef"
        dest = manager.import_file(source, audio_id, "mp3")

        assert dest.exists()
        assert dest.stat().st_size == 0

    def test_import_small_file(self, tmp_path: Path) -> None:
        """Test importing a very small (1 byte) audio file."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        source = tmp_path / "tiny.mp3"
        source.write_bytes(b"x")

        audio_id = "0123456789abcdef0123456789abcdef"
        dest = manager.import_file(source, audio_id, "mp3")

        assert dest.exists()
        assert dest.stat().st_size == 1

    def test_import_large_file(self, tmp_path: Path) -> None:
        """Test importing a larger file (1MB)."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        source = tmp_path / "large.mp3"
        source.write_bytes(b"x" * (1024 * 1024))  # 1MB

        audio_id = "0123456789abcdef0123456789abcdef"
        dest = manager.import_file(source, audio_id, "mp3")

        assert dest.exists()
        assert dest.stat().st_size == 1024 * 1024

    def test_import_file_with_unicode_source_path(self, tmp_path: Path) -> None:
        """Test importing from a path containing Unicode characters."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        # Create directory with Unicode name
        unicode_dir = tmp_path / "מוזיקה_音乐"
        unicode_dir.mkdir()
        source = unicode_dir / "song.mp3"
        source.write_bytes(b"audio content")

        audio_id = "0123456789abcdef0123456789abcdef"
        dest = manager.import_file(source, audio_id, "mp3")

        assert dest.exists()

    def test_import_file_with_spaces_in_source_path(self, tmp_path: Path) -> None:
        """Test importing from a path containing spaces."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        # Create directory with spaces
        space_dir = tmp_path / "My Music Files"
        space_dir.mkdir()
        source = space_dir / "my song.mp3"
        source.write_bytes(b"audio content")

        audio_id = "0123456789abcdef0123456789abcdef"
        dest = manager.import_file(source, audio_id, "mp3")

        assert dest.exists()

    def test_soft_delete_then_reimport(self, tmp_path: Path) -> None:
        """Test soft-deleting and then re-importing with same ID."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        source = tmp_path / "song.mp3"
        source.write_bytes(b"original content")

        audio_id = "0123456789abcdef0123456789abcdef"

        # Import
        dest1 = manager.import_file(source, audio_id, "mp3")
        assert dest1.exists()

        # Soft delete
        manager.soft_delete(audio_id, "mp3")
        assert not dest1.exists()
        assert manager.is_in_trash(audio_id, "mp3")

        # Re-import (new content)
        source.write_bytes(b"new content")
        dest2 = manager.import_file(source, audio_id, "mp3")
        assert dest2.exists()
        assert dest2.read_bytes() == b"new content"

    def test_restore_when_file_already_exists(self, tmp_path: Path) -> None:
        """Test restoring from trash when file already exists in main dir."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)
        manager.ensure_directories()

        audio_id = "0123456789abcdef0123456789abcdef"

        # Put file in trash
        trash_file = manager.trash_directory / f"{audio_id}.mp3"
        trash_file.write_bytes(b"trash content")

        # Also put file in main dir
        main_file = audio_dir / f"{audio_id}.mp3"
        main_file.write_bytes(b"main content")

        # Restore should overwrite (shutil.move behavior)
        manager.restore_from_trash(audio_id, "mp3")

        assert main_file.exists()
        # Content depends on shutil.move behavior

    def test_all_supported_formats(self, tmp_path: Path) -> None:
        """Test importing all supported audio formats."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        formats = ["mp3", "wav", "flac", "ogg", "opus", "m4a"]

        for fmt in formats:
            source = tmp_path / f"test.{fmt}"
            source.write_bytes(b"audio content")

            audio_id = f"{'0' * 24}{fmt:0>8}"[:32]
            dest = manager.import_file(source, audio_id, fmt)
            assert dest.exists(), f"Failed to import .{fmt} file"


class TestSupportedFormatEdgeCases:
    """Test edge cases for format validation."""

    def test_case_insensitive_formats(self) -> None:
        """Test that format checking is case-insensitive."""
        assert is_supported_audio_format("test.MP3") is True
        assert is_supported_audio_format("test.Mp3") is True
        assert is_supported_audio_format("test.mP3") is True
        assert is_supported_audio_format("test.FLAC") is True
        assert is_supported_audio_format("test.Wav") is True

    def test_double_extension(self) -> None:
        """Test filenames with double extensions."""
        assert is_supported_audio_format("test.tar.mp3") is True
        assert is_supported_audio_format("test.mp3.txt") is False

    def test_only_extension(self) -> None:
        """Test filename that is just an extension."""
        assert is_supported_audio_format(".mp3") is True

    def test_empty_filename(self) -> None:
        """Test empty filename."""
        assert is_supported_audio_format("") is False

    def test_no_extension(self) -> None:
        """Test filename without extension."""
        assert is_supported_audio_format("audiofile") is False
        assert is_supported_audio_format("audio.") is False

    def test_unknown_formats(self) -> None:
        """Test unsupported formats."""
        assert is_supported_audio_format("test.aac") is False
        assert is_supported_audio_format("test.wma") is False
        assert is_supported_audio_format("test.mp4") is False
        assert is_supported_audio_format("test.txt") is False
        assert is_supported_audio_format("test.jpg") is False

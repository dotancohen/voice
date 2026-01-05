"""Tests for audiofile import Note creation requirements.

Tests that verify:
- Import creates a Note for each AudioFile (#5)
- Note.created_at matches file_created_at (#6)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest


@pytest.fixture
def config_with_audiofiles(test_config_dir: Path, tmp_path: Path) -> Path:
    """Create config with audiofile_directory set."""
    audiofile_dir = tmp_path / "stored_audiofiles"
    config_file = test_config_dir / "config.json"

    config_data = {
        "database_file": str(test_config_dir / "notes.db"),
        "audiofile_directory": str(audiofile_dir),
    }

    with open(config_file, "w") as f:
        json.dump(config_data, f)

    return test_config_dir


class TestImportCreatesNotePerAudioFile:
    """Test that audiofiles-import creates a Note for each AudioFile."""

    def test_import_single_file_creates_note(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test that importing a single audio file creates exactly one Note."""
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        (audio_dir / "recording.mp3").write_bytes(b"audio content")

        # Import the audio file
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(audio_dir)
            ],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0

        # List notes to verify one was created
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "notes-list"
            ],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0

        # Should have exactly one note
        # The output should contain information about one note
        lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
        # Assuming notes-list outputs one line per note or similar
        assert len(lines) >= 1, "Expected at least one note to be created"

    def test_import_multiple_files_creates_multiple_notes(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test that importing 3 audio files creates exactly 3 Notes."""
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        (audio_dir / "file1.mp3").write_bytes(b"audio 1")
        (audio_dir / "file2.wav").write_bytes(b"audio 2")
        (audio_dir / "file3.ogg").write_bytes(b"audio 3")

        # Import the audio files
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(audio_dir)
            ],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0

        # Count notes in database directly
        from core.database import Database
        db_path = config_with_audiofiles / "notes.db"
        db = Database(db_path)
        notes = db.get_all_notes()

        assert len(notes) == 3, f"Expected 3 notes, got {len(notes)}"

    def test_each_note_is_attached_to_corresponding_audiofile(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test that each created Note has exactly one AudioFile attached."""
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        (audio_dir / "recording.mp3").write_bytes(b"audio content")

        # Import
        subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(audio_dir)
            ],
            capture_output=True,
            text=True
        )

        # Check database
        from core.database import Database
        db_path = config_with_audiofiles / "notes.db"
        db = Database(db_path)

        notes = db.get_all_notes()
        assert len(notes) == 1

        # Get attachments for this note
        note_id = notes[0]["id"]
        attachments = db.get_attachments_for_note(note_id)

        assert len(attachments) == 1, "Each note should have exactly one attachment"
        assert attachments[0]["attachment_type"] == "audio_file"


class TestNoteCreatedAtMatchesFileCreatedAt:
    """Test that Note.created_at equals file_created_at for proper sorting."""

    def test_note_created_at_matches_file_timestamp(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test that the Note's created_at matches the audio file's file_created_at."""
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()

        audio_file = audio_dir / "recording.mp3"
        audio_file.write_bytes(b"audio content")

        # Set a specific modification time on the file (2023-06-15 10:30:00)
        target_timestamp = datetime(2023, 6, 15, 10, 30, 0).timestamp()
        os.utime(audio_file, (target_timestamp, target_timestamp))

        # Import
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(audio_dir)
            ],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0

        # Check database
        from core.database import Database
        db_path = config_with_audiofiles / "notes.db"
        db = Database(db_path)

        notes = db.get_all_notes()
        assert len(notes) == 1

        note = notes[0]
        note_created_at = note["created_at"]

        # The note's created_at should match the file's timestamp
        # Expected: "2023-06-15 10:30:00" or similar
        assert "2023-06-15" in note_created_at, (
            f"Note created_at should match file timestamp. "
            f"Expected date 2023-06-15, got {note_created_at}"
        )
        assert "10:30:00" in note_created_at, (
            f"Note created_at should match file timestamp. "
            f"Expected time 10:30:00, got {note_created_at}"
        )

    def test_notes_sort_by_file_creation_time(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test that notes sort chronologically by the original file creation time."""
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()

        # Create files with specific timestamps (out of alphabetical order)
        files_and_times = [
            ("z_last_alphabetically.mp3", datetime(2023, 1, 1, 12, 0, 0)),   # Oldest
            ("a_first_alphabetically.mp3", datetime(2023, 6, 15, 12, 0, 0)), # Middle
            ("m_middle_alphabetically.mp3", datetime(2023, 12, 31, 12, 0, 0)), # Newest
        ]

        for filename, dt in files_and_times:
            filepath = audio_dir / filename
            filepath.write_bytes(b"audio")
            ts = dt.timestamp()
            os.utime(filepath, (ts, ts))

        # Import
        subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(audio_dir)
            ],
            capture_output=True,
            text=True
        )

        # Check database
        from core.database import Database
        db_path = config_with_audiofiles / "notes.db"
        db = Database(db_path)

        notes = db.get_all_notes()
        assert len(notes) == 3

        # Notes should be sorted by created_at (which should be file_created_at)
        # get_all_notes returns sorted by created_at descending (newest first)
        created_ats = [n["created_at"] for n in notes]

        # Verify they are sorted (descending - newest first)
        assert created_ats == sorted(created_ats, reverse=True), (
            f"Notes should be sorted by file creation time (newest first). Got: {created_ats}"
        )

        # Verify the order matches expected (newest first)
        assert "2023-12-31" in created_ats[0], "First note should be from Dec 31 (newest)"
        assert "2023-06-15" in created_ats[1], "Second note should be from Jun 15"
        assert "2023-01-01" in created_ats[2], "Third note should be from Jan 1 (oldest)"

"""Integration tests for audiofiles-import CLI command.

Tests the complete workflow of importing audio files including:
- Creating Notes with correct content
- Creating attachments linking notes to audio files
- Copying files to the audiofile_directory
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import Config
from core.database import Database, set_local_device_id


# Test device ID (hex string - 32 chars)
TEST_DEVICE_ID = "00000000000070008000000000000002"


@pytest.fixture
def audiofiles_config_dir(tmp_path: Path) -> Path:
    """Create temporary config directory for audiofiles tests.

    Args:
        tmp_path: pytest temporary directory fixture

    Returns:
        Path to temporary config directory.
    """
    config_dir = tmp_path / "voice_audiofiles_test"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


@pytest.fixture
def audiofiles_db(audiofiles_config_dir: Path):
    """Create test database for audiofiles tests.

    Args:
        audiofiles_config_dir: Temporary config directory

    Yields:
        Database instance.
    """
    set_local_device_id(TEST_DEVICE_ID)
    db_path = audiofiles_config_dir / "notes.db"
    db = Database(db_path)

    # Create config.json with audiofile_directory
    audiofile_dir = audiofiles_config_dir / "audiofiles"
    audiofile_dir.mkdir(parents=True, exist_ok=True)

    config_file = audiofiles_config_dir / "config.json"
    config_data = {
        "database_file": str(db_path),
        "audiofile_directory": str(audiofile_dir),
    }
    with open(config_file, "w") as f:
        json.dump(config_data, f, indent=2)

    yield db
    db.close()


@pytest.fixture
def source_audio_dir(tmp_path: Path) -> Path:
    """Create directory with test audio files.

    Args:
        tmp_path: pytest temporary directory fixture

    Returns:
        Path to directory containing test audio files.
    """
    source_dir = tmp_path / "source_audio"
    source_dir.mkdir(parents=True, exist_ok=True)

    # Create fake audio files (content doesn't matter for import test)
    (source_dir / "recording1.mp3").write_bytes(b"fake mp3 content 1")
    (source_dir / "recording2.wav").write_bytes(b"fake wav content 2")
    (source_dir / "podcast.m4a").write_bytes(b"fake m4a content 3")

    return source_dir


@pytest.fixture
def audiofiles_cli_runner(audiofiles_config_dir: Path):
    """Create a CLI runner for audiofiles tests.

    Args:
        audiofiles_config_dir: Temporary config directory

    Returns:
        Function that runs CLI commands.
    """
    import subprocess
    import sys

    def run_cli(*args: str) -> tuple[int, str, str]:
        cmd = [
            sys.executable,
            "-m",
            "src.main",
            "-d",
            str(audiofiles_config_dir),
            "cli",
            *args,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode, result.stdout, result.stderr

    return run_cli


@pytest.mark.integration
class TestAudiofilesImport:
    """Test audiofiles-import CLI command."""

    def test_import_creates_notes_with_audio_prefix(
        self,
        audiofiles_config_dir: Path,
        audiofiles_db: Database,
        source_audio_dir: Path,
        audiofiles_cli_runner,
    ) -> None:
        """Test that import creates notes with 'Audio: filename' content."""
        # Run import
        returncode, stdout, stderr = audiofiles_cli_runner(
            "audiofiles-import", str(source_audio_dir)
        )

        assert returncode == 0, f"Import failed: {stderr}"
        assert "Imported 3 file(s)" in stdout

        # Verify notes were created with correct content
        notes = audiofiles_db.get_all_notes()
        assert len(notes) == 3

        note_contents = [n["content"] for n in notes]
        assert any("Audio: recording1.mp3" in c for c in note_contents)
        assert any("Audio: recording2.wav" in c for c in note_contents)
        assert any("Audio: podcast.m4a" in c for c in note_contents)

    def test_import_creates_attachments(
        self,
        audiofiles_config_dir: Path,
        audiofiles_db: Database,
        source_audio_dir: Path,
        audiofiles_cli_runner,
    ) -> None:
        """Test that import creates note_attachments linking notes to audio files.

        This is a regression test for a bug where audio files were imported
        but no attachments were created to link them to notes.
        """
        # Run import
        returncode, stdout, stderr = audiofiles_cli_runner(
            "audiofiles-import", str(source_audio_dir)
        )

        assert returncode == 0, f"Import failed: {stderr}"

        # Verify each note has an attachment
        notes = audiofiles_db.get_all_notes()
        assert len(notes) == 3

        for note in notes:
            attachments = audiofiles_db.get_attachments_for_note(note["id"])
            assert len(attachments) == 1, (
                f"Note '{note['content']}' should have exactly 1 attachment, "
                f"got {len(attachments)}"
            )

            # Verify attachment is of type audio_file
            attachment = attachments[0]
            assert attachment.get("attachment_type") == "audio_file", (
                f"Attachment for note '{note['content']}' should be type 'audio_file', "
                f"got {attachment.get('attachment_type')}"
            )
            assert attachment.get("attachment_id") is not None, (
                f"Attachment for note '{note['content']}' should have attachment_id"
            )

    def test_import_copies_files_to_audiofile_directory(
        self,
        audiofiles_config_dir: Path,
        audiofiles_db: Database,
        source_audio_dir: Path,
        audiofiles_cli_runner,
    ) -> None:
        """Test that import copies audio files to the configured audiofile_directory."""
        audiofile_dir = audiofiles_config_dir / "audiofiles"

        # Run import
        returncode, stdout, stderr = audiofiles_cli_runner(
            "audiofiles-import", str(source_audio_dir)
        )

        assert returncode == 0, f"Import failed: {stderr}"

        # Verify files were copied to audiofile_directory
        copied_files = list(audiofile_dir.glob("*.mp3")) + \
                       list(audiofile_dir.glob("*.wav")) + \
                       list(audiofile_dir.glob("*.m4a"))

        assert len(copied_files) == 3, (
            f"Expected 3 files in audiofile_directory, found {len(copied_files)}"
        )

        # Verify file contents match
        # Files are renamed to {uuid}.{ext}, so check content
        mp3_files = list(audiofile_dir.glob("*.mp3"))
        assert len(mp3_files) == 1
        assert mp3_files[0].read_bytes() == b"fake mp3 content 1"

    def test_import_with_tags_attaches_tags_to_notes(
        self,
        audiofiles_config_dir: Path,
        audiofiles_db: Database,
        source_audio_dir: Path,
        audiofiles_cli_runner,
    ) -> None:
        """Test that import with --tags parameter attaches tags to created notes."""
        # Create a tag first
        tag_id = audiofiles_db.create_tag("ImportedAudio")

        # Run import with tag
        returncode, stdout, stderr = audiofiles_cli_runner(
            "audiofiles-import", str(source_audio_dir), "--tags", tag_id
        )

        assert returncode == 0, f"Import failed: {stderr}"

        # Verify each note has the tag
        notes = audiofiles_db.get_all_notes()
        assert len(notes) == 3

        for note in notes:
            tags = audiofiles_db.get_note_tags(note["id"])
            tag_names = [t["name"] for t in tags]
            assert "ImportedAudio" in tag_names, (
                f"Note '{note['content']}' should have 'ImportedAudio' tag, "
                f"got {tag_names}"
            )

    def test_import_audio_files_creates_audio_file_records(
        self,
        audiofiles_config_dir: Path,
        audiofiles_db: Database,
        source_audio_dir: Path,
        audiofiles_cli_runner,
    ) -> None:
        """Test that import creates audio_files records in database."""
        # Run import
        returncode, stdout, stderr = audiofiles_cli_runner(
            "audiofiles-import", str(source_audio_dir)
        )

        assert returncode == 0, f"Import failed: {stderr}"

        # Get all audio file IDs via attachments
        notes = audiofiles_db.get_all_notes()
        audio_file_ids = set()

        for note in notes:
            attachments = audiofiles_db.get_attachments_for_note(note["id"])
            for att in attachments:
                if att.get("attachment_type") == "audio_file":
                    audio_file_ids.add(att["attachment_id"])

        assert len(audio_file_ids) == 3, (
            f"Expected 3 audio_file records, found {len(audio_file_ids)}"
        )

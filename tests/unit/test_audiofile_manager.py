"""Unit tests for AudioFileManager.

Tests file operations for audio files including:
- Importing files to the audiofile_directory
- Soft-deleting files (moving to trash)
- Restoring files from trash
- Getting file paths
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime

import pytest

from core.audiofile_manager import AudioFileManager, is_supported_audio_format


class TestAudioFileManagerInit:
    """Test AudioFileManager initialization."""

    def test_initializes_with_directory(self, tmp_path: Path) -> None:
        """Test initialization with directory path."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        assert manager.audiofile_directory == audio_dir
        assert manager.trash_directory == Path(f"{audio_dir}_trash")

    def test_initializes_with_string_path(self, tmp_path: Path) -> None:
        """Test initialization with string path."""
        audio_dir = str(tmp_path / "audiofiles")
        manager = AudioFileManager(audio_dir)

        assert manager.audiofile_directory == Path(audio_dir)


class TestEnsureDirectories:
    """Test ensure_directories method."""

    def test_creates_audiofile_directory(self, tmp_path: Path) -> None:
        """Test that audiofile directory is created."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        manager.ensure_directories()

        assert audio_dir.exists()
        assert audio_dir.is_dir()

    def test_creates_trash_directory(self, tmp_path: Path) -> None:
        """Test that trash directory is created."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        manager.ensure_directories()

        trash_dir = Path(f"{audio_dir}_trash")
        assert trash_dir.exists()
        assert trash_dir.is_dir()


class TestImportFile:
    """Test import_file method."""

    def test_imports_audio_file(self, tmp_path: Path) -> None:
        """Test importing an audio file."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        # Create source file
        source = tmp_path / "test.mp3"
        source.write_bytes(b"fake mp3 content")

        audio_id = "0123456789abcdef0123456789abcdef"
        dest = manager.import_file(source, audio_id, "mp3")

        assert dest == audio_dir / f"{audio_id}.mp3"
        assert dest.exists()
        assert dest.read_bytes() == b"fake mp3 content"

    def test_creates_directory_if_not_exists(self, tmp_path: Path) -> None:
        """Test that import creates directory if needed."""
        audio_dir = tmp_path / "nonexistent" / "audiofiles"
        manager = AudioFileManager(audio_dir)

        source = tmp_path / "test.wav"
        source.write_bytes(b"fake wav")

        audio_id = "0123456789abcdef0123456789abcdef"
        dest = manager.import_file(source, audio_id, "wav")

        assert audio_dir.exists()
        assert dest.exists()

    def test_raises_for_missing_source(self, tmp_path: Path) -> None:
        """Test that FileNotFoundError is raised for missing source."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        source = tmp_path / "nonexistent.mp3"
        audio_id = "0123456789abcdef0123456789abcdef"

        with pytest.raises(FileNotFoundError):
            manager.import_file(source, audio_id, "mp3")

    def test_raises_for_unsupported_format(self, tmp_path: Path) -> None:
        """Test that ValueError is raised for unsupported format."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        source = tmp_path / "test.txt"
        source.write_text("not audio")

        audio_id = "0123456789abcdef0123456789abcdef"

        with pytest.raises(ValueError, match="Unsupported audio format"):
            manager.import_file(source, audio_id, "txt")

    def test_normalizes_extension_to_lowercase(self, tmp_path: Path) -> None:
        """Test that extension is normalized to lowercase."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        source = tmp_path / "test.MP3"
        source.write_bytes(b"fake mp3")

        audio_id = "0123456789abcdef0123456789abcdef"
        dest = manager.import_file(source, audio_id, "MP3")

        assert dest.name == f"{audio_id}.mp3"


class TestSoftDelete:
    """Test soft_delete method."""

    def test_moves_file_to_trash(self, tmp_path: Path) -> None:
        """Test that file is moved to trash directory."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)
        manager.ensure_directories()

        # Create file in audiofiles
        audio_id = "0123456789abcdef0123456789abcdef"
        audio_file = audio_dir / f"{audio_id}.mp3"
        audio_file.write_bytes(b"audio content")

        result = manager.soft_delete(audio_id, "mp3")

        assert result is True
        assert not audio_file.exists()
        assert (manager.trash_directory / f"{audio_id}.mp3").exists()

    def test_returns_false_for_nonexistent_file(self, tmp_path: Path) -> None:
        """Test that False is returned for non-existent file."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        result = manager.soft_delete("nonexistent", "mp3")
        assert result is False

    def test_creates_trash_directory_if_needed(self, tmp_path: Path) -> None:
        """Test that trash directory is created during delete."""
        audio_dir = tmp_path / "audiofiles"
        audio_dir.mkdir(parents=True)
        manager = AudioFileManager(audio_dir)

        audio_id = "0123456789abcdef0123456789abcdef"
        audio_file = audio_dir / f"{audio_id}.mp3"
        audio_file.write_bytes(b"audio")

        manager.soft_delete(audio_id, "mp3")

        assert manager.trash_directory.exists()


class TestRestoreFromTrash:
    """Test restore_from_trash method."""

    def test_restores_file_from_trash(self, tmp_path: Path) -> None:
        """Test restoring a file from trash."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)
        manager.ensure_directories()

        audio_id = "0123456789abcdef0123456789abcdef"

        # Put file in trash
        trash_file = manager.trash_directory / f"{audio_id}.mp3"
        trash_file.write_bytes(b"audio content")

        result = manager.restore_from_trash(audio_id, "mp3")

        assert result is True
        assert not trash_file.exists()
        assert (audio_dir / f"{audio_id}.mp3").exists()

    def test_returns_false_for_nonexistent_in_trash(self, tmp_path: Path) -> None:
        """Test False returned when file not in trash."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)
        manager.ensure_directories()

        result = manager.restore_from_trash("nonexistent", "mp3")
        assert result is False


class TestGetFilePath:
    """Test get_file_path method."""

    def test_returns_path_if_exists(self, tmp_path: Path) -> None:
        """Test returning path for existing file."""
        audio_dir = tmp_path / "audiofiles"
        audio_dir.mkdir(parents=True)
        manager = AudioFileManager(audio_dir)

        audio_id = "0123456789abcdef0123456789abcdef"
        audio_file = audio_dir / f"{audio_id}.mp3"
        audio_file.write_bytes(b"audio")

        path = manager.get_file_path(audio_id, "mp3")

        assert path == audio_file

    def test_returns_none_if_not_exists(self, tmp_path: Path) -> None:
        """Test None returned for non-existent file."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        path = manager.get_file_path("nonexistent", "mp3")
        assert path is None


class TestGetFileCreatedAt:
    """Test get_file_created_at method."""

    def test_returns_datetime_for_existing_file(self, tmp_path: Path) -> None:
        """Test returning datetime for existing file."""
        manager = AudioFileManager(tmp_path)

        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio")

        created_at = manager.get_file_created_at(test_file)

        assert created_at is not None
        assert isinstance(created_at, datetime)

    def test_returns_none_for_nonexistent_file(self, tmp_path: Path) -> None:
        """Test None returned for non-existent file."""
        manager = AudioFileManager(tmp_path)

        created_at = manager.get_file_created_at(tmp_path / "nonexistent.mp3")
        assert created_at is None


class TestGetExtensionFromFilename:
    """Test get_extension_from_filename method."""

    def test_extracts_mp3_extension(self, tmp_path: Path) -> None:
        """Test extracting mp3 extension."""
        manager = AudioFileManager(tmp_path)

        ext = manager.get_extension_from_filename("recording.mp3")
        assert ext == "mp3"

    def test_extracts_wav_extension(self, tmp_path: Path) -> None:
        """Test extracting wav extension."""
        manager = AudioFileManager(tmp_path)

        ext = manager.get_extension_from_filename("audio.WAV")
        assert ext == "wav"

    def test_returns_none_for_unsupported_format(self, tmp_path: Path) -> None:
        """Test None returned for unsupported format."""
        manager = AudioFileManager(tmp_path)

        ext = manager.get_extension_from_filename("document.txt")
        assert ext is None

    def test_returns_none_for_no_extension(self, tmp_path: Path) -> None:
        """Test None returned for filename without extension."""
        manager = AudioFileManager(tmp_path)

        ext = manager.get_extension_from_filename("filename")
        assert ext is None


class TestFileExists:
    """Test file_exists method."""

    def test_returns_true_if_exists(self, tmp_path: Path) -> None:
        """Test True returned when file exists."""
        audio_dir = tmp_path / "audiofiles"
        audio_dir.mkdir(parents=True)
        manager = AudioFileManager(audio_dir)

        audio_id = "0123456789abcdef0123456789abcdef"
        (audio_dir / f"{audio_id}.mp3").write_bytes(b"audio")

        assert manager.file_exists(audio_id, "mp3") is True

    def test_returns_false_if_not_exists(self, tmp_path: Path) -> None:
        """Test False returned when file doesn't exist."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        assert manager.file_exists("nonexistent", "mp3") is False


class TestIsInTrash:
    """Test is_in_trash method."""

    def test_returns_true_if_in_trash(self, tmp_path: Path) -> None:
        """Test True returned when file is in trash."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)
        manager.ensure_directories()

        audio_id = "0123456789abcdef0123456789abcdef"
        (manager.trash_directory / f"{audio_id}.mp3").write_bytes(b"audio")

        assert manager.is_in_trash(audio_id, "mp3") is True

    def test_returns_false_if_not_in_trash(self, tmp_path: Path) -> None:
        """Test False returned when file not in trash."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        assert manager.is_in_trash("nonexistent", "mp3") is False


class TestIsSupportedAudioFormat:
    """Test is_supported_audio_format function."""

    def test_mp3_is_supported(self) -> None:
        """Test MP3 is supported."""
        assert is_supported_audio_format("recording.mp3") is True

    def test_wav_is_supported(self) -> None:
        """Test WAV is supported."""
        assert is_supported_audio_format("recording.wav") is True

    def test_flac_is_supported(self) -> None:
        """Test FLAC is supported."""
        assert is_supported_audio_format("recording.flac") is True

    def test_ogg_is_supported(self) -> None:
        """Test OGG is supported."""
        assert is_supported_audio_format("recording.ogg") is True

    def test_opus_is_supported(self) -> None:
        """Test OPUS is supported."""
        assert is_supported_audio_format("recording.opus") is True

    def test_m4a_is_supported(self) -> None:
        """Test M4A is supported."""
        assert is_supported_audio_format("recording.m4a") is True

    def test_uppercase_extension_is_supported(self) -> None:
        """Test uppercase extensions are supported."""
        assert is_supported_audio_format("recording.MP3") is True
        assert is_supported_audio_format("recording.WAV") is True

    def test_txt_is_not_supported(self) -> None:
        """Test TXT is not supported."""
        assert is_supported_audio_format("document.txt") is False

    def test_no_extension_is_not_supported(self) -> None:
        """Test filename without extension is not supported."""
        assert is_supported_audio_format("filename") is False

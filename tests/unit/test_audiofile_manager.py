"""Unit tests for AudioFileManager.

Tests file operations for audio files including:
- Importing files to the audiofile_directory
- Soft-deleting files (moving to trash)
- Restoring files from trash
- Getting file paths
"""

from __future__ import annotations

import os
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
        dest = manager.import_file(source, f"{audio_id}.mp3")

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
        dest = manager.import_file(source, f"{audio_id}.wav")

        assert audio_dir.exists()
        assert dest.exists()

    def test_raises_for_missing_source(self, tmp_path: Path) -> None:
        """Test that FileNotFoundError is raised for missing source."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        source = tmp_path / "nonexistent.mp3"
        audio_id = "0123456789abcdef0123456789abcdef"

        with pytest.raises(FileNotFoundError):
            manager.import_file(source, f"{audio_id}.mp3")

    def test_raises_for_unsupported_format(self, tmp_path: Path) -> None:
        """Test that ValueError is raised for unsupported format."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        source = tmp_path / "test.txt"
        source.write_text("not audio")

        audio_id = "0123456789abcdef0123456789abcdef"

        with pytest.raises(ValueError, match="Unsupported audio format"):
            manager.import_file(source, f"{audio_id}.txt")

    def test_the_name_is_used_as_the_row_gives_it(self, tmp_path: Path) -> None:
        """The core decides the name (FILE-15); the manager copies to it and refuses a path that leaves the folder."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)

        source = tmp_path / "test.MP3"
        source.write_bytes(b"fake mp3")

        dest = manager.import_file(source, "2026_09_21_14_30_59-abcdefgh.mp3")
        assert dest.name == "2026_09_21_14_30_59-abcdefgh.mp3"
        with pytest.raises(ValueError, match="Not a file name"):
            manager.import_file(source, "../escape.mp3")

    def test_any_posix_name_is_kept_and_nothing_is_overwritten(self, tmp_path: Path) -> None:
        """FILE-15: an imported file keeps its own name, a leading dot and spaces
        included; a file already in the folder is never overwritten."""
        audio_dir = tmp_path / "audiofiles"
        manager = AudioFileManager(audio_dir)
        first = tmp_path / "first.mp3"
        first.write_bytes(b"the first file")
        second = tmp_path / "second.mp3"
        second.write_bytes(b"another file")

        assert manager.import_file(first, ".הקלטה עם רווח.mp3").name == ".הקלטה עם רווח.mp3"
        with pytest.raises(FileExistsError, match="nothing was overwritten"):
            manager.import_file(second, ".הקלטה עם רווח.mp3")
        assert (audio_dir / ".הקלטה עם רווח.mp3").read_bytes() == b"the first file"
        for not_a_name in ("a/b.mp3", "sub/../x.mp3"):
            with pytest.raises(ValueError, match="Not a file name"):
                manager.import_file(second, not_a_name)


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


class TestAudioFileExtensionRule:
    """The on-disk name rule must match voicecore models.rs::audio_file_extension."""

    def test_lowercases_extension(self) -> None:
        from core.audiofile_manager import audio_file_extension

        assert audio_file_extension("REC.MP3") == "mp3"
        assert audio_file_extension("Voice Memo.M4A") == "m4a"

    def test_last_dot_wins(self) -> None:
        from core.audiofile_manager import audio_file_extension

        assert audio_file_extension("my.recording.OGG") == "ogg"

    def test_hebrew_filename(self) -> None:
        from core.audiofile_manager import audio_file_extension

        assert audio_file_extension("הקלטה של פגישה.WAV") == "wav"

    def test_missing_or_empty_extension_falls_back_to_bin(self) -> None:
        from core.audiofile_manager import audio_file_extension

        assert audio_file_extension("noextension") == "bin"
        assert audio_file_extension("trailingdot.") == "bin"
        assert audio_file_extension(".hidden") == "bin"
        assert audio_file_extension("") == "bin"

    def test_record_path_is_the_row_s_local_name(self, tmp_path: Path) -> None:
        manager = AudioFileManager(tmp_path)
        record = {"id": "0123abcd", "filename": "REC.MP3", "local_name": "2026_01_02_03_04_05-0123abcd.mp3"}
        assert manager.get_record_path(record) == tmp_path / "2026_01_02_03_04_05-0123abcd.mp3"
        assert not manager.record_file_exists(record)
        (tmp_path / "2026_01_02_03_04_05-0123abcd.mp3").write_bytes(b"x")
        assert manager.record_file_exists(record)
        with pytest.raises(ValueError, match="no local name"):
            manager.get_record_path({"id": "0123abcd", "filename": "REC.MP3"})

    def test_imported_file_is_found_by_record_path(self, tmp_path: Path) -> None:
        """Import and lookup use the same name: the row's."""
        source = tmp_path / "SOURCE.MP3"
        source.write_bytes(b"data")
        manager = AudioFileManager(tmp_path / "store")
        manager.import_file(source, "2026_01_02_03_04_05-00000abc.mp3")
        assert manager.record_file_exists({"id": "abc", "filename": "SOURCE.MP3", "local_name": "2026_01_02_03_04_05-00000abc.mp3"})


class TestFilenameDates:
    """The date a recorder writes into a file name, and when it is believed."""

    def test_reads_the_shapes_recorders_write(self):
        from core.audiofile_manager import parse_date_from_filename

        expected = datetime(2026, 9, 8, 14, 53, 14)
        assert parse_date_from_filename("Recording 2026-09-08 14-53-14.ogg") == expected
        assert parse_date_from_filename("2026-09-08T14:53:14.m4a") == expected
        assert parse_date_from_filename("20260908_145314.mp3") == expected
        assert parse_date_from_filename("REC_20260908_145314.wav") == expected
        # A Hebrew name around the date is still a date
        assert parse_date_from_filename("הקלטה 2026-09-08 14-53-14.ogg") == expected

    def test_ignores_what_is_not_a_date(self):
        from core.audiofile_manager import parse_date_from_filename

        assert parse_date_from_filename("שיחה עם דוד.mp3") is None
        assert parse_date_from_filename("notes.mp3") is None
        # A date with no time is not enough to overrule the filesystem
        assert parse_date_from_filename("2026-09-08.mp3") is None
        # Digits in the right shape that are not a real date
        assert parse_date_from_filename("2026-13-45 99-99-99.mp3") is None

    def test_filesystem_date_wins_unless_the_name_is_much_older(self, tmp_path):
        """A copy made without preserving dates is what the name is for."""
        from core.audiofile_manager import AudioFileManager

        manager = AudioFileManager(str(tmp_path))

        # Copied without its dates: the filesystem says today, the name a week ago
        stale = tmp_path / "Recording 2026-09-01 09-05-00.ogg"
        stale.write_bytes(b"")
        os.utime(stale, (datetime(2026, 9, 8, 12, 0).timestamp(),) * 2)
        assert manager.get_file_created_at(stale) == datetime(2026, 9, 1, 9, 5, 0)

        # Dates intact: the name and the filesystem agree, so the filesystem stands
        intact = tmp_path / "Recording 2026-09-08 09-05-00.ogg"
        intact.write_bytes(b"")
        filesystem = datetime(2026, 9, 8, 9, 6, 30)
        os.utime(intact, (filesystem.timestamp(),) * 2)
        assert manager.get_file_created_at(intact) == filesystem

        # Just inside the margin: still the filesystem
        edge = tmp_path / "Recording 2026-09-06 09-05-00.ogg"
        edge.write_bytes(b"")
        filesystem = datetime(2026, 9, 8, 8, 0, 0)
        os.utime(edge, (filesystem.timestamp(),) * 2)
        assert manager.get_file_created_at(edge) == filesystem

        # No date in the name: the filesystem, as before
        plain = tmp_path / "הקלטה.ogg"
        plain.write_bytes(b"")
        os.utime(plain, (filesystem.timestamp(),) * 2)
        assert manager.get_file_created_at(plain) == filesystem

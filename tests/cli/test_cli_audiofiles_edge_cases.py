"""Edge case tests for audiofile CLI commands.

Tests corner cases including:
- Large directories
- Unicode paths and filenames
- Missing files
- Permission issues
- Invalid inputs
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def config_with_audiofiles(test_config_dir: Path, tmp_path: Path) -> Path:
    """Create config with audiofile_directory set."""
    import json

    audiofile_dir = tmp_path / "stored_audiofiles"
    config_file = test_config_dir / "config.json"

    config_data = {
        "database_file": str(test_config_dir / "notes.db"),
        "audiofile_directory": str(audiofile_dir),
    }

    with open(config_file, "w") as f:
        json.dump(config_data, f)

    return test_config_dir


class TestImportAudiofilesEdgeCases:
    """Edge case tests for audiofiles-import command."""

    def test_import_empty_directory(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test importing from an empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(empty_dir)
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "No supported audio files" in result.stdout

    def test_import_directory_with_no_audio_files(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test importing from directory with only non-audio files."""
        no_audio_dir = tmp_path / "no_audio"
        no_audio_dir.mkdir()

        # Create non-audio files
        (no_audio_dir / "document.txt").write_text("text file")
        (no_audio_dir / "image.jpg").write_bytes(b"fake image")
        (no_audio_dir / "data.json").write_text('{"key": "value"}')

        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(no_audio_dir)
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "No supported audio files" in result.stdout

    def test_import_unicode_directory_name(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test importing from directory with Unicode name."""
        unicode_dir = tmp_path / "מוזיקה_音乐_Müsik"
        unicode_dir.mkdir()
        (unicode_dir / "song.mp3").write_bytes(b"audio content")

        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(unicode_dir)
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0

    def test_import_unicode_filenames(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test importing files with Unicode filenames."""
        audio_dir = tmp_path / "unicode_files"
        audio_dir.mkdir()

        unicode_files = [
            "שיר_יפה.mp3",
            "音乐文件.wav",
            "песня.ogg",
            "Lied_für_dich.flac",
        ]

        for filename in unicode_files:
            (audio_dir / filename).write_bytes(b"audio content")

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

    def test_import_filenames_with_spaces(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test importing files with spaces in filenames."""
        audio_dir = tmp_path / "space_files"
        audio_dir.mkdir()

        space_files = [
            "my song.mp3",
            "another   track.wav",
            " leading space.ogg",
            "trailing space .flac",
        ]

        for filename in space_files:
            (audio_dir / filename).write_bytes(b"audio content")

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

    def test_import_many_files(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test importing many files at once."""
        many_files_dir = tmp_path / "many_files"
        many_files_dir.mkdir()

        # Create 100 audio files
        for i in range(100):
            (many_files_dir / f"recording_{i:03d}.mp3").write_bytes(b"audio")

        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(many_files_dir)
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        assert result.returncode == 0

    def test_import_large_files(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test importing larger files."""
        large_files_dir = tmp_path / "large_files"
        large_files_dir.mkdir()

        # Create a 1MB file
        (large_files_dir / "large.mp3").write_bytes(b"x" * (1024 * 1024))

        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(large_files_dir)
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        assert result.returncode == 0

    def test_import_empty_files(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test importing empty (0 byte) audio files."""
        empty_files_dir = tmp_path / "empty_files"
        empty_files_dir.mkdir()

        (empty_files_dir / "empty.mp3").touch()

        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(empty_files_dir)
            ],
            capture_output=True,
            text=True
        )

        # Should either succeed or provide meaningful error
        assert result.returncode in [0, 1]

    def test_import_nonexistent_directory(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test importing from non-existent directory."""
        fake_dir = tmp_path / "nonexistent"

        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(fake_dir)
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 1
        assert "not found" in result.stdout.lower() or "error" in result.stdout.lower()

    def test_import_file_instead_of_directory(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test importing a file instead of a directory."""
        file_path = tmp_path / "file.mp3"
        file_path.write_bytes(b"audio content")

        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(file_path)
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 1
        assert "not a directory" in result.stdout.lower() or "error" in result.stdout.lower()

    def test_import_all_supported_formats(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test importing all supported audio formats."""
        all_formats_dir = tmp_path / "all_formats"
        all_formats_dir.mkdir()

        formats = ["mp3", "wav", "flac", "ogg", "opus", "m4a"]
        for fmt in formats:
            (all_formats_dir / f"test.{fmt}").write_bytes(b"audio content")
            (all_formats_dir / f"TEST.{fmt.upper()}").write_bytes(b"audio content")

        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(all_formats_dir)
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0


class TestShowAudiofileEdgeCases:
    """Edge case tests for audiofile-show command."""

    def test_show_invalid_uuid_format(
        self, config_with_audiofiles: Path
    ) -> None:
        """Test audiofile-show with invalid UUID format."""
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofile-show", "not-a-valid-uuid"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 1

    def test_show_empty_id(
        self, config_with_audiofiles: Path
    ) -> None:
        """Test audiofile-show with empty ID."""
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofile-show", ""
            ],
            capture_output=True,
            text=True
        )

        # Should fail gracefully
        assert result.returncode != 0

    def test_show_very_long_id(
        self, config_with_audiofiles: Path
    ) -> None:
        """Test audiofile-show with very long ID."""
        long_id = "a" * 1000

        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofile-show", long_id
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 1


class TestListAudiofilesEdgeCases:
    """Edge case tests for note-audiofiles-list command."""

    def test_list_with_invalid_note_id(
        self, config_with_audiofiles: Path
    ) -> None:
        """Test note-audiofiles-list with invalid note ID."""
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "note-audiofiles-list", "--note-id", "invalid"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 1

    def test_list_with_nonexistent_note_id(
        self, config_with_audiofiles: Path
    ) -> None:
        """Test note-audiofiles-list with non-existent note ID."""
        fake_id = "00000000000070008000999999999999"

        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "note-audiofiles-list", "--note-id", fake_id
            ],
            capture_output=True,
            text=True
        )

        # Should succeed but show no audio files
        assert result.returncode == 0


class TestRecursiveImport:
    """Test recursive import functionality."""

    def test_recursive_import_nested_directories(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test recursive import with nested directory structure."""
        root = tmp_path / "nested"
        root.mkdir()

        # Create nested structure
        (root / "level1").mkdir()
        (root / "level1" / "level2").mkdir()
        (root / "level1" / "level2" / "level3").mkdir()

        # Add audio files at each level
        (root / "root.mp3").write_bytes(b"audio")
        (root / "level1" / "level1.mp3").write_bytes(b"audio")
        (root / "level1" / "level2" / "level2.mp3").write_bytes(b"audio")
        (root / "level1" / "level2" / "level3" / "level3.mp3").write_bytes(b"audio")

        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(root), "--recursive"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0

    def test_nonrecursive_import_ignores_subdirs(
        self, config_with_audiofiles: Path, tmp_path: Path
    ) -> None:
        """Test non-recursive import ignores subdirectories."""
        root = tmp_path / "nested"
        root.mkdir()
        (root / "subdir").mkdir()

        (root / "root.mp3").write_bytes(b"audio")
        (root / "subdir" / "sub.mp3").write_bytes(b"audio")

        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "--config-dir", str(config_with_audiofiles),
                "cli", "audiofiles-import", str(root)
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        # Should only import root.mp3, not sub.mp3

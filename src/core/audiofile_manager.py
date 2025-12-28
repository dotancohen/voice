"""Audio file manager for Voice.

This module handles file operations for audio files:
- Importing audio files to the audiofile_directory
- Soft-deleting files (moving to trash directory)
- Getting file paths and metadata
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import AUDIO_FILE_FORMATS


class AudioFileManager:
    """Manages audio file operations on disk.

    Audio files are stored as {audiofile_directory}/{uuid}.{extension}.
    Deleted files are moved to {audiofile_directory}_trash/.
    """

    def __init__(self, audiofile_directory: Path | str) -> None:
        """Initialize the audio file manager.

        Args:
            audiofile_directory: Path to the directory where audio files are stored.
        """
        self.audiofile_directory = Path(audiofile_directory)
        self.trash_directory = Path(f"{audiofile_directory}_trash")

    def ensure_directories(self) -> None:
        """Create the audiofile and trash directories if they don't exist."""
        self.audiofile_directory.mkdir(parents=True, exist_ok=True)
        self.trash_directory.mkdir(parents=True, exist_ok=True)

    def import_file(self, source: Path | str, audio_id: str, extension: str) -> Path:
        """Import an audio file to the audiofile directory.

        Args:
            source: Path to the source audio file.
            audio_id: UUID of the audio file (hex string).
            extension: File extension (without dot).

        Returns:
            Path to the imported file.

        Raises:
            FileNotFoundError: If the source file doesn't exist.
            ValueError: If the extension is not supported.
        """
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")

        ext_lower = extension.lower()
        if ext_lower not in AUDIO_FILE_FORMATS:
            raise ValueError(
                f"Unsupported audio format: {extension}. "
                f"Supported formats: {', '.join(sorted(AUDIO_FILE_FORMATS))}"
            )

        self.ensure_directories()
        dest = self.audiofile_directory / f"{audio_id}.{ext_lower}"
        shutil.copy2(source, dest)
        return dest

    def soft_delete(self, audio_id: str, extension: str) -> bool:
        """Move an audio file to the trash directory.

        Args:
            audio_id: UUID of the audio file (hex string).
            extension: File extension (without dot).

        Returns:
            True if the file was moved, False if it didn't exist.
        """
        source = self.audiofile_directory / f"{audio_id}.{extension.lower()}"
        if not source.exists():
            return False

        self.trash_directory.mkdir(parents=True, exist_ok=True)
        dest = self.trash_directory / source.name
        shutil.move(str(source), str(dest))
        return True

    def restore_from_trash(self, audio_id: str, extension: str) -> bool:
        """Restore an audio file from the trash directory.

        Args:
            audio_id: UUID of the audio file (hex string).
            extension: File extension (without dot).

        Returns:
            True if the file was restored, False if it wasn't in trash.
        """
        source = self.trash_directory / f"{audio_id}.{extension.lower()}"
        if not source.exists():
            return False

        self.audiofile_directory.mkdir(parents=True, exist_ok=True)
        dest = self.audiofile_directory / source.name
        shutil.move(str(source), str(dest))
        return True

    def get_file_path(self, audio_id: str, extension: str) -> Optional[Path]:
        """Get the path to an audio file if it exists.

        Args:
            audio_id: UUID of the audio file (hex string).
            extension: File extension (without dot).

        Returns:
            Path to the file if it exists, None otherwise.
        """
        path = self.audiofile_directory / f"{audio_id}.{extension.lower()}"
        return path if path.exists() else None

    def get_file_created_at(self, path: Path | str) -> Optional[datetime]:
        """Get the creation time of a file from filesystem metadata.

        Args:
            path: Path to the file.

        Returns:
            The file creation time, or None if it can't be determined.
        """
        path = Path(path)
        if not path.exists():
            return None

        try:
            # Try to get birth time (creation time)
            stat = path.stat()
            # On Linux, st_birthtime is not available, use st_mtime as fallback
            if hasattr(stat, "st_birthtime"):
                return datetime.fromtimestamp(stat.st_birthtime)
            else:
                # Fall back to modification time
                return datetime.fromtimestamp(stat.st_mtime)
        except (OSError, ValueError):
            return None

    def get_extension_from_filename(self, filename: str) -> Optional[str]:
        """Extract the extension from a filename.

        Args:
            filename: The filename to extract extension from.

        Returns:
            The lowercase extension (without dot), or None if no extension.
        """
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else None
        return ext if ext and ext in AUDIO_FILE_FORMATS else None

    def file_exists(self, audio_id: str, extension: str) -> bool:
        """Check if an audio file exists.

        Args:
            audio_id: UUID of the audio file (hex string).
            extension: File extension (without dot).

        Returns:
            True if the file exists, False otherwise.
        """
        path = self.audiofile_directory / f"{audio_id}.{extension.lower()}"
        return path.exists()

    def is_in_trash(self, audio_id: str, extension: str) -> bool:
        """Check if an audio file is in the trash directory.

        Args:
            audio_id: UUID of the audio file (hex string).
            extension: File extension (without dot).

        Returns:
            True if the file is in trash, False otherwise.
        """
        path = self.trash_directory / f"{audio_id}.{extension.lower()}"
        return path.exists()


def is_supported_audio_format(filename: str) -> bool:
    """Check if a filename has a supported audio format extension.

    Args:
        filename: The filename to check.

    Returns:
        True if the extension is supported, False otherwise.
    """
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext in AUDIO_FILE_FORMATS

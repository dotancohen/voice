"""Audio file manager for Voice.

This module handles file operations for audio files:
- Importing audio files to the audiofile_directory
- Getting file paths and metadata
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .models import AUDIO_FILE_FORMATS

logger = logging.getLogger(__name__)

#: Extension used on disk when the original filename has none.
#: Mirrors AUDIO_FILE_DEFAULT_EXTENSION in voicecore models.rs.
AUDIO_FILE_DEFAULT_EXTENSION = "bin"


def audio_file_extension(filename: str) -> str:
    """Normalised extension used for an audio file on disk and in cloud storage.

    This must match ``audio_file_extension`` in voicecore ``models.rs``: every
    platform derives ``{audio_id}.{ext}`` from the original filename with this
    rule, so a file written by one device is found by all the others.

    - Lowercased (``REC.MP3`` -> ``mp3``)
    - Last dot wins (``my.recording.ogg`` -> ``ogg``)
    - No extension, empty stem or empty extension -> ``bin``
    """
    if "." not in filename:
        return AUDIO_FILE_DEFAULT_EXTENSION
    stem, ext = filename.rsplit(".", 1)
    if not stem or not ext or "/" in ext:
        return AUDIO_FILE_DEFAULT_EXTENSION
    return ext.lower()


# A recording's own date sometimes survives only in its name. These are the
# shapes the common recorders write; every one carries a time as well as a
# date, so a name that holds only a date is not treated as one.
FILENAME_DATE_PATTERNS = [
    # 2026-09-08 14-53-14, 2026-09-08T14:53:14, 2026-09-08_14.53.14,
    # and "Recording 2026-09-08 14-53-14" around them
    re.compile(r"(?P<Y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})[ T_](?P<H>\d{2})[-:.](?P<M>\d{2})[-:.](?P<S>\d{2})"),
    # 20260908_145314 and REC_20260908_145314
    re.compile(r"(?P<Y>\d{4})(?P<m>\d{2})(?P<d>\d{2})[_-](?P<H>\d{2})(?P<M>\d{2})(?P<S>\d{2})"),
]

# How much older than the filesystem date a name's date must be before it is
# believed: less than this and the filesystem is simply right.
FILENAME_DATE_MARGIN = timedelta(hours=48)


def parse_date_from_filename(filename: str) -> Optional[datetime]:
    """The date a recorder wrote into a file name, or None if there is none.

    The time in a file name is the local time where the recording was made,
    so it is returned as a naive datetime, like the filesystem dates it is
    compared against.
    """
    for pattern in FILENAME_DATE_PATTERNS:
        match = pattern.search(filename)
        if not match:
            continue
        try:
            return datetime(
                int(match.group("Y")),
                int(match.group("m")),
                int(match.group("d")),
                int(match.group("H")),
                int(match.group("M")),
                int(match.group("S")),
            )
        except ValueError:
            # Digits in that shape that are not a real date, e.g. month 99
            continue
    return None


class AudioFileManager:
    """Manages audio file operations on disk.

    Audio files are stored as {audiofile_directory}/{uuid}.{extension}.
    """

    def __init__(self, audiofile_directory: Path | str) -> None:
        """Initialize the audio file manager.

        Args:
            audiofile_directory: Path to the directory where audio files are stored.
        """
        self.audiofile_directory = Path(audiofile_directory)

    def ensure_directories(self) -> None:
        """Create the audiofile directory if it does not exist."""
        self.audiofile_directory.mkdir(parents=True, exist_ok=True)

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

    def get_file_created_at(
        self, path: Path | str, original_name: Optional[str] = None
    ) -> Optional[datetime]:
        """When the recording was made, as well as this computer can tell.

        The filesystem is asked first, because it is right whenever the file
        was copied with its dates intact. A date in the file name is used only
        when it is more than 48 hours older than the filesystem date, which is
        what a copy made without preserving dates looks like (``rsync`` without
        ``-a``, a download, a restore from a phone). A file name date that is
        close to the filesystem date, or newer than it, is ignored.

        Args:
            path: Path to the file.
            original_name: The name the file arrived under, when that is not
                the name it is stored under. A stored recording is named
                ``{audio_id}.{ext}`` and so carries no date; the name the
                recorder gave it, which is kept in the database, often does.

        Returns:
            The file creation time, or None if it can't be determined.
        """
        path = Path(path)
        if not path.exists():
            return None
        name = original_name or path.name

        filesystem_date = None
        try:
            stat = path.stat()
            # Linux has no birth time, so the modification time stands in
            if hasattr(stat, "st_birthtime"):
                filesystem_date = datetime.fromtimestamp(stat.st_birthtime)
            else:
                filesystem_date = datetime.fromtimestamp(stat.st_mtime)
        except (OSError, ValueError):
            filesystem_date = None

        name_date = parse_date_from_filename(name)
        if name_date is None:
            return filesystem_date
        if filesystem_date is None:
            return name_date
        if filesystem_date - name_date > FILENAME_DATE_MARGIN:
            logger.info(
                "%s: using the date in the name (%s); the filesystem says %s, "
                "more than %d hours later, so the file was copied without its dates",
                name,
                name_date,
                filesystem_date,
                FILENAME_DATE_MARGIN.total_seconds() // 3600,
            )
            return name_date
        return filesystem_date

    def get_extension_from_filename(self, filename: str) -> Optional[str]:
        """Extract the extension from a filename.

        Args:
            filename: The filename to extract extension from.

        Returns:
            The lowercase extension (without dot), or None if no extension.
        """
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else None
        return ext if ext and ext in AUDIO_FILE_FORMATS else None

    def get_record_path(self, audio_file: dict) -> Path:
        """Expected on-disk path for an audio file record (may not exist yet).

        Args:
            audio_file: Dict with ``id`` and ``filename`` keys.
        """
        return self.audiofile_directory / f"{audio_file['id']}.{audio_file_extension(audio_file.get('filename', ''))}"

    def record_file_exists(self, audio_file: dict) -> bool:
        """Whether the binary for an audio file record is on this device."""
        return self.get_record_path(audio_file).is_file()


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

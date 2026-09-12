"""Cloud storage helpers for audio files.

Thin Python layer over the voicecore functions that move audio binaries
between this device and cloud storage (S3 today). Everything here is
on-demand: nothing downloads unless a user action asks for it, except on
installations that enabled ``sync.mirror_audio_files``.

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from voicecore import (
    DownloadResult,
    download_audio_file_from_cloud as _download_audio_file_from_cloud,
    download_audio_files_for_note as _download_audio_files_for_note,
    download_missing_audio_files as _download_missing_audio_files,
)

from .audiofile_manager import AudioFileManager

__all__ = [
    "DownloadResult",
    "STATUS_LOCAL",
    "STATUS_IN_CLOUD",
    "STATUS_PENDING",
    "audio_file_status",
    "missing_audio_files",
    "download_audio_file",
    "download_audio_files_for_note",
    "download_missing_audio_files",
    "describe_download_result",
]

#: The binary is on this device.
STATUS_LOCAL = "local"
#: The binary is not on this device but is in cloud storage and can be downloaded.
STATUS_IN_CLOUD = "in_cloud"
#: The binary is neither here nor in cloud storage: the device that imported
#: it has not uploaded it yet.
STATUS_PENDING = "pending"


def audio_file_status(audio_file: Dict[str, Any], audiofile_directory: Path | str) -> str:
    """Classify where an audio file's binary currently is.

    Args:
        audio_file: Audio file dict from the database (needs ``id``, ``filename``,
            ``storage_provider`` and ``storage_key``).
        audiofile_directory: The local audio directory.

    Returns:
        One of STATUS_LOCAL, STATUS_IN_CLOUD, STATUS_PENDING.
    """
    manager = AudioFileManager(audiofile_directory)
    if manager.record_file_exists(audio_file):
        return STATUS_LOCAL
    if audio_file.get("storage_provider") and audio_file.get("storage_key"):
        return STATUS_IN_CLOUD
    return STATUS_PENDING


def missing_audio_files(
    audio_files: List[Dict[str, Any]], audiofile_directory: Optional[Path | str]
) -> Dict[str, List[Dict[str, Any]]]:
    """Split audio files that are not on this device by whether they can be fetched.

    Returns:
        ``{"in_cloud": [...], "pending": [...]}``. Both lists are empty when
        ``audiofile_directory`` is not configured, because without it nothing
        can be downloaded anywhere.
    """
    result: Dict[str, List[Dict[str, Any]]] = {STATUS_IN_CLOUD: [], STATUS_PENDING: []}
    if not audiofile_directory:
        return result
    for af in audio_files:
        status = audio_file_status(af, audiofile_directory)
        if status != STATUS_LOCAL:
            result[status].append(af)
    return result


def download_audio_file(audio_file_id: str, config_dir: Optional[Path | str] = None) -> Dict[str, Any]:
    """Download one audio file on demand.

    Returns:
        ``{"status": "downloaded" | "already_local" | "not_in_cloud", "bytes": int}``

    Raises:
        RuntimeError: storage not configured on this device, offline, object
            missing in the bucket, or a local disk problem. The message is
            meant to be shown to the user as-is.
    """
    return _download_audio_file_from_cloud(audio_file_id, str(config_dir) if config_dir else None)


def download_audio_files_for_note(note_id: str, config_dir: Optional[Path | str] = None) -> DownloadResult:
    """Download every audio file of a note that is in the cloud but not here."""
    return _download_audio_files_for_note(note_id, str(config_dir) if config_dir else None)


def download_missing_audio_files(config_dir: Optional[Path | str] = None) -> DownloadResult:
    """Download every audio file that is in the cloud but not here (mirror)."""
    return _download_missing_audio_files(str(config_dir) if config_dir else None)


def describe_download_result(result: DownloadResult) -> str:
    """One-line human description of a download result."""
    parts: List[str] = []
    if result.downloaded:
        parts.append(f"downloaded {result.downloaded}")
    if result.already_local:
        parts.append(f"{result.already_local} already on this device")
    if result.not_in_cloud:
        parts.append(f"{result.not_in_cloud} not uploaded by their device yet")
    if result.failed:
        parts.append(f"{result.failed} failed")
    if result.deferred:
        parts.append(f"{result.deferred} not attempted")
    return ", ".join(parts) if parts else "nothing to download"

"""The words of the Issues view and of where a recording's copies are
(ISSUE-1, FILE-22): one text for the command line, the GUI, the text interface
and the web interface."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from voicecore import get_this_device_id

from src.core.models import UUID_SHORT_LEN


def size_words(n: Optional[int]) -> str:
    """A file size as people read it; "size unknown" when no device measured it."""
    if n is None:
        return "size unknown"
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} bytes"


def place_names(db, config=None) -> Dict[str, str]:
    """The name of every device the database or the configuration knows, by id."""
    names: Dict[str, str] = {}
    if config is not None:
        for device in config.get_devices():
            if device.get("device_name"):
                names[device["device_id"]] = device["device_name"]
    for card in db.list_device_cards():
        if card.get("name"):
            names.setdefault(card["device_id"], card["name"])
    return names


def place_label(place: str, names: Dict[str, str], here: Optional[str] = None) -> str:
    """"the bucket", "this device", a device's name, or the start of its id."""
    here = here or get_this_device_id()
    if place == "cloud":
        return "the bucket"
    if place == here:
        return "this device"
    return names.get(place, place[:UUID_SHORT_LEN])


def reason_words(recording: Dict[str, Any], limit_bytes: int, names: Dict[str, str], here: Optional[str] = None) -> str:
    reason = recording["reason"]
    if reason == "no_bucket":
        return "no bucket is set up for the account"
    if reason == "too_large":
        return f"larger than the account's upload limit of {size_words(limit_bytes)}"
    if reason == "waiting_for_upload":
        holders = ", ".join(place_label(p, names, here) for p in recording["held_by"])
        return f"waiting for {holders} to upload it"
    if reason in ("imported_here_file_missing", "recorded_here_file_missing"):
        sentence = MADE_HERE_BUT_MISSING["imported" if reason == "imported_here_file_missing" else "recorded"]
        return f"no device and no bucket is known to hold it; {sentence[0].lower()}{sentence[1:]}"
    return "no device and no bucket is known to hold it"


def issue_sections(issues: Dict[str, Any], names: Dict[str, str], here: Optional[str] = None) -> List[Tuple[str, List[str]]]:
    """The Issues view as sections of lines; a kind with nothing in it is left out."""
    sections: List[Tuple[str, List[str]]] = []
    not_in_cloud = issues["recordings_not_in_cloud"]
    if not_in_cloud:
        sections.append((
            f"Recordings not in cloud storage ({len(not_in_cloud)})",
            [f"{r['filename']} ({size_words(r['size_bytes'])}): {reason_words(r, issues['max_upload_bytes'], names, here)}" for r in not_in_cloud],
        ))
    transcriptions = issues["orphaned_transcriptions"]
    if transcriptions:
        sections.append((
            f"Transcriptions whose recording is not there ({len(transcriptions)})",
            [f"Transcription {t['transcription_id'][:UUID_SHORT_LEN]} of recording {t['audio_file_id'][:UUID_SHORT_LEN]}: {t['content_start']}" for t in transcriptions],
        ))
    attachments = issues["orphaned_attachments"]
    if attachments:
        lines = []
        for a in attachments:
            missing = []
            if a["note_missing"]:
                missing.append(f"its note {a['note_id'][:UUID_SHORT_LEN]}")
            if a["target_missing"]:
                missing.append(f"its recording {a['target_id'][:UUID_SHORT_LEN]}")
            lines.append(f"Attachment {a['attachment_id'][:UUID_SHORT_LEN]}: {' and '.join(missing)} is not there")
        sections.append((f"Attachments whose note or recording is not there ({len(attachments)})", lines))
    recordings = issues["orphaned_recordings"]
    if recordings:
        sections.append((
            f"Recordings no note holds ({len(recordings)})",
            [f"{r['filename']} ({r['audio_id'][:UUID_SHORT_LEN]})" for r in recordings],
        ))
    tags = issues["tags_with_whitespace"]
    if tags:
        sections.append((
            f"Tags whose names contain spaces ({len(tags)})",
            [t["path"] for t in tags],
        ))
    return sections


# What "Where are the copies?" says when this device made a recording, no
# place is known to hold it and its file is not in the audio folder (FILE-25)
MADE_HERE_BUT_MISSING = {
    "imported": "Imported on this device, but its file was not found in the audio folder after the import",
    "recorded": "Recorded on this device, but its file was not found in the audio folder after the recording",
}


def _here(config) -> Optional[str]:
    """This device's id from the configuration, when there is one."""
    return config.get_this_device_id_hex() if config is not None else None


def location_lines(db, audio_id: str, config=None) -> List[str]:
    """Where a recording's copies are, one line per place, as last stated.

    When no place is known and this device made the recording (an import or its
    recorder), but its file is not in the audio folder under the name the row
    stores, a second line says so: the row was made, and the file never arrived
    or was moved away.
    """
    from src.core.timestamp_utils import format_timestamp

    names = place_names(db, config)
    lines = []
    for location in db.file_locations(audio_id):
        state = "holds it" if location["present"] else "does not hold it"
        since = format_timestamp(location["changed_at"] // 1000)
        lines.append(f"{place_label(location['place'], names, _here(config))}: {state} (since {since})")
    if lines:
        return lines
    lines = ["No place is known to hold it"]
    audio_dir = config.get_audiofile_directory() if config is not None else None
    kind = db.made_here_but_missing(audio_id, audio_dir, _here(config)) if audio_dir else None
    if kind:
        lines.append(MADE_HERE_BUT_MISSING[kind])
    return lines

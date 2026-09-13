"""The words of the Issues view and of where a recording's copies are
(ISSUE-1, FILE-22): one text for the command line, the GUI, the text interface
and the web interface."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from voicecore import get_local_device_id

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
        for peer in config.get_peers():
            if peer.get("peer_name"):
                names[peer["peer_id"]] = peer["peer_name"]
    for card in db.list_devices():
        if card.get("name"):
            names.setdefault(card["device_id"], card["name"])
    return names


def place_label(place: str, names: Dict[str, str], here: Optional[str] = None) -> str:
    """"the bucket", "this device", a device's name, or the start of its id."""
    here = here or get_local_device_id()
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


def location_lines(db, audio_id: str, config=None) -> List[str]:
    """Where a recording's copies are, one line per place, as last stated."""
    from src.core.timestamp_utils import format_timestamp

    names = place_names(db, config)
    lines = []
    for location in db.file_locations(audio_id):
        state = "holds it" if location["present"] else "does not hold it"
        since = format_timestamp(location["changed_at"] // 1000)
        lines.append(f"{place_label(location['place'], names)}: {state} (since {since})")
    return lines or ["No place is known to hold it"]

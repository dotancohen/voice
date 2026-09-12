"""Recordings waiting to be transcribed, and whether this machine does them.

The Android application transcribes recordings of up to ten minutes and refers
anything longer to the desktop, because Whisper holds the whole recording in
memory as it works (see ``VoiceFamily/TECHNICAL-DECISIONS.md`` §3.4). Without
something on this side, such a recording simply stays untranscribed.

This module finds those recordings. Doing the work is a **choice made per
machine**: the two settings below live in ``config.json`` and are never synced,
because whether a computer can transcribe a two-hour meeting is a fact about
that computer. A laptop without the hardware leaves the setting off and nothing
changes for it; the machine with the hardware turns it on and clears the
backlog.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# The phone's limit, which is what creates the backlog in the first place. The
# default here matches VoiceAndroid's Magic.TRANSCRIBE_MAX_SECONDS_ON_PHONE.
PHONE_LIMIT_MINUTES = 10

# Keys inside the (local-only) transcription section of config.json.
KEY_ENABLED = "transcribe_long_recordings"
KEY_MIN_MINUTES = "long_recording_minutes"


def is_enabled(config) -> bool:
    """Whether this machine transcribes the backlog of long recordings.

    Off unless it was turned on. A machine without the hardware for it should
    not quietly spend an hour on a recording nobody asked it about.
    """
    try:
        return bool(config.get_transcription_config().get(KEY_ENABLED, False))
    except Exception as e:  # a missing or malformed section is "not enabled"
        logger.debug(f"No transcription backlog setting: {e}")
        return False


def minimum_minutes(config) -> int:
    """The length past which a recording belongs to this machine, in minutes.

    Defaults to the phone's own limit, so what the phone refused is exactly
    what this picks up.
    """
    try:
        value = config.get_transcription_config().get(KEY_MIN_MINUTES, PHONE_LIMIT_MINUTES)
        minutes = int(value)
        return minutes if minutes > 0 else PHONE_LIMIT_MINUTES
    except (TypeError, ValueError):
        return PHONE_LIMIT_MINUTES


def set_enabled(config, enabled: bool) -> None:
    """Turn the backlog transcription on or off for this machine."""
    tcfg = config.get_transcription_config()
    tcfg[KEY_ENABLED] = bool(enabled)
    config.set_transcription_config(tcfg)


def set_minimum_minutes(config, minutes: int) -> None:
    """Set the length past which a recording is transcribed here."""
    if minutes <= 0:
        raise ValueError("The minimum must be a positive number of minutes")
    tcfg = config.get_transcription_config()
    tcfg[KEY_MIN_MINUTES] = int(minutes)
    config.set_transcription_config(tcfg)


def is_finished_transcription(transcription: Dict[str, Any]) -> bool:
    """Whether a transcription row holds real text.

    The same rule as the phone's ``Transcription.isFinished``: not still
    pending, and not an error left behind by an interrupted run.
    """
    content = (transcription.get("content") or "").strip()
    if not content:
        return False
    return not content.startswith("Pending...") and not content.startswith("Error:")


def find_untranscribed(
    db,
    min_seconds: int,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Recordings at least ``min_seconds`` long with no finished transcription.

    Oldest first, so a backlog is cleared in the order it accumulated.

    Args:
        db: The database.
        min_seconds: Only recordings at least this long. A recording whose
            length is not recorded is skipped: its length is exactly what this
            decision needs, and guessing it wrong means spending an hour on
            something the phone could have done.
        limit: At most this many, for a run that should not take all night.

    Returns:
        The audio file rows, oldest first.
    """
    waiting: List[Dict[str, Any]] = []
    for audio_file in db.get_all_audio_files():
        if audio_file.get("deleted_at"):
            continue
        duration = audio_file.get("duration_seconds")
        if not duration or duration < min_seconds:
            continue
        rows = db.get_transcriptions_for_audio_file(audio_file["id"])
        alive = [r for r in rows if not r.get("deleted_at")]
        if any(is_finished_transcription(r) for r in alive):
            continue
        waiting.append(audio_file)

    waiting.sort(key=lambda a: a.get("imported_at") or 0)
    if limit is not None and limit > 0:
        return waiting[:limit]
    return waiting

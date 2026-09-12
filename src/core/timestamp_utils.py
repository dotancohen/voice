"""Timestamp utilities for Voice.

Provides functions to convert between Unix timestamps and formatted strings
for display purposes.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

DISPLAY_FORMAT = "%Y-%m-%d %H:%M:%S"

#: No real timezone is a full day from UTC; anything at or beyond this is a
#: corrupted value and is shown as if no zone had been recorded.
MAX_OFFSET_SECONDS = 24 * 3600


def format_timestamp(ts: Optional[int], offset_seconds: Optional[int] = None) -> str:
    """Show an instant as the clock read where the action happened.

    A note written at 15:20 in Jerusalem reads 15:20 in New York too, because
    the offset that was in force when it was written is stored beside it.

    Args:
        ts: Unix timestamp (seconds since epoch) or None
        offset_seconds: seconds east of UTC where the action happened. Without
            one (a row written before these were recorded, or by a device that
            never reported its zone) this computer's timezone is used, which is
            what every reader did before.

    Returns:
        Formatted string "YYYY-MM-DD HH:MM:SS", or empty string if ts is None
    """
    if ts is None:
        return ""
    # An offset that cannot be true, from a corrupted row, is treated as
    # unknown rather than raising: the reader's own clock is the honest answer
    if offset_seconds is None or abs(offset_seconds) >= MAX_OFFSET_SECONDS:
        # Timezone-aware UTC first, so the result does not depend on how the
        # process was started
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime(DISPLAY_FORMAT)
    where = timezone(timedelta(seconds=offset_seconds))
    return datetime.fromtimestamp(ts, tz=where).strftime(DISPLAY_FORMAT)


def local_timezone() -> Tuple[int, Optional[str]]:
    """This computer's offset from UTC right now, and its IANA name if known.

    The offset renders the clock; the name is what a later feature will show
    ("recorded in Jerusalem"). Reported to the core when a database is opened,
    so every timestamp written from here carries both.
    """
    offset = datetime.now().astimezone().utcoffset()
    seconds = int(offset.total_seconds()) if offset else 0
    return seconds, _iana_timezone_name()


def _iana_timezone_name() -> Optional[str]:
    """The IANA name of this computer's timezone, e.g. "Asia/Jerusalem"."""
    from_env = os.environ.get("TZ")
    if from_env and "/" in from_env:
        return from_env

    etc_timezone = Path("/etc/timezone")
    try:
        if etc_timezone.is_file():
            name = etc_timezone.read_text(encoding="utf-8").strip()
            if name:
                return name
    except OSError:
        pass

    # The usual arrangement: /etc/localtime points into the zoneinfo database
    try:
        localtime = Path("/etc/localtime")
        if localtime.is_symlink():
            parts = localtime.resolve().parts
            if "zoneinfo" in parts:
                return "/".join(parts[parts.index("zoneinfo") + 1:])
    except OSError:
        pass
    return None


def datetime_to_timestamp(dt: Optional[datetime]) -> Optional[int]:
    """Convert datetime to Unix timestamp.

    Args:
        dt: datetime object or None

    Returns:
        Unix timestamp (seconds since epoch) or None
    """
    if dt is None:
        return None
    return int(dt.timestamp())

"""Timestamp utilities for Voice.

Provides functions to convert between Unix timestamps and formatted strings
for display purposes.
"""

from datetime import datetime, timezone
from typing import Optional


def format_timestamp(ts: Optional[int]) -> str:
    """Format Unix timestamp to local timezone for display.

    Args:
        ts: Unix timestamp (seconds since epoch) or None

    Returns:
        Formatted string "YYYY-MM-DD HH:MM:SS" in local timezone,
        or empty string if ts is None
    """
    if ts is None:
        return ""
    # Create a timezone-aware UTC datetime, then convert to local time
    # This ensures correct conversion regardless of system timezone settings
    utc_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    local_dt = utc_dt.astimezone()  # Convert to local timezone
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


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


def current_timestamp() -> int:
    """Get current time as Unix timestamp.

    Returns:
        Current Unix timestamp (seconds since epoch)
    """
    return int(datetime.now().timestamp())

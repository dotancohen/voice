"""Test helper functions for Voice tests.

This module provides utility functions for generating test UUIDs and
accessing pre-defined test UUIDs.
"""

from __future__ import annotations

import uuid


# Pre-generated UUIDs for consistent test data
# Using deterministic UUIDs for predictable testing
TEST_DEVICE_ID = uuid.UUID("00000000-0000-7000-8000-000000000001").bytes

# Tag UUIDs (using a pattern for easy identification)
TAG_UUIDS = {
    "Work": uuid.UUID("00000000-0000-7000-8000-000000000101").bytes,
    "Projects": uuid.UUID("00000000-0000-7000-8000-000000000102").bytes,
    "Voice": uuid.UUID("00000000-0000-7000-8000-000000000103").bytes,
    "Meetings": uuid.UUID("00000000-0000-7000-8000-000000000104").bytes,
    "Personal": uuid.UUID("00000000-0000-7000-8000-000000000105").bytes,
    "Family": uuid.UUID("00000000-0000-7000-8000-000000000106").bytes,
    "Health": uuid.UUID("00000000-0000-7000-8000-000000000107").bytes,
    "Geography": uuid.UUID("00000000-0000-7000-8000-000000000108").bytes,
    "Europe": uuid.UUID("00000000-0000-7000-8000-000000000109").bytes,
    "France": uuid.UUID("00000000-0000-7000-8000-000000000110").bytes,
    "Paris_France": uuid.UUID("00000000-0000-7000-8000-000000000111").bytes,
    "Germany": uuid.UUID("00000000-0000-7000-8000-000000000112").bytes,
    "Asia": uuid.UUID("00000000-0000-7000-8000-000000000113").bytes,
    "Israel": uuid.UUID("00000000-0000-7000-8000-000000000114").bytes,
    "Foo": uuid.UUID("00000000-0000-7000-8000-000000000115").bytes,
    "bar_Foo": uuid.UUID("00000000-0000-7000-8000-000000000116").bytes,
    "Boom": uuid.UUID("00000000-0000-7000-8000-000000000117").bytes,
    "bar_Boom": uuid.UUID("00000000-0000-7000-8000-000000000118").bytes,
    "US": uuid.UUID("00000000-0000-7000-8000-000000000119").bytes,
    "Texas": uuid.UUID("00000000-0000-7000-8000-000000000120").bytes,
    "Paris_Texas": uuid.UUID("00000000-0000-7000-8000-000000000121").bytes,
}

# Note UUIDs
NOTE_UUIDS = {
    1: uuid.UUID("00000000-0000-7000-8000-000000000201").bytes,
    2: uuid.UUID("00000000-0000-7000-8000-000000000202").bytes,
    3: uuid.UUID("00000000-0000-7000-8000-000000000203").bytes,
    4: uuid.UUID("00000000-0000-7000-8000-000000000204").bytes,
    5: uuid.UUID("00000000-0000-7000-8000-000000000205").bytes,
    6: uuid.UUID("00000000-0000-7000-8000-000000000206").bytes,
    7: uuid.UUID("00000000-0000-7000-8000-000000000207").bytes,
    8: uuid.UUID("00000000-0000-7000-8000-000000000208").bytes,
    9: uuid.UUID("00000000-0000-7000-8000-000000000209").bytes,
}


def uuid_to_hex(value: bytes) -> str:
    """Convert UUID bytes to hex string."""
    return uuid.UUID(bytes=value).hex


def get_tag_uuid(key: str) -> bytes:
    """Get tag UUID bytes by key name."""
    return TAG_UUIDS[key]


def get_tag_uuid_hex(key: str) -> str:
    """Get tag UUID hex string by key name."""
    return uuid_to_hex(TAG_UUIDS[key])


def get_note_uuid(num: int) -> bytes:
    """Get note UUID bytes by number."""
    return NOTE_UUIDS[num]


def get_note_uuid_hex(num: int) -> str:
    """Get note UUID hex string by number."""
    return uuid_to_hex(NOTE_UUIDS[num])

"""Corner cases of showing a time as the clock read where it happened.

A timestamp is an instant; the offset stored beside it says what the clock
read where the action happened. These tests cover the awkward parts: UTC
itself, offsets that are not whole hours, the far ends of the map, dates
before the epoch, the hour that happens twice each autumn, and an edit whose
clock reads earlier than the note it changed.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from core.timestamp_utils import (
    current_timestamp,
    datetime_to_timestamp,
    format_timestamp,
    local_timezone,
)

# 2026-09-08 12:20:00 UTC, a summer afternoon in Jerusalem
NOON = 1_788_870_000

JERUSALEM_SUMMER = 3 * 3600
JERUSALEM_WINTER = 2 * 3600
NEW_YORK_SUMMER = -4 * 3600
INDIA = 5 * 3600 + 1800
NEPAL = 5 * 3600 + 2700
CHATHAM = 12 * 3600 + 2700
KIRITIMATI = 14 * 3600
BAKER_ISLAND = -12 * 3600
JERUSALEM_MEAN_TIME = 8454  # +02:20:54, before timezones were tidy


class TestOffsets:
    def test_utc_is_a_real_answer_and_not_a_missing_one(self):
        """Zero is a device in London, not a device that never said where it was."""
        assert format_timestamp(NOON, 0) == "2026-09-08 12:20:00"
        assert format_timestamp(NOON, 0) != format_timestamp(NOON, JERUSALEM_SUMMER)

    def test_offsets_that_are_not_whole_hours(self):
        assert format_timestamp(NOON, INDIA) == "2026-09-08 17:50:00"
        assert format_timestamp(NOON, NEPAL) == "2026-09-08 18:05:00"
        assert format_timestamp(NOON, CHATHAM) == "2026-09-09 01:05:00"
        assert format_timestamp(NOON, -3 * 3600 - 1800) == "2026-09-08 08:50:00"

    def test_an_offset_measured_in_seconds(self):
        assert format_timestamp(NOON, JERUSALEM_MEAN_TIME) == "2026-09-08 14:40:54"

    def test_the_two_ends_of_the_map_are_a_day_apart(self):
        assert format_timestamp(NOON, KIRITIMATI) == "2026-09-09 02:20:00"
        assert format_timestamp(NOON, BAKER_ISLAND) == "2026-09-08 00:20:00"

    def test_before_the_epoch(self):
        moon = -14_182_940  # 1969-07-20 20:17:40 UTC
        assert format_timestamp(moon, 0) == "1969-07-20 20:17:40"
        assert format_timestamp(moon, JERUSALEM_WINTER) == "1969-07-20 22:17:40"

    def test_nothing_to_show(self):
        assert format_timestamp(None) == ""
        assert format_timestamp(None, JERUSALEM_SUMMER) == ""

    def test_without_an_offset_the_reader_s_own_clock_is_used(self):
        expected = datetime.fromtimestamp(NOON, tz=timezone.utc).astimezone()
        assert format_timestamp(NOON) == expected.strftime("%Y-%m-%d %H:%M:%S")
        assert format_timestamp(NOON, None) == format_timestamp(NOON)


class TestDaylightSaving:
    def test_the_hour_that_happens_twice(self):
        """The night the clocks go back, two instants show the same wall clock."""
        first = 1_792_879_200  # 2026-10-24 22:00:00 UTC
        second = first + 3600
        assert format_timestamp(first, JERUSALEM_SUMMER) == "2026-10-25 01:00:00"
        assert format_timestamp(second, JERUSALEM_WINTER) == "2026-10-25 01:00:00"
        assert second > first, "only the instant tells them apart"

    def test_nothing_lands_in_the_hour_that_never_happens(self):
        """02:00 to 03:00 does not exist on the night the clocks go forward."""
        before = 1_774_645_200  # 2026-03-27 23:00:00 at +02:00
        after = before + 4 * 3600
        assert format_timestamp(before, JERUSALEM_WINTER) == "2026-03-27 23:00:00"
        shown = format_timestamp(after, JERUSALEM_SUMMER)
        assert shown == "2026-03-28 04:00:00"
        assert shown[11:13] != "02"

    def test_an_edit_can_read_earlier_than_the_note(self):
        """Written in Jerusalem, edited an hour later from New York."""
        created = NOON
        modified = NOON + 3600
        created_shown = format_timestamp(created, JERUSALEM_SUMMER)
        modified_shown = format_timestamp(modified, NEW_YORK_SUMMER)
        assert modified > created
        assert modified_shown < created_shown
        assert created_shown == "2026-09-08 15:20:00"
        assert modified_shown == "2026-09-08 09:20:00"


class TestValuesThatShouldNotBeThere:
    def test_an_impossible_offset_does_not_crash_or_lie(self):
        """No zone is a hundred hours from UTC; such a row is drawn locally."""
        local = datetime.fromtimestamp(NOON, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        assert format_timestamp(NOON, 100 * 3600) == local
        assert format_timestamp(NOON, -100 * 3600) == local

    def test_the_edges_that_are_still_real(self):
        """Fourteen hours east and twelve west are real places and must work."""
        assert format_timestamp(NOON, KIRITIMATI) == "2026-09-09 02:20:00"
        assert format_timestamp(NOON, BAKER_ISLAND) == "2026-09-08 00:20:00"


class TestThisComputersZone:
    def test_local_timezone_reports_an_offset_and_maybe_a_name(self):
        offset, name = local_timezone()
        assert isinstance(offset, int)
        assert -12 * 3600 <= offset <= 14 * 3600
        assert name is None or "/" in name

    def test_the_offset_matches_what_python_thinks(self):
        offset, _ = local_timezone()
        expected = datetime.now().astimezone().utcoffset()
        assert offset == int(expected.total_seconds())

    def test_a_note_written_now_reads_the_same_here(self):
        """The round trip an application makes: stamp now, show it back."""
        offset, _ = local_timezone()
        now = current_timestamp()
        here = format_timestamp(now, offset)
        assert here == format_timestamp(now)

    def test_converting_a_datetime_keeps_the_instant(self):
        aware = datetime(2026, 9, 8, 15, 20, tzinfo=timezone(timedelta(seconds=JERUSALEM_SUMMER)))
        assert datetime_to_timestamp(aware) == NOON
        assert format_timestamp(datetime_to_timestamp(aware), JERUSALEM_SUMMER) == "2026-09-08 15:20:00"
        assert datetime_to_timestamp(None) is None

"""A note keeps the clock it was written on, all the way through the stack.

These go through the real database: the application reports its timezone, the
core stores the offset beside the instant, the binding hands both back, and
the formatter draws the clock the author was reading. Travel is simulated by
telling the application it is somewhere else.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from core.database import Database
from core.timestamp_utils import format_timestamp

JERUSALEM = (3 * 3600, "Asia/Jerusalem")
NEW_YORK = (-4 * 3600, "America/New_York")
KATHMANDU = (5 * 3600 + 2700, "Asia/Kathmandu")
UTC = (0, "Etc/UTC")


def open_database(path: Path, zone, monkeypatch) -> Database:
    """A database opened by a computer that believes it is in `zone`."""
    monkeypatch.setattr("core.database.local_timezone", lambda: zone)
    return Database(path)


class TestTravel:
    def test_a_note_records_the_clock_of_the_place_it_was_written(self, tmp_path, monkeypatch):
        db = open_database(tmp_path / "notes.db", JERUSALEM, monkeypatch)
        note_id = db.create_note("פגישה בירושלים")

        note = db.get_note(note_id)
        assert note["created_at_offset"] == JERUSALEM[0]
        assert note["created_at_zone"] == "Asia/Jerusalem"

    def test_the_time_does_not_move_when_the_reader_does(self, tmp_path, monkeypatch):
        db = open_database(tmp_path / "notes.db", JERUSALEM, monkeypatch)
        note_id = db.create_note("פגישה בירושלים")
        note = db.get_note(note_id)
        in_jerusalem = format_timestamp(note["created_at"], note["created_at_offset"])

        # The whole computer moves to New York, not just the application
        was = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        try:
            travelled = open_database(tmp_path / "notes.db", NEW_YORK, monkeypatch)
            note = travelled.get_note(note_id)
            in_new_york = format_timestamp(note["created_at"], note["created_at_offset"])

            assert in_new_york == in_jerusalem, "the note keeps the clock it was written on"
            # and that is no longer the clock on the wall where it is being read
            assert in_new_york != format_timestamp(note["created_at"])
        finally:
            if was is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = was
            time.tzset()

    def test_an_edit_made_after_travelling_reads_earlier_than_the_note(self, tmp_path, monkeypatch):
        db = open_database(tmp_path / "notes.db", JERUSALEM, monkeypatch)
        note_id = db.create_note("רשימת קניות")

        travelled = open_database(tmp_path / "notes.db", NEW_YORK, monkeypatch)
        travelled.update_note(note_id, "רשימת קניות מעודכנת")

        note = travelled.get_note(note_id)
        created = format_timestamp(note["created_at"], note["created_at_offset"])
        modified = format_timestamp(note["modified_at"], note["modified_at_offset"])

        assert note["modified_at"] >= note["created_at"], "the edit happened later"
        assert modified < created, f"but reads earlier: created {created}, modified {modified}"
        assert note["created_at_zone"] == "Asia/Jerusalem"
        assert note["modified_at_zone"] == "America/New_York"

    def test_a_computer_in_utc_records_zero_rather_than_nothing(self, tmp_path, monkeypatch):
        db = open_database(tmp_path / "notes.db", UTC, monkeypatch)
        note_id = db.create_note("פתק מלונדון")
        note = db.get_note(note_id)

        assert note["created_at_offset"] == 0, "zero is recorded, not treated as missing"
        assert format_timestamp(note["created_at"], note["created_at_offset"]) == format_timestamp(
            note["created_at"], 0
        )

    def test_an_offset_that_is_not_a_whole_hour(self, tmp_path, monkeypatch):
        db = open_database(tmp_path / "notes.db", KATHMANDU, monkeypatch)
        note_id = db.create_note("פתק מקטמנדו")
        note = db.get_note(note_id)

        assert note["created_at_offset"] == 5 * 3600 + 2700
        minutes = format_timestamp(note["created_at"], note["created_at_offset"])[14:16]
        elsewhere = format_timestamp(note["created_at"], 5 * 3600)[14:16]
        assert minutes != elsewhere, "the forty-five minutes are not lost"

    def test_notes_stay_in_order_even_when_the_clock_goes_backwards(self, tmp_path, monkeypatch):
        db = open_database(tmp_path / "notes.db", JERUSALEM, monkeypatch)
        db.create_note("לפני הטיסה")

        travelled = open_database(tmp_path / "notes.db", NEW_YORK, monkeypatch)
        travelled.create_note("After the flight")

        notes = travelled.get_all_notes()
        assert notes[0]["content"] == "After the flight", "newest by instant comes first"
        newest = format_timestamp(notes[0]["created_at"], notes[0]["created_at_offset"])
        older = format_timestamp(notes[1]["created_at"], notes[1]["created_at_offset"])
        assert newest < older, "even though it shows an earlier clock"

    def test_the_history_of_a_travelling_note(self, tmp_path, monkeypatch):
        db = open_database(tmp_path / "notes.db", JERUSALEM, monkeypatch)
        note_id = db.create_note("גרסה ראשונה")

        travelled = open_database(tmp_path / "notes.db", KATHMANDU, monkeypatch)
        travelled.update_note(note_id, "גרסה שנייה")

        history = travelled.get_field_history("note", note_id, "content")
        offsets = {version.get("created_at_offset") for version in history}
        assert JERUSALEM[0] in offsets
        assert KATHMANDU[0] in offsets

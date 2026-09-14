"""Calculating data that was never calculated.

A Recording whose length could not be read when it was imported has none, and
one copied without its dates has no creation date. Neither is lost data — it can
be read off the file — and this module closes those gaps. What it must never do
is guess: a Recording's timezone cannot be derived from the file, and writing
this machine's offset would state something false about where the user was.

A Recording with no length is ordinary: `create_audio_file` leaves the length
NULL, so those tests use the real database; the counting is also tested by
handing `survey_rows` rows. Nothing here writes into a database to manufacture a
condition; see `VoiceFamily/TECHNICAL-DECISIONS.md` 6.5.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pytest

from core import missing_data
from core.database import Database


class FakeConfig:
    def __init__(self, audio_dir=None):
        self._audio_dir = str(audio_dir) if audio_dir else None

    def get_audiofile_directory(self):
        return self._audio_dir


@pytest.fixture
def db():
    return Database(":memory:")


def _recording(db, audio_dir: Path, name: str, seconds: int | None = None) -> str:
    """A Recording in the database with a real (silent) file behind it."""
    audio_id = db.create_audio_file(name)
    # The file is where the row says: its stored disk name (FILE-15)
    path = audio_dir / db.get_audio_file(audio_id)["disk_name"]
    # One second of 8 kHz 16-bit mono silence, as a WAV ffprobe can read
    frames = 8000 * (seconds or 1)
    data = b"\x00\x00" * frames
    header = (
        b"RIFF" + (36 + len(data)).to_bytes(4, "little") + b"WAVEfmt "
        + (16).to_bytes(4, "little") + (1).to_bytes(2, "little") + (1).to_bytes(2, "little")
        + (8000).to_bytes(4, "little") + (16000).to_bytes(4, "little")
        + (2).to_bytes(2, "little") + (16).to_bytes(2, "little")
        + b"data" + len(data).to_bytes(4, "little")
    )
    path.write_bytes(header + data)
    return audio_id


def recording_row(audio_id: str, duration: int | None = None,
                  made_at: int | None = None, offset: int | None = 10800,
                  deleted_at: str | None = None) -> Dict[str, Any]:
    """An audio file row as ``get_all_audio_files`` returns one."""
    return {
        "id": audio_id,
        "filename": "הקלטה.opus",
        "duration_seconds": duration,
        "file_created_at": made_at,
        "imported_at": 1_757_419_500,
        "imported_at_offset": offset,
        "deleted_at": deleted_at,
    }


class TestCountingGaps:
    """What is missing, counted from rows, including states no API can produce."""

    def test_nothing_missing(self):
        survey = missing_data.survey_rows(
            [recording_row("a1", duration=90, made_at=1_757_000_000)],
            lambda r: True,
        )
        assert survey.total_calculable == 0
        assert survey.summary() == "Nothing is missing."

    def test_a_recording_with_no_length_is_counted(self):
        survey = missing_data.survey_rows(
            [recording_row("a1", made_at=1_757_000_000)], lambda r: True
        )
        gaps = {g.key: g.count for g in survey.gaps}
        assert gaps["duration"] == 1

    def test_a_deleted_recording_is_not_counted(self):
        survey = missing_data.survey_rows(
            [recording_row("a1", deleted_at="2026-09-11 12:00:00")],
            lambda r: True,
        )
        gaps = {g.key: g.count for g in survey.gaps}
        assert gaps["duration"] == 0

    def test_a_recording_whose_file_is_elsewhere_is_counted_but_not_calculable(self):
        survey = missing_data.survey_rows(
            [recording_row("a1", duration=90, made_at=1)], lambda r: False
        )
        absent = next(g for g in survey.gaps if g.key == "absent_file")
        assert absent.count == 1
        assert absent.calculable is False

    def test_a_missing_timezone_is_reported_as_uncalculable(self):
        survey = missing_data.survey_rows(
            [recording_row("a1", duration=90, made_at=1, offset=None)], lambda r: True
        )
        timezone = next(g for g in survey.gaps if g.key == "timezone")
        assert timezone.count == 1
        assert timezone.calculable is False
        assert "guessing" in timezone.note

    def test_the_summary_reads_as_lines_a_person_can_read(self):
        summary = missing_data.survey_rows(
            [recording_row("a1")], lambda r: True
        ).summary()
        assert "Recordings with no length recorded" in summary
        assert "display cache" not in summary

class TestSurveyingTheDatabase:
    """The survey over a real database, for the states a real database reaches."""

    def test_a_recording_with_no_length_is_counted(self, db, tmp_path):
        _recording(db, tmp_path, "הקלטה.wav")
        survey = missing_data.survey(db, FakeConfig(tmp_path))
        gaps = {g.key: g.count for g in survey.gaps}
        assert gaps["duration"] == 1
        assert survey.total_calculable >= 1

    def test_a_note_created_now_needs_nothing(self, db, tmp_path):
        db.create_note("פגישה")
        gaps = {g.key: g.count for g in missing_data.survey(db, FakeConfig(tmp_path)).gaps}
        assert "note_cache" not in gaps, "display caches are not a gap: every note is written with them"

    def test_a_recording_with_no_file_here_is_counted_but_not_calculable(self, db, tmp_path):
        db.create_audio_file("במקום אחר.opus")  # no file written
        survey = missing_data.survey(db, FakeConfig(tmp_path))
        absent = next(g for g in survey.gaps if g.key == "absent_file")
        assert absent.count == 1
        assert absent.calculable is False

    def test_a_deleted_recording_is_not_counted(self, db, tmp_path):
        audio_id = _recording(db, tmp_path, "מחוק.wav")
        db.delete_audio_file(audio_id)
        gaps = {g.key: g.count for g in missing_data.survey(db, FakeConfig(tmp_path)).gaps}
        assert gaps["duration"] == 0


class TestCalculatingFromFiles:
    """Lengths and dates, read off real files in a real database."""

    def test_a_length_is_read_off_the_file(self, db, tmp_path):
        audio_id = _recording(db, tmp_path, "שתי שניות.wav", seconds=2)
        assert db.get_audio_file(audio_id).get("duration_seconds") in (None, 0)

        report = missing_data.calculate_missing_data(db, FakeConfig(tmp_path))

        assert report.calculated.get("duration") == 1
        assert db.get_audio_file(audio_id)["duration_seconds"] == 2

    def test_a_length_already_known_is_left_alone(self, db, tmp_path):
        audio_id = _recording(db, tmp_path, "ידוע.wav", seconds=2)
        db.update_audio_file_duration(audio_id, 999)

        report = missing_data.calculate_missing_data(db, FakeConfig(tmp_path))

        assert report.calculated.get("duration", 0) == 0
        assert db.get_audio_file(audio_id)["duration_seconds"] == 999

    def test_a_creation_date_is_read_off_the_file(self, db, tmp_path):
        audio_id = _recording(db, tmp_path, "תאריך.wav")
        assert not db.get_audio_file(audio_id).get("file_created_at")

        report = missing_data.calculate_missing_data(
            db, FakeConfig(tmp_path), durations=False
        )

        assert report.calculated.get("file_created_at") == 1
        assert db.get_audio_file(audio_id)["file_created_at"] > 0

    def test_a_date_in_the_recorded_name_beats_a_fresh_filesystem_date(self, db, tmp_path):
        """The date the recorder wrote is in the name the file arrived under.

        A stored Recording's disk name can differ from it, so the only place that date
        survives is the filename kept in the database. The file on disk was
        written just now, which is what a copy made without its dates looks
        like, so the name is believed.
        """
        audio_id = _recording(db, tmp_path, "Recording 2019-03-04 10-20-30 פגישה.wav")

        report = missing_data.calculate_missing_data(
            db, FakeConfig(tmp_path), durations=False
        )

        assert report.calculated.get("file_created_at") == 1
        made = db.get_audio_file(audio_id)["file_created_at"]
        assert datetime.fromtimestamp(made).year == 2019

    def test_a_recording_whose_file_is_elsewhere_is_reported_not_invented(self, db, tmp_path):
        db.create_audio_file("במקום אחר.opus")

        report = missing_data.calculate_missing_data(db, FakeConfig(tmp_path))

        assert report.failed.get("absent_file") == 1
        assert report.calculated.get("duration", 0) == 0

    def test_nothing_is_read_when_no_audio_directory_is_configured(self, db, tmp_path):
        _recording(db, tmp_path, "הקלטה.wav")

        report = missing_data.calculate_missing_data(db, FakeConfig(None))

        assert report.total_calculated == 0
        assert any("audio directory" in d for d in report.details)

    def test_a_run_can_be_limited(self, db, tmp_path):
        for i in range(4):
            _recording(db, tmp_path, f"הקלטה-{i}.wav")

        report = missing_data.calculate_missing_data(
            db, FakeConfig(tmp_path), limit=2
        )

        assert report.calculated.get("duration") == 2

    def test_each_repair_can_be_left_out(self, db, tmp_path):
        _recording(db, tmp_path, "הקלטה.wav")
        db.create_note("פגישה")

        report = missing_data.calculate_missing_data(
            db, FakeConfig(tmp_path), durations=False, file_dates=False
        )

        assert report.total_calculated == 0

    def test_progress_is_reported_as_it_goes(self, db, tmp_path):
        _recording(db, tmp_path, "הקלטה.wav", seconds=1)
        lines: List[str] = []
        missing_data.calculate_missing_data(
            db, FakeConfig(tmp_path), progress=lines.append
        )
        assert lines
        assert any("הקלטה.wav" in line for line in lines)

    def test_running_it_twice_changes_nothing_the_second_time(self, db, tmp_path):
        _recording(db, tmp_path, "הקלטה.wav", seconds=1)

        first = missing_data.calculate_missing_data(db, FakeConfig(tmp_path))
        second = missing_data.calculate_missing_data(db, FakeConfig(tmp_path))

        assert first.total_calculated > 0
        assert second.total_calculated == 0

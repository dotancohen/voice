"""The Recordings the phone was too small for.

The Android application transcribes up to ten minutes and refers anything
longer to the desktop. These tests cover what the desktop then considers its
work, and the rule that it only does that work when this machine has been told
it can — a laptop without the hardware must not quietly spend an hour on a
recording nobody asked it about.
"""

from __future__ import annotations

import pytest

from core import transcription_backlog as backlog
from core.database import Database


class FakeConfig:
    """Just enough Config to hold a transcription section."""

    def __init__(self, section=None):
        self._section = dict(section or {})

    def get_transcription_config(self):
        return dict(self._section)

    def set_transcription_config(self, section):
        self._section = dict(section)


def test_a_machine_does_not_transcribe_the_backlog_unless_told_to():
    assert backlog.is_enabled(FakeConfig()) is False
    assert backlog.is_enabled(FakeConfig({"transcribe_long_recordings": False})) is False


def test_a_machine_that_was_told_to_does():
    assert backlog.is_enabled(FakeConfig({"transcribe_long_recordings": True})) is True


def test_turning_it_on_and_off_is_remembered():
    config = FakeConfig()
    backlog.set_enabled(config, True)
    assert backlog.is_enabled(config) is True
    backlog.set_enabled(config, False)
    assert backlog.is_enabled(config) is False


def test_a_config_without_the_section_is_not_enabled():
    class NoSection:
        def get_transcription_config(self):
            raise RuntimeError("no transcription config at all")

    assert backlog.is_enabled(NoSection()) is False


def test_the_default_length_is_the_phones_own_limit():
    assert backlog.minimum_minutes(FakeConfig()) == backlog.PHONE_LIMIT_MINUTES
    assert backlog.PHONE_LIMIT_MINUTES == 10


@pytest.mark.parametrize("bad", ["", "lots", None, 0, -5])
def test_a_nonsense_length_falls_back_to_the_phones_limit(bad):
    assert backlog.minimum_minutes(FakeConfig({"long_recording_minutes": bad})) == 10


class TestWhatIsWaiting:
    """Which Recordings count as waiting for this machine."""

    def _db(self) -> Database:
        return Database(":memory:")

    def test_a_long_recording_with_no_transcription_is_waiting(self):
        db = self._db()
        audio_id = db.create_audio_file("פגישה.opus")
        db.update_audio_file_duration(audio_id, 2 * 3600)

        waiting = backlog.find_untranscribed(db, 600)
        assert [a["id"] for a in waiting] == [audio_id]

    def test_a_short_recording_is_not_waiting(self):
        db = self._db()
        audio_id = db.create_audio_file("הערה.opus")
        db.update_audio_file_duration(audio_id, 5 * 60)

        assert backlog.find_untranscribed(db, 600) == []

    def test_a_recording_of_unknown_length_is_left_alone(self):
        # Its length is exactly what the decision needs; guessing it wrong
        # means spending an hour on something the phone could have done.
        db = self._db()
        db.create_audio_file("בלי אורך.opus")

        assert backlog.find_untranscribed(db, 600) == []

    def test_a_recording_that_already_has_a_transcription_is_not_waiting(self):
        db = self._db()
        audio_id = db.create_audio_file("הרצאה.opus")
        db.update_audio_file_duration(audio_id, 3 * 3600)
        db.create_transcription(audio_id, "תמלול שלם", "local_whisper")

        assert backlog.find_untranscribed(db, 600) == []

    def test_a_pending_transcription_does_not_count_as_done(self):
        db = self._db()
        audio_id = db.create_audio_file("ממתין.opus")
        db.update_audio_file_duration(audio_id, 3 * 3600)
        db.create_transcription(audio_id, "Pending... (2026-09-11 10:00:00+03:00)", "local_whisper")

        assert [a["id"] for a in backlog.find_untranscribed(db, 600)] == [audio_id]

    def test_a_failed_transcription_does_not_count_as_done(self):
        db = self._db()
        audio_id = db.create_audio_file("נכשל.opus")
        db.update_audio_file_duration(audio_id, 3 * 3600)
        db.create_transcription(
            audio_id,
            "Error: the app was closed before the transcription finished",
            "local_whisper",
        )

        assert [a["id"] for a in backlog.find_untranscribed(db, 600)] == [audio_id]

    def test_a_deleted_transcription_does_not_count_as_done(self):
        db = self._db()
        audio_id = db.create_audio_file("נמחק.opus")
        db.update_audio_file_duration(audio_id, 3 * 3600)
        transcription_id = db.create_transcription(audio_id, "תמלול", "local_whisper")
        db.delete_transcription(transcription_id)

        assert [a["id"] for a in backlog.find_untranscribed(db, 600)] == [audio_id]

    def test_a_deleted_recording_is_not_waiting(self):
        db = self._db()
        audio_id = db.create_audio_file("מחוק.opus")
        db.update_audio_file_duration(audio_id, 3 * 3600)
        db.delete_audio_file(audio_id)

        assert backlog.find_untranscribed(db, 600) == []

    def test_the_oldest_is_first_so_a_backlog_clears_in_order(self):
        db = self._db()
        ids = []
        for i in range(3):
            audio_id = db.create_audio_file(f"ישיבה-{i}.opus")
            db.update_audio_file_duration(audio_id, 3600 + i)
            ids.append(audio_id)

        waiting = backlog.find_untranscribed(db, 600)
        assert len(waiting) == 3
        imported = [a.get("imported_at") or 0 for a in waiting]
        assert imported == sorted(imported)

    def test_a_run_can_be_limited(self):
        db = self._db()
        for i in range(5):
            audio_id = db.create_audio_file(f"ארוכה-{i}.opus")
            db.update_audio_file_duration(audio_id, 3600)

        assert len(backlog.find_untranscribed(db, 600, limit=2)) == 2
        assert len(backlog.find_untranscribed(db, 600)) == 5


class TestWhatCountsAsFinished:
    """The same rule as the phone's, so both agree on what is done."""

    def test_real_text_is_finished(self):
        assert backlog.is_finished_transcription({"content": "שלום עולם"}) is True

    def test_pending_and_error_are_not(self):
        assert backlog.is_finished_transcription({"content": "Pending... (x)"}) is False
        assert backlog.is_finished_transcription({"content": "Error: something"}) is False

    def test_empty_is_not(self):
        assert backlog.is_finished_transcription({"content": ""}) is False
        assert backlog.is_finished_transcription({"content": "   "}) is False
        assert backlog.is_finished_transcription({}) is False

    def test_hebrew_text_that_mentions_an_error_is_finished(self):
        assert backlog.is_finished_transcription({"content": "שגיאה הייתה בפגישה"}) is True

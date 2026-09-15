"""Where a recording's copies are, in words (FILE-22): the line for a recording
this device made whose file is not in the audio folder (FILE-25)."""

from __future__ import annotations

from pathlib import Path

from voicecore import get_this_device_id

from core.database import Database
from src.core import issues_text


class FakeConfig:
    def __init__(self, audio_dir: Path) -> None:
        self._audio_dir = str(audio_dir)

    def get_audiofile_directory(self) -> str:
        return self._audio_dir

    def get_config_dir(self) -> Path:
        return Path(self._audio_dir)

    def get_devices(self) -> list:
        return []

    def get_this_device_id_hex(self) -> str:
        # This process's device, the one the database stamps as a recording's origin
        return get_this_device_id()


def test_an_imported_recording_whose_file_is_not_there_says_so(tmp_path: Path) -> None:
    db = Database(":memory:")
    audio_id = db.create_audio_file("נעלם.mp3")
    lines = issues_text.location_lines(db, audio_id, FakeConfig(tmp_path))
    assert lines == ["No place is known to hold it", issues_text.MADE_HERE_BUT_MISSING["imported"]]


def test_an_imported_recording_whose_file_is_there_has_no_such_line(tmp_path: Path) -> None:
    db = Database(":memory:")
    audio_id = db.create_audio_file("כאן.mp3")
    (tmp_path / db.get_audio_file(audio_id)["disk_name"]).write_bytes(b"audio")
    lines = issues_text.location_lines(db, audio_id, FakeConfig(tmp_path))
    assert issues_text.MADE_HERE_BUT_MISSING["imported"] not in lines


def test_a_recording_another_device_imported_is_not_said_to_be_imported_here(tmp_path: Path) -> None:
    db = Database(":memory:")
    audio_id = "01a09e17299276c0a72d86fa589572c0"
    db.apply_sync_audio_file(audio_id, 1735689600, "משם.mp3", 1735689600, None, None, 1735689600, None, 1735689700)
    assert db.made_here_but_missing(audio_id, str(tmp_path)) is None
    lines = issues_text.location_lines(db, audio_id, FakeConfig(tmp_path))
    assert lines == ["No place is known to hold it"]


def test_the_issues_reason_words_carry_the_same_sentence() -> None:
    words = issues_text.reason_words({"reason": "imported_here_file_missing", "held_by": []}, 0, {})
    assert words.startswith("no device and no bucket is known to hold it; imported on this device")
    words = issues_text.reason_words({"reason": "recorded_here_file_missing", "held_by": []}, 0, {})
    assert words.startswith("no device and no bucket is known to hold it; recorded on this device")

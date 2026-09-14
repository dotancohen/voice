"""GUI tests for where a recording's copies are and removing this computer's
copy, from a recording's menu in the note pane (FILE-22)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from core.config import Config
from core.database import Database
from tests.fake_s3 import TEST_KEY_ID, TEST_SECRET, FakeS3, bucket_holding
from ui.note_pane import NotePane


@pytest.fixture
def s3():
    fake = FakeS3(TEST_KEY_ID, TEST_SECRET).start()
    yield fake
    fake.stop()


@pytest.fixture
def pane_with_recording(qapp, test_config: Config, tmp_path: Path):
    """A note pane on the configuration's database: removing a copy runs
    through the sync client, which opens that database (FILE-26)."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    test_config.set_audiofile_directory(str(audio_dir))
    db = Database(Path(test_config._rust_config.get_database_file()))
    note_id = db.create_note("פתק עם הקלטה")
    audio_id = db.create_audio_file("הקלטה במחשב.ogg", 1735689600)
    db.attach_to_note(note_id, audio_id, "audio_file")
    path = audio_dir / db.get_audio_file(audio_id)["disk_name"]
    path.write_bytes(b"recording bytes")
    pane = NotePane(db, audiofile_directory=audio_dir, config_dir=test_config.get_config_dir(), config=test_config)
    pane.load_note(note_id)
    yield pane, db, audio_id, path
    db.close()


@pytest.mark.gui
class TestRecordingCopiesInTheNotePane:
    def test_where_the_copies_are_lists_this_computer_after_comparing_the_folder(self, pane_with_recording, monkeypatch) -> None:
        pane, db, audio_id, _ = pane_with_recording
        shown = {}
        monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text: shown.update(title=title, text=text))
        pane._show_recording_locations(audio_id)
        assert shown["title"] == "Where the copies are"
        assert shown["text"].startswith("this device: holds it")

    def test_the_only_copy_is_not_removed_and_the_refusal_is_shown(self, pane_with_recording, monkeypatch) -> None:
        pane, db, audio_id, path = pane_with_recording
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
        warned = {}
        monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warned.update(title=title, text=text))
        pane._remove_local_copy(audio_id)
        assert warned["title"] == "Not removed"
        assert "no other place is known to hold it" in warned["text"]
        assert path.exists()

    def test_a_copy_the_bucket_holds_is_removed_after_the_user_agrees(self, pane_with_recording, s3: FakeS3, monkeypatch) -> None:
        pane, db, audio_id, path = pane_with_recording
        bucket_holding(s3, db, audio_id, path)
        answers = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: next(answers))

        pane._remove_local_copy(audio_id)
        assert path.exists(), "No keeps the file"

        pane._remove_local_copy(audio_id)
        assert not path.exists()
        places = {loc["place"]: loc["present"] for loc in db.file_locations(audio_id)}
        assert places["cloud"] is True
        assert False in places.values(), "this computer states that it no longer holds it"
        assert db.get_audio_file(audio_id) is not None, "the recording stays"

"""GUI tests for where a recording's copies are and removing this computer's
copy, from a recording's menu in the note pane (FILE-22)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from core.config import Config
from core.database import Database
from ui.note_pane import NotePane


@pytest.fixture
def pane_with_recording(qapp, test_config: Config, empty_db: Database, tmp_path: Path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    test_config.set_audiofile_directory(str(audio_dir))
    note_id = empty_db.create_note("פתק עם הקלטה")
    audio_id = empty_db.create_audio_file("הקלטה במחשב.ogg", 1735689600)
    empty_db.attach_to_note(note_id, audio_id, "audio_file")
    path = audio_dir / empty_db.get_audio_file(audio_id)["disk_name"]
    path.write_bytes(b"recording bytes")
    pane = NotePane(empty_db, audiofile_directory=audio_dir, config_dir=test_config.get_config_dir())
    pane.load_note(note_id)
    return pane, empty_db, audio_id, path


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
        assert "on this device only" in warned["text"]
        assert path.exists()

    def test_a_copy_held_elsewhere_is_removed_after_the_user_agrees(self, pane_with_recording, monkeypatch) -> None:
        pane, db, audio_id, path = pane_with_recording
        db.update_audio_file_storage(audio_id, "s3", "k.ogg")
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

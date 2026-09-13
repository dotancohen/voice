"""The text interface: where a recording's copies are (w), and removing this
computer's copy on the second press of x (FILE-22)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.config import Config
from src.core.database import Database
from src.tui import NoteDetail, VoiceTUI

pytestmark = pytest.mark.tui


@pytest.fixture
def with_recording(empty_db: Database, test_config: Config, tmp_path: Path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    test_config.set_audiofile_directory(str(audio_dir))
    note_id = empty_db.create_note("פתק עם הקלטה")
    audio_id = empty_db.create_audio_file("הקלטה בטרמינל.ogg", 1735689600)
    empty_db.attach_to_note(note_id, audio_id, "audio_file")
    path = audio_dir / empty_db.get_audio_file(audio_id)["disk_name"]
    path.write_bytes(b"bytes")
    return empty_db, test_config, note_id, audio_id, path


class TestRecordingCopies:
    async def test_w_says_where_the_copies_are_and_x_twice_removes_a_copy_held_elsewhere(self, with_recording, monkeypatch) -> None:
        db, config, note_id, audio_id, path = with_recording
        app = VoiceTUI(db, config)
        said = []
        async with app.run_test() as pilot:
            monkeypatch.setattr(app, "notify", lambda message, **kwargs: said.append(message))
            app.query_one("#note-detail", NoteDetail).load_note(note_id)
            await pilot.pause()

            app.action_show_locations()
            assert said[-1].startswith("this device: holds it"), said

            app.action_remove_local_copy()
            assert path.exists() and "Press x again" in said[-1]
            app.action_remove_local_copy()
            assert path.exists(), "the only copy is not removed"
            assert said[-1].startswith("Not removed") and "on this device only" in said[-1]

            db.update_audio_file_storage(audio_id, "s3", "k.ogg")
            app.action_remove_local_copy()
            app.action_remove_local_copy()
            await pilot.pause()
            assert not path.exists()
            assert said[-1] == "Removed הקלטה בטרמינל.ogg from this computer"

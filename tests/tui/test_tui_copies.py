"""The text interface: where a recording's copies are (w), and removing this
computer's copy on the second press of x (FILE-22)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.config import Config
from src.core.database import Database
from src.tui import NoteDetail, VoiceTUI
from tests.fake_s3 import TEST_KEY_ID, TEST_SECRET, FakeS3, bucket_holding

pytestmark = pytest.mark.tui


@pytest.fixture
def s3():
    fake = FakeS3(TEST_KEY_ID, TEST_SECRET).start()
    yield fake
    fake.stop()


@pytest.fixture
def with_recording(test_config: Config, tmp_path: Path):
    """A recording in the configuration's database: removing a copy runs
    through the sync client, which opens that database (FILE-26)."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    test_config.set_audiofile_directory(str(audio_dir))
    db = Database(Path(test_config._rust_config.get_database_file()))
    note_id = db.create_note("פתק עם הקלטה")
    audio_id = db.create_audio_file("הקלטה בטרמינל.ogg", 1735689600)
    db.attach_to_note(note_id, audio_id, "audio_file")
    path = audio_dir / db.get_audio_file(audio_id)["disk_name"]
    path.write_bytes(b"bytes")
    yield db, test_config, note_id, audio_id, path
    db.close()


class TestRecordingCopies:
    async def test_w_says_where_the_copies_are_and_x_twice_removes_a_copy_the_bucket_holds(self, with_recording, s3: FakeS3, monkeypatch) -> None:
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
            assert said[-1].startswith("Not removed") and "no other place is known to hold it" in said[-1]

            bucket_holding(s3, db, audio_id, path)
            app.action_remove_local_copy()
            app.action_remove_local_copy()
            await pilot.pause()
            assert not path.exists()
            assert said[-1] == "Removed הקלטה בטרמינל.ogg from this device; the bucket holds it"

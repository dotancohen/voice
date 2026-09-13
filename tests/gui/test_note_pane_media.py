"""GUI tests for the "media missing" notice and Download button in NotePane."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import Config
from core.database import Database
from ui.note_pane import NotePane


@pytest.fixture
def media_env(test_config: Config, empty_db: Database, tmp_path: Path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    test_config.set_audiofile_directory(str(audio_dir))
    note_id = empty_db.create_note("פתק עם הקלטה בענן")
    audio_id = empty_db.create_audio_file("הקלטה.MP3", None)
    empty_db.attach_to_note(note_id, audio_id, "audio_file")
    return test_config, empty_db, audio_dir, note_id, audio_id


@pytest.mark.gui
class TestNotePaneMediaMissing:
    def test_in_cloud_shows_notice_and_download_button(self, qapp, media_env) -> None:
        config, db, audio_dir, note_id, audio_id = media_env
        db.update_audio_file_storage(audio_id, "s3", f"audio/{audio_id}.mp3")

        pane = NotePane(db, audiofile_directory=audio_dir, config_dir=config.get_config_dir())
        pane.load_note(note_id)

        assert not pane.media_missing_label.isHidden()
        assert "Media missing: 1 file(s)" in pane.media_missing_label.text()
        assert not pane.download_media_button.isHidden()

    def test_pending_upload_shows_notice_without_button(self, qapp, media_env) -> None:
        config, db, audio_dir, note_id, _ = media_env

        pane = NotePane(db, audiofile_directory=audio_dir, config_dir=config.get_config_dir())
        pane.load_note(note_id)

        assert not pane.media_missing_label.isHidden()
        assert "not uploaded by their device yet" in pane.media_missing_label.text()
        assert pane.download_media_button.isHidden()

    def test_local_file_hides_notice(self, qapp, media_env) -> None:
        config, db, audio_dir, note_id, audio_id = media_env
        db.update_audio_file_storage(audio_id, "s3", f"audio/{audio_id}.mp3")
        # Written under the name the row carries (Stage 13)
        (audio_dir / db.get_audio_file(audio_id)["disk_name"]).write_bytes(b"x")

        pane = NotePane(db, audiofile_directory=audio_dir, config_dir=config.get_config_dir())
        pane.load_note(note_id)

        assert pane.media_missing_label.isHidden()
        assert pane.download_media_button.isHidden()

    def test_clear_hides_notice(self, qapp, media_env) -> None:
        config, db, audio_dir, note_id, audio_id = media_env
        db.update_audio_file_storage(audio_id, "s3", f"audio/{audio_id}.mp3")
        pane = NotePane(db, audiofile_directory=audio_dir, config_dir=config.get_config_dir())
        pane.load_note(note_id)
        assert not pane.download_media_button.isHidden()

        pane.clear()
        assert pane.media_missing_label.isHidden()
        assert pane.download_media_button.isHidden()

    def test_no_audio_directory_shows_nothing(self, qapp, media_env) -> None:
        config, db, _, note_id, audio_id = media_env
        db.update_audio_file_storage(audio_id, "s3", f"audio/{audio_id}.mp3")
        pane = NotePane(db, audiofile_directory=None, config_dir=config.get_config_dir())
        pane.load_note(note_id)
        assert pane.media_missing_label.isHidden()
        assert pane.download_media_button.isHidden()

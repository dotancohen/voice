"""TUI tests for the "media missing" notice and Download action."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import Config
from core.database import Database
from tui import NoteDetail, TUIAudioPlayer, VoiceTUI
from textual.widgets import Button, Static


@pytest.fixture
def media_env(test_config: Config, empty_db: Database, tmp_path: Path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    test_config.set_audiofile_directory(str(audio_dir))
    note_id = empty_db.create_note("פתק עם הקלטה בענן")
    audio_id = empty_db.create_audio_file("הקלטה.MP3", None)
    empty_db.attach_to_note(note_id, audio_id, "audio_file")
    return test_config, empty_db, audio_dir, note_id, audio_id


@pytest.mark.tui
class TestTuiMediaMissing:
    async def test_in_cloud_shows_download_button(self, media_env, monkeypatch) -> None:
        config, db, audio_dir, note_id, audio_id = media_env
        db.update_audio_file_storage(audio_id, "s3", f"audio/{audio_id}.mp3")
        monkeypatch.setattr("tui.is_mpv_available", lambda: True)

        app = VoiceTUI(db, config)
        async with app.run_test() as pilot:
            detail = app.query_one("#note-detail", NoteDetail)
            detail.load_note(note_id)
            await pilot.pause()

            player = app.query_one("#tui-audio-player", TUIAudioPlayer)
            assert player.has_downloadable_media()
            assert app.query_one("#download-btn", Button).display is True
            label = app.query_one("#audio-missing-label", Static)
            assert label.display is True
            assert "Media missing: 1" in str(label.content)

    async def test_pending_upload_has_no_download_button(self, media_env, monkeypatch) -> None:
        config, db, audio_dir, note_id, _ = media_env
        monkeypatch.setattr("tui.is_mpv_available", lambda: True)

        app = VoiceTUI(db, config)
        async with app.run_test() as pilot:
            detail = app.query_one("#note-detail", NoteDetail)
            detail.load_note(note_id)
            await pilot.pause()

            player = app.query_one("#tui-audio-player", TUIAudioPlayer)
            assert not player.has_downloadable_media()
            assert app.query_one("#download-btn", Button).display is False
            label = app.query_one("#audio-missing-label", Static)
            assert "not uploaded by their device yet" in str(label.content)

    async def test_fallback_text_mentions_missing_media(self, media_env, monkeypatch) -> None:
        """Without MPV the attachments text still tells the user how to download."""
        config, db, audio_dir, note_id, audio_id = media_env
        db.update_audio_file_storage(audio_id, "s3", f"audio/{audio_id}.mp3")
        monkeypatch.setattr("tui.is_mpv_available", lambda: False)

        app = VoiceTUI(db, config)
        async with app.run_test() as pilot:
            detail = app.query_one("#note-detail", NoteDetail)
            detail.load_note(note_id)
            await pilot.pause()
            from textual.widgets import Label
            text = str(app.query_one("#note-attachments", Label).content)
            assert "media missing (press 'd' to download)" in text

    async def test_download_action_without_note_warns(self, media_env) -> None:
        config, db, *_ = media_env
        app = VoiceTUI(db, config)
        async with app.run_test() as pilot:
            await pilot.press("d")
            await pilot.pause()
            detail = app.query_one("#note-detail", NoteDetail)
            assert detail._downloading is False

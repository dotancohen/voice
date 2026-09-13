"""CLI tests for cloud storage commands.

Covers the on-demand download commands, the mirror option, and the media
status shown by audiofile-show. Nothing here reaches the network.
"""

from __future__ import annotations

import json
import subprocess
import sys
import os
from pathlib import Path
from typing import List

import pytest

from core.config import Config
from core.database import Database, set_local_device_id

TEST_DEVICE_ID = "00000000000070008000000000000001"


def run_cli(config_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "src.main", "cli", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "VOICE_CONFIG_DIR": str(config_dir)},
    )


def local_name_of(config_dir: Path, audio_id: str) -> str:
    """The name a recording's file has in the audio directory: what its row says (Stage 13)."""
    from core.database import Database

    db = Database(config_dir / "notes.db")
    try:
        return db.get_audio_file(audio_id)["disk_name"]
    finally:
        db.close()


@pytest.fixture
def storage_env(test_config_dir: Path, tmp_path: Path):
    """Config with an audio directory and a DB containing one note with one pending file."""
    set_local_device_id(TEST_DEVICE_ID)
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    config = Config(config_dir=test_config_dir)
    config.set_audiofile_directory(str(audio_dir))
    db = Database(Path(config.get("database_file")))
    note_id = db.create_note("פתק עם הקלטה")
    audio_id = db.create_audio_file("הקלטה.MP3", None)
    db.attach_to_note(note_id, audio_id, "audio_file")
    db.close()
    return test_config_dir, audio_dir, note_id, audio_id


class TestStorageStatusAndMirror:
    def test_status_shows_mirror_disabled_by_default(self, storage_env) -> None:
        config_dir, *_ = storage_env
        result = run_cli(config_dir, "storage", "status")
        assert result.returncode == 0
        assert "Mirror: disabled" in result.stdout

    def test_mirror_enable_then_status(self, storage_env) -> None:
        config_dir, *_ = storage_env
        result = run_cli(config_dir, "storage", "mirror", "enable")
        assert result.returncode == 0
        assert "Mirror enabled" in result.stdout

        result = run_cli(config_dir, "storage", "status")
        assert "Mirror: enabled" in result.stdout

        result = run_cli(config_dir, "storage", "mirror", "disable")
        assert result.returncode == 0
        assert "Mirror: disabled" in run_cli(config_dir, "storage", "status").stdout

    def test_status_json_includes_mirror(self, storage_env) -> None:
        config_dir, *_ = storage_env
        result = run_cli(config_dir, "--format", "json", "storage", "status")
        assert result.returncode == 0
        assert json.loads(result.stdout.strip().splitlines()[-1])["mirror_audio_files"] is False

    def test_download_missing_without_config_is_a_noop(self, storage_env) -> None:
        config_dir, *_ = storage_env
        result = run_cli(config_dir, "storage", "download-missing")
        assert result.returncode == 0, result.stderr
        assert "nothing to download" in result.stdout


class TestOnDemandDownloadCommands:
    def test_audiofile_download_pending_record(self, storage_env) -> None:
        config_dir, _, _, audio_id = storage_env
        result = run_cli(config_dir, "audiofile-download", audio_id)
        assert result.returncode == 0, result.stderr
        assert "not been uploaded" in result.stdout

    def test_audiofile_download_already_local(self, storage_env) -> None:
        config_dir, audio_dir, _, audio_id = storage_env
        (audio_dir / local_name_of(config_dir, audio_id)).write_bytes(b"x")
        result = run_cli(config_dir, "audiofile-download", audio_id)
        assert result.returncode == 0, result.stderr
        assert "already on this device" in result.stdout

    def test_audiofile_download_unknown_id(self, storage_env) -> None:
        config_dir, *_ = storage_env
        result = run_cli(config_dir, "audiofile-download", "00000000000070008000000000000099")
        assert result.returncode == 1
        assert "not found" in result.stderr

    def test_note_audiofiles_download_pending(self, storage_env) -> None:
        config_dir, _, note_id, _ = storage_env
        result = run_cli(config_dir, "note-audiofiles-download", note_id)
        assert result.returncode == 0, result.stderr
        assert "not uploaded by their device yet" in result.stdout

    def test_note_audiofiles_download_in_cloud_without_config_fails_clearly(self, storage_env) -> None:
        config_dir, _, note_id, audio_id = storage_env
        db = Database(Path(Config(config_dir=config_dir).get("database_file")))
        db.update_audio_file_storage(audio_id, "s3", f"audio/{audio_id}.mp3")
        db.close()

        result = run_cli(config_dir, "note-audiofiles-download", note_id)
        assert result.returncode == 1
        assert "not configured" in result.stderr


class TestAudiofileShowMediaStatus:
    def test_show_reports_pending_and_missing(self, storage_env) -> None:
        config_dir, _, _, audio_id = storage_env
        result = run_cli(config_dir, "audiofile-show", audio_id)
        assert result.returncode == 0, result.stderr
        assert "Cloud storage: not uploaded yet" in result.stdout
        assert "not on this device" in result.stdout

    def test_show_reports_the_local_path_the_row_names(self, storage_env) -> None:
        config_dir, audio_dir, _, audio_id = storage_env
        name = local_name_of(config_dir, audio_id)
        (audio_dir / name).write_bytes(b"x")
        result = run_cli(config_dir, "audiofile-show", audio_id)
        # An imported file keeps its own name, extension case and all (FILE-15)
        assert name == "הקלטה.MP3"
        assert name in result.stdout
        assert "not on this device" not in result.stdout

    def test_list_reports_media_status(self, storage_env) -> None:
        config_dir, _, note_id, _ = storage_env
        result = run_cli(config_dir, "note-audiofiles-list", "--note-id", note_id)
        assert result.returncode == 0, result.stderr
        assert "Media: not on this device, not uploaded by its device yet" in result.stdout

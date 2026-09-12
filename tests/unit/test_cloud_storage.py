"""Unit tests for on-demand cloud storage helpers.

These tests never touch the network: they exercise the local decision logic
(where is the media? what would be downloaded?) and the paths that must work
without cloud credentials being present on the device.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.audiofile_manager import AudioFileManager
from core.cloud_storage import (
    STATUS_IN_CLOUD,
    STATUS_LOCAL,
    STATUS_PENDING,
    DownloadResult,
    audio_file_status,
    describe_download_result,
    download_audio_file,
    download_audio_files_for_note,
    download_missing_audio_files,
    missing_audio_files,
)
from core.config import Config
from core.database import Database, set_local_device_id

TEST_DEVICE_ID = "00000000000070008000000000000001"


@pytest.fixture
def cloud_env(test_config_dir: Path, tmp_path: Path):
    """Config + database + audio directory wired together like a real install."""
    set_local_device_id(TEST_DEVICE_ID)
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    config = Config(config_dir=test_config_dir)
    config.set_audiofile_directory(str(audio_dir))
    db = Database(Path(config.get("database_file")))
    yield config, db, audio_dir
    db.close()


def _record(db: Database, filename: str, in_cloud: bool) -> dict:
    audio_id = db.create_audio_file(filename, None)
    if in_cloud:
        db.update_audio_file_storage(audio_id, "s3", f"audio/{audio_id}.x")
    return db.get_audio_file(audio_id)


class TestAudioFileStatus:
    def test_local_file_wins(self, cloud_env) -> None:
        _, db, audio_dir = cloud_env
        af = _record(db, "הקלטה.MP3", in_cloud=True)
        # File written with the shared lowercase-extension rule
        (audio_dir / f"{af['id']}.mp3").write_bytes(b"x")
        assert audio_file_status(af, audio_dir) == STATUS_LOCAL

    def test_uppercase_extension_record_is_found(self, cloud_env) -> None:
        """Regression: REC.MP3 must resolve to <id>.mp3 on disk."""
        _, db, audio_dir = cloud_env
        af = _record(db, "REC.MP3", in_cloud=False)
        (audio_dir / f"{af['id']}.mp3").write_bytes(b"x")
        assert AudioFileManager(audio_dir).record_file_exists(af)
        assert audio_file_status(af, audio_dir) == STATUS_LOCAL

    def test_in_cloud_when_missing_locally(self, cloud_env) -> None:
        _, db, audio_dir = cloud_env
        af = _record(db, "meeting.ogg", in_cloud=True)
        assert audio_file_status(af, audio_dir) == STATUS_IN_CLOUD

    def test_pending_when_nowhere(self, cloud_env) -> None:
        _, db, audio_dir = cloud_env
        af = _record(db, "פגישה.wav", in_cloud=False)
        assert audio_file_status(af, audio_dir) == STATUS_PENDING


class TestMissingAudioFiles:
    def test_split_by_fetchability(self, cloud_env) -> None:
        _, db, audio_dir = cloud_env
        local = _record(db, "a.mp3", in_cloud=True)
        (audio_dir / f"{local['id']}.mp3").write_bytes(b"x")
        cloud = _record(db, "b.mp3", in_cloud=True)
        pending = _record(db, "c.mp3", in_cloud=False)

        missing = missing_audio_files([local, cloud, pending], audio_dir)
        assert [af["id"] for af in missing[STATUS_IN_CLOUD]] == [cloud["id"]]
        assert [af["id"] for af in missing[STATUS_PENDING]] == [pending["id"]]

    def test_no_audio_directory_means_nothing_is_fetchable(self, cloud_env) -> None:
        _, db, _ = cloud_env
        cloud = _record(db, "b.mp3", in_cloud=True)
        missing = missing_audio_files([cloud], None)
        assert missing == {STATUS_IN_CLOUD: [], STATUS_PENDING: []}


class TestDownloadWithoutNetwork:
    def test_download_pending_record_reports_not_in_cloud(self, cloud_env) -> None:
        config, db, _ = cloud_env
        af = _record(db, "pending.mp3", in_cloud=False)
        result = download_audio_file(af["id"], config.get_config_dir())
        assert result["status"] == "not_in_cloud"

    def test_download_local_record_is_noop(self, cloud_env) -> None:
        config, db, audio_dir = cloud_env
        af = _record(db, "local.mp3", in_cloud=True)
        (audio_dir / f"{af['id']}.mp3").write_bytes(b"x")
        result = download_audio_file(af["id"], config.get_config_dir())
        assert result["status"] == "already_local"

    def test_download_in_cloud_without_config_is_a_clear_error(self, cloud_env) -> None:
        config, db, _ = cloud_env
        af = _record(db, "remote.mp3", in_cloud=True)
        with pytest.raises(RuntimeError) as excinfo:
            download_audio_file(af["id"], config.get_config_dir())
        assert "not configured" in str(excinfo.value)

    def test_download_unknown_id_is_an_error(self, cloud_env) -> None:
        config, _, _ = cloud_env
        with pytest.raises(RuntimeError):
            download_audio_file("00000000000070008000000000000099", config.get_config_dir())

    def test_download_for_note_with_only_pending_files_needs_no_config(self, cloud_env) -> None:
        config, db, _ = cloud_env
        note_id = db.create_note("פתק עם הקלטה שעדיין לא הועלתה")
        af = _record(db, "pending.mp3", in_cloud=False)
        db.attach_to_note(note_id, af["id"], "audio_file")

        result = download_audio_files_for_note(note_id, config.get_config_dir())
        assert isinstance(result, DownloadResult)
        assert result.not_in_cloud == 1
        assert result.downloaded == 0
        assert result.failed == 0
        assert result.errors == []

    def test_download_for_note_with_local_files_needs_no_config(self, cloud_env) -> None:
        config, db, audio_dir = cloud_env
        note_id = db.create_note("note")
        af = _record(db, "local.mp3", in_cloud=True)
        (audio_dir / f"{af['id']}.mp3").write_bytes(b"x")
        db.attach_to_note(note_id, af["id"], "audio_file")

        result = download_audio_files_for_note(note_id, config.get_config_dir())
        assert result.already_local == 1
        assert result.failed == 0

    def test_download_for_note_in_cloud_without_config_is_an_error(self, cloud_env) -> None:
        config, db, _ = cloud_env
        note_id = db.create_note("note")
        af = _record(db, "remote.mp3", in_cloud=True)
        db.attach_to_note(note_id, af["id"], "audio_file")
        with pytest.raises(RuntimeError):
            download_audio_files_for_note(note_id, config.get_config_dir())

    def test_download_missing_without_config_is_a_silent_noop(self, cloud_env) -> None:
        config, db, _ = cloud_env
        _record(db, "remote.mp3", in_cloud=True)
        result = download_missing_audio_files(config.get_config_dir())
        assert result.downloaded == 0
        assert result.errors == []

    def test_download_requires_audio_directory(self, test_config_dir: Path) -> None:
        set_local_device_id(TEST_DEVICE_ID)
        config = Config(config_dir=test_config_dir)  # no audiofile_directory
        with pytest.raises(RuntimeError) as excinfo:
            download_missing_audio_files(config.get_config_dir())
        assert "Audiofile directory not configured" in str(excinfo.value)


class TestUploadPendingSkipsForeignRecords:
    def test_records_without_local_file_are_skipped_not_failed(self, cloud_env) -> None:
        """A record synced from another device must not be treated as an error here."""
        import json

        from voicecore import upload_pending_audio_files

        config, db, _ = cloud_env
        _record(db, "on-another-device.mp3", in_cloud=False)
        db.set_file_storage_config("s3", json.dumps({
            "bucket": "b", "region": "us-east-1",
            "access_key_id": "k", "secret_access_key": "s",
        }))

        result = upload_pending_audio_files(str(config.get_config_dir()))
        assert result.skipped == 1
        assert result.uploaded == 0
        assert result.failed == 0
        assert result.deferred == 0
        assert result.errors == []


class TestDescribeDownloadResult:
    def test_describes_each_counter(self, cloud_env) -> None:
        config, db, _ = cloud_env
        note_id = db.create_note("note")
        af = _record(db, "pending.mp3", in_cloud=False)
        db.attach_to_note(note_id, af["id"], "audio_file")
        result = download_audio_files_for_note(note_id, config.get_config_dir())
        text = describe_download_result(result)
        assert "1 not uploaded by their device yet" in text

    def test_nothing_to_download(self, cloud_env) -> None:
        config, db, _ = cloud_env
        note_id = db.create_note("note without audio")
        result = download_audio_files_for_note(note_id, config.get_config_dir())
        assert describe_download_result(result) == "nothing to download"

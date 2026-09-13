"""The command line: issues, removing this device's copy, the upload limit,
and where the copies are in a recording's details (ISSUE-1, FILE-22, FILE-23)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.database import Database

PROJECT = Path(__file__).parent.parent.parent


@pytest.fixture
def device(tmp_path: Path):
    config_dir = tmp_path / "voice"
    config_dir.mkdir()
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({"database_file": str(config_dir / "notes.db"), "audiofile_directory": str(audio_dir)}))
    return config_dir, audio_dir


def cli(config_dir: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "VOICE_CONFIG_DIR": str(config_dir), "PYTHONPATH": str(PROJECT)}
    return subprocess.run([sys.executable, "-m", "src.main", "cli", *args], capture_output=True, text=True, env=env, cwd=str(PROJECT), timeout=120)


def with_db(config_dir: Path, action):
    db = Database(config_dir / "notes.db")
    try:
        return action(db)
    finally:
        db.close()


def test_issues_lists_each_kind_in_words_and_as_json(device) -> None:
    config_dir, audio_dir = device
    assert cli(config_dir, "issues").stdout.strip().endswith("Nothing needs your attention.")

    def make(db: Database):
        audio_id = db.create_audio_file("בלי פתק.ogg", 1735689600)
        (audio_dir / db.get_audio_file(audio_id)["disk_name"]).write_bytes(b"abc")
        # As an import does: the hash, and with it the size
        db.store_content_hash(audio_id, audio_dir)
        db.create_tag("פגישת צוות", None)
        return audio_id

    audio_id = with_db(config_dir, make)
    text = cli(config_dir, "issues")
    assert text.returncode == 0, text.stderr
    assert "Recordings not in cloud storage (1)" in text.stdout
    assert "בלי פתק.ogg (3 bytes): no bucket is set up for the account" in text.stdout
    assert "Recordings no note holds (1)" in text.stdout
    assert "Tags whose names contain spaces (1)" in text.stdout and "פגישת צוות" in text.stdout

    as_json = cli(config_dir, "--format", "json", "issues")
    assert as_json.returncode == 0, as_json.stderr
    data = json.loads(as_json.stdout.splitlines()[-1] if as_json.stdout.strip().startswith("Using") else as_json.stdout[as_json.stdout.index("{"):])
    assert data["count"] == 3
    assert data["recordings_not_in_cloud"][0]["audio_id"] == audio_id


def test_a_copy_is_removed_from_this_device_only_when_another_place_holds_it(device) -> None:
    config_dir, audio_dir = device

    def make(db: Database):
        audio_id = db.create_audio_file("יחיד.ogg", 1735689600)
        (audio_dir / db.get_audio_file(audio_id)["disk_name"]).write_bytes(b"only copy")
        return audio_id, db.get_audio_file(audio_id)["disk_name"]

    audio_id, disk_name = with_db(config_dir, make)
    refused = cli(config_dir, "audiofile-remove-local", audio_id)
    assert refused.returncode == 1
    assert "on this device only" in refused.stderr
    assert (audio_dir / disk_name).exists()

    with_db(config_dir, lambda db: db.update_audio_file_storage(audio_id, "s3", "k.ogg"))
    shown = cli(config_dir, "audiofile-show", audio_id)
    assert "Copies:" in shown.stdout and "the bucket: holds it" in shown.stdout

    removed = cli(config_dir, "audiofile-remove-local", audio_id)
    assert removed.returncode == 0, removed.stderr
    assert "it is still in the bucket" in removed.stdout
    assert not (audio_dir / disk_name).exists()
    shown = cli(config_dir, "audiofile-show", audio_id)
    assert "this device: does not hold it" in shown.stdout


def test_the_upload_limit_is_shown_and_set_once_a_bucket_exists(device) -> None:
    config_dir, _ = device
    assert "Upload limit: 100 MB" in cli(config_dir, "storage", "upload-limit").stdout
    refused = cli(config_dir, "storage", "upload-limit", "250")
    assert refused.returncode == 1 and "No bucket" in refused.stderr
    with_db(config_dir, lambda db: db.set_file_storage_config("s3", json.dumps({"bucket": "voice-abc", "region": "eu-central-1", "access_key_id": "k", "secret_access_key": "s"})))
    assert cli(config_dir, "storage", "upload-limit", "250").returncode == 0
    assert "Upload limit: 250 MB for every device of the account" in cli(config_dir, "storage", "upload-limit").stdout

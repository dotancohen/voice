"""The web interface: issues, where a recording's copies are, removing this
device's copy, and the account's upload limit (ISSUE-1, FILE-22, FILE-23)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import Config
from core.database import Database
from src.web import create_app


@pytest.fixture
def setup(tmp_path: Path):
    config_dir = tmp_path / "voice"
    config_dir.mkdir()
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    config = Config(config_dir=config_dir)
    config.set_audiofile_directory(str(audio_dir))
    db = Database(Path(config._rust_config.get_database_file()))
    app = create_app(config_dir=config_dir)
    app.config["TESTING"] = True
    yield app.test_client(), db, audio_dir
    db.close()


def test_issues_locations_removal_and_the_upload_limit(setup) -> None:
    client, db, audio_dir = setup
    audio_id = db.create_audio_file("הקלטה.ogg", 1735689600)
    db.attach_to_note(db.create_note("פתק"), audio_id, "audio_file")
    disk_name = db.get_audio_file(audio_id)["disk_name"]
    (audio_dir / disk_name).write_bytes(b"sound")

    issues = client.get("/api/issues")
    assert issues.status_code == 200
    assert [r["reason"] for r in issues.get_json()["recordings_not_in_cloud"]] == ["no_bucket"]

    assert client.get(f"/api/audiofiles/{'0' * 12}7{'0' * 19}/locations").status_code == 404
    refused = client.post(f"/api/audiofiles/{audio_id}/remove-local")
    assert refused.status_code == 409
    assert "on this device only" in refused.get_json()["error"]
    assert (audio_dir / disk_name).exists()

    db.update_audio_file_storage(audio_id, "s3", "k.ogg")
    removed = client.post(f"/api/audiofiles/{audio_id}/remove-local")
    assert removed.status_code == 200, removed.get_json()
    assert not (audio_dir / disk_name).exists()
    located = client.get(f"/api/audiofiles/{audio_id}/locations").get_json()["locations"]
    assert {(l["place"], l["present"]) for l in located} >= {("cloud", True)}
    assert any(not l["present"] for l in located), "this device states that it no longer holds it"

    assert client.get("/api/storage/upload-limit").get_json() == {"max_upload_mb": 100}
    assert client.put("/api/storage/upload-limit", json={"megabytes": "many"}).status_code == 400
    db.set_file_storage_config("s3", json.dumps({"bucket": "voice-abc", "region": "eu-central-1", "access_key_id": "k", "secret_access_key": "s"}))
    changed = client.put("/api/storage/upload-limit", json={"megabytes": 250})
    assert changed.status_code == 200 and changed.get_json() == {"max_upload_mb": 250}

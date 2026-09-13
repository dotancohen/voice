"""Where the copies of a recording are (FILE-22), the account's upload limit
(FILE-23) and the Issues list (ISSUE-1), through the desktop's database class."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.database import Database

HERE = "01a09526bbbb70808f15a84d31aaa8d2"
PHONE = "01a0952602bc70808f15a84d31aaa8d2"


@pytest.fixture
def audio_dir(tmp_path: Path) -> Path:
    path = tmp_path / "audio"
    path.mkdir()
    return path


def recording(db: Database, audio_dir: Path, name: str, content: bytes, in_note: bool = True) -> str:
    audio_id = db.create_audio_file(name, 1735689600)
    if in_note:
        db.attach_to_note(db.create_note(""), audio_id, "audio_file")
    (audio_dir / db.get_audio_file(audio_id)["disk_name"]).write_bytes(content)
    db.store_content_hash(audio_id, audio_dir)
    return audio_id


def places(db: Database, audio_id: str) -> dict:
    return {loc["place"]: loc["present"] for loc in db.file_locations(audio_id)}


def test_the_folder_is_compared_and_a_copy_is_removed_only_when_another_place_holds_it(empty_db: Database, audio_dir: Path) -> None:
    audio_id = recording(empty_db, audio_dir, "הקלטה ביום הולדת.m4a", b"voice" * 100)
    assert empty_db.check_files_here(audio_dir, HERE) == (1, 0)
    assert places(empty_db, audio_id) == {HERE: True}

    with pytest.raises(Exception, match="on this device only"):
        empty_db.remove_local_copy(audio_id, audio_dir, HERE)
    assert (audio_dir / empty_db.get_audio_file(audio_id)["disk_name"]).exists()

    empty_db.update_audio_file_storage(audio_id, "s3", "k.m4a")
    assert places(empty_db, audio_id) == {"cloud": True, HERE: True}
    empty_db.remove_local_copy(audio_id, audio_dir, HERE)
    assert places(empty_db, audio_id) == {"cloud": True, HERE: False}
    assert not (audio_dir / empty_db.get_audio_file(audio_id)["disk_name"]).exists()
    assert empty_db.get_audio_file(audio_id) is not None, "the recording stays"


def test_a_file_deleted_by_hand_is_stated_gone_and_a_missing_folder_says_nothing(empty_db: Database, audio_dir: Path, tmp_path: Path) -> None:
    audio_id = recording(empty_db, audio_dir, "נמחק ביד.ogg", b"x" * 50)
    empty_db.check_files_here(audio_dir, HERE)
    (audio_dir / empty_db.get_audio_file(audio_id)["disk_name"]).unlink()
    assert empty_db.check_files_here(tmp_path / "unmounted card", HERE) == (0, 0)
    assert places(empty_db, audio_id) == {HERE: True}
    assert empty_db.check_files_here(audio_dir, HERE) == (0, 1)
    assert places(empty_db, audio_id) == {HERE: False}


def test_the_upload_limit_is_the_accounts_and_the_issues_give_each_reason(empty_db: Database, audio_dir: Path) -> None:
    assert empty_db.max_upload_bytes() == 100 * 1024 * 1024
    big = recording(empty_db, audio_dir, "שיעור ארוך.wav", b"\0" * (1024 * 1024 + 1))
    small = recording(empty_db, audio_dir, "פתק.ogg", b"\1" * 100)
    loose = recording(empty_db, audio_dir, "בלי פתק.ogg", b"\2" * 10, in_note=False)
    empty_db.create_tag("פגישת צוות", None)

    no_bucket = empty_db.issues(audio_dir, HERE)
    assert {r["reason"] for r in no_bucket["recordings_not_in_cloud"]} == {"no_bucket"}

    with pytest.raises(Exception):
        empty_db.set_max_upload_mb(1)
    empty_db.set_file_storage_config("s3", json.dumps({"bucket": "voice-abc", "region": "eu-central-1", "access_key_id": "k", "secret_access_key": "s"}))
    empty_db.set_max_upload_mb(1)
    assert empty_db.max_upload_bytes() == 1024 * 1024

    found = empty_db.issues(audio_dir, HERE)
    reasons = {r["audio_id"]: r["reason"] for r in found["recordings_not_in_cloud"]}
    assert reasons == {big: "too_large", small: "waiting_for_upload", loose: "waiting_for_upload"}
    assert [r["audio_id"] for r in found["orphaned_recordings"]] == [loose]
    assert [t["name"] for t in found["tags_with_whitespace"]] == ["פגישת צוות"]
    assert found["count"] == 5
    assert found["max_upload_bytes"] == 1024 * 1024

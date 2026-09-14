"""Where the copies of a recording are (FILE-22), the account's upload limit
(FILE-23) and the Issues list (ISSUE-1), through the desktop's database class."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.database import Database
from tests.fake_s3 import TEST_BUCKET, TEST_KEY_ID, TEST_SECRET, FakeS3, bucket_holding

HERE = "01a09526bbbb70808f15a84d31aaa8d2"
PHONE = "01a0952602bc70808f15a84d31aaa8d2"


@pytest.fixture
def audio_dir(tmp_path: Path) -> Path:
    path = tmp_path / "audio"
    path.mkdir()
    return path


@pytest.fixture
def s3():
    fake = FakeS3(TEST_KEY_ID, TEST_SECRET).start()
    yield fake
    fake.stop()


def recording(db: Database, audio_dir: Path, name: str, content: bytes, in_note: bool = True, here: str = HERE) -> str:
    audio_id = db.create_audio_file(name, 1735689600)
    if in_note:
        db.attach_to_note(db.create_note(""), audio_id, "audio_file")
    (audio_dir / db.get_audio_file(audio_id)["disk_name"]).write_bytes(content)
    db.store_content_hash(audio_id, audio_dir, here)
    return audio_id


def places(db: Database, audio_id: str) -> dict:
    return {loc["place"]: loc["present"] for loc in db.file_locations(audio_id)}


def test_a_copy_is_removed_only_when_the_bucket_confirms_now_that_it_holds_the_file(test_config, audio_dir: Path, s3: FakeS3) -> None:
    """FILE-26: what the rows say is not enough. The bucket is asked; an object
    that is not there, or waits for the lifecycle rule, confirms nothing, and
    the copy stays with the reason. The removal runs through the sync client,
    which opens the configuration's database, so the test uses that one."""
    from voicecore import SyncClient

    test_config.set_audiofile_directory(str(audio_dir))
    here = test_config.get_device_id_hex()
    db = Database(Path(test_config._rust_config.get_database_file()))
    try:
        audio_id = recording(db, audio_dir, "הקלטה ביום הולדת.m4a", b"voice" * 100, here=here)
        path = audio_dir / db.get_audio_file(audio_id)["disk_name"]
        assert places(db, audio_id) == {here: True}, "hashing the file states this device's copy"
        client = SyncClient(str(test_config.get_config_dir()))
        with pytest.raises(Exception, match="no other place is known to hold it"):
            client.remove_local_copy(audio_id)

        key = bucket_holding(s3, db, audio_id, path, here)
        del s3.buckets[TEST_BUCKET][key]
        with pytest.raises(Exception, match="the bucket does not hold it"):
            client.remove_local_copy(audio_id)
        assert places(db, audio_id) == {"cloud": False, here: True}, "the bucket's answer is stated"
        assert path.exists()

        other = recording(db, audio_dir, "ממתינה למחיקה.ogg", b"other" * 50, here=here)
        other_key = bucket_holding(s3, db, other, audio_dir / db.get_audio_file(other)["disk_name"], here)
        s3.tags.setdefault(TEST_BUCKET, {})[other_key] = {"voice-purged": "1"}
        with pytest.raises(Exception, match="the bucket does not hold it"):
            client.remove_local_copy(other)

        bucket_holding(s3, db, audio_id, path, here)
        assert client.remove_local_copy(audio_id) == f"Removed {path.name} from this device; the bucket holds it"
        assert places(db, audio_id) == {"cloud": True, here: False}
        assert not path.exists()
        assert db.get_audio_file(audio_id) is not None, "the recording stays"
    finally:
        db.close()


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

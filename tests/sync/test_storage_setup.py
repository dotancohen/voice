"""The bucket wizard (Stage 8, Stage 14), driven against a small S3 in a
thread: the key cleaned, the bucket made private, hardened and given its
rules, the round trip, the save that reaches every device by sync, the
failures in words, and a key replaced."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.database import Database
from core.storage_setup import SetupState, checklist, create_bucket, harden, policy_text, replace_key, round_trip, save, saved_state, set_lifecycle, take_key
from tests.fake_s3 import FakeS3

KEY_ID = "AKIAIOSFODNN7EXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
PROJECT = Path(__file__).parent.parent.parent


@pytest.fixture
def s3():
    fake = FakeS3(KEY_ID, SECRET).start()
    yield fake
    fake.stop()


def state_for(s3: FakeS3, bucket: str = "voice-abc123") -> SetupState:
    state = SetupState(region="us-east-1", bucket=bucket, endpoint=s3.endpoint)
    assert take_key(state, f"Access key ID: {KEY_ID} ", f" {SECRET}\n") is None
    return state


class TestTheWizardSteps:
    def test_the_policy_never_deletes_and_the_pasted_key_is_cleaned(self) -> None:
        assert "Delete" not in policy_text()
        state = SetupState(endpoint="http://127.0.0.1:1")
        assert take_key(state, "", SECRET) == "The access key id is empty."
        assert take_key(state, KEY_ID, "") == "The secret access key is empty."
        amazon = SetupState()
        assert "AKIA" in take_key(amazon, "short", SECRET)
        assert take_key(amazon, f"Access key ID: {KEY_ID}", SECRET) is None
        assert amazon.access_key_id == KEY_ID

    def test_the_bucket_is_made_private_hardened_ruled_and_proven(self, s3: FakeS3, empty_db: Database) -> None:
        state = state_for(s3)
        assert create_bucket(state) is None
        assert state.created and "voice-abc123" in s3.buckets
        rows = harden(state)
        assert [(r["name"], r["passed"]) for r in rows] == [("Public access blocked", True), ("Encrypted at rest", True), ("TLS only", True)]
        assert "<BlockPublicAcls>true</BlockPublicAcls>" in s3.settings["voice-abc123"]["publicAccessBlock"]
        assert "AES256" in s3.settings["voice-abc123"]["encryption"]
        assert "aws:SecureTransport" in s3.settings["voice-abc123"]["policy"]
        assert set_lifecycle(state) is None
        lifecycle = s3.settings["voice-abc123"]["lifecycle"]
        assert "STANDARD_IA" in lifecycle and "voice-purged" in lifecycle and "DaysAfterInitiation" in lifecycle
        assert round_trip(state) is None
        assert state.round_trip_key.startswith("voice-setup-check-")
        assert s3.tags["voice-abc123"][state.round_trip_key] == {"voice-purged": "1"}, "the check object is tagged, since the key cannot delete"
        assert not s3.deleted_anything()

        save(state, empty_db)
        saved = saved_state(empty_db)
        assert saved is not None and saved.bucket == "voice-abc123" and saved.access_key_id == KEY_ID and saved.endpoint == s3.endpoint

    def test_a_taken_name_gets_a_suggestion_and_a_wrong_secret_is_explained(self, s3: FakeS3) -> None:
        s3.taken_names.add("voice-taken1")
        state = state_for(s3, "voice-taken1")
        problem = create_bucket(state)
        assert problem is not None and "taken" in problem and "Try voice-" in problem
        assert create_bucket(state_for(s3, "notes")) is not None, "a name outside voice- is refused before any request"

        wrong = state_for(s3)
        wrong.secret_access_key = "not-the-secret"
        problem = round_trip(wrong)
        assert problem is not None and "secret" in problem and "wrong" in problem, problem

    def test_the_key_is_replaced_after_a_round_trip_and_the_checklist_reads_the_state(self, s3: FakeS3, test_config, empty_db: Database) -> None:
        state = state_for(s3)
        assert create_bucket(state) is None
        save(state, empty_db)
        assert replace_key(empty_db, "  AKIANEWKEY000000000  ", "new-secret") is not None, "the new key must pass the round trip first"
        s3.access_key_id, s3.secret_access_key = "AKIANEWKEY000000000A", "new-secret"
        assert replace_key(empty_db, "AKIANEWKEY000000000A", "new-secret") is None
        assert saved_state(empty_db).access_key_id == "AKIANEWKEY000000000A"

        rows = {r["name"]: r for r in checklist(test_config, empty_db, listening=False)}
        assert rows["Bucket"]["done"] and "voice-abc123" in rows["Bucket"]["detail"]
        assert not rows["Paired devices"]["done"] and rows["Paired devices"]["action"] == "show_code"
        assert not rows["Listener"]["done"] and rows["Listener"]["action"] == "listen"
        assert rows["Not duplicated"]["done"]
        assert not rows["Last exchange"]["done"]

    def test_a_large_recording_goes_up_in_parts_and_a_dropped_part_is_the_only_one_sent_again(self, s3: FakeS3, test_config, test_config_dir: Path) -> None:
        """FILE-19: a file larger than one part is uploaded in parts through
        the bucket's three requests; the part that failed is sent again at the
        next upload and the parts already there are not; the object is the
        whole file, keyed by its content hash (FILE-18)."""
        from voicecore import upload_pending_audio_files

        empty_db = Database(Path(test_config._rust_config.get_database_file()))  # the one the upload opens by the configuration
        state = state_for(s3)
        assert create_bucket(state) is None
        save(state, empty_db)
        audio_dir = test_config_dir / "audio"
        audio_dir.mkdir()
        test_config.set_audiofile_directory(str(audio_dir))
        audio_id = empty_db.create_audio_file("שיעור.ogg", 1735689600)
        row = empty_db.get_audio_file(audio_id)
        one_mib = 1024 * 1024
        content = bytes(range(256)) * (9 * one_mib // 256)  # 9 MiB: a full part and a short one
        (audio_dir / row["local_name"]).write_bytes(content)
        content_hash = empty_db.store_content_hash(audio_id, audio_dir)

        s3.fail_part = 2
        first = upload_pending_audio_files(str(test_config_dir))
        assert (first.uploaded, first.failed) == (0, 1), first.errors
        assert "voice-abc123" in s3.buckets and not s3.buckets["voice-abc123"], "no object until every part is there"
        assert empty_db.get_audio_file(audio_id)["storage_key"] is None

        second = upload_pending_audio_files(str(test_config_dir))
        assert (second.uploaded, second.failed) == (1, 0), second.errors
        key = f"{content_hash}.ogg"
        assert s3.buckets["voice-abc123"][key] == content
        assert empty_db.get_audio_file(audio_id)["storage_key"] == key
        part_puts = [q for m, _, k, q in s3.requests if m == "PUT" and k == key and "partNumber" in q]
        assert len(part_puts) == 3, "part 1 once, part 2 twice (the dropped one and its retry); never part 1 again"
        assert [m for m, _, _, q in s3.requests if m == "POST" and "uploads" in q].count("POST") == 1, "one upload begun, continued at the second run"
        assert not s3.deleted_anything()
        empty_db.close()


@pytest.mark.cli
class TestFromTheCommandLine:
    def test_storage_setup_and_check_run_without_questions_when_everything_is_given(self, s3: FakeS3, tmp_path: Path) -> None:
        env = {**os.environ, "VOICE_CONFIG_DIR": str(tmp_path), "PYTHONPATH": str(PROJECT)}
        result = subprocess.run(
            [sys.executable, "-m", "src.main", "cli", "--format", "json", "storage", "setup",
             "--access-key-id", KEY_ID, "--secret-access-key", SECRET, "--region", "us-east-1", "--bucket", "voice-cli001", "--endpoint", s3.endpoint, "--yes"],
            capture_output=True, text=True, env=env, cwd=str(PROJECT), timeout=120,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        report = json.loads(result.stdout)
        assert report["saved"] and report["bucket"] == "voice-cli001"
        assert all(r["passed"] for r in report["hardened"])
        assert "voice-cli001" in s3.buckets

        check = subprocess.run([sys.executable, "-m", "src.main", "cli", "--format", "json", "storage", "check"], capture_output=True, text=True, env=env, cwd=str(PROJECT), timeout=120)
        assert check.returncode == 0, check.stderr + check.stdout
        rows = {r["name"]: r["passed"] for r in json.loads(check.stdout)}
        assert rows == {"Bucket": True, "Round trip": True, "Public access blocked": True, "Encrypted at rest": True, "TLS only": True, "Lifecycle rules": True}

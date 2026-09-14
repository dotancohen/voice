"""Cloud storage against a real S3 server on this machine.

The server is moto's (tests/local_s3.py), reached over TCP exactly as Amazon
is reached, with authentication on: every request is signed with a key made in
its IAM, and a wrong secret is refused. Each test takes a bucket of its own.

The happy paths: the setup wizard's steps, an upload and a download, an upload
in parts, an encrypted upload, and an object already in the bucket. The
failures of the bucket: no bucket, a wrong secret, an object that is gone, and
an object whose bytes are not the recording. The failures of the network, with
a `FaultyLink` between the device and the bucket: refused, answering 503,
cut in the middle of a part or a download, frozen, and slow.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest
from voicecore import download_audio_file_from_cloud, upload_pending_audio_files

from core.config import Config
from core.database import Database
from core.storage_setup import SetupState, check_all_paths, create_bucket, devices_of, harden, round_trip, save, set_lifecycle, take_key
from tests.faulty_network import FaultyLink
from tests.local_s3 import REGION

MIB = 1024 * 1024


@dataclass
class Device:
    """A device of the account with a bucket configured and an audio folder."""

    config_dir: Path
    config: Config
    db: Database
    audio_dir: Path
    bucket: str

    def recording(self, name: str, content: bytes) -> str:
        audio_id = self.db.create_audio_file(name, 1735689600)
        (self.audio_dir / self.db.get_audio_file(audio_id)["disk_name"]).write_bytes(content)
        self.db.store_content_hash(audio_id, self.audio_dir)
        return audio_id

    def path(self, audio_id: str) -> Path:
        return self.audio_dir / self.db.get_audio_file(audio_id)["disk_name"]

    def upload(self):
        return upload_pending_audio_files(str(self.config_dir))

    def download(self, audio_id: str):
        return download_audio_file_from_cloud(audio_id, str(self.config_dir))


def make_bucket(local_s3, secret: str = None) -> SetupState:
    state = SetupState(region=REGION, bucket=local_s3.new_bucket_name(), endpoint=local_s3.endpoint)
    assert take_key(state, local_s3.access_key_id, secret or local_s3.secret_access_key) is None
    return state


def device_with(state: SetupState, config_dir: Path) -> Device:
    config_dir.mkdir(parents=True, exist_ok=True)
    config = Config(config_dir=config_dir)
    audio_dir = config_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    config.set_audiofile_directory(str(audio_dir))
    db = Database(Path(config._rust_config.get_database_file()))
    save(state, db)
    return Device(config_dir, config, db, audio_dir, state.bucket)


@pytest.fixture
def device(local_s3, tmp_path: Path):
    """A device and an empty bucket the device reaches directly."""
    state = make_bucket(local_s3)
    assert create_bucket(state) is None
    assert set_lifecycle(state) is None
    dev = device_with(state, tmp_path / "device")
    yield dev
    dev.db.close()


@pytest.fixture
def linked_device(local_s3, tmp_path: Path):
    """A device that reaches its bucket only through a faulty link."""
    state = make_bucket(local_s3)
    assert create_bucket(state) is None
    link = FaultyLink(local_s3.port)
    state.endpoint = link.url
    dev = device_with(state, tmp_path / "device")
    yield dev, link
    link.stop()
    dev.db.close()


def within(seconds: float, operation: Callable):
    """Run the operation; fail the test if it has not ended in `seconds`.
    Returns (its result or the exception it raised, the seconds it took)."""
    box = {}

    def run():
        try:
            box["value"] = operation()
        except BaseException as e:  # noqa: BLE001 - handed back to the test
            box["value"] = e

    started = time.monotonic()
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    took = time.monotonic() - started
    if worker.is_alive():
        pytest.fail(f"Still running after {seconds:.0f} s: a dead link must end the operation, not hang it")
    # Taken out of the box: an exception's traceback holds `run`'s frame and the
    # frame holds `box`, so while `box` held the exception that cycle kept the
    # device's Database alive until the garbage collector's next run
    return box.pop("value"), took


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class TestTheWizardAgainstARealS3:
    def test_the_wizard_makes_a_private_hardened_bucket_with_its_rules(self, local_s3) -> None:
        state = make_bucket(local_s3)
        assert create_bucket(state) is None
        assert set_lifecycle(state) is None
        assert round_trip(state) is None, "a write, a read back and a tag on the new bucket"
        rows = harden(state)
        assert [r["name"] for r in rows] == ["Public access blocked", "Encrypted at rest", "TLS only"]
        assert all(r["passed"] for r in rows), rows
        s3 = local_s3.client()
        assert s3.get_public_access_block(Bucket=state.bucket)["PublicAccessBlockConfiguration"]["BlockPublicPolicy"] is True
        rules = {r["ID"] for r in s3.get_bucket_lifecycle_configuration(Bucket=state.bucket)["Rules"]}
        assert rules == {"voice-infrequent-access", "voice-purged", "voice-abandoned-uploads"}

    def test_after_hardening_a_write_without_tls_is_refused_and_the_wizard_says_why(self, local_s3) -> None:
        """The TLS-only policy is in force: this server speaks plain HTTP, so
        the round trip that worked before hardening is refused after it, and
        the wizard names the policy and the https:// address rather than
        blaming the secret."""
        state = make_bucket(local_s3)
        assert create_bucket(state) is None
        assert round_trip(state) is None
        assert all(r["passed"] for r in harden(state))
        refused = round_trip(state)
        assert refused is not None
        assert "accepts only https://" in refused, refused
        assert "secret may be wrong" not in refused

    def test_a_bucket_in_us_east_1_behind_an_endpoint_is_made(self, local_s3) -> None:
        """Amazon's first region takes no location constraint; behind an
        endpoint the wizard used to send one and be refused."""
        state = SetupState(region="us-east-1", bucket=local_s3.new_bucket_name(), endpoint=local_s3.endpoint)
        assert take_key(state, local_s3.access_key_id, local_s3.secret_access_key) is None
        assert create_bucket(state) is None
        assert local_s3.client().head_bucket(Bucket=state.bucket)["ResponseMetadata"]["HTTPStatusCode"] == 200
        assert round_trip(state) is None, "the new bucket takes a write, a read back and a tag"
        assert create_bucket(state) is None, "a bucket that is there already is taken as made"

    def test_a_wrong_secret_is_refused_in_words(self, local_s3) -> None:
        state = make_bucket(local_s3, secret="wJalrXUtnFEMI/K7MDENG/bPxRfiCYWRONGSECRET")
        problem = create_bucket(state)
        # The explanation, then the service's own words
        assert problem.startswith("The secret is wrong, or has a space on the end."), problem
        assert "SignatureDoesNotMatch" in problem, problem

    def test_the_bucket_check_of_a_saved_configuration_finds_the_bucket(self, device: Device) -> None:
        rows = {r["name"]: r for r in check_all_paths(str(device.config_dir), devices_of(device.config))}
        assert rows["Bucket: Bucket"]["passed"], rows
        assert rows["Bucket: Round trip"]["passed"], rows
        assert rows["Bucket: Lifecycle rules"]["passed"], rows


class TestUploadsAndDownloads:
    def test_a_recording_goes_up_whole_and_comes_back_whole(self, device: Device, local_s3) -> None:
        content = os.urandom(200_000)
        audio_id = device.recording("שיחה עם סבתא.m4a", content)
        result = device.upload()
        assert (result.uploaded, result.failed) == (1, 0), result.errors
        key = f"{sha256(content)}.m4a"
        assert local_s3.objects(device.bucket) == {key: content}
        assert device.db.get_audio_file(audio_id)["storage_key"] == key

        device.path(audio_id).unlink()
        assert device.download(audio_id) == {"status": "downloaded", "bytes": len(content)}
        assert device.path(audio_id).read_bytes() == content
        assert device.upload().uploaded == 0, "nothing is sent twice"

    def test_a_recording_larger_than_a_part_goes_up_in_parts(self, device: Device, local_s3) -> None:
        content = os.urandom(20 * MIB)
        audio_id = device.recording("הרצאה ארוכה.wav", content)
        result = device.upload()
        assert (result.uploaded, result.failed) == (1, 0), result.errors
        assert local_s3.objects(device.bucket)[f"{sha256(content)}.wav"] == content
        assert local_s3.unfinished_uploads(device.bucket) == []
        device.path(audio_id).unlink()
        assert device.download(audio_id)["status"] == "downloaded"
        assert device.path(audio_id).read_bytes() == content

    def test_an_encrypted_recording_is_stored_encrypted_and_comes_back_plain(self, device: Device, local_s3) -> None:
        from voicecore import recording_key_export, set_encryption_on

        recording_key_export(str(device.config_dir))
        set_encryption_on(True, str(device.config_dir))
        content = os.urandom(300_000)
        audio_id = device.recording("סוד.ogg", content)
        result = device.upload()
        assert (result.uploaded, result.failed) == (1, 0), result.errors
        stored = local_s3.objects(device.bucket)[f"{sha256(content)}.ogg.enc"]
        assert stored[:8] == b"VOICEENC" and content[:1000] not in stored
        device.path(audio_id).unlink()
        assert device.download(audio_id)["status"] == "downloaded"
        assert device.path(audio_id).read_bytes() == content

    def test_a_second_recording_with_the_same_bytes_makes_no_second_object(self, device: Device, local_s3) -> None:
        content = os.urandom(50_000)
        device.recording("ראשון.mp3", content)
        assert device.upload().uploaded == 1
        second = device.recording("שני.mp3", content)
        result = device.upload()
        assert (result.uploaded, result.failed) == (1, 0), result.errors
        assert list(local_s3.objects(device.bucket)) == [f"{sha256(content)}.mp3"]
        assert device.db.get_audio_file(second)["storage_key"] == f"{sha256(content)}.mp3"


class TestFailuresOfTheBucket:
    def test_a_bucket_that_does_not_exist_fails_the_upload_and_marks_nothing(self, local_s3, tmp_path: Path) -> None:
        state = make_bucket(local_s3)  # never created
        dev = device_with(state, tmp_path / "device")
        try:
            audio_id = dev.recording("אין דלי.ogg", os.urandom(10_000))
            result = dev.upload()
            assert (result.uploaded, result.failed) == (0, 1)
            assert result.errors
            assert dev.db.get_audio_file(audio_id)["storage_key"] is None
        finally:
            dev.db.close()

    def test_a_wrong_secret_fails_the_upload_and_marks_nothing(self, local_s3, tmp_path: Path) -> None:
        good = make_bucket(local_s3)
        assert create_bucket(good) is None
        bad = make_bucket(local_s3, secret="wJalrXUtnFEMI/K7MDENG/bPxRfiCYWRONGSECRET")
        bad.bucket = good.bucket
        dev = device_with(bad, tmp_path / "device")
        try:
            audio_id = dev.recording("מפתח שגוי.ogg", os.urandom(10_000))
            result = dev.upload()
            assert (result.uploaded, result.failed) == (0, 1)
            assert dev.db.get_audio_file(audio_id)["storage_key"] is None
            assert local_s3.objects(good.bucket) == {}
        finally:
            dev.db.close()

    def test_a_download_of_an_object_that_is_gone_says_so_and_leaves_no_file(self, device: Device, local_s3) -> None:
        content = os.urandom(40_000)
        audio_id = device.recording("נעלם.ogg", content)
        assert device.upload().uploaded == 1
        local_s3.client().delete_object(Bucket=device.bucket, Key=f"{sha256(content)}.ogg")
        device.path(audio_id).unlink()
        with pytest.raises(RuntimeError, match="not found|Not found|NotFound"):
            device.download(audio_id)
        assert not device.path(audio_id).exists()
        assert not Path(str(device.path(audio_id)) + ".part").exists()

    def test_a_download_whose_bytes_are_not_the_recording_is_removed(self, device: Device, local_s3) -> None:
        content = os.urandom(40_000)
        audio_id = device.recording("הוחלף.ogg", content)
        assert device.upload().uploaded == 1
        local_s3.client().put_object(Bucket=device.bucket, Key=f"{sha256(content)}.ogg", Body=b"something else entirely")
        device.path(audio_id).unlink()
        with pytest.raises(RuntimeError, match="not the recording"):
            device.download(audio_id)
        assert not device.path(audio_id).exists()


class TestTheBucketOverAFailingNetwork:
    def test_an_unreachable_bucket_fails_the_upload_after_three_tries_and_the_next_run_uploads(self, linked_device, local_s3) -> None:
        dev, link = linked_device
        content = os.urandom(30_000)
        audio_id = dev.recording("בלי רשת.ogg", content)
        link.refuse()
        result, took = within(150, dev.upload)
        assert (result.uploaded, result.failed) == (0, 1), result.errors
        # A refused connection is known at once: the second try comes straight
        # after the first, the third a minute later (FILE-14)
        assert 55 < took < 90, f"two tries at once and a third after a minute; it took {took:.1f} s"
        assert dev.db.get_audio_file(audio_id)["storage_key"] is None

        link.pass_through()
        assert dev.upload().uploaded == 1
        assert local_s3.objects(dev.bucket) == {f"{sha256(content)}.ogg": content}

    def test_a_part_refused_with_503_is_sent_again_and_the_parts_already_there_are_not(self, linked_device, local_s3) -> None:
        dev, link = linked_device
        content = os.urandom(20 * MIB)
        dev.recording("עומס.wav", content)
        key = f"{sha256(content)}.wav"
        link.answer(503, request=f"PUT /{dev.bucket}/{key}?partNumber=2".encode())
        first = dev.upload()
        assert (first.uploaded, first.failed) == (0, 1), first.errors
        assert local_s3.objects(dev.bucket) == {}, "no object until every part is there"
        sent_before = link.bytes_up

        link.pass_through()
        second = dev.upload()
        assert (second.uploaded, second.failed) == (1, 0), second.errors
        assert local_s3.objects(dev.bucket)[key] == content
        assert local_s3.unfinished_uploads(dev.bucket) == []
        assert link.bytes_up - sent_before < 16 * MIB, "part 1 was not sent again"

    def test_an_upload_cut_in_the_middle_of_a_part_completes_at_the_next_run(self, linked_device, local_s3) -> None:
        dev, link = linked_device
        content = os.urandom(20 * MIB)
        audio_id = dev.recording("נקטע.wav", content)
        link.cut_after(bytes_up=4 * MIB)
        first = dev.upload()
        assert (first.uploaded, first.failed) == (0, 1), first.errors
        assert dev.db.get_audio_file(audio_id)["storage_key"] is None

        link.pass_through()
        second = dev.upload()
        assert (second.uploaded, second.failed) == (1, 0), second.errors
        assert local_s3.objects(dev.bucket)[f"{sha256(content)}.wav"] == content
        assert local_s3.unfinished_uploads(dev.bucket) == []

    def test_an_upload_over_a_link_that_freezes_ends_in_bounded_time(self, linked_device, local_s3) -> None:
        dev, link = linked_device
        content = os.urandom(12 * MIB)
        audio_id = dev.recording("קפא.wav", content)
        link.freeze_after(bytes_up=3 * MIB)
        result, took = within(300, dev.upload)
        assert not isinstance(result, BaseException), result
        assert (result.uploaded, result.failed) == (0, 1)
        # Three tries, each ended by the stall timeout, the third a minute after the second (FILE-14)
        assert took < 210, f"a frozen link must end each try within the stall timeout; it took {took:.0f} s"
        assert dev.db.get_audio_file(audio_id)["storage_key"] is None

        link.pass_through()
        assert dev.upload().uploaded == 1
        assert local_s3.objects(dev.bucket)[f"{sha256(content)}.wav"] == content

    def test_a_download_cut_in_the_middle_leaves_no_file_and_the_next_download_is_whole(self, linked_device) -> None:
        dev, link = linked_device
        content = os.urandom(5 * MIB)
        audio_id = dev.recording("הורדה.ogg", content)
        assert dev.upload().uploaded == 1
        dev.path(audio_id).unlink()
        link.cut_after(bytes_down=MIB)
        with pytest.raises(RuntimeError):
            dev.download(audio_id)
        assert not dev.path(audio_id).exists(), "a file that did not arrive whole is not in its place"

        link.pass_through()
        assert dev.download(audio_id)["status"] == "downloaded"
        assert dev.path(audio_id).read_bytes() == content

    def test_a_download_over_a_link_that_freezes_ends_in_bounded_time(self, linked_device) -> None:
        dev, link = linked_device
        content = os.urandom(5 * MIB)
        audio_id = dev.recording("הורדה קפואה.ogg", content)
        assert dev.upload().uploaded == 1
        dev.path(audio_id).unlink()
        link.freeze_after(bytes_down=MIB)
        outcome, took = within(300, lambda: dev.download(audio_id))
        assert isinstance(outcome, RuntimeError), outcome
        # Three tries, each ended by the read timeout, the third a minute after the second (FILE-14)
        assert took < 210, f"a frozen link must end each try within the read timeout; it took {took:.0f} s"
        assert not dev.path(audio_id).exists()

        link.pass_through()
        assert dev.download(audio_id)["status"] == "downloaded"
        assert dev.path(audio_id).read_bytes() == content

    def test_a_part_over_a_link_slower_than_the_stall_timeout_uploads(self, linked_device, local_s3) -> None:
        """One part of eight megabytes over a slow uplink takes minutes while
        the bucket says nothing back; an upload that keeps moving is not a
        dead link."""
        dev, link = linked_device
        content = os.urandom(9 * MIB)
        dev.recording("העלאה איטית.wav", content)
        link.throttle(200_000)
        result, took = within(300, dev.upload)
        assert not isinstance(result, BaseException), result
        assert (result.uploaded, result.failed) == (1, 0), result.errors
        assert took > 35, f"the link was meant to be slower than the stall timeout; the upload took {took:.0f} s"
        assert local_s3.objects(dev.bucket)[f"{sha256(content)}.wav"] == content

    def test_a_bucket_that_never_answers_ends_the_upload_in_bounded_time(self, linked_device) -> None:
        dev, link = linked_device
        audio_id = dev.recording("דלי שותק.ogg", os.urandom(20_000))
        link.stall()
        result, took = within(480, dev.upload)
        assert not isinstance(result, BaseException), result
        assert (result.uploaded, result.failed) == (0, 1)
        # Thirty seconds for the existence check, then the body goes into the
        # socket buffers at once and the answer is waited for a minute (FILE-14)
        # The existence check, then three tries each waiting out the answer deadline, the third a minute after the second (FILE-14)
        assert took < 420, f"a bucket that never answers must end each try within its deadlines; it took {took:.0f} s"
        assert dev.db.get_audio_file(audio_id)["storage_key"] is None

    def test_a_slow_link_uploads_and_downloads_whole(self, linked_device) -> None:
        dev, link = linked_device
        content = os.urandom(9 * MIB)
        audio_id = dev.recording("איטי.wav", content)
        link.throttle(4 * MIB)
        result, _ = within(120, dev.upload)
        assert (result.uploaded, result.failed) == (1, 0), result.errors
        dev.path(audio_id).unlink()
        outcome, _ = within(120, lambda: dev.download(audio_id))
        assert outcome["status"] == "downloaded", outcome
        assert dev.path(audio_id).read_bytes() == content


class TestWhereTheCopiesAre:
    """FILE-22 with a real bucket: an upload states the bucket's copy, a
    download states this device's, and a download that finds the object gone
    states that the bucket no longer holds it."""

    def test_an_upload_and_a_download_state_where_the_copies_are(self, device: Device, local_s3) -> None:
        content = os.urandom(20_000)
        audio_id = device.recording("איפה העותקים.ogg", content)
        assert device.upload().uploaded == 1
        located = {loc["place"]: loc["present"] for loc in device.db.file_locations(audio_id)}
        assert located.get("cloud") is True

        device.path(audio_id).unlink()
        assert device.download(audio_id)["status"] == "downloaded"
        here = [loc for loc in device.db.file_locations(audio_id) if loc["place"] != "cloud"]
        assert here and all(loc["present"] for loc in here), here

    def test_a_download_that_finds_the_object_gone_states_the_bucket_lacks_it(self, device: Device, local_s3) -> None:
        content = os.urandom(20_000)
        audio_id = device.recording("נעלם מהדלי.ogg", content)
        assert device.upload().uploaded == 1
        local_s3.client().delete_object(Bucket=device.bucket, Key=f"{sha256(content)}.ogg")
        device.path(audio_id).unlink()
        with pytest.raises(RuntimeError):
            device.download(audio_id)
        located = {loc["place"]: loc["present"] for loc in device.db.file_locations(audio_id)}
        assert located.get("cloud") is False
        issues = device.db.issues(device.audio_dir)
        assert [r["audio_id"] for r in issues["recordings_not_in_cloud"]] == [audio_id], "it is an issue again"


class TestStorageBookkeeping:
    """What the rows say about the bucket, without a request to it."""

    def test_a_new_recording_waits_for_upload_until_the_row_says_uploaded(self, device: Device) -> None:
        audio_id = device.db.create_audio_file("ממתין.mp3", None)
        assert audio_id in [af["id"] for af in device.db.get_audio_files_pending_upload()]
        device.db.update_audio_file_storage(audio_id, "s3", "ממתין.mp3")
        assert audio_id not in [af["id"] for af in device.db.get_audio_files_pending_upload()]
        device.db.clear_audio_file_storage(audio_id)
        assert audio_id in [af["id"] for af in device.db.get_audio_files_pending_upload()]

    def test_the_saved_configuration_is_the_wizards(self, device: Device) -> None:
        saved = device.db.get_file_storage_config()
        assert saved["provider"] == "s3"
        config = saved["config"] if isinstance(saved["config"], dict) else __import__("json").loads(saved["config"])
        assert config["bucket"] == device.bucket and config["region"] == REGION
        assert device.db.is_file_storage_enabled() is True

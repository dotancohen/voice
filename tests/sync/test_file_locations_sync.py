"""Where the copies of a recording are, between devices (FILE-22).

The owner's case: one device removes its copy to save space while another
uploads the file to the bucket. Neither statement undoes the other, and after
a sync both devices know both. And a file deleted by hand from a device's
folder is known on the other device once the folder is compared.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from voicecore import SyncClient, upload_pending_audio_files

from core.database import set_this_device_id
from core.storage_setup import SetupState, create_bucket, save, take_key
from tests.local_s3 import REGION

from .conftest import DEVICE_A_ID, DEVICE_B_ID, SyncNode, create_sync_node, start_sync_server
from .test_sync_files import give_recording, local_path


@pytest.fixture
def pair(tmp_path: Path):
    node_a = create_sync_node("NodeA", DEVICE_A_ID, tmp_path)
    node_b = create_sync_node("NodeB", DEVICE_B_ID, tmp_path)
    for node in (node_a, node_b):
        audio_dir = node.config_dir / "audio"
        audio_dir.mkdir()
        node.config.set_audiofile_directory(str(audio_dir))
    start_sync_server(node_b)
    assert node_b.wait_for_server()
    node_a.config.add_device(node_b.device_id_hex, node_b.name, node_b.url)
    yield node_a, node_b
    node_b.stop_server()
    node_a.db.close()
    node_b.db.close()


def sync_a(node_a: SyncNode, node_b: SyncNode, operation: str = "sync_with_device"):
    set_this_device_id(node_a.device_id)
    result = getattr(SyncClient(str(node_a.config_dir)), operation)(node_b.device_id_hex)
    assert result.success, result.errors
    return result


def held(node: SyncNode, audio_id: str) -> dict:
    node.reload_db()
    return {loc["place"]: loc["present"] for loc in node.db.file_locations(audio_id)}


def test_a_copy_removed_on_one_device_while_another_uploads_is_known_on_both(pair, local_s3) -> None:
    node_a, node_b = pair
    state = SetupState(region=REGION, bucket=local_s3.new_bucket_name(), endpoint=local_s3.endpoint)
    assert take_key(state, local_s3.access_key_id, local_s3.secret_access_key) is None
    assert create_bucket(state) is None
    save(state, node_a.db)
    audio_id, _ = give_recording(node_a, 50_000)

    # A delivers the recording and the bucket's configuration to B
    delivered = sync_a(node_a, node_b, "deliver")
    assert delivered.sent == 1
    a, b = node_a.device_id_hex, node_b.device_id_hex
    assert held(node_b, audio_id) == {a: True, b: True}, "B states its copy and A's"

    # At once: A removes its copy to save space, once B promises to keep its
    # own (FILE-26); B uploads the file
    set_this_device_id(node_a.device_id)
    removed = SyncClient(str(node_a.config_dir)).remove_local_copy(audio_id)
    assert removed.endswith(f"{node_b.name} holds it"), removed
    assert not local_path(node_a, audio_id).exists()
    set_this_device_id(node_b.device_id)
    uploaded = upload_pending_audio_files(str(node_b.config_dir))
    assert (uploaded.uploaded, uploaded.failed) == (1, 0), uploaded.errors

    sync_a(node_a, node_b)
    both = {"cloud": True, a: False, b: True}
    assert held(node_a, audio_id) == both
    assert held(node_b, audio_id) == both
    assert node_a.db.file_locations(audio_id) == node_b.db.file_locations(audio_id)


def test_a_file_deleted_by_hand_is_known_on_the_other_device(pair) -> None:
    node_a, node_b = pair
    audio_id, path_a = give_recording(node_a, 20_000)
    sync_a(node_a, node_b, "deliver")
    a, b = node_a.device_id_hex, node_b.device_id_hex

    # A's own folder is compared when A syncs
    path_a.unlink()
    sync_a(node_a, node_b)
    assert held(node_b, audio_id) == {a: False, b: True}

    # B's folder is compared when B's application looks; A learns it at its next sync
    local_path(node_b, audio_id).unlink()
    assert node_b.db.check_files_here(node_b.config_dir / "audio", b) == (0, 1)
    sync_a(node_a, node_b)
    assert held(node_a, audio_id) == {a: False, b: False}
    issues = node_a.db.issues(node_a.config_dir / "audio", a)
    assert [r["reason"] for r in issues["recordings_not_in_cloud"]] == ["no_bucket"]

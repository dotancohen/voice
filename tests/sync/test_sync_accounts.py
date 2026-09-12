"""Account identity (ACCT-1..ACCT-5) and snapshots (SNAP-1..SNAP-4), end to end.

Two devices exchange changes only when they hold the same account. The check
sits in the handshake on both sides, and nothing crosses when it fails.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests

from voicecore import SyncClient

from .conftest import (
    ACCOUNT_ID,
    AUTH,
    OTHER_ACCOUNT_ID,
    DEVICE_A_ID,
    DEVICE_B_ID,
    SyncNode,
    create_note_on_node,
    create_sync_node,
    start_sync_server,
)


def handshake(url: str, account_id: str | None, headers: dict = AUTH) -> requests.Response:
    """A handshake by the test client, naming `account_id` in the body."""
    body = {"device_id": headers["X-Device-ID"], "device_name": "Test", "protocol_version": "1.1"}
    if account_id is not None:
        body["account_id"] = account_id
    return requests.post(f"{url}/sync/handshake", json=body, headers=headers)


class TestAccountIdentity:
    def test_every_database_has_an_account_id(self, sync_node_a: SyncNode):
        """A node created in the test account carries it (ACCT-1, ACCT-4)."""
        assert sync_node_a.db.account_id() == ACCOUNT_ID
        assert len(sync_node_a.db.account_id()) == 32

    def test_the_handshake_tells_the_account(self, running_server_a: SyncNode):
        """A caller of the same account is let in and told which account it reached (ACCT-2)."""
        resp = handshake(running_server_a.url, ACCOUNT_ID)
        assert resp.status_code == 200
        assert resp.json()["account_id"] == ACCOUNT_ID

    def test_another_account_is_refused_with_its_code(self, running_server_a: SyncNode):
        """A caller whose handshake names another account gets a sentence, a code and nothing else (ACCT-2)."""
        resp = handshake(running_server_a.url, OTHER_ACCOUNT_ID)
        assert resp.status_code == 403
        body = resp.json()
        assert body["code"] == "ACCOUNT_MISMATCH"
        assert "nothing was exchanged" in body["error"]

    def test_a_request_for_another_account_is_refused_before_the_handshake(self, running_server_a: SyncNode):
        """The headers name an account this server does not hold (AUTH-3)."""
        resp = handshake(running_server_a.url, OTHER_ACCOUNT_ID, headers={**AUTH, "X-Account-ID": OTHER_ACCOUNT_ID})
        assert resp.status_code == 404
        assert resp.json()["code"] == "ACCOUNT_UNKNOWN"

    def test_a_request_without_a_key_is_refused(self, running_server_a: SyncNode):
        """Every route but the health check needs the device key (AUTH-3)."""
        resp = requests.get(f"{running_server_a.url}/sync/changes", headers={"X-Account-ID": ACCOUNT_ID, "X-Device-ID": AUTH["X-Device-ID"]})
        assert resp.status_code == 401
        assert resp.json()["code"] == "KEY_MISSING"
        assert requests.get(f"{running_server_a.url}/sync/status").status_code == 200

    def test_a_handshake_that_names_no_account_is_refused(self, running_server_a: SyncNode):
        resp = handshake(running_server_a.url, None)
        assert resp.status_code == 400
        assert resp.json()["code"] == "ACCOUNT_MISSING"

    def test_a_mismatched_pair_exchanges_nothing(self, tmp_path: Path):
        """The whole path through the real client and server (ACCT-3)."""
        node_a = create_sync_node("node_a", DEVICE_A_ID, tmp_path)
        node_b = create_sync_node("node_b", DEVICE_B_ID, tmp_path, account_id=OTHER_ACCOUNT_ID)
        create_note_on_node(node_a, "של A")
        create_note_on_node(node_b, "של B")
        start_sync_server(node_b)
        try:
            assert node_b.wait_for_server()
            node_a.config.add_peer(node_b.device_id_hex, node_b.name, node_b.url)
            client = SyncClient(str(node_a.config_dir))

            result = client.sync_with_peer(node_b.device_id_hex)

            assert not result.success
            # The headers name an account the server does not hold, so the
            # refusal comes before the handshake body is read (AUTH-3).
            assert any("ACCOUNT_UNKNOWN" in e for e in result.errors), result.errors
            assert result.pulled == 0 and result.pushed == 0
            node_a.reload_db()
            node_b.reload_db()
            assert [n["content"] for n in node_a.db.get_all_notes()] == ["של A"]
            assert [n["content"] for n in node_b.db.get_all_notes()] == ["של B"]
        finally:
            node_b.stop_server()

    def test_a_database_with_notes_keeps_its_account(self, tmp_path: Path):
        """Opening a used database for another account is refused, not corrected (ACCT-4)."""
        from core.database import Database
        path = tmp_path / "notes.db"
        db = Database(path, ACCOUNT_ID)
        db.create_note("יש כאן פתק")
        db.close()
        with pytest.raises(Exception) as refused:
            Database(path, OTHER_ACCOUNT_ID)
        assert "ACCOUNT_DISAGREES" in str(refused.value)
        assert Database(path).account_id() == ACCOUNT_ID


class TestSnapshots:
    def test_a_sync_leaves_a_snapshot_on_both_sides(self, two_nodes_with_servers):
        """Before anything is applied, each side copies its database (SNAP-3)."""
        node_a, node_b = two_nodes_with_servers
        create_note_on_node(node_a, "לפני הסנכרון")
        node_a.config.add_peer(node_b.device_id_hex, node_b.name, node_b.url)
        client = SyncClient(str(node_a.config_dir))

        result = client.sync_with_peer(node_b.device_id_hex)

        assert result.success, result.errors
        assert (node_a.config_dir / "snapshots").is_dir()
        assert [s["name"] for s in node_a.db.list_snapshots()], "the client snapshotted before pulling"
        node_b.reload_db()
        assert [s["name"] for s in node_b.db.list_snapshots()], "the server snapshotted at the handshake"

    def test_the_sixth_snapshot_deletes_the_first_and_a_restore_brings_a_note_back(self, sync_node_a: SyncNode):
        """SNAP-2 and SNAP-4 through the Python wrapper."""
        note_id = sync_node_a.db.create_note("יחזור")
        names = [Path(sync_node_a.db.snapshot()).name for _ in range(6)]
        listed = sync_node_a.db.list_snapshots()
        assert len(listed) == 5
        assert names[0] not in [s["name"] for s in listed], "the oldest is gone"
        assert all(s["note_count"] == 1 for s in listed)

        sync_node_a.db.delete_note(note_id)
        assert sync_node_a.db.get_note(note_id) is None
        sync_node_a.db.restore_snapshot(listed[0]["name"])
        assert sync_node_a.db.get_note(note_id) is not None
        assert sync_node_a.db.list_snapshots()[0]["note_count"] == 0, "the replaced state is the newest snapshot"


class TestAccountMove:
    def test_a_move_keeps_the_notes_and_forgets_the_peers(self, sync_node_a: SyncNode):
        """ACCT-5: the deliberate way to merge accounts."""
        note_id = sync_node_a.db.create_note("עובר איתי")
        sync_node_a.db.update_peer_sync_time("00000000000070008000000000000099", "Desk")

        sync_node_a.db.move_to_account(OTHER_ACCOUNT_ID)

        assert sync_node_a.db.account_id() == OTHER_ACCOUNT_ID
        assert sync_node_a.db.get_note(note_id) is not None
        assert sync_node_a.db.get_peer_last_sync("00000000000070008000000000000099") is None
        assert sync_node_a.db.list_snapshots(), "a snapshot was taken first"

    def test_a_move_needs_a_valid_id(self, sync_node_a: SyncNode):
        with pytest.raises(Exception):
            sync_node_a.db.move_to_account("not-an-account")

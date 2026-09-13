"""Proof that it worked (Stage 10): the line "X notes and Y recordings are not
duplicated off this device", the peers' last operation, and where a
recording's copies are."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .conftest import DEVICE_A_ID, DEVICE_B_ID, SyncNode, create_note_on_node, create_sync_node, start_sync_server

PROJECT = Path(__file__).parent.parent.parent


def cli(node: SyncNode, *args: str, fmt: str = "json") -> subprocess.CompletedProcess:
    env = {**os.environ, "VOICE_CONFIG_DIR": str(node.config_dir), "PYTHONPATH": str(PROJECT)}
    return subprocess.run(
        [sys.executable, "-m", "src.main", "cli", "--format", fmt, *args],
        capture_output=True, text=True, env=env, cwd=str(PROJECT), timeout=60,
    )


def status(node: SyncNode) -> dict:
    result = cli(node, "sync", "status")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestProof:
    def test_the_line_counts_what_is_here_only_until_a_sync_sends_it(self, tmp_path: Path) -> None:
        a = create_sync_node("a", DEVICE_A_ID, tmp_path)
        b = create_sync_node("b", DEVICE_B_ID, tmp_path)
        a.db.close()
        assert status(a)["not_duplicated"] == {"notes": 0, "recordings": 0}
        line = cli(a, "sync", "status", fmt="text").stdout
        assert "Everything is duplicated off this device." in line

        a.reload_db()
        create_note_on_node(a, "רק כאן")
        a.db.close()
        assert status(a)["not_duplicated"] == {"notes": 1, "recordings": 0}
        line = cli(a, "sync", "status", fmt="text").stdout
        assert "1 note and 0 recordings are not duplicated off this device." in line

        start_sync_server(b)
        try:
            assert b.wait_for_server()
            added = cli(a, "sync", "add-peer", b.device_id_hex, "B", b.url)
            assert added.returncode == 0, added.stderr
            synced = cli(a, "sync", "now", "--peer", b.device_id_hex)
            assert synced.returncode == 0, synced.stderr
            after = status(a)
            assert after["not_duplicated"] == {"notes": 0, "recordings": 0}
            peers = after["peers"]
            assert len(peers) == 1
            assert peers[0]["peer_id"] == b.device_id_hex
            assert peers[0]["last_operation"] == "sync"
            assert peers[0]["last_reached_at"] is not None
            text = cli(a, "sync", "status", fmt="text").stdout
            assert "B: last reached" in text and "last operation: sync" in text
        finally:
            b.stop_server()

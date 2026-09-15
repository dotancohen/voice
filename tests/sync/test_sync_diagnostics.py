"""Diagnostics (DIAG-2, DIAG-4): the request id on a result, and the connection check."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .conftest import DEVICE_A_ID, DEVICE_B_ID, OTHER_ACCOUNT_ID, SyncNode, create_sync_node, start_sync_server

PROJECT = Path(__file__).parent.parent.parent


def cli(node: SyncNode, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "VOICE_CONFIG_DIR": str(node.config_dir), "PYTHONPATH": str(PROJECT)}
    return subprocess.run(
        [sys.executable, "-m", "src.main", "cli", "--format", "json", *args],
        capture_output=True, text=True, env=env, cwd=str(PROJECT), timeout=60,
    )


class TestDiagnostics:
    def test_a_result_carries_its_request_id_and_the_check_passes_between_admitted_devices(self, tmp_path: Path) -> None:
        a = create_sync_node("a", DEVICE_A_ID, tmp_path)
        b = create_sync_node("b", DEVICE_B_ID, tmp_path)
        start_sync_server(b)
        try:
            assert b.wait_for_server()
            a.db.close()
            added = cli(a, "sync", "add-device", b.device_id_hex, "B", b.url)
            assert added.returncode == 0, added.stderr

            synced = cli(a, "sync", "now", "--device", b.device_id_hex)
            assert synced.returncode == 0, synced.stderr
            result = json.loads(synced.stdout)
            assert result["success"]
            assert re.fullmatch(r"[0-9a-f]{16}", result["request_id"]), result
            assert result["clock_skew_seconds"] == 0

            checked = cli(a, "sync", "check", b.device_id_hex)
            assert checked.returncode == 0, checked.stderr + checked.stdout
            check = json.loads(checked.stdout)
            assert check["passed"]
            names = [r["name"] for r in check["rows"]]
            for name in ("Reachable", "Certificate", "Account", "Key", "Clock", "Free space here", "Free space there", "Listener here"):
                assert name in names, names
            assert all(r["code"] == "" for r in check["rows"])
        finally:
            b.stop_server()

    def test_the_check_names_a_refused_key_and_an_unreachable_device(self, tmp_path: Path) -> None:
        a = create_sync_node("a", DEVICE_A_ID, tmp_path)
        # Made in another account so that the fixture admits neither on the
        # other; then moved to a's account: same account, unknown device
        b = create_sync_node("b", DEVICE_B_ID, tmp_path / "other", account_id=OTHER_ACCOUNT_ID)
        b.db.move_to_account(a.db.account_id())
        b.db.close()
        start_sync_server(b)
        try:
            assert b.wait_for_server()
            a.db.close()
            cli(a, "sync", "add-device", b.device_id_hex, "B", b.url)
            checked = cli(a, "sync", "check", b.device_id_hex)
            assert checked.returncode == 1
            check = json.loads(checked.stdout)
            key = next(r for r in check["rows"] if r["name"] == "Key")
            assert not key["passed"] and key["code"] == "DEVICE_UNKNOWN", check

            cli(a, "sync", "add-device", "00000000000070008000000000000001", "Nobody", "http://127.0.0.1:1")
            checked = cli(a, "sync", "check", "00000000000070008000000000000001")
            assert checked.returncode == 1
            rows = json.loads(checked.stdout)["rows"]
            assert rows[0]["name"] == "Reachable" and not rows[0]["passed"], rows
        finally:
            b.stop_server()

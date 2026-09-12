"""Pairing (PAIR-1..PAIR-4): a fresh device joins from a code."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from voicecore import SyncClient

from .conftest import (
    DEVICE_A_ID,
    DEVICE_B_ID,
    OTHER_ACCOUNT_ID,
    SyncNode,
    create_note_on_node,
    create_sync_node,
    start_sync_server,
)


def cli(node: SyncNode, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VOICE_CONFIG_DIR"] = str(node.config_dir)
    env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent)
    return subprocess.run(
        [sys.executable, "-m", "src.main", "cli", "--format", "json", *args],
        capture_output=True, text=True, env=env, cwd=str(Path(__file__).parent.parent.parent),
    )


class TestPairing:
    def test_a_fresh_device_joins_from_the_code_and_syncs(self, tmp_path: Path):
        """show-code on the holder, join on the fresh device, then a sync."""
        desk = create_sync_node("desk", DEVICE_A_ID, tmp_path)
        phone = create_sync_node("phone", DEVICE_B_ID, tmp_path, account_id=OTHER_ACCOUNT_ID)
        create_note_on_node(desk, "על השולחן")
        start_sync_server(desk)
        try:
            assert desk.wait_for_server()
            shown = cli(desk, "account", "show-code", "--url", desk.url)
            assert shown.returncode == 0, shown.stderr
            text = json.loads(shown.stdout)["setup_text"]
            assert text.startswith("voice://pair?v=1&")
            assert len(text) < 300

            joined = cli(phone, "account", "join", text)
            assert joined.returncode == 0, joined.stderr
            result = json.loads(joined.stdout)
            assert result["account_id"] == desk.db.account_id()
            assert result["peer_id"] == desk.device_id_hex

            phone.reload_db()
            assert phone.db.account_id() == desk.db.account_id(), "the phone took the account"
            phone_config = json.loads((phone.config_dir / "config.json").read_text())
            assert len(phone_config["sync"]["device_key"]) == 43
            assert phone_config["sync"]["peers"][0]["peer_id"] == desk.device_id_hex
            desk.reload_db()
            cards = {c["device_id"] for c in desk.db.list_devices()}
            assert phone.device_id_hex in cards, "the desk holds the phone's card"

            again = cli(phone, "account", "join", text)
            assert again.returncode == 1
            assert "TOKEN_INVALID" in again.stderr, "the token was spent"

            synced = SyncClient(str(phone.config_dir)).sync_with_peer(desk.device_id_hex)
            assert synced.success, synced.errors
            phone.reload_db()
            assert [n["content"] for n in phone.db.get_all_notes()] == ["על השולחן"]
        finally:
            desk.stop_server()

    def test_a_device_with_notes_refuses_the_code(self, tmp_path: Path):
        desk = create_sync_node("desk", DEVICE_A_ID, tmp_path)
        phone = create_sync_node("phone", DEVICE_B_ID, tmp_path, account_id=OTHER_ACCOUNT_ID)
        create_note_on_node(phone, "כבר יש לי")
        shown = cli(desk, "account", "show-code", "--url", "http://127.0.0.1:1")
        text = json.loads(shown.stdout)["setup_text"]
        refused = cli(phone, "account", "join", text)
        assert refused.returncode == 1
        assert "DEVICE_HOLDS_NOTES" in refused.stderr
        assert "Show this device's code to the other one" in refused.stderr

    def test_hide_code_withdraws_it(self, tmp_path: Path):
        desk = create_sync_node("desk", DEVICE_A_ID, tmp_path)
        phone = create_sync_node("phone", DEVICE_B_ID, tmp_path, account_id=OTHER_ACCOUNT_ID)
        start_sync_server(desk)
        try:
            assert desk.wait_for_server()
            text = json.loads(cli(desk, "account", "show-code", "--url", desk.url).stdout)["setup_text"]
            hidden = cli(desk, "account", "hide-code")
            assert hidden.returncode == 0
            refused = cli(phone, "account", "join", text)
            assert refused.returncode == 1
            assert "TOKEN_INVALID" in refused.stderr
        finally:
            desk.stop_server()

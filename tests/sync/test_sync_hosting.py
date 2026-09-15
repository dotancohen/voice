"""Hosting (Stage 3, PAIR-5, AUTH-4): a server that holds no account of its
own takes one by grant and serves it to the account's devices."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

from .conftest import (
    DEVICE_A_ID,
    DEVICE_B_ID,
    SyncNode,
    create_note_on_node,
    create_sync_node,
    start_sync_server,
)

PROJECT = Path(__file__).parent.parent.parent


def cli(root: Path, *args: str, account: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "VOICE_CONFIG_DIR": str(root), "PYTHONPATH": str(PROJECT)}
    env.pop("VOICE_ACCOUNT_ID", None)
    cmd = [sys.executable, "-m", "src.main"]
    if account:
        cmd += ["-a", account]
    cmd += ["cli", "--format", "json", *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(PROJECT), timeout=60)


def shown(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


def free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_root(root: Path, port: int) -> subprocess.Popen:
    """'sync serve' over a root, every account in it, plain http on this machine."""
    env = {**os.environ, "VOICE_CONFIG_DIR": str(root), "PYTHONPATH": str(PROJECT)}
    env.pop("VOICE_ACCOUNT_ID", None)
    process = subprocess.Popen(
        [sys.executable, "-m", "src.main", "cli", "sync", "serve", "--host", "127.0.0.1", "--port", str(port), "--plain-http"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT),
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if requests.get(f"{url}/sync/status", timeout=1).status_code == 200:
                return process
        except requests.RequestException:
            pass
        time.sleep(0.1)
    process.kill()
    out, err = process.communicate()
    raise AssertionError(f"the server did not start: {err.decode()} {out.decode()}")


def stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    if process.stdout:
        process.stdout.close()
    if process.stderr:
        process.stderr.close()


class TestHosting:
    def test_a_holder_grants_a_server_and_a_phone_joins_through_it(self, tmp_path: Path) -> None:
        root = tmp_path / "server"
        port = free_port()
        url = f"http://127.0.0.1:{port}"
        server = serve_root(root, port)
        try:
            assert not (root / "notes.db").exists(), "a server makes no account of its own"
            assert (root / "accounts.db").is_file(), "but it has an index"
            assert shown(cli(root, "account", "list")) == []

            grant = shown(cli(root, "account", "host", "--label", "meirav", "--url", url))
            text = grant["setup_text"]
            assert text.startswith("voice://pair?v=1&") and "g=1" in text and "&a=" not in text
            assert not (root / "notes.db").exists()

            # The holder: a device with notes, in its own directory
            desk = create_sync_node("desk", DEVICE_A_ID, tmp_path)
            create_note_on_node(desk, "על השולחן")
            desk.db.close()
            granted = shown(cli(desk.config_dir, "account", "grant-host", text))
            desk.reload_db()
            assert granted["account_id"] == desk.db.account_id()
            assert granted["device_url"] == url
            server_id = granted["device_id"]

            listed = shown(cli(root, "account", "list"))
            assert [(a["account_id"], a["label"], a["hosted"], a["is_default"]) for a in listed] == [(desk.db.account_id(), "meirav", True, False)]
            hosted_config = json.loads((root / desk.db.account_id() / "config.json").read_text())
            assert len(hosted_config["sync"]["device_key"]) == 43, "the server holds the key the holder made"

            # The text is spent
            again = create_sync_node("again", DEVICE_B_ID, tmp_path)
            again.db.close()
            refused = cli(again.config_dir, "account", "grant-host", text)
            assert refused.returncode == 1 and "TOKEN_INVALID" in refused.stderr
            again.reload_db()

            # The holder syncs with the server
            desk.db.close()
            delivered = shown(cli(desk.config_dir, "sync", "now", "--device", server_id))
            assert delivered["success"], delivered
            desk.reload_db()
            listed_devices = shown(cli(desk.config_dir, "device", "list"))
            server_card = next(d for d in listed_devices if d["device_id"] == server_id)
            assert server_card["listens"] and url in server_card["addresses"]

            # The server shows a code for the hosted account; a fresh phone joins through it
            code = shown(cli(root, "account", "show-code", "--url", url, account="meirav"))
            phone = create_sync_node("phone", DEVICE_B_ID, tmp_path / "p", account_id="0199aaaaaaaa7000800000000000000a")
            phone.db.close()
            joined = shown(cli(phone.config_dir, "account", "join", code["setup_text"]))
            assert joined["device_id"] == server_id
            phone.reload_db()
            assert phone.db.account_id() == desk.db.account_id()
            create_note_on_node(phone, "מהטלפון")
            phone.db.close()
            synced = shown(cli(phone.config_dir, "sync", "now", "--device", server_id))
            assert synced["success"], synced
            phone.reload_db()
            assert sorted(n["content"] for n in phone.db.get_all_notes()) == ["מהטלפון", "על השולחן"], "the phone has the desk's note through the server"

            desk.db.close()
            synced = shown(cli(desk.config_dir, "sync", "now", "--device", server_id))
            assert synced["success"], synced
            desk.reload_db()
            assert sorted(n["content"] for n in desk.db.get_all_notes()) == ["מהטלפון", "על השולחן"]

            # The audit log of the hosted account names devices and routes, never a key or a note
            audit = (root / desk.db.account_id() / "audit.log").read_text()
            assert f"{desk.device_id_hex} POST /sync/handshake in=" in audit
            assert f"{phone.device_id_hex} GET /sync/changes" in audit
            assert hosted_config["sync"]["device_key"] not in audit
            assert "מהטלפון" not in audit
        finally:
            stop(server)

    def test_a_directory_that_is_an_account_cannot_host(self, sync_node_a: SyncNode) -> None:
        sync_node_a.db.close()
        result = cli(sync_node_a.config_dir, "account", "host", "--url", "http://127.0.0.1:1")
        assert result.returncode == 1
        assert "cannot host others" in result.stderr

    def test_a_grant_text_is_refused_by_join_and_a_code_by_grant_host(self, tmp_path: Path) -> None:
        root = tmp_path / "server"
        grant = shown(cli(root, "account", "host", "--url", "http://127.0.0.1:1"))
        desk = create_sync_node("desk", DEVICE_A_ID, tmp_path)
        desk.db.close()
        result = cli(desk.config_dir, "account", "join", grant["setup_text"])
        assert result.returncode == 1 and "grant" in result.stderr
        desk.reload_db()
        code = shown(cli(desk.config_dir, "account", "show-code", "--url", "http://127.0.0.1:1"))
        desk.db.close()
        result = cli(desk.config_dir, "account", "grant-host", code["setup_text"])
        assert result.returncode == 1 and "grant" in result.stderr

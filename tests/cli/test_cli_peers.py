"""The peers of a device from the command line (Stage 5): the last one, a local name, forgetting."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

DESK = "0199aaaaaaaa7000800000000000000a"


def run_cli(db_dir: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "VOICE_CONFIG_DIR": str(db_dir)}
    return subprocess.run([sys.executable, "-m", "src.main", "cli", "--format", "json", *args], capture_output=True, text=True, env=env)


def shown(result: subprocess.CompletedProcess) -> object:
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


@pytest.mark.cli
class TestPeers:
    def test_a_peer_is_listed_renamed_and_forgotten(self, tmp_path: Path) -> None:
        shown(run_cli(tmp_path, "sync", "add-peer", DESK, "Desk", "https://desk:8384"))
        peers = shown(run_cli(tmp_path, "sync", "list-peers"))
        assert [(p["peer_id"], p["peer_name"], p["is_last"], p["last_operation"]) for p in peers] == [(DESK, "Desk", False, "")]

        shown(run_cli(tmp_path, "sync", "rename-peer", DESK[:8], "Study"))
        peers = shown(run_cli(tmp_path, "sync", "list-peers"))
        assert peers[0]["peer_name"] == "Study"

        forgotten = shown(run_cli(tmp_path, "sync", "remove-peer", DESK))
        assert forgotten == {"removed": True, "peer_id": DESK}
        assert shown(run_cli(tmp_path, "sync", "list-peers")) == []
        # An empty root became an index with one account; the peers live in the account's file
        account_dir = Path(shown(run_cli(tmp_path, "account", "show"))["directory"])
        config = json.loads((account_dir / "config.json").read_text())
        assert config["sync"]["forgotten_peers"] == [DESK]

        # Added again by hand: no longer forgotten
        shown(run_cli(tmp_path, "sync", "add-peer", DESK, "Desk", "https://desk:8384"))
        config = json.loads((account_dir / "config.json").read_text())
        assert config["sync"]["forgotten_peers"] == []

    def test_renaming_an_unknown_peer_fails(self, tmp_path: Path) -> None:
        result = run_cli(tmp_path, "sync", "rename-peer", "ffffffff", "Nobody")
        assert result.returncode == 1
        assert "No single peer" in result.stderr

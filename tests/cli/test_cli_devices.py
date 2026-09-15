"""The devices of a device from the command line (Stage 5): the last one, a local name, forgetting."""

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
class TestDevices:
    def test_a_device_is_listed_renamed_and_forgotten(self, tmp_path: Path) -> None:
        shown(run_cli(tmp_path, "sync", "add-device", DESK, "Desk", "https://desk:8384"))
        devices = shown(run_cli(tmp_path, "sync", "list-devices"))
        assert [(p["device_id"], p["device_name"], p["is_last"], p["last_operation"]) for p in devices] == [(DESK, "Desk", False, "")]

        shown(run_cli(tmp_path, "sync", "rename-device", DESK[:8], "Study"))
        devices = shown(run_cli(tmp_path, "sync", "list-devices"))
        assert devices[0]["device_name"] == "Study"

        forgotten = shown(run_cli(tmp_path, "sync", "forget-device", DESK))
        assert forgotten == {"removed": True, "device_id": DESK}
        assert shown(run_cli(tmp_path, "sync", "list-devices")) == []
        # An empty root became an index with one account; the devices live in the account's file
        account_dir = Path(shown(run_cli(tmp_path, "account", "show"))["directory"])
        config = json.loads((account_dir / "config.json").read_text())
        assert config["sync"]["forgotten_devices"] == [DESK]

        # Added again by hand: no longer forgotten
        shown(run_cli(tmp_path, "sync", "add-device", DESK, "Desk", "https://desk:8384"))
        config = json.loads((account_dir / "config.json").read_text())
        assert config["sync"]["forgotten_devices"] == []

    def test_renaming_an_unknown_device_fails(self, tmp_path: Path) -> None:
        result = run_cli(tmp_path, "sync", "rename-device", "ffffffff", "Nobody")
        assert result.returncode == 1
        assert "No single device" in result.stderr

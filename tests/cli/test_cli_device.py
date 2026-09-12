"""The `device` commands: list and revoke (CARD-1, AUTH-6)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.database import Database

OTHER_DEVICE = "00000000000070008000000000000077"


@pytest.fixture
def cli_db(test_db_path: Path, empty_db: Database) -> Database:
    """An empty database the command line will actually open."""
    config_file = test_db_path.parent / "config.json"
    config_file.write_text(json.dumps({"database_file": str(test_db_path)}))
    return empty_db


def run_cli(db_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "src.main", "-d", str(db_dir), "cli", *args],
        capture_output=True,
        text=True,
    )


@pytest.mark.cli
class TestDeviceCommands:
    def test_this_device_has_a_card_after_the_first_run(self, test_db_path: Path, cli_db: Database) -> None:
        """Running anything makes this installation's key and card (AUTH-1)."""
        result = run_cli(test_db_path.parent, "--format", "json", "device", "list")
        assert result.returncode == 0, result.stderr
        devices = json.loads(result.stdout)
        assert len(devices) == 1
        card = devices[0]
        assert card["application"] == "voice"
        assert card["revoked"] is False
        config = json.loads((test_db_path.parent / "config.json").read_text())
        assert len(config["sync"]["device_key"]) == 43, "the key is 32 random bytes as base64url"

    def test_revoke_refuses_this_device_and_marks_another(self, test_db_path: Path, cli_db: Database) -> None:
        from voicecore import device_key_hash
        run_cli(test_db_path.parent, "device", "list")  # makes this device's card
        cli_db.admit_device(OTHER_DEVICE, "Lost phone", device_key_hash("its-key"))

        listed = run_cli(test_db_path.parent, "device", "list")
        assert "Lost phone" in listed.stdout

        own = json.loads((test_db_path.parent / "config.json").read_text())["device_id"]
        refused = run_cli(test_db_path.parent, "device", "revoke", own)
        assert refused.returncode == 1
        assert "This is this device" in refused.stderr

        revoked = run_cli(test_db_path.parent, "device", "revoke", OTHER_DEVICE[:8])
        assert revoked.returncode == 0, revoked.stderr
        assert "Revoked Lost phone" in revoked.stdout
        cards = {c["device_id"]: c for c in Database(test_db_path).list_devices()}
        assert cards[OTHER_DEVICE]["revoked"] is True
        assert cards[own]["revoked"] is False

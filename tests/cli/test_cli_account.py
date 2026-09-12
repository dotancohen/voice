"""The `account` commands: show, snapshot, snapshots, restore, move."""

from __future__ import annotations

import json
import subprocess
import sys
import os
from pathlib import Path

import pytest

from core.database import Database

OTHER_ACCOUNT = "0199bbbbbbbb7000800000000000000b"


@pytest.fixture
def cli_db(test_db_path: Path, empty_db: Database) -> Database:
    """An empty database the command line will actually open."""
    config_file = test_db_path.parent / "config.json"
    config_file.write_text(json.dumps({"database_file": str(test_db_path)}))
    return empty_db


def run_cli(db_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "src.main", "cli", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "VOICE_CONFIG_DIR": str(db_dir)},
    )


@pytest.mark.cli
class TestAccountCommands:
    def test_show_names_the_account(self, test_db_path: Path, cli_db: Database) -> None:
        result = run_cli(test_db_path.parent, "--format", "json", "account", "show")
        assert result.returncode == 0, result.stderr
        shown = json.loads(result.stdout)
        assert shown["account_id"] == cli_db.account_id()
        assert len(shown["account_id"]) == 32

    def test_a_snapshot_is_listed_and_a_restore_brings_a_note_back(
        self, test_db_path: Path, cli_db: Database
    ) -> None:
        note_id = cli_db.create_note("לפני")
        taken = run_cli(test_db_path.parent, "account", "snapshot")
        assert taken.returncode == 0, taken.stderr
        assert "Snapshot written" in taken.stdout

        listed = run_cli(test_db_path.parent, "account", "snapshots")
        assert listed.returncode == 0
        name = [line for line in listed.stdout.splitlines() if line.startswith("notes-")][0].split()[0]
        assert "1 notes" in listed.stdout

        cli_db.delete_note(note_id)
        restored = run_cli(test_db_path.parent, "account", "restore", name, "--yes")
        assert restored.returncode == 0, restored.stderr
        assert Database(test_db_path).get_note(note_id) is not None

    def test_restore_refuses_a_name_that_is_not_listed(self, test_db_path: Path, cli_db: Database) -> None:
        result = run_cli(test_db_path.parent, "account", "restore", "notes-nothing.db", "--yes")
        assert result.returncode == 1
        assert "No snapshot named" in result.stderr

    def test_move_needs_the_current_id_typed_in_full(self, test_db_path: Path, cli_db: Database) -> None:
        current = cli_db.account_id()
        note_id = cli_db.create_note("עובר")

        wrong = run_cli(test_db_path.parent, "account", "move", "--to", OTHER_ACCOUNT, "--current", current[:8])
        assert wrong.returncode == 1
        assert "Type the full current id" in wrong.stderr
        assert Database(test_db_path).account_id() == current

        right = run_cli(test_db_path.parent, "account", "move", "--to", OTHER_ACCOUNT, "--current", current)
        assert right.returncode == 0, right.stderr
        assert "Moved 1 notes" in right.stdout
        moved = Database(test_db_path)
        assert moved.account_id() == OTHER_ACCOUNT
        assert moved.get_note(note_id) is not None
        assert moved.list_snapshots(), "a snapshot was taken first"

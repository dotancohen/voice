"""CLI tests for the trash bin: trash-list, note-recover, note-purge.

Run through the command line the way a person runs it, against a database
the command line can really see.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.database import Database


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
class TestTrashCommands:
    def test_an_empty_trash_says_so(self, test_db_path: Path, cli_db: Database) -> None:
        result = run_cli(test_db_path.parent, "trash-list")

        assert result.returncode == 0, result.stderr
        assert "trash is empty" in result.stdout.lower()

    def test_a_deleted_note_is_listed_with_its_text(
        self, test_db_path: Path, cli_db: Database
    ) -> None:
        note_id = cli_db.create_note("פתק שנמחק ונמצא בפח")
        cli_db.delete_note(note_id)

        result = run_cli(test_db_path.parent, "trash-list")

        assert result.returncode == 0, result.stderr
        assert "פתק שנמחק ונמצא בפח" in result.stdout
        assert note_id[:12] in result.stdout

    def test_recover_puts_the_note_back(
        self, test_db_path: Path, cli_db: Database
    ) -> None:
        note_id = cli_db.create_note("להחזיר אותי")
        cli_db.delete_note(note_id)

        result = run_cli(test_db_path.parent, "note-recover", note_id)

        assert result.returncode == 0, result.stderr
        assert cli_db.get_note(note_id) is not None
        assert cli_db.get_deleted_notes() == []

    def test_recovering_a_note_that_is_not_in_the_trash_fails(
        self, test_db_path: Path, cli_db: Database
    ) -> None:
        note_id = cli_db.create_note("פתק חי")

        result = run_cli(test_db_path.parent, "note-recover", note_id)

        assert result.returncode != 0
        assert result.stderr.strip() != ""

    def test_purge_removes_the_note_for_good(
        self, test_db_path: Path, cli_db: Database
    ) -> None:
        note_id = cli_db.create_note("להיעלם לתמיד")
        cli_db.delete_note(note_id)

        result = run_cli(test_db_path.parent, "note-purge", note_id, "--yes")

        assert result.returncode == 0, result.stderr
        assert cli_db.get_note_raw(note_id) is None
        assert cli_db.get_deleted_notes() == []

    def test_purge_refuses_a_note_that_is_not_in_the_trash(
        self, test_db_path: Path, cli_db: Database
    ) -> None:
        """Deleting is one step; removing for good is another."""
        note_id = cli_db.create_note("פתק חי")

        result = run_cli(test_db_path.parent, "note-purge", note_id, "--yes")

        assert result.returncode != 0
        assert cli_db.get_note(note_id) is not None

    def test_purge_json_names_what_went(
        self, test_db_path: Path, cli_db: Database
    ) -> None:
        note_id = cli_db.create_note("פתק עם הקלטה")
        audio_id = cli_db.create_audio_file("recording.ogg")
        cli_db.attach_to_note(note_id, audio_id, "audio_file")
        cli_db.delete_note(note_id)

        result = run_cli(
            test_db_path.parent, "--format", "json", "note-purge", note_id, "--yes"
        )

        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["purged"] is True
        assert data["audio_files"] == [audio_id]

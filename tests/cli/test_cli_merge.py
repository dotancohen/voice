"""CLI tests for notes-merge.

The merge was broken for weeks in a way no test saw: the core read the
timestamps as text, every merge answered "Note not found", and the only test
that called it threw the error away. Nothing ran the command a user runs, so
this file does, and checks what the merge produced rather than that it did
not crash.
"""

from __future__ import annotations

import json
import subprocess
import sys
import os
from pathlib import Path

import pytest

from core.database import Database


@pytest.fixture
def cli_db(test_db_path: Path, empty_db: Database) -> Database:
    """An empty database the command line will actually open.

    The command line reads `config.json` in the directory it is given and
    opens the file named there; without it, it would open its own default
    and see an empty database, and every assertion here would pass for the
    wrong reason.
    """
    config_file = test_db_path.parent / "config.json"
    config_file.write_text(json.dumps({"database_file": str(test_db_path)}))
    return empty_db


def run_cli(db_dir: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the desktop command line exactly as a person would."""
    return subprocess.run(
        [sys.executable, "-m", "src.main", "cli", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "VOICE_CONFIG_DIR": str(db_dir)},
    )


@pytest.mark.cli
class TestMergeNotesCommand:
    """Test the notes-merge CLI command."""

    def test_merge_keeps_both_texts_in_the_older_note(
        self, test_db_path: Path, cli_db: Database
    ) -> None:
        """Both notes' text survives, in the note that was written first."""
        first = cli_db.create_note("הפגישה נדחתה ליום רביעי")
        second = cli_db.create_note("להביא את המסמכים מהמשרד")

        # Prove the command line is looking at this database before asking
        # what it did to it: pointed at the wrong one it would find nothing
        # to merge, and a test could pass without merging anything.
        listing = run_cli(test_db_path.parent, "notes-list")
        assert first[:12] in listing.stdout and second[:12] in listing.stdout

        result = run_cli(test_db_path.parent, "notes-merge", first, second)

        assert result.returncode == 0, result.stderr
        assert "Merged notes" in result.stdout

        survivor = cli_db.get_note(first)
        assert survivor is not None
        assert "הפגישה נדחתה ליום רביעי" in survivor["content"]
        assert "להביא את המסמכים מהמשרד" in survivor["content"]
        assert cli_db.get_note(second) is None, "The second note should be deleted"

    def test_merge_moves_the_recording(
        self, test_db_path: Path, cli_db: Database
    ) -> None:
        """A recording attached to the second note follows its text."""
        first = cli_db.create_note("סיכום השיחה")
        second = cli_db.create_note("ההקלטה עצמה")
        audio = cli_db.create_audio_file("Recording 2026-09-08 15-20-00.ogg")
        cli_db.attach_to_note(second, audio, "audio_file")

        result = run_cli(test_db_path.parent, "notes-merge", first, second)

        assert result.returncode == 0, result.stderr
        attachments = cli_db.get_attachments_for_note(first)
        assert [a["attachment_id"] for a in attachments] == [audio]

    def test_merge_reports_a_note_that_does_not_exist(
        self, test_db_path: Path, cli_db: Database
    ) -> None:
        """A merge that cannot be done says so, and says why.

        The whole point: an error here must reach the user's screen with its
        reason, not be turned into silence or into a different message.
        """
        real = cli_db.create_note("פתק אמיתי")
        missing = "00000000000040008000000000000099"

        result = run_cli(test_db_path.parent, "notes-merge", real, missing)

        assert result.returncode != 0
        assert result.stderr.strip() != "", "A failed merge must explain itself"

    def test_merge_json_output(
        self, test_db_path: Path, cli_db: Database
    ) -> None:
        """The JSON form names the survivor, the deleted note and the text."""
        first = cli_db.create_note("שורה ראשונה")
        second = cli_db.create_note("שורה שנייה")

        result = run_cli(
            test_db_path.parent, "--format", "json", "notes-merge", first, second
        )

        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["survivor_id"] == first
        assert data["deleted_id"] == second
        assert "שורה ראשונה" in data["content"]
        assert "שורה שנייה" in data["content"]

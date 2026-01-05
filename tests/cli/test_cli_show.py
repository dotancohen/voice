"""CLI tests for note-show command.

Tests displaying individual note details in various formats.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import get_note_uuid_hex

from core.database import Database


@pytest.mark.cli
class TestShowNote:
    """Test note-show CLI command."""

    def test_show_note_text_format(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test showing note in text format."""
        note_id = get_note_uuid_hex(1)
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main", "-d", str(test_db_path.parent), "cli",
                "note-show", note_id
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert f"ID: {note_id}" in result.stdout
        assert "Created:" in result.stdout
        assert "Meeting notes" in result.stdout

    def test_show_note_json_format(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test showing note in JSON format."""
        note_id = get_note_uuid_hex(1)
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main", "-d", str(test_db_path.parent), "cli",
                "--format", "json",
                "note-show", note_id
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        note = json.loads(result.stdout)
        assert note["id"] == note_id
        assert "content" in note
        assert "created_at" in note

    def test_show_note_csv_format(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test showing note in CSV format."""
        note_id = get_note_uuid_hex(2)
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main", "-d", str(test_db_path.parent), "cli",
                "--format", "csv",
                "note-show", note_id
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        # CSV format: id,created_at,content,tags
        assert result.stdout.startswith(note_id + ",")
        assert "documentation" in result.stdout

    def test_show_note_with_tags(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test showing note that has tags."""
        note_id = get_note_uuid_hex(1)
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main", "-d", str(test_db_path.parent), "cli",
                "note-show", note_id
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "Tags:" in result.stdout
        assert "Work" in result.stdout

    def test_show_note_nonexistent(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test showing non-existent note."""
        # Use a valid UUID format but nonexistent note
        nonexistent_id = "00000000000070008000000000009999"
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main", "-d", str(test_db_path.parent), "cli",
                "note-show", nonexistent_id
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 1
        assert "not found" in result.stderr.lower()

    def test_show_note_hebrew_content(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test showing note with Hebrew content."""
        note_id = get_note_uuid_hex(6)
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main", "-d", str(test_db_path.parent), "cli",
                "note-show", note_id
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "שלום עולם" in result.stdout

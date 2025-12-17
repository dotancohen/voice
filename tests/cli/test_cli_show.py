"""CLI tests for show-note command.

Tests displaying individual note details in various formats.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.database import Database


@pytest.mark.cli
class TestShowNote:
    """Test show-note CLI command."""

    def test_show_note_text_format(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test showing note in text format."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "show-note", "1"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "ID: 1" in result.stdout
        assert "Created:" in result.stdout
        assert "Meeting notes" in result.stdout

    def test_show_note_json_format(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test showing note in JSON format."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "--format", "json",
                "show-note", "1"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        note = json.loads(result.stdout)
        assert note["id"] == 1
        assert "content" in note
        assert "created_at" in note

    def test_show_note_csv_format(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test showing note in CSV format."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "--format", "csv",
                "show-note", "2"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        # CSV format: id,created_at,content,tags
        assert result.stdout.startswith("2,")
        assert "documentation" in result.stdout

    def test_show_note_with_tags(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test showing note that has tags."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "show-note", "1"
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
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "show-note", "9999"
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
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "show-note", "6"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "שלום עולם" in result.stdout

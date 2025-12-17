"""CLI tests for list commands (list-notes, list-tags).

Tests the CLI commands for listing notes and tags in various formats.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.database import Database


@pytest.mark.cli
class TestListNotes:
    """Test list-notes CLI command."""

    def test_list_notes_text_format(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test listing notes in text format."""
        result = subprocess.run(
            ["python3", "-m", "src.cli", "-d", str(test_db_path.parent), "list-notes"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "ID:" in result.stdout
        assert "Created:" in result.stdout
        # Should show multiple notes
        assert result.stdout.count("ID:") == 9

    def test_list_notes_json_format(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test listing notes in JSON format."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "--format", "json",
                "list-notes"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        notes = json.loads(result.stdout)
        assert isinstance(notes, list)
        assert len(notes) == 9
        assert all("id" in note for note in notes)
        assert all("content" in note for note in notes)

    def test_list_notes_csv_format(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test listing notes in CSV format."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "--format", "csv",
                "list-notes"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        lines = result.stdout.strip().split("\n")
        assert lines[0] == "id,created_at,content,tags"
        assert len(lines) == 10  # Header + 9 notes

    def test_list_notes_empty_database(self, test_db_path: Path) -> None:
        """Test listing notes from empty database."""
        # Create empty database
        from core.database import Database
        db = Database(test_db_path)
        db.close()

        result = subprocess.run(
            ["python3", "-m", "src.cli", "-d", str(test_db_path.parent), "list-notes"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "No notes found" in result.stdout


@pytest.mark.cli
class TestListTags:
    """Test list-tags CLI command."""

    def test_list_tags_text_format(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test listing tags in text format with hierarchy."""
        result = subprocess.run(
            ["python3", "-m", "src.cli", "-d", str(test_db_path.parent), "list-tags"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        # Should show root tags
        assert "Work" in result.stdout
        assert "Personal" in result.stdout
        assert "Geography" in result.stdout
        # Should show indented children
        assert "  Projects" in result.stdout
        assert "  Meetings" in result.stdout

    def test_list_tags_json_format(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test listing tags in JSON format."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "--format", "json",
                "list-tags"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        tags = json.loads(result.stdout)
        assert isinstance(tags, list)
        assert len(tags) == 21  # All tags from fixture
        assert all("id" in tag for tag in tags)
        assert all("name" in tag for tag in tags)

    def test_list_tags_csv_format(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test listing tags in CSV format."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "--format", "csv",
                "list-tags"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        lines = result.stdout.strip().split("\n")
        assert lines[0] == "id,name,parent_id"
        assert len(lines) == 22  # Header + 21 tags

    def test_list_tags_shows_hierarchy(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test that tag hierarchy is properly displayed."""
        result = subprocess.run(
            ["python3", "-m", "src.cli", "-d", str(test_db_path.parent), "list-tags"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        lines = result.stdout.strip().split("\n")

        # Find Work and its children
        work_line = next(i for i, line in enumerate(lines) if "Work (ID:" in line)
        projects_line = next(i for i, line in enumerate(lines) if "Projects (ID:" in line)

        # Projects should come after Work and be indented
        assert projects_line > work_line
        assert lines[projects_line].startswith("  ")

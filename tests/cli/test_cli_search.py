"""CLI tests for search command.

Tests searching notes by text and tags via CLI.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.database import Database


@pytest.mark.cli
class TestSearchText:
    """Test search command with text queries."""

    def test_search_by_text(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test searching by text."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "search", "--text", "meeting"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "Meeting notes" in result.stdout
        assert "Found 1 note(s)" in result.stdout

    def test_search_case_insensitive(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test that text search is case-insensitive."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "search", "--text", "DOCTOR"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "Doctor appointment" in result.stdout

    def test_search_hebrew_text(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test searching Hebrew text."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "search", "--text", "שלום"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "שלום עולם" in result.stdout

    def test_search_no_results(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test search with no matching results."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "search", "--text", "nonexistent"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "No notes found" in result.stdout


@pytest.mark.cli
class TestSearchTags:
    """Test search command with tag filters."""

    def test_search_by_single_tag(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test searching by single tag."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "search", "--tag", "Work"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        # Should find notes with Work tag
        assert "Meeting notes" in result.stdout
        assert "documentation" in result.stdout

    def test_search_by_hierarchical_tag(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test searching by hierarchical tag path."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "search", "--tag", "Geography/Europe/France/Paris"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "reunion" in result.stdout.lower()

    def test_search_parent_includes_children(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test that parent tag search includes child tags."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "search", "--tag", "Personal"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        # Should find notes with Personal and its children (Family, Health)
        assert "Found 4 note(s)" in result.stdout

    def test_search_multiple_tags_and_logic(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test searching with multiple tags (AND logic)."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "search",
                "--tag", "Work",
                "--tag", "Work/Projects"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        # Should find notes with both Work AND Projects
        assert "Found 2 note(s)" in result.stdout

    def test_search_nonexistent_tag(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test searching with non-existent tag."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "search", "--tag", "NonExistentTag"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "Warning: Tag 'NonExistentTag' not found" in result.stderr
        # Should show no results
        assert "No notes found" in result.stdout or result.stdout.count("ID:") == 0


@pytest.mark.cli
class TestSearchCombined:
    """Test search command with combined text and tags."""

    def test_search_text_and_tag(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test searching with both text and tag."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "search",
                "--text", "meeting",
                "--tag", "Work"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "Meeting notes" in result.stdout
        assert "Found 1 note(s)" in result.stdout

    def test_search_text_and_multiple_tags(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test searching with text and multiple tags."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "search",
                "--text", "reunion",
                "--tag", "Personal",
                "--tag", "Geography"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "reunion" in result.stdout.lower()
        assert "Found 1 note(s)" in result.stdout


@pytest.mark.cli
class TestSearchOutputFormats:
    """Test search command output formats."""

    def test_search_json_format(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test search with JSON output."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "--format", "json",
                "search", "--tag", "Work"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        notes = json.loads(result.stdout)
        assert isinstance(notes, list)
        assert len(notes) >= 2

    def test_search_csv_format(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test search with CSV output."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "--format", "csv",
                "search", "--text", "Doctor"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        lines = result.stdout.strip().split("\n")
        assert lines[0] == "id,created_at,content,tags"
        assert "Doctor" in result.stdout

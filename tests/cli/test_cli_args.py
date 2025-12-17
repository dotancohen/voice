"""CLI tests for argument parsing and general functionality.

Tests CLI argument parsing, help messages, and error handling.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.database import Database


@pytest.mark.cli
class TestCLIArguments:
    """Test CLI argument parsing."""

    def test_no_command_shows_help(self) -> None:
        """Test that running CLI without command shows help."""
        result = subprocess.run(
            ["python3", "-m", "src.cli"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 1
        assert "usage:" in result.stdout.lower()
        assert "list-notes" in result.stdout
        assert "show-note" in result.stdout
        assert "list-tags" in result.stdout
        assert "search" in result.stdout

    def test_help_flag(self) -> None:
        """Test --help flag."""
        result = subprocess.run(
            ["python3", "-m", "src.cli", "--help"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "usage:" in result.stdout.lower()
        assert "--config-dir" in result.stdout

    def test_custom_config_dir(
        self, tmp_path: Path, populated_db: Database, test_db_path: Path
    ) -> None:
        """Test using custom config directory."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "list-notes"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "ID:" in result.stdout

    def test_invalid_command(self) -> None:
        """Test running invalid command."""
        result = subprocess.run(
            ["python3", "-m", "src.cli", "invalid-command"],
            capture_output=True,
            text=True
        )

        assert result.returncode != 0

    def test_show_note_missing_id(self, test_db_path: Path) -> None:
        """Test show-note without providing note ID."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "show-note"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode != 0
        assert "error" in result.stderr.lower()


@pytest.mark.cli
class TestCLIOutputFormats:
    """Test CLI output format options."""

    def test_invalid_format(self, test_db_path: Path, populated_db: Database) -> None:
        """Test specifying invalid output format."""
        result = subprocess.run(
            [
                "python3", "-m", "src.cli",
                "-d", str(test_db_path.parent),
                "--format", "invalid",
                "list-notes"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode != 0
        assert "error" in result.stderr.lower()

    def test_format_before_command(
        self, test_db_path: Path, populated_db: Database
    ) -> None:
        """Test that --format must come before subcommand."""
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
        # Should parse JSON successfully
        assert result.stdout.startswith("[")


@pytest.mark.cli
class TestCLISubcommandHelp:
    """Test help for individual subcommands."""

    def test_list_notes_help(self) -> None:
        """Test list-notes help."""
        result = subprocess.run(
            ["python3", "-m", "src.cli", "list-notes", "--help"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "list-notes" in result.stdout.lower()

    def test_show_note_help(self) -> None:
        """Test show-note help."""
        result = subprocess.run(
            ["python3", "-m", "src.cli", "show-note", "--help"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "note_id" in result.stdout.lower()

    def test_list_tags_help(self) -> None:
        """Test list-tags help."""
        result = subprocess.run(
            ["python3", "-m", "src.cli", "list-tags", "--help"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "list-tags" in result.stdout.lower()

    def test_search_help(self) -> None:
        """Test search help."""
        result = subprocess.run(
            ["python3", "-m", "src.cli", "search", "--help"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "--text" in result.stdout
        assert "--tag" in result.stdout

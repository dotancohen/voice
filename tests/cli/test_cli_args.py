"""CLI tests for argument parsing and general functionality.

Tests CLI argument parsing, help messages, and error handling.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from core.database import Database


@pytest.mark.cli
class TestCLIArguments:
    """Test CLI argument parsing."""

    def test_no_command_shows_error(self) -> None:
        """Test that running CLI without command shows error message."""
        result = subprocess.run(
            [sys.executable, "-m", "src.main", "cli"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 1
        assert "No CLI command specified" in result.stderr
        assert "--help" in result.stderr

    def test_help_flag(self) -> None:
        """Test --help flag shows CLI subcommands."""
        result = subprocess.run(
            [sys.executable, "-m", "src.main", "cli", "--help"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "usage:" in result.stdout.lower()
        assert "notes-list" in result.stdout
        assert "note-show" in result.stdout
        assert "tags-list" in result.stdout
        assert "notes-search" in result.stdout

    def test_custom_config_dir(
        self, tmp_path: Path, populated_db: Database, test_db_path: Path
    ) -> None:
        """Test using custom config directory."""
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "-d", str(test_db_path.parent),
                "cli", "notes-list"
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        # New format is: "ID | Created | First line content"
        assert "|" in result.stdout

    def test_invalid_command(self) -> None:
        """Test running invalid command."""
        result = subprocess.run(
            [sys.executable, "-m", "src.main", "cli", "invalid-command"],
            capture_output=True,
            text=True
        )

        assert result.returncode != 0

    def test_show_note_missing_id(self, test_db_path: Path) -> None:
        """Test note-show without providing note ID."""
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "-d", str(test_db_path.parent),
                "cli", "note-show"
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
                sys.executable, "-m", "src.main",
                "-d", str(test_db_path.parent),
                "cli", "--format", "invalid",
                "notes-list"
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
                sys.executable, "-m", "src.main",
                "-d", str(test_db_path.parent),
                "cli", "--format", "json",
                "notes-list"
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

    def test_notes_list_help(self) -> None:
        """Test notes-list help."""
        result = subprocess.run(
            [sys.executable, "-m", "src.main", "cli", "notes-list", "--help"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "notes-list" in result.stdout.lower()

    def test_note_show_help(self) -> None:
        """Test note-show help."""
        result = subprocess.run(
            [sys.executable, "-m", "src.main", "cli", "note-show", "--help"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "note_id" in result.stdout.lower()

    def test_tags_list_help(self) -> None:
        """Test tags-list help."""
        result = subprocess.run(
            [sys.executable, "-m", "src.main", "cli", "tags-list", "--help"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "tags-list" in result.stdout.lower()

    def test_notes_search_help(self) -> None:
        """Test notes-search help."""
        result = subprocess.run(
            [sys.executable, "-m", "src.main", "cli", "notes-search", "--help"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "--text" in result.stdout
        assert "--tag" in result.stdout

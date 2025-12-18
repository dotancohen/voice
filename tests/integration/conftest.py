"""Pytest fixtures for integration tests.

Provides fixtures for large datasets and cross-interface testing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generator

import pytest

from core.config import Config
from core.database import Database


@pytest.fixture
def large_db(test_config_dir: Path) -> Generator[Database, None, None]:
    """Create test database with large dataset for performance testing.

    Creates:
    - 1000 notes with varying content lengths
    - 100 tags in a 10-level deep hierarchy
    - Multiple tag assignments per note

    Args:
        test_config_dir: Temporary config directory

    Yields:
        Database instance with large dataset.
    """
    db_path = test_config_dir / "large_test.db"
    db = Database(db_path)

    with db.conn:
        cursor = db.conn.cursor()

        # Create deep tag hierarchy (10 levels, 10 branches)
        tag_id = 1
        for branch in range(10):
            parent_id = None
            for level in range(10):
                cursor.execute(
                    "INSERT INTO tags (id, name, parent_id) VALUES (?, ?, ?)",
                    (tag_id, f"Tag_B{branch}_L{level}", parent_id),
                )
                parent_id = tag_id
                tag_id += 1

        # Create 1000 notes with varying content
        base_time = datetime(2025, 1, 1, 0, 0, 0)
        for note_id in range(1, 1001):
            created_at = base_time + timedelta(hours=note_id)
            content_length = 50 + (note_id % 500)  # Vary content length 50-550 chars
            content = f"Note {note_id}: " + "x" * content_length

            cursor.execute(
                "INSERT INTO notes (id, created_at, content) VALUES (?, ?, ?)",
                (note_id, created_at.strftime("%Y-%m-%d %H:%M:%S"), content),
            )

            # Assign 1-5 tags per note
            num_tags = (note_id % 5) + 1
            for i in range(num_tags):
                assigned_tag_id = ((note_id + i * 7) % 100) + 1
                try:
                    cursor.execute(
                        "INSERT INTO note_tags (note_id, tag_id) VALUES (?, ?)",
                        (note_id, assigned_tag_id),
                    )
                except Exception:
                    pass  # Ignore duplicate key errors

        db.conn.commit()

    # Create config.json
    config_file = test_config_dir / "config.json"
    config_data = {
        "database_file": str(db_path),
        "window_geometry": None,
        "themes": {"dark": {"warning_color": "#FFFF00"}},
    }
    with open(config_file, "w") as f:
        json.dump(config_data, f, indent=2)

    yield db
    db.close()
    if db_path.exists():
        db_path.unlink()
    if config_file.exists():
        config_file.unlink()


@pytest.fixture
def cli_runner(test_config_dir: Path):
    """Create a CLI runner function for integration tests.

    Returns:
        Function that runs CLI commands and returns (returncode, stdout, stderr).
    """

    def run_cli(*args: str) -> tuple[int, str, str]:
        """Run CLI command with given arguments.

        Args:
            *args: CLI arguments (e.g., "list-notes", "--format", "json")

        Returns:
            Tuple of (return_code, stdout, stderr).
        """
        cmd = [
            sys.executable,
            "-m",
            "src.main",
            "-d",
            str(test_config_dir),
            "cli",
            *args,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode, result.stdout, result.stderr

    return run_cli


@pytest.fixture
def web_client(test_config_dir: Path, populated_db: Database):
    """Create Flask test client for integration tests.

    Args:
        test_config_dir: Temporary config directory
        populated_db: Populated database fixture

    Returns:
        Flask test client.
    """
    from web import create_app

    app = create_app(config_dir=test_config_dir)
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client

"""Pytest fixtures for integration tests.

Provides fixtures for large datasets and cross-interface testing.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generator

import pytest

from core.config import Config
from core.database import Database, set_local_device_id


# Device ID for large_db fixture
LARGE_DB_DEVICE_ID = uuid.UUID("00000000-0000-7000-8000-000000000099").bytes


def generate_uuid(prefix: int, index: int) -> bytes:
    """Generate a deterministic UUID bytes for testing.

    Args:
        prefix: First digit of the UUID's counter part (0-99)
        index: Index to generate unique UUID (0-9999)

    Returns:
        16-byte UUID
    """
    # Format: 00000000-0000-7000-8000-0000PP00IIII
    # Must be 32 hex characters (16 bytes)
    # 8 + 4 + 4 + 4 + 4 + 2 + 2 + 4 = 32
    hex_str = f"000000000000700080000000{prefix:02d}00{index:04d}"
    return uuid.UUID(hex_str).bytes


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
    # Set device ID before creating database
    set_local_device_id(LARGE_DB_DEVICE_ID)

    db_path = test_config_dir / "large_test.db"
    db = Database(db_path)

    base_time = datetime(2025, 1, 1, 0, 0, 0)

    with db.conn:
        cursor = db.conn.cursor()

        # Create deep tag hierarchy (10 levels, 10 branches)
        # Total 100 tags
        tag_index = 0
        tag_uuids = []  # Store all tag UUIDs for reference

        for branch in range(10):
            parent_id = None
            for level in range(10):
                tag_id = generate_uuid(1, tag_index)
                tag_uuids.append(tag_id)
                tag_time = base_time + timedelta(minutes=tag_index)
                cursor.execute(
                    "INSERT INTO tags (id, name, parent_id, created_at) VALUES (?, ?, ?, ?)",
                    (tag_id, f"Tag_B{branch}_L{level}", parent_id, tag_time.strftime("%Y-%m-%d %H:%M:%S")),
                )
                parent_id = tag_id
                tag_index += 1

        # Create 1000 notes with varying content
        note_uuids = []
        for note_num in range(1, 1001):
            note_id = generate_uuid(2, note_num)
            note_uuids.append(note_id)
            created_at = base_time + timedelta(hours=note_num)
            content_length = 50 + (note_num % 500)  # Vary content length 50-550 chars
            content = f"Note {note_num}: " + "x" * content_length

            cursor.execute(
                "INSERT INTO notes (id, created_at, content) VALUES (?, ?, ?)",
                (note_id, created_at.strftime("%Y-%m-%d %H:%M:%S"), content),
            )

            # Assign 1-5 tags per note
            num_tags = (note_num % 5) + 1
            for i in range(num_tags):
                assigned_tag_idx = ((note_num + i * 7) % 100)
                assigned_tag_id = tag_uuids[assigned_tag_idx]
                try:
                    cursor.execute(
                        "INSERT INTO note_tags (note_id, tag_id, created_at) VALUES (?, ?, ?)",
                        (note_id, assigned_tag_id, created_at.strftime("%Y-%m-%d %H:%M:%S")),
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

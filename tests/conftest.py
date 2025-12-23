"""Pytest fixtures for Voice tests.

This module provides fixtures for test configuration, database, and Qt application setup.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Generator, Dict, List

import pytest
from PySide6.QtWidgets import QApplication
from uuid6 import uuid7

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.config import Config
from core.database import Database, set_local_device_id


# Pre-generated UUIDs for consistent test data
# Using deterministic UUIDs for predictable testing
TEST_DEVICE_ID = uuid.UUID("00000000-0000-7000-8000-000000000001").bytes

# Tag UUIDs (using a pattern for easy identification)
TAG_UUIDS = {
    "Work": uuid.UUID("00000000-0000-7000-8000-000000000101").bytes,
    "Projects": uuid.UUID("00000000-0000-7000-8000-000000000102").bytes,
    "Voice": uuid.UUID("00000000-0000-7000-8000-000000000103").bytes,
    "Meetings": uuid.UUID("00000000-0000-7000-8000-000000000104").bytes,
    "Personal": uuid.UUID("00000000-0000-7000-8000-000000000105").bytes,
    "Family": uuid.UUID("00000000-0000-7000-8000-000000000106").bytes,
    "Health": uuid.UUID("00000000-0000-7000-8000-000000000107").bytes,
    "Geography": uuid.UUID("00000000-0000-7000-8000-000000000108").bytes,
    "Europe": uuid.UUID("00000000-0000-7000-8000-000000000109").bytes,
    "France": uuid.UUID("00000000-0000-7000-8000-000000000110").bytes,
    "Paris_France": uuid.UUID("00000000-0000-7000-8000-000000000111").bytes,
    "Germany": uuid.UUID("00000000-0000-7000-8000-000000000112").bytes,
    "Asia": uuid.UUID("00000000-0000-7000-8000-000000000113").bytes,
    "Israel": uuid.UUID("00000000-0000-7000-8000-000000000114").bytes,
    "Foo": uuid.UUID("00000000-0000-7000-8000-000000000115").bytes,
    "bar_Foo": uuid.UUID("00000000-0000-7000-8000-000000000116").bytes,
    "Boom": uuid.UUID("00000000-0000-7000-8000-000000000117").bytes,
    "bar_Boom": uuid.UUID("00000000-0000-7000-8000-000000000118").bytes,
    "US": uuid.UUID("00000000-0000-7000-8000-000000000119").bytes,
    "Texas": uuid.UUID("00000000-0000-7000-8000-000000000120").bytes,
    "Paris_Texas": uuid.UUID("00000000-0000-7000-8000-000000000121").bytes,
}

# Note UUIDs
NOTE_UUIDS = {
    1: uuid.UUID("00000000-0000-7000-8000-000000000201").bytes,
    2: uuid.UUID("00000000-0000-7000-8000-000000000202").bytes,
    3: uuid.UUID("00000000-0000-7000-8000-000000000203").bytes,
    4: uuid.UUID("00000000-0000-7000-8000-000000000204").bytes,
    5: uuid.UUID("00000000-0000-7000-8000-000000000205").bytes,
    6: uuid.UUID("00000000-0000-7000-8000-000000000206").bytes,
    7: uuid.UUID("00000000-0000-7000-8000-000000000207").bytes,
    8: uuid.UUID("00000000-0000-7000-8000-000000000208").bytes,
    9: uuid.UUID("00000000-0000-7000-8000-000000000209").bytes,
}


def uuid_to_hex(value: bytes) -> str:
    """Convert UUID bytes to hex string."""
    return uuid.UUID(bytes=value).hex


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Create QApplication instance for Qt tests.

    Returns:
        QApplication instance that persists for entire test session.
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def test_config_dir(tmp_path: Path) -> Path:
    """Create temporary config directory for tests.

    Args:
        tmp_path: pytest temporary directory fixture

    Returns:
        Path to temporary config directory.
    """
    config_dir = tmp_path / "voice_test"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


@pytest.fixture
def test_config(test_config_dir: Path) -> Config:
    """Create test configuration.

    Args:
        test_config_dir: Temporary config directory

    Returns:
        Config instance for testing.
    """
    return Config(config_dir=test_config_dir)


@pytest.fixture
def test_db_path(test_config_dir: Path) -> Path:
    """Get path for test database.

    Args:
        test_config_dir: Temporary config directory

    Returns:
        Path to test database file.
    """
    return test_config_dir / "test_notes.db"


@pytest.fixture
def empty_db(test_db_path: Path) -> Generator[Database, None, None]:
    """Create empty test database.

    Args:
        test_db_path: Path to test database

    Yields:
        Empty Database instance.
    """
    # Set test device ID
    set_local_device_id(TEST_DEVICE_ID)

    db = Database(test_db_path)
    yield db
    db.close()
    if test_db_path.exists():
        test_db_path.unlink()


@pytest.fixture
def populated_db(test_db_path: Path) -> Generator[Database, None, None]:
    """Create test database with sample data.

    Creates a hierarchical tag structure and multiple notes for testing:

    Tag Hierarchy:
        Work
        ├── Projects
        │   └── Voice
        └── Meetings
        Personal
        ├── Family
        └── Health
        Geography
        ├── Europe
        │   ├── France
        │   │   └── Paris
        │   └── Germany
        ├── Asia
        │   └── Israel
        └── US
            └── Texas
                └── Paris
        Foo
        └── bar
        Boom
        └── bar

    Notes:
        1. "Meeting notes from project kickoff" (Work, Projects, Meetings)
        2. "Remember to update documentation" (Work, Projects, Voice)
        3. "Doctor appointment next Tuesday" (Personal, Health)
        4. "Family reunion in Paris" (Personal, Family, France, Paris)
        5. "Trip to Israel planning" (Personal, Asia, Israel)
        6. "שלום עולם - Hebrew text test" (Personal)
        7. "Testing ambiguous tag with Foo/bar" (Foo, bar under Foo)
        8. "Another note with Boom/bar" (Boom, bar under Boom)
        9. "Cowboys in Paris, Texas" (US, Texas, Paris under Texas)

    Args:
        test_db_path: Path to test database

    Yields:
        Populated Database instance.
    """
    # Set test device ID
    set_local_device_id(TEST_DEVICE_ID)

    db = Database(test_db_path)

    # Create tag hierarchy
    tags = [
        # (uuid_key, name, parent_uuid_key or None)
        ("Work", "Work", None),
        ("Projects", "Projects", "Work"),
        ("Voice", "Voice", "Projects"),
        ("Meetings", "Meetings", "Work"),
        ("Personal", "Personal", None),
        ("Family", "Family", "Personal"),
        ("Health", "Health", "Personal"),
        ("Geography", "Geography", None),
        ("Europe", "Europe", "Geography"),
        ("France", "France", "Europe"),
        ("Paris_France", "Paris", "France"),
        ("Germany", "Germany", "Europe"),
        ("Asia", "Asia", "Geography"),
        ("Israel", "Israel", "Asia"),
        ("Foo", "Foo", None),
        ("bar_Foo", "bar", "Foo"),
        ("Boom", "Boom", None),
        ("bar_Boom", "bar", "Boom"),
        ("US", "US", "Geography"),
        ("Texas", "Texas", "US"),
        ("Paris_Texas", "Paris", "Texas"),
    ]

    with db.conn:
        cursor = db.conn.cursor()
        base_time = datetime(2025, 1, 1, 10, 0, 0)

        for uuid_key, name, parent_key in tags:
            tag_id = TAG_UUIDS[uuid_key]
            parent_id = TAG_UUIDS[parent_key] if parent_key else None
            cursor.execute(
                "INSERT INTO tags (id, name, parent_id, created_at) VALUES (?, ?, ?, ?)",
                (tag_id, name, parent_id, base_time.strftime("%Y-%m-%d %H:%M:%S"))
            )

        # Create notes
        # Map note number to (content, list of tag uuid keys)
        notes = [
            (1, "Meeting notes from project kickoff", ["Work", "Projects", "Meetings"]),
            (2, "Remember to update documentation", ["Work", "Projects", "Voice"]),
            (3, "Doctor appointment next Tuesday", ["Personal", "Health"]),
            (4, "Family reunion in Paris", ["Personal", "Family", "France", "Paris_France"]),
            (5, "Trip to Israel planning", ["Personal", "Asia", "Israel"]),
            (6, "שלום עולם - Hebrew text test", ["Personal"]),
            (7, "Testing ambiguous tag with Foo/bar", ["Foo", "bar_Foo"]),
            (8, "Another note with Boom/bar", ["Boom", "bar_Boom"]),
            (9, "Cowboys in Paris, Texas", ["US", "Texas", "Paris_Texas"]),
        ]

        for i, (note_num, content, tag_keys) in enumerate(notes):
            note_id = NOTE_UUIDS[note_num]
            # Stagger creation times
            created_at = base_time.replace(hour=10 + i)
            cursor.execute(
                "INSERT INTO notes (id, created_at, content) VALUES (?, ?, ?)",
                (note_id, created_at.strftime("%Y-%m-%d %H:%M:%S"), content)
            )

            # Associate tags
            for tag_key in tag_keys:
                tag_id = TAG_UUIDS[tag_key]
                cursor.execute(
                    "INSERT INTO note_tags (note_id, tag_id, created_at) VALUES (?, ?, ?)",
                    (note_id, tag_id, created_at.strftime("%Y-%m-%d %H:%M:%S"))
                )

        db.conn.commit()

    # Create config.json for CLI tests
    import json
    config_file = test_db_path.parent / "config.json"
    config_data = {
        "database_file": str(test_db_path),
        "window_geometry": None,
        "themes": {
            "dark": {
                "warning_color": "#FFFF00"
            }
        }
    }
    with open(config_file, "w") as f:
        json.dump(config_data, f, indent=2)

    yield db
    db.close()
    if test_db_path.exists():
        test_db_path.unlink()
    if config_file.exists():
        config_file.unlink()


# Helper functions for tests to get UUIDs
def get_tag_uuid(key: str) -> bytes:
    """Get tag UUID bytes by key name."""
    return TAG_UUIDS[key]


def get_tag_uuid_hex(key: str) -> str:
    """Get tag UUID hex string by key name."""
    return uuid_to_hex(TAG_UUIDS[key])


def get_note_uuid(num: int) -> bytes:
    """Get note UUID bytes by number."""
    return NOTE_UUIDS[num]


def get_note_uuid_hex(num: int) -> str:
    """Get note UUID hex string by number."""
    return uuid_to_hex(NOTE_UUIDS[num])

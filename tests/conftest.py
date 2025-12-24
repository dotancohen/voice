"""Pytest fixtures for Voice tests.

This module provides fixtures for test configuration, database, and Qt application setup.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Generator, Dict, List, Any

import pytest
from PySide6.QtWidgets import QApplication

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.config import Config
from core.database import Database, set_local_device_id


# Test device ID (hex string - 32 chars)
TEST_DEVICE_ID = "00000000000070008000000000000001"

# These will be populated by the populated_db fixture
TAG_IDS: Dict[str, str] = {}
NOTE_IDS: Dict[int, str] = {}

# Backward compatibility - these are now dynamic, not pre-determined
# Tests should use get_tag_uuid_hex() and get_note_uuid_hex() instead
TAG_UUIDS: Dict[str, bytes] = {}  # Will be populated after fixture runs
NOTE_UUIDS: Dict[int, bytes] = {}  # Will be populated after fixture runs


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
    global TAG_IDS, NOTE_IDS, TAG_UUIDS, NOTE_UUIDS
    TAG_IDS.clear()
    NOTE_IDS.clear()
    TAG_UUIDS.clear()
    NOTE_UUIDS.clear()

    # Set test device ID
    set_local_device_id(TEST_DEVICE_ID)

    db = Database(test_db_path)

    # Create tag hierarchy using Database API
    # (key, name, parent_key or None)
    tags = [
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

    for key, name, parent_key in tags:
        parent_id = TAG_IDS.get(parent_key) if parent_key else None
        tag_id = db.create_tag(name, parent_id)
        TAG_IDS[key] = tag_id
        TAG_UUIDS[key] = uuid.UUID(hex=tag_id).bytes

    # Create notes
    # (note_num, content, list of tag keys)
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

    for note_num, content, tag_keys in notes:
        note_id = db.create_note(content)
        NOTE_IDS[note_num] = note_id
        NOTE_UUIDS[note_num] = uuid.UUID(hex=note_id).bytes

        # Associate tags
        for tag_key in tag_keys:
            db.add_tag_to_note(note_id, TAG_IDS[tag_key])

    # Create config.json for CLI tests
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
    hex_id = TAG_IDS.get(key)
    if hex_id:
        return uuid.UUID(hex=hex_id).bytes
    raise KeyError(f"Tag key '{key}' not found. Make sure populated_db fixture is used.")


def get_tag_uuid_hex(key: str) -> str:
    """Get tag UUID hex string by key name."""
    hex_id = TAG_IDS.get(key)
    if hex_id:
        return hex_id
    raise KeyError(f"Tag key '{key}' not found. Make sure populated_db fixture is used.")


def get_note_uuid(num: int) -> bytes:
    """Get note UUID bytes by number."""
    hex_id = NOTE_IDS.get(num)
    if hex_id:
        return uuid.UUID(hex=hex_id).bytes
    raise KeyError(f"Note number {num} not found. Make sure populated_db fixture is used.")


def get_note_uuid_hex(num: int) -> str:
    """Get note UUID hex string by number."""
    hex_id = NOTE_IDS.get(num)
    if hex_id:
        return hex_id
    raise KeyError(f"Note number {num} not found. Make sure populated_db fixture is used.")

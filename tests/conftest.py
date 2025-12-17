"""Pytest fixtures for Voice Rewrite tests.

This module provides fixtures for test configuration, database, and Qt application setup.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Generator

import pytest
from PySide6.QtWidgets import QApplication

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.config import Config
from core.database import Database


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
    config_dir = tmp_path / "voicerewrite_test"
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
        Work (1)
        ├── Projects (2)
        │   └── VoiceRewrite (3)
        └── Meetings (4)
        Personal (5)
        ├── Family (6)
        └── Health (7)
        Geography (8)
        ├── Europe (9)
        │   ├── France (10)
        │   │   └── Paris (11)
        │   └── Germany (12)
        └── Asia (13)
            └── Israel (14)

    Notes:
        1. "Meeting notes from project kickoff" (Work, Projects, Meetings)
        2. "Remember to update documentation" (Work, Projects, VoiceRewrite)
        3. "Doctor appointment next Tuesday" (Personal, Health)
        4. "Family reunion in Paris" (Personal, Family, France, Paris)
        5. "Trip to Israel planning" (Personal, Asia, Israel)
        6. "שלום עולם - Hebrew text test" (Personal)

    Args:
        test_db_path: Path to test database

    Yields:
        Populated Database instance.
    """
    db = Database(test_db_path)

    # Create tag hierarchy
    tags = [
        # Work hierarchy
        (1, "Work", None),
        (2, "Projects", 1),
        (3, "VoiceRewrite", 2),
        (4, "Meetings", 1),
        # Personal hierarchy
        (5, "Personal", None),
        (6, "Family", 5),
        (7, "Health", 5),
        # Geography hierarchy
        (8, "Geography", None),
        (9, "Europe", 8),
        (10, "France", 9),
        (11, "Paris", 10),
        (12, "Germany", 9),
        (13, "Asia", 8),
        (14, "Israel", 13),
    ]

    with db.conn:
        cursor = db.conn.cursor()
        for tag_id, name, parent_id in tags:
            cursor.execute(
                "INSERT INTO tags (id, name, parent_id) VALUES (?, ?, ?)",
                (tag_id, name, parent_id)
            )

        # Create notes
        base_time = datetime(2025, 1, 1, 10, 0, 0)
        notes = [
            (1, "Meeting notes from project kickoff", [1, 2, 4]),
            (2, "Remember to update documentation", [1, 2, 3]),
            (3, "Doctor appointment next Tuesday", [5, 7]),
            (4, "Family reunion in Paris", [5, 6, 10, 11]),
            (5, "Trip to Israel planning", [5, 13, 14]),
            (6, "שלום עולם - Hebrew text test", [5]),
        ]

        for i, (note_id, content, tag_ids) in enumerate(notes):
            # Stagger creation times
            created_at = base_time.replace(hour=10 + i)
            cursor.execute(
                "INSERT INTO notes (id, created_at, content) VALUES (?, ?, ?)",
                (note_id, created_at.strftime("%Y-%m-%d %H:%M:%S"), content)
            )

            # Associate tags
            for tag_id in tag_ids:
                cursor.execute(
                    "INSERT INTO note_tags (note_id, tag_id) VALUES (?, ?)",
                    (note_id, tag_id)
                )

        db.conn.commit()

    yield db
    db.close()
    if test_db_path.exists():
        test_db_path.unlink()

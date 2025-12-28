"""Fixtures for display tests."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Generator

import pytest
from flask import Flask
from flask.testing import FlaskClient

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture
def web_app(test_db_path: Path, populated_db) -> Generator[Flask, None, None]:
    """Create Flask app for testing."""
    from src.web import create_app
    app = create_app(config_dir=test_db_path.parent)
    app.config["TESTING"] = True
    yield app


@pytest.fixture
def client(web_app: Flask) -> FlaskClient:
    """Create Flask test client."""
    return web_app.test_client()

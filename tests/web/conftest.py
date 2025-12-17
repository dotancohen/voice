"""Pytest fixtures for web API tests.

Provides Flask test client and test database for web API testing.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from typing import Generator

from flask import Flask
from flask.testing import FlaskClient

from src.web import create_app
from core.database import Database


@pytest.fixture
def web_app(test_db_path: Path, populated_db: Database) -> Generator[Flask, None, None]:
    """Create Flask app for testing.

    Args:
        test_db_path: Path to test database
        populated_db: Populated database fixture

    Yields:
        Flask application instance
    """
    app = create_app(config_dir=test_db_path.parent)
    app.config["TESTING"] = True
    yield app


@pytest.fixture
def client(web_app: Flask) -> FlaskClient:
    """Create Flask test client.

    Args:
        web_app: Flask application

    Returns:
        Flask test client for making requests
    """
    return web_app.test_client()

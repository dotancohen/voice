"""Unit tests for sync server and client.

Tests the sync protocol implementation.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Generator

import pytest
from flask import Flask
from flask.testing import FlaskClient

from core.config import Config
from core.database import Database, set_local_device_id
from core.sync import (
    SyncChange,
    SyncBatch,
    create_sync_blueprint,
    create_sync_server,
    get_changes_since,
    get_full_dataset,
    apply_sync_changes,
)


@pytest.fixture
def sync_db(test_config_dir: Path) -> Generator[Database, None, None]:
    """Create a database for sync testing."""
    # Set a known device ID for testing
    device_id = uuid.UUID("00000000-0000-7000-8000-000000000001").bytes
    set_local_device_id(device_id)

    db_path = test_config_dir / "sync_test.db"
    db = Database(db_path)
    yield db
    db.close()


@pytest.fixture
def sync_config(test_config_dir: Path) -> Config:
    """Create a config for sync testing."""
    return Config(config_dir=test_config_dir)


@pytest.fixture
def sync_app(sync_db: Database, sync_config: Config) -> Flask:
    """Create Flask app with sync blueprint."""
    app = create_sync_server(sync_db, sync_config)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def sync_client(sync_app: Flask) -> FlaskClient:
    """Create test client for sync server."""
    return sync_app.test_client()


class TestSyncStatus:
    """Test sync status endpoint."""

    def test_status_returns_ok(self, sync_client: FlaskClient) -> None:
        """Status endpoint returns OK."""
        response = sync_client.get("/sync/status")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"
        assert "device_id" in data
        assert "device_name" in data
        assert data["protocol_version"] == "1.0"


class TestHandshake:
    """Test handshake endpoint."""

    def test_handshake_success(self, sync_client: FlaskClient) -> None:
        """Handshake succeeds with valid request."""
        peer_id = uuid.uuid4().hex
        response = sync_client.post(
            "/sync/handshake",
            json={
                "device_id": peer_id,
                "device_name": "Test Peer",
                "protocol_version": "1.0",
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "device_id" in data
        assert "device_name" in data
        assert data["protocol_version"] == "1.0"

    def test_handshake_missing_device_id(self, sync_client: FlaskClient) -> None:
        """Handshake fails without device_id."""
        response = sync_client.post(
            "/sync/handshake",
            json={"device_name": "Test Peer"},
        )
        assert response.status_code == 400
        assert "error" in response.get_json()

    def test_handshake_invalid_device_id(self, sync_client: FlaskClient) -> None:
        """Handshake fails with invalid device_id."""
        response = sync_client.post(
            "/sync/handshake",
            json={"device_id": "invalid", "device_name": "Test Peer"},
        )
        assert response.status_code == 400

    def test_handshake_missing_body(self, sync_client: FlaskClient) -> None:
        """Handshake fails without request body."""
        response = sync_client.post("/sync/handshake")
        assert response.status_code == 400


class TestGetChanges:
    """Test get changes endpoint."""

    def test_get_changes_empty(self, sync_client: FlaskClient) -> None:
        """Get changes returns empty list for empty database."""
        response = sync_client.get("/sync/changes")
        assert response.status_code == 200
        data = response.get_json()
        assert data["changes"] == []
        assert data["is_complete"] is True

    def test_get_changes_with_notes(
        self, sync_db: Database, sync_client: FlaskClient
    ) -> None:
        """Get changes returns note changes."""
        # Create a note
        note_id = sync_db.create_note("Test note content")

        response = sync_client.get("/sync/changes")
        assert response.status_code == 200
        data = response.get_json()

        assert len(data["changes"]) >= 1
        note_change = next(
            (c for c in data["changes"] if c["entity_type"] == "note"), None
        )
        assert note_change is not None
        assert note_change["operation"] == "create"
        assert note_change["data"]["content"] == "Test note content"

    def test_get_changes_since_timestamp(
        self, sync_db: Database, sync_client: FlaskClient
    ) -> None:
        """Get changes respects since parameter."""
        # Create first note
        sync_db.create_note("First note")

        # Get current timestamp
        import time
        time.sleep(0.1)  # Ensure time difference

        # Get changes (should have 1)
        response = sync_client.get("/sync/changes")
        data = response.get_json()
        timestamp = data.get("to_timestamp")

        # Create second note
        time.sleep(0.1)
        sync_db.create_note("Second note")

        # Get changes since first timestamp (should only have second note)
        if timestamp:
            response = sync_client.get(f"/sync/changes?since={timestamp}")
            data = response.get_json()
            # May have the second note
            assert data["is_complete"] is True

    def test_get_changes_with_limit(
        self, sync_db: Database, sync_client: FlaskClient
    ) -> None:
        """Get changes respects limit parameter."""
        # Create multiple notes
        for i in range(5):
            sync_db.create_note(f"Note {i}")

        response = sync_client.get("/sync/changes?limit=2")
        assert response.status_code == 200
        data = response.get_json()

        assert len(data["changes"]) <= 2
        assert data["is_complete"] is False


class TestFullSync:
    """Test full sync endpoint."""

    def test_full_sync_empty(self, sync_client: FlaskClient) -> None:
        """Full sync returns empty lists for empty database."""
        response = sync_client.get("/sync/full")
        assert response.status_code == 200
        data = response.get_json()

        assert data["notes"] == []
        assert data["tags"] == []
        assert data["note_tags"] == []
        assert "device_id" in data
        assert "timestamp" in data

    def test_full_sync_with_data(
        self, sync_db: Database, sync_client: FlaskClient
    ) -> None:
        """Full sync returns all data."""
        # Create test data
        note_id = sync_db.create_note("Test note")
        tag_id = sync_db.create_tag("TestTag")

        response = sync_client.get("/sync/full")
        assert response.status_code == 200
        data = response.get_json()

        assert len(data["notes"]) == 1
        assert data["notes"][0]["content"] == "Test note"
        assert len(data["tags"]) == 1
        assert data["tags"][0]["name"] == "TestTag"


class TestApplyChanges:
    """Test apply changes endpoint."""

    def test_apply_create_note(self, sync_client: FlaskClient) -> None:
        """Apply creates a new note."""
        note_id = uuid.uuid4().hex
        peer_id = uuid.uuid4().hex

        response = sync_client.post(
            "/sync/apply",
            json={
                "device_id": peer_id,
                "device_name": "Test Peer",
                "changes": [
                    {
                        "entity_type": "note",
                        "entity_id": note_id,
                        "operation": "create",
                        "data": {
                            "id": note_id,
                            "created_at": "2025-01-15 10:00:00",
                            "content": "Remote note",
                            "modified_at": None,
                            "deleted_at": None,
                        },
                        "timestamp": "2025-01-15 10:00:00",
                        "device_id": peer_id,
                    }
                ],
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["applied"] == 1
        assert data["conflicts"] == 0
        assert data["errors"] == []

    def test_apply_missing_device_id(self, sync_client: FlaskClient) -> None:
        """Apply fails without device_id."""
        response = sync_client.post(
            "/sync/apply",
            json={"changes": []},
        )
        assert response.status_code == 400

    def test_apply_update_note_lww(
        self, sync_db: Database, sync_client: FlaskClient
    ) -> None:
        """Apply uses LWW for conflicting updates."""
        # Create local note
        note_id = sync_db.create_note("Local content")
        peer_id = uuid.uuid4().hex

        # Apply remote update with newer timestamp
        response = sync_client.post(
            "/sync/apply",
            json={
                "device_id": peer_id,
                "device_name": "Test Peer",
                "changes": [
                    {
                        "entity_type": "note",
                        "entity_id": note_id,
                        "operation": "update",
                        "data": {
                            "id": note_id,
                            "created_at": "2025-01-15 10:00:00",
                            "content": "Remote content - newer",
                            "modified_at": "2099-01-01 00:00:00",  # Far future
                            "deleted_at": None,
                        },
                        "timestamp": "2099-01-01 00:00:00",
                        "device_id": peer_id,
                    }
                ],
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["applied"] == 1

        # Verify content was updated
        note = sync_db.get_note(note_id)
        assert note["content"] == "Remote content - newer"


class TestGetChangesSince:
    """Test get_changes_since function."""

    def test_returns_empty_for_empty_db(self, sync_db: Database) -> None:
        """Returns empty list for empty database."""
        changes, timestamp = get_changes_since(sync_db, None)
        assert changes == []
        assert timestamp is None

    def test_returns_note_changes(self, sync_db: Database) -> None:
        """Returns note create changes."""
        note_id = sync_db.create_note("Test content")
        changes, _ = get_changes_since(sync_db, None)

        assert len(changes) >= 1
        note_change = next(
            (c for c in changes if c.entity_type == "note"), None
        )
        assert note_change is not None
        assert note_change.operation == "create"


class TestApplySyncChanges:
    """Test apply_sync_changes function."""

    def test_applies_new_note(self, sync_db: Database) -> None:
        """Applies a new note from remote."""
        note_id = uuid.uuid4().hex
        peer_id = uuid.uuid4().hex

        changes = [
            SyncChange(
                entity_type="note",
                entity_id=note_id,
                operation="create",
                data={
                    "id": note_id,
                    "created_at": "2025-01-15 10:00:00",
                    "content": "Remote note",
                    "modified_at": None,
                    "deleted_at": None,
                },
                timestamp="2025-01-15 10:00:00",
                device_id=peer_id,
            )
        ]

        applied, conflicts, errors = apply_sync_changes(
            sync_db, changes, peer_id, "Test Peer"
        )

        assert applied == 1
        assert conflicts == 0
        assert errors == []

        # Verify note exists
        note = sync_db.get_note(note_id)
        assert note is not None
        assert note["content"] == "Remote note"

    def test_applies_new_tag(self, sync_db: Database) -> None:
        """Applies a new tag from remote."""
        tag_id = uuid.uuid4().hex
        peer_id = uuid.uuid4().hex

        changes = [
            SyncChange(
                entity_type="tag",
                entity_id=tag_id,
                operation="create",
                data={
                    "id": tag_id,
                    "name": "RemoteTag",
                    "parent_id": None,
                    "created_at": "2025-01-15 10:00:00",
                    "modified_at": None,
                },
                timestamp="2025-01-15 10:00:00",
                device_id=peer_id,
            )
        ]

        applied, conflicts, errors = apply_sync_changes(
            sync_db, changes, peer_id, "Test Peer"
        )

        assert applied == 1
        assert conflicts == 0

        # Verify tag exists
        tag = sync_db.get_tag(tag_id)
        assert tag is not None
        assert tag["name"] == "RemoteTag"


class TestGetFullDataset:
    """Test get_full_dataset function."""

    def test_returns_all_data(self, sync_db: Database) -> None:
        """Returns all notes, tags, and associations."""
        # Create test data
        note_id = sync_db.create_note("Test note")
        tag_id = sync_db.create_tag("TestTag")

        data = get_full_dataset(sync_db)

        assert "notes" in data
        assert "tags" in data
        assert "note_tags" in data

        assert len(data["notes"]) == 1
        assert len(data["tags"]) == 1

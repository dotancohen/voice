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


@pytest.fixture
def peer_db(test_config_dir: Path) -> Generator[Database, None, None]:
    """A second device, so that sync can be tested as it really happens."""
    set_local_device_id(PEER_DEVICE.bytes)
    db = Database(test_config_dir / "sync_peer.db")
    yield db
    db.close()
    set_local_device_id(LOCAL_DEVICE.bytes)


LOCAL_DEVICE = uuid.UUID("00000000-0000-7000-8000-000000000001")
PEER_DEVICE = uuid.UUID("00000000-0000-7000-8000-000000000002")


def on_device(device: uuid.UUID) -> None:
    """Write as this device from here on.

    The device identity is process-wide, so a test with two databases has to
    say which one is acting before every write.
    """
    set_local_device_id(device.bytes)


def push(
    source: Database,
    source_device: uuid.UUID,
    target: Database,
    target_device: uuid.UUID,
    cursor: object = None,
) -> tuple:
    """Send everything the source has learned since `cursor` to the target.

    Returns (applied, conflicts, errors, cursor for the next push).
    """
    on_device(source_device)
    changes, next_cursor = get_changes_since(source, cursor)
    on_device(target_device)
    applied, conflicts, errors = apply_sync_changes(
        target, changes, source_device.hex, "Test Peer"
    )
    return applied, conflicts, errors, next_cursor


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
        assert data["protocol_version"] == "1.1"


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
        assert data["protocol_version"] == "1.1"

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
        # A new database is created with its system tags, so the feed is never
        # truly empty; what matters is that it holds nothing of the user's
        assert [c for c in data["changes"] if c["entity_type"] == "note"] == []
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

        # The cursor feed is the one with a single limit across every type;
        # the timestamp feed deliberately limits each type separately (PROTO-7)
        response = sync_client.get("/sync/changes?cursor=0&limit=2")
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
        assert [t for t in data["tags"] if not t["name"].startswith("_")] == []
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
        own_tags = [t for t in data["tags"] if not t["name"].startswith("_")]
        assert len(own_tags) == 1
        assert own_tags[0]["name"] == "TestTag"


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
                            "created_at": 1736935200,
                            "content": "Remote note",
                            "modified_at": None,
                            "deleted_at": None,
                        },
                        "timestamp": 1736935200,
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

    def test_apply_row_only_update_keeps_the_local_text(
        self, sync_db: Database, sync_client: FlaskClient
    ) -> None:
        """A bare row never overwrites a field that has history (VER-4).

        Rows in the feed are denormalised hints so that a reader without the
        version graph still sees a value. The value itself travels as a
        version, so a row whose content differs from the head is ignored
        rather than written: no last-write-wins, and nothing to merge yet.
        """
        note_id = sync_db.create_note("תוכן מקומי")
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
                        "operation": "update",
                        "data": {
                            "id": note_id,
                            "created_at": 1736935200,
                            "content": "תוכן מרוחק",
                            "modified_at": 4070908800,
                            "deleted_at": None,
                        },
                        "timestamp": 4070908800,
                        "device_id": peer_id,
                    }
                ],
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["applied"] == 1
        assert data["conflicts"] == 0
        assert sync_db.get_note(note_id)["content"] == "תוכן מקומי"

    def test_apply_update_note_creates_conflict(
        self, sync_db: Database, sync_client: FlaskClient
    ) -> None:
        """Two texts written apart are both kept, and a conflict is recorded.

        This is the shape a real peer sends: the row plus the version that
        carries the text. The two versions have no common ancestor, so
        neither can win; both are kept in the note and a conflict record is
        created for the reader to resolve.
        """
        note_id = sync_db.create_note("תוכן מקומי")
        peer_id = uuid.uuid4().hex
        version_id = uuid.uuid4().hex

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
                            "created_at": 1736935200,
                            "content": "תוכן מרוחק",
                            "modified_at": 4070908800,
                            "deleted_at": None,
                        },
                        "timestamp": 4070908800,
                        "device_id": peer_id,
                    },
                    {
                        "entity_type": "field_version",
                        "entity_id": version_id,
                        "operation": "create",
                        "data": {
                            "id": version_id,
                            "entity_type": "note",
                            "entity_id": note_id,
                            "field": "content",
                            "parent_id": None,
                            "merge_parent_id": None,
                            "content": "תוכן מרוחק",
                            "device_id": peer_id,
                            "device_name": "Test Peer",
                            "created_at": 4070908800,
                            "published": True,
                        },
                        "timestamp": 4070908800,
                        "device_id": peer_id,
                    },
                ],
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        # Should create conflict, not silently apply
        assert data["conflicts"] == 1

        # Verify BOTH versions are preserved in merged content
        note = sync_db.get_note(note_id)
        assert "תוכן מקומי" in note["content"]
        assert "תוכן מרוחק" in note["content"]


class TestGetChangesSince:
    """Test get_changes_since function."""

    def test_returns_only_the_system_tags_for_empty_db(self, sync_db: Database) -> None:
        """A database with nothing of the user's in it offers nothing of the
        user's, though the tags it was created with are there."""
        changes, timestamp = get_changes_since(sync_db, None)
        assert [c for c in changes if c.entity_type == "note"] == []
        assert all(
            c.entity_type != "tag" or c.data["name"].startswith("_") for c in changes
        )

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
                    "created_at": 1736935200,
                    "content": "Remote note",
                    "modified_at": None,
                    "deleted_at": None,
                },
                timestamp=1736935200,
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
                    "created_at": 1736935200,
                    "modified_at": None,
                },
                timestamp=1736935200,
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


class TestApplySyncChangesDeleteConflicts:
    """A delete that did not see an edit never destroys the edit.

    These use a second real database rather than hand-written rows, because
    the value of a field travels as a version and a bare row is only a hint
    (VER-4). A test that sends rows alone proves nothing about what a peer
    would really do.
    """

    def test_edit_arriving_after_a_local_delete_keeps_the_note(
        self, sync_db: Database, peer_db: Database
    ) -> None:
        """Here the note is deleted, there it is edited: the edit wins."""
        on_device(LOCAL_DEVICE)
        note_id = sync_db.create_note("תוכן מקורי")
        _, _, _, to_peer = push(sync_db, LOCAL_DEVICE, peer_db, PEER_DEVICE)
        _, _, _, to_local = push(peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE)

        on_device(LOCAL_DEVICE)
        sync_db.delete_note(note_id)
        on_device(PEER_DEVICE)
        peer_db.update_note(note_id, "עריכה חשובה מאוד")

        _, conflicts, errors, _ = push(
            peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE, to_local
        )

        assert errors == []
        assert conflicts == 1
        on_device(LOCAL_DEVICE)
        note = sync_db.get_note_raw(note_id)
        assert note is not None
        assert note["deleted_at"] is None, "The edit must keep the note alive"
        assert note["content"] == "עריכה חשובה מאוד"
        assert sync_db.get_note_conflict_types(note_id) == ["delete"]

        # And the device that deleted tells the other, so both agree.
        push(sync_db, LOCAL_DEVICE, peer_db, PEER_DEVICE, to_peer)
        on_device(PEER_DEVICE)
        peer_note = peer_db.get_note_raw(note_id)
        assert peer_note is not None
        assert peer_note["deleted_at"] is None
        assert peer_note["content"] == "עריכה חשובה מאוד"
        assert peer_db.get_note_conflict_types(note_id) == ["delete"]

    def test_delete_arriving_after_a_local_edit_keeps_the_note(
        self, sync_db: Database, peer_db: Database
    ) -> None:
        """The same disagreement seen from the other side."""
        on_device(LOCAL_DEVICE)
        note_id = sync_db.create_note("תוכן מקורי")
        push(sync_db, LOCAL_DEVICE, peer_db, PEER_DEVICE)
        _, _, _, to_local = push(peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE)

        on_device(LOCAL_DEVICE)
        sync_db.update_note(note_id, "עריכה מקומית חשובה")
        on_device(PEER_DEVICE)
        peer_db.delete_note(note_id)

        _, conflicts, errors, _ = push(
            peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE, to_local
        )

        assert errors == []
        assert conflicts == 1
        on_device(LOCAL_DEVICE)
        note = sync_db.get_note_raw(note_id)
        assert note is not None
        assert note["deleted_at"] is None, "The local edit must survive"
        assert note["content"] == "עריכה מקומית חשובה"

    def test_delete_of_an_unedited_note_propagates(
        self, sync_db: Database, peer_db: Database
    ) -> None:
        """Nobody edited it, so the delete simply travels."""
        on_device(LOCAL_DEVICE)
        note_id = sync_db.create_note("פתק לא ערוך")
        push(sync_db, LOCAL_DEVICE, peer_db, PEER_DEVICE)
        _, _, _, to_local = push(peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE)

        on_device(PEER_DEVICE)
        peer_db.delete_note(note_id)

        _, conflicts, errors, _ = push(
            peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE, to_local
        )

        assert errors == []
        assert conflicts == 0
        on_device(LOCAL_DEVICE)
        note = sync_db.get_note_raw(note_id)
        assert note is not None
        assert note["deleted_at"] is not None, "The delete should have arrived"
        assert sync_db.get_note(note_id) is None

    def test_a_second_delete_after_seeing_the_edit_is_obeyed(
        self, sync_db: Database, peer_db: Database
    ) -> None:
        """The user who wanted the note gone deletes again, and it goes.

        This is the way out of a delete conflict: the second delete records
        what the user saw, which now includes the edit, so no resurrection.
        """
        on_device(LOCAL_DEVICE)
        note_id = sync_db.create_note("תוכן מקורי")
        _, _, _, to_peer = push(sync_db, LOCAL_DEVICE, peer_db, PEER_DEVICE)
        _, _, _, to_local = push(peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE)

        on_device(LOCAL_DEVICE)
        sync_db.delete_note(note_id)
        on_device(PEER_DEVICE)
        peer_db.update_note(note_id, "עריכה חשובה מאוד")

        push(peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE, to_local)
        _, _, _, to_peer = push(sync_db, LOCAL_DEVICE, peer_db, PEER_DEVICE, to_peer)

        # The note is alive on both. Delete it again, having seen the edit.
        on_device(LOCAL_DEVICE)
        sync_db.delete_note(note_id)
        _, conflicts, errors, _ = push(
            sync_db, LOCAL_DEVICE, peer_db, PEER_DEVICE, to_peer
        )

        assert errors == []
        assert conflicts == 0
        on_device(PEER_DEVICE)
        peer_note = peer_db.get_note_raw(note_id)
        assert peer_note is not None
        assert peer_note["deleted_at"] is not None, "The second delete stands"


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
        # Every database is created with the system tags, so count only the
        # tag this test made.
        user_tags = [t for t in data["tags"] if not t["name"].startswith("_")]
        assert [t["id"] for t in user_tags] == [tag_id]
        assert data["notes"][0]["id"] == note_id

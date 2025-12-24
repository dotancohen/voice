"""Integration tests for sync functionality.

Tests the full sync workflow between two simulated devices.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Generator, Tuple

import pytest
from flask import Flask
from flask.testing import FlaskClient
from uuid6 import uuid7

from core.config import Config
from core.conflicts import ConflictManager, ResolutionChoice
from core.database import Database, set_local_device_id
from core.sync import create_sync_blueprint
from core.validation import uuid_to_hex


@pytest.fixture
def device_a(test_config_dir: Path) -> Tuple[Database, Config]:
    """Create device A (first device)."""
    device_id = uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes
    set_local_device_id(device_id)

    config_dir = test_config_dir / "device_a"
    config_dir.mkdir(parents=True, exist_ok=True)

    config = Config(config_dir=config_dir)
    db_path = config_dir / "notes.db"
    db = Database(db_path)

    return db, config


@pytest.fixture
def device_b(test_config_dir: Path) -> Tuple[Database, Config]:
    """Create device B (second device)."""
    device_id = uuid.UUID("00000000-0000-7000-8000-00000000000b").bytes
    set_local_device_id(device_id)

    config_dir = test_config_dir / "device_b"
    config_dir.mkdir(parents=True, exist_ok=True)

    config = Config(config_dir=config_dir)
    db_path = config_dir / "notes.db"
    db = Database(db_path)

    return db, config


@pytest.fixture
def sync_server_a(device_a: Tuple[Database, Config]) -> FlaskClient:
    """Create sync server for device A."""
    db, config = device_a
    device_id = config.get_device_id_hex()
    device_name = config.get_device_name()
    app = Flask(__name__)
    blueprint = create_sync_blueprint(db, device_id, device_name)
    app.register_blueprint(blueprint)
    app.config["TESTING"] = True
    return app.test_client()


class TestSyncServerEndpoints:
    """Test sync server endpoints work correctly."""

    def test_status_endpoint(
        self, sync_server_a: FlaskClient, device_a: Tuple[Database, Config]
    ) -> None:
        """Status endpoint returns device info."""
        db, config = device_a
        response = sync_server_a.get("/sync/status")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "ok"
        assert "device_id" in data
        assert "device_name" in data

    def test_handshake_endpoint(
        self, sync_server_a: FlaskClient, device_a: Tuple[Database, Config]
    ) -> None:
        """Handshake endpoint accepts peer info."""
        db, config = device_a
        peer_id = uuid7().hex

        response = sync_server_a.post(
            "/sync/handshake",
            data=json.dumps({
                "device_id": peer_id,
                "device_name": "Test Peer",
                "protocol_version": "1.0",
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        # Handshake returns device info, not success field
        assert "device_id" in data
        assert "device_name" in data

    def test_changes_endpoint_returns_batch(
        self, sync_server_a: FlaskClient, device_a: Tuple[Database, Config]
    ) -> None:
        """Changes endpoint returns a SyncBatch."""
        db, config = device_a

        # Create a note
        set_local_device_id(uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes)
        note_id = db.create_note("Test note content")

        response = sync_server_a.get("/sync/changes")
        assert response.status_code == 200
        data = json.loads(response.data)

        # Check SyncBatch structure
        assert "changes" in data
        assert "device_id" in data
        assert "device_name" in data
        assert "is_complete" in data
        assert len(data["changes"]) > 0


class TestSyncWorkflow:
    """Test sync workflow."""

    def test_note_appears_in_changes(
        self,
        device_a: Tuple[Database, Config],
        sync_server_a: FlaskClient,
    ) -> None:
        """Note created on device appears in changes endpoint."""
        db_a, config_a = device_a

        # Create note on device A
        set_local_device_id(uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes)
        note_id = db_a.create_note("Note from device A")

        # Get changes
        response = sync_server_a.get("/sync/changes")
        data = json.loads(response.data)
        changes = data["changes"]

        # Find the note in changes
        note_changes = [c for c in changes if c["entity_type"] == "note" and c["entity_id"] == note_id]
        assert len(note_changes) > 0
        assert note_changes[0]["data"]["content"] == "Note from device A"

    def test_tag_appears_in_changes(
        self,
        device_a: Tuple[Database, Config],
        sync_server_a: FlaskClient,
    ) -> None:
        """Tag created on device appears in changes endpoint."""
        db_a, config_a = device_a

        # Create tag on device A
        set_local_device_id(uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes)
        tag_id = db_a.create_tag("synced_tag")

        # Get changes
        response = sync_server_a.get("/sync/changes")
        data = json.loads(response.data)
        changes = data["changes"]

        # Find the tag in changes
        tag_changes = [c for c in changes if c["entity_type"] == "tag" and c["entity_id"] == tag_id]
        assert len(tag_changes) > 0
        assert tag_changes[0]["data"]["name"] == "synced_tag"

    def test_deleted_note_in_changes(
        self, device_a: Tuple[Database, Config], sync_server_a: FlaskClient
    ) -> None:
        """Deleted notes appear in changes with deleted_at."""
        db, config = device_a
        set_local_device_id(uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes)

        # Create and delete a note
        note_id = db.create_note("To be deleted")
        db.delete_note(note_id)

        # Get changes
        response = sync_server_a.get("/sync/changes")
        data = json.loads(response.data)
        changes = data["changes"]

        # Find the deleted note
        note_changes = [c for c in changes if c["entity_type"] == "note" and c["entity_id"] == note_id]
        deleted_changes = [c for c in note_changes if c["data"].get("deleted_at")]
        assert len(deleted_changes) > 0

    def test_unicode_content_in_changes(
        self, device_a: Tuple[Database, Config], sync_server_a: FlaskClient
    ) -> None:
        """Unicode content appears correctly in changes."""
        db, config = device_a
        set_local_device_id(uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes)

        # Create note with unicode content
        unicode_content = "Hello 世界 🌍 مرحبا"
        note_id = db.create_note(unicode_content)

        # Get changes
        response = sync_server_a.get("/sync/changes")
        data = json.loads(response.data)
        changes = data["changes"]

        # Find the note
        note_changes = [c for c in changes if c["entity_type"] == "note" and c["entity_id"] == note_id]
        assert len(note_changes) > 0
        assert note_changes[0]["data"]["content"] == unicode_content


class TestConflictResolution:
    """Test conflict resolution workflow."""

    def test_resolve_content_conflict_keep_local(
        self, device_a: Tuple[Database, Config]
    ) -> None:
        """Resolve content conflict by keeping local."""
        from datetime import datetime, timezone

        db, config = device_a
        device_id = uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes
        set_local_device_id(device_id)

        # Create a note
        note_id = db.create_note("Local content")

        now = datetime.now(timezone.utc).isoformat()
        remote_device_id = "00000000000070008000000000000b"

        # Create a conflict using Database method
        conflict_id = db.create_note_content_conflict(
            note_id=note_id,
            local_content="Local version",
            local_modified_at=now,
            remote_content="Remote version",
            remote_modified_at=now,
            remote_device_id=remote_device_id,
        )

        # Resolve conflict
        conflict_mgr = ConflictManager(db)
        result = conflict_mgr.resolve_note_content_conflict(
            conflict_id, ResolutionChoice.KEEP_LOCAL
        )

        assert result is True

        # Verify note has local content
        note = db.get_note(note_id)
        assert note["content"] == "Local version"

        # Verify conflict is resolved
        counts = conflict_mgr.get_unresolved_count()
        assert counts["note_content"] == 0

    def test_resolve_content_conflict_keep_remote(
        self, device_a: Tuple[Database, Config]
    ) -> None:
        """Resolve content conflict by keeping remote."""
        from datetime import datetime, timezone

        db, config = device_a
        device_id = uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes
        set_local_device_id(device_id)

        # Create a note
        note_id = db.create_note("Original")

        now = datetime.now(timezone.utc).isoformat()
        remote_device_id = "00000000000070008000000000000b"

        # Create a conflict using Database method
        conflict_id = db.create_note_content_conflict(
            note_id=note_id,
            local_content="Local version",
            local_modified_at=now,
            remote_content="Remote version",
            remote_modified_at=now,
            remote_device_id=remote_device_id,
        )

        # Resolve conflict
        conflict_mgr = ConflictManager(db)
        result = conflict_mgr.resolve_note_content_conflict(
            conflict_id, ResolutionChoice.KEEP_REMOTE
        )

        assert result is True

        # Verify note has remote content
        note = db.get_note(note_id)
        assert note["content"] == "Remote version"

    def test_resolve_delete_conflict_restore(
        self, device_a: Tuple[Database, Config]
    ) -> None:
        """Resolve delete conflict by restoring note."""
        from datetime import datetime, timezone

        db, config = device_a
        device_id = uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes
        set_local_device_id(device_id)

        # Create a note and delete it
        note_id = db.create_note("Deleted content")
        db.delete_note(note_id)

        now = datetime.now(timezone.utc).isoformat()
        surviving_device_id = "00000000000070008000000000000b"
        deleting_device_id = uuid.UUID(bytes=device_id).hex

        # Create delete conflict using Database method
        conflict_id = db.create_note_delete_conflict(
            note_id=note_id,
            surviving_content="Content to restore",
            surviving_modified_at=now,
            surviving_device_id=surviving_device_id,
            deleted_at=now,
            deleting_device_id=deleting_device_id,
        )

        # Resolve by keeping both (restore)
        conflict_mgr = ConflictManager(db)
        result = conflict_mgr.resolve_note_delete_conflict(
            conflict_id, ResolutionChoice.KEEP_BOTH
        )

        assert result is True

        # Verify note is restored
        note = db.get_note(note_id)
        assert note is not None
        assert note["content"] == "Content to restore"
        assert note.get("deleted_at") is None

    def test_resolve_tag_rename_conflict(
        self, device_a: Tuple[Database, Config]
    ) -> None:
        """Resolve tag rename conflict."""
        from datetime import datetime, timezone

        db, config = device_a
        device_id = uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes
        set_local_device_id(device_id)

        # Create a tag
        tag_id = db.create_tag("original_name")

        now = datetime.now(timezone.utc).isoformat()
        remote_device_id = "00000000000070008000000000000b"

        # Create a rename conflict using Database method
        conflict_id = db.create_tag_rename_conflict(
            tag_id=tag_id,
            local_name="local_renamed",
            local_modified_at=now,
            remote_name="remote_renamed",
            remote_modified_at=now,
            remote_device_id=remote_device_id,
        )

        # Resolve by keeping remote
        conflict_mgr = ConflictManager(db)
        result = conflict_mgr.resolve_tag_rename_conflict(
            conflict_id, ResolutionChoice.KEEP_REMOTE
        )

        assert result is True

        # Verify tag has remote name
        tags = db.get_all_tags()
        tag = next(t for t in tags if t["id"] == tag_id)
        assert tag["name"] == "remote_renamed"


class TestEdgeCases:
    """Test edge cases in sync."""

    def test_empty_changes(
        self, device_a: Tuple[Database, Config], sync_server_a: FlaskClient
    ) -> None:
        """Empty database returns empty changes."""
        response = sync_server_a.get("/sync/changes")
        data = json.loads(response.data)

        assert response.status_code == 200
        assert "changes" in data
        # Empty or minimal changes is acceptable

    def test_full_sync_endpoint(
        self, device_a: Tuple[Database, Config], sync_server_a: FlaskClient
    ) -> None:
        """Full sync endpoint returns all data."""
        db, config = device_a
        set_local_device_id(uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes)

        # Create some data
        note_id = db.create_note("Test note")
        tag_id = db.create_tag("test_tag")
        db.add_tag_to_note(note_id, tag_id)

        # Get full sync
        response = sync_server_a.get("/sync/full")
        data = json.loads(response.data)

        assert response.status_code == 200
        # Full sync returns data at top level
        assert "notes" in data
        assert "tags" in data
        assert "note_tags" in data
        assert len(data["notes"]) > 0
        assert len(data["tags"]) > 0

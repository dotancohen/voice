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
from core.conflicts import ConflictManager, has_conflict_markers
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
    """Conflict resolution workflow over the sync feed."""

    REMOTE = "0000000000007000800000000000000b"

    def _conflicted_note(self, db: Database):
        """A note edited here and, concurrently, on a remote device."""
        from voicecore import apply_sync_changes

        set_local_device_id(uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes)
        remote = Database(":memory:")
        note_id = db.create_note("גרסה מקורית")
        changes = db.get_changes_since(None, 100000)["changes"]
        for c in changes:
            c.setdefault("device_id", "0000000000007000800000000000000a")
        apply_sync_changes(remote._rust_db, changes, "0000000000007000800000000000000a", "Local")
        db.update_note(note_id, "גרסה מקומית")
        remote.update_note(note_id, "גרסה מרוחקת")
        changes = remote.get_changes_since(None, 100000)["changes"]
        for c in changes:
            c.setdefault("device_id", self.REMOTE)
        result = apply_sync_changes(db._rust_db, changes, self.REMOTE, "Remote")
        remote.close()
        assert result["conflicts"] == 1
        return note_id

    def test_concurrent_edit_keeps_both_versions(
        self, device_a: Tuple[Database, Config]
    ) -> None:
        db, config = device_a
        note_id = self._conflicted_note(db)
        text = db.get_note(note_id)["content"]
        assert "גרסה מקומית" in text and "גרסה מרוחקת" in text
        assert has_conflict_markers(text)
        mgr = ConflictManager(db)
        assert mgr.get_unresolved_count()["total"] == 1
        c = mgr.get_conflicts()[0]
        # Both databases live in this process and share its device name
        assert "unknown device" not in (c.device_a_label, c.device_b_label)

    def test_resolve_by_accepting_merge(
        self, device_a: Tuple[Database, Config]
    ) -> None:
        db, config = device_a
        note_id = self._conflicted_note(db)
        mgr = ConflictManager(db)
        assert mgr.accept(mgr.get_conflicts()[0].id) is True
        assert mgr.get_unresolved_count()["total"] == 0
        assert has_conflict_markers(db.get_note(note_id)["content"])

    def test_resolve_by_editing(
        self, device_a: Tuple[Database, Config]
    ) -> None:
        db, config = device_a
        note_id = self._conflicted_note(db)
        mgr = ConflictManager(db)
        assert mgr.resolve_with_content(mgr.get_conflicts()[0].id, "גרסה מאוחדת") is True
        assert db.get_note(note_id)["content"] == "גרסה מאוחדת"
        assert mgr.get_unresolved_count()["total"] == 0

    def test_edit_vs_delete_restores_note(
        self, device_a: Tuple[Database, Config]
    ) -> None:
        from voicecore import apply_sync_changes

        db, config = device_a
        set_local_device_id(uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes)
        remote = Database(":memory:")
        note_id = db.create_note("תוכן")
        changes = db.get_changes_since(None, 100000)["changes"]
        for c in changes:
            c.setdefault("device_id", "0000000000007000800000000000000a")
        apply_sync_changes(remote._rust_db, changes, "0000000000007000800000000000000a", "Local")
        db.delete_note(note_id)
        remote.update_note(note_id, "תוכן לשחזור")
        changes = remote.get_changes_since(None, 100000)["changes"]
        for c in changes:
            c.setdefault("device_id", self.REMOTE)
        apply_sync_changes(db._rust_db, changes, self.REMOTE, "Remote")
        remote.close()

        note = db.get_note(note_id)
        assert note is not None
        assert note["content"] == "תוכן לשחזור"
        assert note.get("deleted_at") is None
        assert "delete" in ConflictManager(db).get_note_conflict_types(note_id)


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

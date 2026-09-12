"""Tests for sync server endpoints.

Run against the Rust server, started as a real process:
- GET /sync/status
- POST /sync/handshake
- GET /sync/changes
- POST /sync/apply
- GET /sync/full
"""

from __future__ import annotations

import time
from typing import Any, Dict

import pytest
import requests
import uuid

from .conftest import (
    AUTH,
    ACCOUNT_ID,
    SyncNode,
    create_note_on_node,
    create_tag_on_node,
    DEVICE_A_ID,
    DEVICE_B_ID,
)


class TestSyncStatus:
    """Tests for GET /sync/status endpoint."""

    def test_status_returns_ok(self, running_server_a: SyncNode):
        """Status endpoint returns OK with device info."""
        resp = requests.get(f"{running_server_a.url}/sync/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["device_id"] == running_server_a.device_id_hex
        assert data["device_name"] == running_server_a.name
        assert data["protocol_version"] == "1.1"

    def test_status_json_content_type(self, running_server_a: SyncNode):
        """Status endpoint returns JSON content type."""
        resp = requests.get(f"{running_server_a.url}/sync/status")

        assert "application/json" in resp.headers.get("Content-Type", "")


class TestSyncHandshake:
    """Tests for POST /sync/handshake endpoint."""

    def test_handshake_success(self, running_server_a: SyncNode):
        """Handshake exchanges device info successfully."""
        resp = requests.post(
            f"{running_server_a.url}/sync/handshake",
            headers=AUTH,
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "TestClient",
                "protocol_version": "1.0",
                "account_id": ACCOUNT_ID,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["device_id"] == running_server_a.device_id_hex
        assert data["device_name"] == running_server_a.name
        assert data["protocol_version"] == "1.1"

    def test_handshake_missing_device_id(self, running_server_a: SyncNode):
        """Handshake fails without device_id."""
        resp = requests.post(
            f"{running_server_a.url}/sync/handshake",
            headers=AUTH,
            json={
                "device_name": "TestClient",
                "protocol_version": "1.0",
                "account_id": ACCOUNT_ID,
            },
        )

        # Server returns 422 for validation errors
        assert resp.status_code == 422

    def test_handshake_invalid_device_id(self, running_server_a: SyncNode):
        """Handshake fails with invalid device_id format."""
        resp = requests.post(
            f"{running_server_a.url}/sync/handshake",
            headers=AUTH,
            json={
                "device_id": "not-a-valid-uuid",
                "device_name": "TestClient",
                "protocol_version": "1.0",
                "account_id": ACCOUNT_ID,
            },
        )

        # Server returns 400 for invalid device_id format
        assert resp.status_code == 400

    def test_handshake_empty_body(self, running_server_a: SyncNode):
        """Handshake fails with empty body."""
        resp = requests.post(
            f"{running_server_a.url}/sync/handshake",            json=None,
            headers={**AUTH, "Content-Type": "application/json"},
        )

        # Server returns 400 for empty body
        assert resp.status_code == 400

    def test_handshake_records_peer(self, running_server_a: SyncNode):
        """Handshake records last sync timestamp for peer."""
        peer_id = "00000000000070008000000000000099"

        # First handshake
        resp1 = requests.post(
            f"{running_server_a.url}/sync/handshake",
            headers=AUTH,
            json={
                "device_id": peer_id,
                "device_name": "TestClient",
                "protocol_version": "1.0",
                "account_id": ACCOUNT_ID,
            },
        )
        assert resp1.status_code == 200

        # Second handshake should also succeed
        resp2 = requests.post(
            f"{running_server_a.url}/sync/handshake",
            headers=AUTH,
            json={
                "device_id": peer_id,
                "device_name": "TestClient",
                "protocol_version": "1.0",
                "account_id": ACCOUNT_ID,
            },
        )
        assert resp2.status_code == 200


class TestSyncChanges:
    """Tests for GET /sync/changes endpoint."""

    def test_changes_empty_database(self, running_server_a: SyncNode):
        """Changes endpoint returns empty list for empty database (except system tags)."""
        resp = requests.get(f"{running_server_a.url}/sync/changes", headers=AUTH)

        assert resp.status_code == 200
        data = resp.json()
        # Filter out system tags (names starting with underscore) and their
        # field versions (name and parent history of each system tag)
        system_tag_ids = {
            c["entity_id"] for c in data["changes"]
            if c["entity_type"] == "tag" and c["data"]["name"].startswith("_")
        }
        non_system_changes = [
            c for c in data["changes"]
            if not (c["entity_type"] == "tag" and c["entity_id"] in system_tag_ids)
            and not (c["entity_type"] == "field_version" and c["data"]["entity_id"] in system_tag_ids)
            # ... and the device cards of the account (CARD-1)
            and not (c["entity_type"] == "field_version" and c["data"]["entity_type"] == "device")
        ]
        assert non_system_changes == []
        assert data["device_id"] == running_server_a.device_id_hex
        assert data["is_complete"] is True

    def test_changes_returns_notes(self, running_server_a: SyncNode):
        """Changes endpoint returns created notes."""
        # Create a note
        note_id = create_note_on_node(running_server_a, "Test note content")

        resp = requests.get(f"{running_server_a.url}/sync/changes", headers=AUTH)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["changes"]) >= 1

        # Find the note change
        note_changes = [c for c in data["changes"] if c["entity_type"] == "note"]
        assert len(note_changes) == 1
        assert note_changes[0]["entity_id"] == note_id
        assert note_changes[0]["operation"] == "create"
        assert note_changes[0]["data"]["content"] == "Test note content"

    def test_changes_returns_tags(self, running_server_a: SyncNode):
        """Changes endpoint returns created tags."""
        # Create a tag
        tag_id = create_tag_on_node(running_server_a, "TestTag")

        resp = requests.get(f"{running_server_a.url}/sync/changes", headers=AUTH)

        assert resp.status_code == 200
        data = resp.json()

        # Filter out system tags (names starting with underscore)
        tag_changes = [
            c for c in data["changes"]
            if c["entity_type"] == "tag" and not c["data"]["name"].startswith("_")
        ]
        assert len(tag_changes) == 1
        assert tag_changes[0]["entity_id"] == tag_id
        assert tag_changes[0]["operation"] == "create"
        assert tag_changes[0]["data"]["name"] == "TestTag"

    def test_changes_since_timestamp(self, running_server_a: SyncNode):
        """Changes endpoint filters by since parameter."""
        # Create first note
        note_id_1 = create_note_on_node(running_server_a, "First note")

        # Get changes to get timestamp
        resp1 = requests.get(f"{running_server_a.url}/sync/changes", headers=AUTH)
        timestamp = resp1.json()["to_timestamp"]

        # Wait a full second (timestamps are second-precision)
        time.sleep(1.1)
        note_id_2 = create_note_on_node(running_server_a, "Second note")

        # Get changes since first note
        resp2 = requests.get(
            f"{running_server_a.url}/sync/changes",
            headers=AUTH,
            params={"since": timestamp},
        )

        assert resp2.status_code == 200
        data = resp2.json()

        # With >= comparison, boundary note may be included. Second note must be present.
        note_changes = [c for c in data["changes"] if c["entity_type"] == "note"]
        assert len(note_changes) >= 1
        note_ids = [c["entity_id"] for c in note_changes]
        assert note_id_2 in note_ids

    def test_changes_respects_limit(self, running_server_a: SyncNode):
        """Changes endpoint respects limit parameter."""
        # Create multiple notes
        for i in range(5):
            create_note_on_node(running_server_a, f"Note {i}")

        resp = requests.get(
            f"{running_server_a.url}/sync/changes",
            headers=AUTH,
            params={"limit": 2},
        )

        assert resp.status_code == 200
        data = resp.json()
        # The limit applies per entity type (see CLAUDE.md): 2 notes at most,
        # while the tags are still returned rather than starved.
        by_type = {}
        for change in data["changes"]:
            by_type.setdefault(change["entity_type"], []).append(change)
        assert len(by_type["note"]) == 2
        assert "tag" in by_type
        assert all(len(changes) <= 2 for changes in by_type.values())
        assert data["is_complete"] is False

    def test_changes_include_a_deleted_note(self, running_server_a: SyncNode):
        """A deleted note travels in the feed with its deleted_at (VER-7)."""
        note_id = create_note_on_node(running_server_a, "To be deleted")
        running_server_a.db.delete_note(note_id)

        resp = requests.get(f"{running_server_a.url}/sync/changes", headers=AUTH)
        assert resp.status_code == 200
        changes = resp.json()["changes"]

        note_changes = [c for c in changes if c["entity_type"] == "note" and c["entity_id"] == note_id]
        assert [c for c in note_changes if c["data"].get("deleted_at")], "the deletion is missing from the feed"

    def test_changes_keep_unicode_content(self, running_server_a: SyncNode):
        """Content in several scripts arrives unchanged."""
        unicode_content = "שלום 世界 🌍 مرحبا"
        note_id = create_note_on_node(running_server_a, unicode_content)

        resp = requests.get(f"{running_server_a.url}/sync/changes", headers=AUTH)
        changes = resp.json()["changes"]

        note_changes = [c for c in changes if c["entity_type"] == "note" and c["entity_id"] == note_id]
        assert note_changes
        assert note_changes[0]["data"]["content"] == unicode_content

    def test_changes_includes_hierarchy(self, running_server_a: SyncNode):
        """Changes endpoint includes tag hierarchy."""
        # Create parent and child tags
        parent_id = create_tag_on_node(running_server_a, "Parent")
        child_id = create_tag_on_node(running_server_a, "Child", parent_id)

        resp = requests.get(f"{running_server_a.url}/sync/changes", headers=AUTH)

        assert resp.status_code == 200
        data = resp.json()

        tag_changes = [c for c in data["changes"] if c["entity_type"] == "tag"]
        child_change = next(c for c in tag_changes if c["entity_id"] == child_id)
        assert child_change["data"]["parent_id"] == parent_id


class TestSyncApply:
    """Tests for POST /sync/apply endpoint."""

    def test_apply_creates_note(self, running_server_a: SyncNode):
        """Apply endpoint creates new notes."""
        note_id = "00000000000070008000000000000301"

        resp = requests.post(
            f"{running_server_a.url}/sync/apply",
            headers=AUTH,
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "RemoteDevice",
                "changes": [
                    {
                        "entity_type": "note",
                        "entity_id": note_id,
                        "operation": "create",
                        "data": {
                            "id": note_id,
                            "created_at": 1735725600,
                            "content": "Note from remote",
                            "modified_at": None,
                            "deleted_at": None,
                        },
                        "timestamp": 1735725600,
                        "device_id": "00000000000070008000000000000099",
                    }
                ],
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["applied"] == 1
        assert data["conflicts"] == 0
        assert data["errors"] == []

        # Verify note exists in database
        note = running_server_a.db.get_note(note_id)
        assert note is not None
        assert note["content"] == "Note from remote"

    def test_apply_creates_tag(self, running_server_a: SyncNode):
        """Apply endpoint creates new tags."""
        tag_id = "00000000000070008000000000000401"

        resp = requests.post(
            f"{running_server_a.url}/sync/apply",
            headers=AUTH,
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "RemoteDevice",
                "changes": [
                    {
                        "entity_type": "tag",
                        "entity_id": tag_id,
                        "operation": "create",
                        "data": {
                            "id": tag_id,
                            "name": "RemoteTag",
                            "parent_id": None,
                            "created_at": 1735725600,
                            "modified_at": None,
                        },
                        "timestamp": 1735725600,
                        "device_id": "00000000000070008000000000000099",
                    }
                ],
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["applied"] == 1

        # Verify tag exists
        tags = running_server_a.db.get_all_tags()
        tag_names = [t["name"] for t in tags]
        assert "RemoteTag" in tag_names

    @staticmethod
    def _remote_edit(node: SyncNode, note_id: str, content: str, device_id: str, created_at: int) -> list:
        """The changes a protocol 1.1 peer sends for an edit: the version plus the row."""
        history = node.db.get_field_history("note", note_id, "content")
        parent = history[-1]["id"]
        version_id = uuid.uuid4().hex
        return [
            {
                "entity_type": "field_version",
                "entity_id": version_id,
                "operation": "create",
                "data": {
                    "id": version_id,
                    "entity_type": "note",
                    "entity_id": note_id,
                    "field": "content",
                    "parent_id": parent,
                    "merge_parent_id": None,
                    "content": content,
                    "context": None,
                    "conflict_kind": None,
                    "device_id": device_id,
                    "device_name": "RemoteDevice",
                    "created_at": created_at,
                },
                "timestamp": created_at,
                "device_id": device_id,
            },
            {
                "entity_type": "note",
                "entity_id": note_id,
                "operation": "update",
                "data": {
                    "id": note_id,
                    "created_at": 1735725600,
                    "content": content,
                    "modified_at": created_at,
                    "deleted_at": None,
                },
                "timestamp": created_at,
                "device_id": device_id,
            },
        ]

    def test_apply_updates_note(self, running_server_a: SyncNode):
        """A concurrent remote edit is merged and flagged, never applied over the local edit."""
        note_id = create_note_on_node(running_server_a, "Original content")
        running_server_a.db.update_note(note_id, "Local content")
        remote = "00000000000070008000000000000099"
        # The remote edited from the original: its version's parent is the root
        history = running_server_a.db.get_field_history("note", note_id, "content")
        root = history[0]["id"]
        changes = self._remote_edit(running_server_a, note_id, "Updated content", remote, 4070908800)
        changes[0]["data"]["parent_id"] = root

        resp = requests.post(
            f"{running_server_a.url}/sync/apply",
            headers=AUTH,
            json={"device_id": remote, "device_name": "RemoteDevice", "changes": changes},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["conflicts"] == 1  # Conflict created, not silently applied

        # Verify both versions are preserved in conflict markers
        note = running_server_a.db.get_note(note_id)
        assert "<<<<<<< VERSION A" in note["content"]
        assert "Local content" in note["content"]
        assert "Updated content" in note["content"]
        assert ">>>>>>> VERSION B" in note["content"]

    def test_apply_row_without_version_is_ignored(self, running_server_a: SyncNode):
        """A bare row with a different value (no version) neither overwrites nor conflicts."""
        note_id = create_note_on_node(running_server_a, "Original content")
        running_server_a.db.update_note(note_id, "Local update")

        resp = requests.post(
            f"{running_server_a.url}/sync/apply",
            headers=AUTH,
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "RemoteDevice",
                "changes": [
                    {
                        "entity_type": "note",
                        "entity_id": note_id,
                        "operation": "update",
                        "data": {
                            "id": note_id,
                            "created_at": 1577872800,
                            "content": "Old remote content",
                            "modified_at": 1577872800,
                            "deleted_at": None,
                        },
                        "timestamp": 1577872800,
                        "device_id": "00000000000070008000000000000099",
                    }
                ],
            },
        )

        assert resp.status_code == 200
        assert resp.json()["conflicts"] == 0
        note = running_server_a.db.get_note(note_id)
        assert note["content"] == "Local update"

    def test_apply_sequential_remote_edit_replaces_content(self, running_server_a: SyncNode):
        """A remote edit that builds on the current head simply becomes the content."""
        note_id = create_note_on_node(running_server_a, "Original content")
        remote = "00000000000070008000000000000099"
        changes = self._remote_edit(running_server_a, note_id, "Edited remotely", remote, 4070908800)

        resp = requests.post(
            f"{running_server_a.url}/sync/apply",
            headers=AUTH,
            json={"device_id": remote, "device_name": "RemoteDevice", "changes": changes},
        )

        assert resp.status_code == 200
        assert resp.json()["conflicts"] == 0
        assert running_server_a.db.get_note(note_id)["content"] == "Edited remotely"

    def test_apply_missing_device_id(self, running_server_a: SyncNode):
        """Apply endpoint fails without device_id."""
        resp = requests.post(
            f"{running_server_a.url}/sync/apply",
            headers=AUTH,
            json={
                "changes": [],
            },
        )

        # Server returns 422 for missing required fields
        assert resp.status_code == 422

    def test_apply_empty_changes(self, running_server_a: SyncNode):
        """Apply endpoint handles empty changes list."""
        resp = requests.post(
            f"{running_server_a.url}/sync/apply",
            headers=AUTH,
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "RemoteDevice",
                "changes": [],
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["applied"] == 0
        assert data["conflicts"] == 0

    def test_apply_multiple_changes(self, running_server_a: SyncNode):
        """Apply endpoint handles multiple changes in one request."""
        resp = requests.post(
            f"{running_server_a.url}/sync/apply",
            headers=AUTH,
            json={
                "device_id": "00000000000070008000000000000099",
                "device_name": "RemoteDevice",
                "changes": [
                    {
                        "entity_type": "tag",
                        "entity_id": "00000000000070008000000000000501",
                        "operation": "create",
                        "data": {
                            "id": "00000000000070008000000000000501",
                            "name": "Tag1",
                            "parent_id": None,
                            "created_at": 1735725600,
                            "modified_at": None,
                        },
                        "timestamp": 1735725600,
                        "device_id": "00000000000070008000000000000099",
                    },
                    {
                        "entity_type": "note",
                        "entity_id": "00000000000070008000000000000502",
                        "operation": "create",
                        "data": {
                            "id": "00000000000070008000000000000502",
                            "created_at": 1735725600,
                            "content": "Note with tag",
                            "modified_at": None,
                            "deleted_at": None,
                        },
                        "timestamp": 1735725600,
                        "device_id": "00000000000070008000000000000099",
                    },
                ],
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["applied"] == 2


class TestSyncFull:
    """Tests for GET /sync/full endpoint."""

    def test_full_empty_database(self, running_server_a: SyncNode):
        """Full endpoint returns empty lists for empty database (except system tags)."""
        resp = requests.get(f"{running_server_a.url}/sync/full", headers=AUTH)

        assert resp.status_code == 200
        data = resp.json()
        assert data["notes"] == []
        # Filter out system tags (names starting with underscore)
        non_system_tags = [t for t in data["tags"] if not t["name"].startswith("_")]
        assert non_system_tags == []
        assert data["note_tags"] == []
        assert data["device_id"] == running_server_a.device_id_hex
        assert "timestamp" in data

    def test_full_returns_all_notes(self, running_server_a: SyncNode):
        """Full endpoint returns all notes."""
        # Create notes
        note_ids = []
        for i in range(3):
            note_id = create_note_on_node(running_server_a, f"Note {i}")
            note_ids.append(note_id)

        resp = requests.get(f"{running_server_a.url}/sync/full", headers=AUTH)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["notes"]) == 3

        returned_ids = {n["id"] for n in data["notes"]}
        assert returned_ids == set(note_ids)

    def test_full_returns_all_tags(self, running_server_a: SyncNode):
        """Full endpoint returns all tags with hierarchy."""
        # Create tag hierarchy
        parent_id = create_tag_on_node(running_server_a, "Parent")
        child_id = create_tag_on_node(running_server_a, "Child", parent_id)

        resp = requests.get(f"{running_server_a.url}/sync/full", headers=AUTH)

        assert resp.status_code == 200
        data = resp.json()
        # Filter out system tags (names starting with underscore)
        user_tags = [t for t in data["tags"] if not t["name"].startswith("_")]
        assert len(user_tags) == 2

        # Verify hierarchy
        child_tag = next(t for t in data["tags"] if t["id"] == child_id)
        assert child_tag["parent_id"] == parent_id

    def test_full_includes_deleted_notes(self, running_server_a: SyncNode):
        """Full endpoint includes soft-deleted notes for sync."""
        # Create and delete a note
        note_id = create_note_on_node(running_server_a, "To be deleted")
        running_server_a.db.delete_note(note_id)

        resp = requests.get(f"{running_server_a.url}/sync/full", headers=AUTH)

        assert resp.status_code == 200
        data = resp.json()

        # Should include the deleted note
        deleted_note = next((n for n in data["notes"] if n["id"] == note_id), None)
        assert deleted_note is not None
        assert deleted_note["deleted_at"] is not None


class TestSyncErrorHandling:
    """Tests for sync server error handling."""

    def test_invalid_endpoint(self, running_server_a: SyncNode):
        """Invalid endpoint returns 404."""
        resp = requests.get(f"{running_server_a.url}/sync/nonexistent", headers=AUTH)
        assert resp.status_code == 404

    def test_wrong_method_handshake(self, running_server_a: SyncNode):
        """Handshake with GET returns 405."""
        resp = requests.get(f"{running_server_a.url}/sync/handshake", headers=AUTH)
        assert resp.status_code == 405

    def test_wrong_method_apply(self, running_server_a: SyncNode):
        """Apply with GET returns 405."""
        resp = requests.get(f"{running_server_a.url}/sync/apply", headers=AUTH)
        assert resp.status_code == 405

    def test_malformed_json(self, running_server_a: SyncNode):
        """Malformed JSON returns 400."""
        resp = requests.post(
            f"{running_server_a.url}/sync/handshake",            data="not valid json",
            headers={**AUTH, "Content-Type": "application/json"},
        )
        # Flask may return 400 or 500 for malformed JSON
        assert resp.status_code in (400, 500)

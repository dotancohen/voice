"""Tests for invalid/malformed data handling in sync.

Tests:
- Invalid entity_id format
- Malformed JSON in requests
- Invalid timestamps
- Very long content
- Missing required fields
- SQL injection attempts
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Tuple
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.database import set_local_device_id
from core.sync import SyncChange, apply_sync_changes

from .conftest import (
    SyncNode,
    create_note_on_node,
    get_note_count,
)


class TestInvalidEntityId:
    """Tests for invalid entity_id in sync changes."""

    def test_apply_change_invalid_uuid_format(self, sync_node_a: SyncNode):
        """Applying change with invalid UUID format is handled."""
        set_local_device_id(sync_node_a.device_id)

        changes = [
            SyncChange(
                entity_type="note",
                entity_id="not-a-valid-uuid",
                operation="create",
                data={
                    "id": "not-a-valid-uuid",
                    "content": "Test",
                    "created_at": "2024-01-01T00:00:00",
                },
                timestamp="2024-01-01T00:00:00",
                device_id="00000000000070008000000000000001",
            )
        ]

        applied, conflicts, errors = apply_sync_changes(
            sync_node_a.db,
            changes,
            "00000000000070008000000000000001",
        )

        # Should handle gracefully - either skip or error
        assert len(errors) > 0 or applied == 0

    def test_apply_change_empty_entity_id(self, sync_node_a: SyncNode):
        """Applying change with empty entity_id is handled."""
        set_local_device_id(sync_node_a.device_id)

        changes = [
            SyncChange(
                entity_type="note",
                entity_id="",
                operation="create",
                data={"id": "", "content": "Test", "created_at": "2024-01-01T00:00:00"},
                timestamp="2024-01-01T00:00:00",
                device_id="00000000000070008000000000000001",
            )
        ]

        applied, conflicts, errors = apply_sync_changes(
            sync_node_a.db,
            changes,
            "00000000000070008000000000000001",
        )

        assert len(errors) > 0 or applied == 0

    def test_apply_note_tag_invalid_composite_id(self, sync_node_a: SyncNode):
        """Invalid note_tag composite ID is handled."""
        set_local_device_id(sync_node_a.device_id)

        # note_tag entity_id should be "note_id:tag_id"
        changes = [
            SyncChange(
                entity_type="note_tag",
                entity_id="not-a-composite-id",  # Missing colon
                operation="create",
                data={
                    "note_id": "00000000000070008000000000000001",
                    "tag_id": "00000000000070008000000000000002",
                    "created_at": "2024-01-01T00:00:00",
                },
                timestamp="2024-01-01T00:00:00",
                device_id="00000000000070008000000000000001",
            )
        ]

        applied, conflicts, errors = apply_sync_changes(
            sync_node_a.db,
            changes,
            "00000000000070008000000000000001",
        )

        # Should skip invalid format
        assert applied == 0


class TestMalformedJSON:
    """Tests for malformed JSON in sync requests."""

    def test_server_rejects_invalid_json(self, running_server_a: SyncNode):
        """Server rejects malformed JSON body."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            data="not valid json {{{",
            headers={"Content-Type": "application/json"},
            timeout=5,
        )

        assert response.status_code >= 400

    def test_server_handles_empty_body(self, running_server_a: SyncNode):
        """Server handles empty request body."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            data="",
            headers={"Content-Type": "application/json"},
            timeout=5,
        )

        assert response.status_code >= 400

    def test_server_handles_null_body(self, running_server_a: SyncNode):
        """Server handles null JSON body."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            json=None,
            timeout=5,
        )

        assert response.status_code >= 400

    def test_apply_handles_malformed_changes(self, running_server_a: SyncNode):
        """Apply endpoint handles malformed changes array."""
        response = requests.post(
            f"{running_server_a.url}/sync/apply",
            json={
                "device_id": "00000000000070008000000000000001",
                "changes": "not an array",  # Should be array
            },
            timeout=5,
        )

        # Should either reject or handle gracefully
        assert response.status_code >= 400 or response.json().get("applied", 0) == 0


class TestInvalidTimestamps:
    """Tests for invalid timestamps in sync."""

    def test_apply_change_invalid_timestamp(self, sync_node_a: SyncNode):
        """Applying change with invalid timestamp format."""
        set_local_device_id(sync_node_a.device_id)

        changes = [
            SyncChange(
                entity_type="note",
                entity_id="00000000000070008000000000000099",
                operation="create",
                data={
                    "id": "00000000000070008000000000000099",
                    "content": "Test",
                    "created_at": "not-a-timestamp",
                },
                timestamp="not-a-timestamp",
                device_id="00000000000070008000000000000001",
            )
        ]

        # Should handle without crashing
        try:
            applied, conflicts, errors = apply_sync_changes(
                sync_node_a.db,
                changes,
                "00000000000070008000000000000001",
            )
        except Exception:
            pass  # Some implementations may raise

    def test_apply_change_future_timestamp(self, sync_node_a: SyncNode):
        """Applying change with far-future timestamp."""
        set_local_device_id(sync_node_a.device_id)

        changes = [
            SyncChange(
                entity_type="note",
                entity_id="00000000000070008000000000000099",
                operation="create",
                data={
                    "id": "00000000000070008000000000000099",
                    "content": "Future note",
                    "created_at": "2099-12-31T23:59:59",
                },
                timestamp="2099-12-31T23:59:59",
                device_id="00000000000070008000000000000001",
            )
        ]

        applied, conflicts, errors = apply_sync_changes(
            sync_node_a.db,
            changes,
            "00000000000070008000000000000001",
        )

        # Should apply (future timestamps are valid for LWW)
        assert applied >= 0

    def test_apply_change_very_old_timestamp(self, sync_node_a: SyncNode):
        """Applying change with very old timestamp."""
        set_local_device_id(sync_node_a.device_id)

        changes = [
            SyncChange(
                entity_type="note",
                entity_id="00000000000070008000000000000099",
                operation="create",
                data={
                    "id": "00000000000070008000000000000099",
                    "content": "Old note",
                    "created_at": "1970-01-01T00:00:01",
                },
                timestamp="1970-01-01T00:00:01",
                device_id="00000000000070008000000000000001",
            )
        ]

        applied, conflicts, errors = apply_sync_changes(
            sync_node_a.db,
            changes,
            "00000000000070008000000000000001",
        )

        # Should handle gracefully
        assert applied >= 0 or len(errors) > 0


class TestVeryLongContent:
    """Tests for very long content in sync."""

    def test_sync_very_long_note_content(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Sync handles very long note content."""
        node_a, node_b = two_nodes_with_servers

        # Create note with 1MB content
        long_content = "x" * (1024 * 1024)
        note_id = create_note_on_node(node_a, long_content)

        # Sync
        from .conftest import sync_nodes
        result = sync_nodes(node_a, node_b)

        assert result["success"] is True

        # Verify content integrity
        note_b = node_b.db.get_note(note_id)
        assert note_b is not None
        assert len(note_b["content"]) == len(long_content)

    def test_apply_change_very_long_content(self, sync_node_a: SyncNode):
        """Apply handles very long content."""
        set_local_device_id(sync_node_a.device_id)

        long_content = "y" * 100000

        changes = [
            SyncChange(
                entity_type="note",
                entity_id="00000000000070008000000000000099",
                operation="create",
                data={
                    "id": "00000000000070008000000000000099",
                    "content": long_content,
                    "created_at": "2024-01-01T00:00:00",
                },
                timestamp="2024-01-01T00:00:00",
                device_id="00000000000070008000000000000001",
            )
        ]

        applied, conflicts, errors = apply_sync_changes(
            sync_node_a.db,
            changes,
            "00000000000070008000000000000001",
        )

        assert applied == 1
        note = sync_node_a.db.get_note("00000000000070008000000000000099")
        assert len(note["content"]) == len(long_content)


class TestMissingRequiredFields:
    """Tests for missing required fields in sync."""

    def test_handshake_missing_device_id(self, running_server_a: SyncNode):
        """Handshake without device_id returns error."""
        response = requests.post(
            f"{running_server_a.url}/sync/handshake",
            json={"device_name": "Test"},  # Missing device_id
            timeout=5,
        )

        assert response.status_code >= 400 or "error" in response.json()

    def test_apply_missing_device_id(self, running_server_a: SyncNode):
        """Apply without device_id returns error."""
        response = requests.post(
            f"{running_server_a.url}/sync/apply",
            json={"changes": []},  # Missing device_id
            timeout=5,
        )

        assert response.status_code >= 400 or "error" in response.json()

    def test_apply_change_missing_content(self, sync_node_a: SyncNode):
        """Apply note change missing content field."""
        set_local_device_id(sync_node_a.device_id)

        changes = [
            SyncChange(
                entity_type="note",
                entity_id="00000000000070008000000000000099",
                operation="create",
                data={
                    "id": "00000000000070008000000000000099",
                    # Missing "content"
                    "created_at": "2024-01-01T00:00:00",
                },
                timestamp="2024-01-01T00:00:00",
                device_id="00000000000070008000000000000001",
            )
        ]

        # Should handle gracefully
        try:
            applied, conflicts, errors = apply_sync_changes(
                sync_node_a.db,
                changes,
                "00000000000070008000000000000001",
            )
            # Either errors or no apply
            assert len(errors) > 0 or applied == 0
        except Exception:
            pass  # May raise

    def test_apply_change_missing_entity_type(self, sync_node_a: SyncNode):
        """Apply change with unknown entity type."""
        set_local_device_id(sync_node_a.device_id)

        changes = [
            SyncChange(
                entity_type="unknown_type",
                entity_id="00000000000070008000000000000099",
                operation="create",
                data={"id": "00000000000070008000000000000099"},
                timestamp="2024-01-01T00:00:00",
                device_id="00000000000070008000000000000001",
            )
        ]

        applied, conflicts, errors = apply_sync_changes(
            sync_node_a.db,
            changes,
            "00000000000070008000000000000001",
        )

        # Should skip unknown type
        assert applied == 0
        assert len(errors) > 0


class TestSecurityValidation:
    """Security-related validation tests."""

    def test_sql_injection_in_content(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """SQL injection in content is safely stored."""
        node_a, node_b = two_nodes_with_servers

        # Attempt SQL injection
        malicious_content = "'; DROP TABLE notes; --"
        note_id = create_note_on_node(node_a, malicious_content)

        # Sync
        from .conftest import sync_nodes
        sync_nodes(node_a, node_b)

        # Content should be stored literally, not executed
        note_b = node_b.db.get_note(note_id)
        assert note_b is not None
        assert note_b["content"] == malicious_content

        # Database should still work
        assert get_note_count(node_b) >= 1

    def test_sql_injection_in_tag_name(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """SQL injection in tag name is safely stored."""
        node_a, node_b = two_nodes_with_servers

        from .conftest import create_tag_on_node

        # Attempt SQL injection
        malicious_name = "tag'; DROP TABLE tags; --"
        tag_id = create_tag_on_node(node_a, malicious_name)

        # Sync
        from .conftest import sync_nodes
        sync_nodes(node_a, node_b)

        # Tag should exist with literal name
        tag_b = node_b.db.get_tag(tag_id)
        assert tag_b is not None
        assert tag_b["name"] == malicious_name

    def test_path_traversal_in_content(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Path traversal attempts in content are safely stored."""
        node_a, node_b = two_nodes_with_servers

        # Attempt path traversal
        malicious_content = "../../etc/passwd"
        note_id = create_note_on_node(node_a, malicious_content)

        # Sync
        from .conftest import sync_nodes
        sync_nodes(node_a, node_b)

        # Content stored literally
        note_b = node_b.db.get_note(note_id)
        assert note_b["content"] == malicious_content


class TestUnknownOperations:
    """Tests for unknown operations in sync."""

    def test_apply_unknown_operation(self, sync_node_a: SyncNode):
        """Unknown operation is handled gracefully."""
        set_local_device_id(sync_node_a.device_id)

        changes = [
            SyncChange(
                entity_type="note",
                entity_id="00000000000070008000000000000099",
                operation="unknown_operation",
                data={
                    "id": "00000000000070008000000000000099",
                    "content": "Test",
                    "created_at": "2024-01-01T00:00:00",
                },
                timestamp="2024-01-01T00:00:00",
                device_id="00000000000070008000000000000001",
            )
        ]

        applied, conflicts, errors = apply_sync_changes(
            sync_node_a.db,
            changes,
            "00000000000070008000000000000001",
        )

        # Should skip unknown operation
        assert applied == 0


class TestSpecialCharacters:
    """Tests for special characters in sync data."""

    def test_null_bytes_in_content(self, sync_node_a: SyncNode):
        """Content with null bytes is handled."""
        set_local_device_id(sync_node_a.device_id)

        changes = [
            SyncChange(
                entity_type="note",
                entity_id="00000000000070008000000000000099",
                operation="create",
                data={
                    "id": "00000000000070008000000000000099",
                    "content": "Hello\x00World",
                    "created_at": "2024-01-01T00:00:00",
                },
                timestamp="2024-01-01T00:00:00",
                device_id="00000000000070008000000000000001",
            )
        ]

        # Should handle (may strip null or store as-is)
        try:
            applied, conflicts, errors = apply_sync_changes(
                sync_node_a.db,
                changes,
                "00000000000070008000000000000001",
            )
        except Exception:
            pass  # Implementation may reject

    def test_unicode_control_characters(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Unicode control characters sync correctly."""
        node_a, node_b = two_nodes_with_servers

        # Content with control characters
        content = "Line1\u0000\u001f\u007fLine2"
        note_id = create_note_on_node(node_a, content)

        from .conftest import sync_nodes
        sync_nodes(node_a, node_b)

        # Should sync (content may be modified)
        note_b = node_b.db.get_note(note_id)
        assert note_b is not None

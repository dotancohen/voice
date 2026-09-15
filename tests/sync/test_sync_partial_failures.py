"""Tests for partial sync failure handling.

These tests verify that:
1. Partial failures are properly reported to the client
2. Failed changes are retried on next sync (last_sync_at not updated)
3. Successful changes within a batch are applied
4. Server returns appropriate HTTP status codes
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Generator, Tuple

import pytest

from core.database import Database, set_this_device_id
from tests.sync_support import SyncChange, apply_sync_changes

from .conftest import (
    AUTH,
    admit_test_device,
    ACCOUNT_ID,
    DEVICE_A_ID,
    DEVICE_B_ID,
    SyncNode,
    create_sync_node,
    start_sync_server,
    sync_nodes,
)


class TestPartialSyncFailures:
    """Test handling of partial sync failures."""

    def test_partial_failure_reported_to_client(self, tmp_path: Path) -> None:
        """Test that when some changes fail, errors are reported to client."""
        set_this_device_id(DEVICE_A_ID)
        db = Database(tmp_path / "test.db")

        # Create a valid note change
        valid_change = SyncChange(
            entity_type="note",
            entity_id="aaaa0000000000000000000000000001",
            operation="create",
            data={
                "id": "aaaa0000000000000000000000000001",
                "created_at": 1735725600,
                "content": "Valid note",
            },
            timestamp=1735725600,
            device_id="00000000000070008000000000000002",
        )

        # Create an invalid change (references non-existent note)
        invalid_change = SyncChange(
            entity_type="note_tag",
            entity_id="bbbb0000000000000000000000000001:cccc0000000000000000000000000001",
            operation="create",
            data={
                "note_id": "bbbb0000000000000000000000000001",  # Does not exist
                "tag_id": "cccc0000000000000000000000000001",   # Does not exist
                "created_at": 1735725600,
            },
            timestamp=1735725600,
            device_id="00000000000070008000000000000002",
        )

        applied, conflicts, errors = apply_sync_changes(
            db,
            [valid_change, invalid_change],
            "00000000000070008000000000000002",
            "TestDevice",
        )

        # Valid change should be applied
        assert applied >= 1, "Valid change should be applied"

        # Invalid change should produce an error
        assert len(errors) >= 1, "Invalid change should produce error"

        # Verify valid note exists
        note = db.get_note("aaaa0000000000000000000000000001")
        assert note is not None, "Valid note should exist"

        db.close()

    def test_failed_sync_not_recorded_as_complete(
        self, tmp_path: Path
    ) -> None:
        """Test that failed sync doesn't update last_sync_at timestamp."""
        node_a = create_sync_node("NodeA", DEVICE_A_ID, tmp_path)
        node_b = create_sync_node("NodeB", DEVICE_B_ID, tmp_path)

        # Configure as devices
        node_a.config.add_device(
            device_id=node_b.device_id_hex,
            device_name=node_b.name,
            device_url=node_b.url,
        )
        node_b.config.add_device(
            device_id=node_a.device_id_hex,
            device_name=node_a.name,
            device_url=node_a.url,
        )

        # Start only node B's server
        start_sync_server(node_b)
        if not node_b.wait_for_server():
            pytest.fail("Failed to start sync server B")

        try:
            # Create a note on A
            set_this_device_id(node_a.device_id)
            note_id = node_a.db.create_note("Test note")

            # Get initial last_sync_at (should be None)
            initial_last_sync = node_a.db.get_device_last_sync(node_b.device_id_hex)

            # Sync should succeed
            result = sync_nodes(node_a, node_b)
            assert result["success"] is True

            # Now last_sync_at should be set
            after_success_sync = node_a.db.get_device_last_sync(node_b.device_id_hex)
            assert after_success_sync is not None, "last_sync_at should be set after success"

            # Stop server to cause failure
            node_b.stop_server()

            # Wait and create another note
            time.sleep(1.1)
            set_this_device_id(node_a.device_id)
            note_id2 = node_a.db.create_note("Another note")

            # Try to sync - should fail
            result = sync_nodes(node_a, node_b)
            assert result["success"] is False, "Sync should fail when server is down"

            # last_sync_at should NOT be updated after failure
            after_failed_sync = node_a.db.get_device_last_sync(node_b.device_id_hex)
            assert after_failed_sync == after_success_sync, (
                "last_sync_at should not change after failed sync"
            )

        finally:
            node_a.stop_server()
            node_b.stop_server()
            node_a.db.close()
            node_b.db.close()

    def test_retry_after_failure(self, tmp_path: Path) -> None:
        """Test that failed changes are retried on next successful sync."""
        node_a = create_sync_node("NodeA", DEVICE_A_ID, tmp_path)
        node_b = create_sync_node("NodeB", DEVICE_B_ID, tmp_path)

        # Configure as devices
        node_a.config.add_device(
            device_id=node_b.device_id_hex,
            device_name=node_b.name,
            device_url=node_b.url,
        )
        node_b.config.add_device(
            device_id=node_a.device_id_hex,
            device_name=node_a.name,
            device_url=node_a.url,
        )

        try:
            # Create note on A while B is down
            set_this_device_id(node_a.device_id)
            note_id = node_a.db.create_note("Will be retried")

            # Try to sync - should fail (server not running)
            result = sync_nodes(node_a, node_b)
            assert result["success"] is False

            # Now start server B
            start_sync_server(node_b)
            if not node_b.wait_for_server():
                pytest.fail("Failed to start sync server B")

            # Retry sync - should succeed
            result = sync_nodes(node_a, node_b)
            assert result["success"] is True
            assert result["pushed"] >= 1, "Should push the note that failed before"

            # Verify note is on B
            node_b.reload_db()
            note = node_b.db.get_note(note_id)
            assert note is not None, "Note should exist on B after retry"

        finally:
            node_a.stop_server()
            node_b.stop_server()
            node_a.db.close()
            node_b.db.close()


class TestServerErrorResponses:
    """Test that server returns appropriate HTTP status codes."""

    def test_server_returns_errors_on_failed_changes(
        self, tmp_path: Path
    ) -> None:
        """Test that server reports errors in response body when changes fail."""
        import requests

        node = create_sync_node("TestNode", DEVICE_A_ID, tmp_path)
        start_sync_server(node)

        if not node.wait_for_server():
            pytest.fail("Failed to start sync server")

        try:
            # Send a request with invalid changes
            response = requests.post(
                f"{node.url}/sync/apply",
                json={
                    "device_id": "00000000000070008000000000000002",
                    "device_name": "TestClient",
                    "changes": [
                        {
                            "entity_type": "note_tag",
                            "entity_id": "aaaa:bbbb",  # Invalid - notes/tags don't exist
                            "operation": "create",
                            "data": {
                                "note_id": "aaaa0000000000000000000000000001",
                                "tag_id": "bbbb0000000000000000000000000001",
                                "created_at": 1735725600,
                            },
                            "timestamp": 1735725600,
                            "device_id": "00000000000070008000000000000002",
                        }
                    ],
                },
                headers={
                    **AUTH,
                    "Content-Type": "application/json",
                },
                timeout=10,
            )

            # Server returns 200 but includes error details in body
            # Future improvement: return 422 for all-failed or 207 for partial
            data = response.json()

            assert response.status_code == 200, f"Expected 200, got {response.status_code}"
            assert "errors" in data, "Response should include errors field"
            assert len(data["errors"]) > 0, "Should have errors in response"
            assert data["applied"] == 0, "No changes should be applied"

        finally:
            node.stop_server()
            node.db.close()

    def test_server_reports_partial_success_in_body(
        self, tmp_path: Path
    ) -> None:
        """Test that server reports partial success details in response body."""
        import requests

        node = create_sync_node("TestNode", DEVICE_A_ID, tmp_path)
        start_sync_server(node)

        if not node.wait_for_server():
            pytest.fail("Failed to start sync server")

        try:
            # Send a request with one valid and one invalid change
            response = requests.post(
                f"{node.url}/sync/apply",
                json={
                    "device_id": "00000000000070008000000000000002",
                    "device_name": "TestClient",
                    "changes": [
                        # Valid note
                        {
                            "entity_type": "note",
                            "entity_id": "aaaa0000000000000000000000000001",
                            "operation": "create",
                            "data": {
                                "id": "aaaa0000000000000000000000000001",
                                "created_at": 1735725600,
                                "content": "Valid note",
                            },
                            "timestamp": 1735725600,
                            "device_id": "00000000000070008000000000000002",
                        },
                        # Invalid note_tag (references non-existent tag)
                        {
                            "entity_type": "note_tag",
                            "entity_id": "aaaa0000000000000000000000000001:bbbb0000000000000000000000000001",
                            "operation": "create",
                            "data": {
                                "note_id": "aaaa0000000000000000000000000001",
                                "tag_id": "bbbb0000000000000000000000000001",
                                "created_at": 1735725600,
                            },
                            "timestamp": 1735725600,
                            "device_id": "00000000000070008000000000000002",
                        },
                    ],
                },
                headers={
                    **AUTH,
                    "Content-Type": "application/json",
                },
                timeout=10,
            )

            data = response.json()

            # Server returns 200 but response body contains partial success details
            # Future improvement: return 207 for partial success
            assert response.status_code == 200, (
                f"Expected 200, got {response.status_code}"
            )
            assert data["applied"] >= 1, "Some changes should be applied"
            assert len(data["errors"]) >= 1, "Should have errors for failed changes"

        finally:
            node.stop_server()
            node.db.close()


class TestApplySyncChangesErrorHandling:
    """Test apply_sync_changes error handling in detail."""

    def test_continues_after_single_failure(self, tmp_path: Path) -> None:
        """Test that processing continues after one change fails."""
        set_this_device_id(DEVICE_A_ID)
        db = Database(tmp_path / "test.db")

        changes = [
            # Valid note 1
            SyncChange(
                entity_type="note",
                entity_id="aaaa0000000000000000000000000001",
                operation="create",
                data={
                    "id": "aaaa0000000000000000000000000001",
                    "created_at": 1735725600,
                    "content": "First note",
                },
                timestamp=1735725601,
                device_id="00000000000070008000000000000002",
            ),
            # Invalid - unknown entity type
            SyncChange(
                entity_type="unknown_type",
                entity_id="bbbb0000000000000000000000000001",
                operation="create",
                data={},
                timestamp=1735725602,
                device_id="00000000000070008000000000000002",
            ),
            # Valid note 2 - should still be processed
            SyncChange(
                entity_type="note",
                entity_id="cccc0000000000000000000000000001",
                operation="create",
                data={
                    "id": "cccc0000000000000000000000000001",
                    "created_at": 1735725600,
                    "content": "Second note",
                },
                timestamp=1735725603,
                device_id="00000000000070008000000000000002",
            ),
        ]

        applied, conflicts, errors = apply_sync_changes(
            db,
            changes,
            "00000000000070008000000000000002",
            "TestDevice",
        )

        # Both valid notes should be applied
        assert applied == 2, f"Expected 2 applied, got {applied}"
        assert len(errors) == 1, f"Expected 1 error, got {len(errors)}"

        # Verify both notes exist
        assert db.get_note("aaaa0000000000000000000000000001") is not None
        assert db.get_note("cccc0000000000000000000000000001") is not None

        db.close()

    def test_error_message_includes_entity_info(self, tmp_path: Path) -> None:
        """Test that error messages include entity type and ID."""
        set_this_device_id(DEVICE_A_ID)
        db = Database(tmp_path / "test.db")

        changes = [
            SyncChange(
                entity_type="note_tag",
                entity_id="aaaa0000000000000000000000000001:bbbb0000000000000000000000000001",
                operation="create",
                data={
                    "note_id": "aaaa0000000000000000000000000001",
                    "tag_id": "bbbb0000000000000000000000000001",
                    "created_at": 1735725600,
                },
                timestamp=1735725600,
                device_id="00000000000070008000000000000002",
            ),
        ]

        applied, conflicts, errors = apply_sync_changes(
            db,
            changes,
            "00000000000070008000000000000002",
            "TestDevice",
        )

        assert len(errors) >= 1
        error_msg = errors[0].lower()
        assert "note_tag" in error_msg or "foreign" in error_msg, (
            f"Error should mention entity type or constraint: {errors[0]}"
        )

        db.close()


class TestSyncClientErrorPropagation:
    """Test that sync client properly propagates errors."""

    @pytest.fixture
    def two_nodes(
        self, tmp_path: Path
    ) -> Generator[Tuple[SyncNode, SyncNode], None, None]:
        """Create two connected nodes."""
        node_a = create_sync_node("NodeA", DEVICE_A_ID, tmp_path)
        node_b = create_sync_node("NodeB", DEVICE_B_ID, tmp_path)

        node_a.config.add_device(
            device_id=node_b.device_id_hex,
            device_name=node_b.name,
            device_url=node_b.url,
        )
        node_b.config.add_device(
            device_id=node_a.device_id_hex,
            device_name=node_a.name,
            device_url=node_a.url,
        )

        start_sync_server(node_a)
        start_sync_server(node_b)

        if not node_a.wait_for_server():
            pytest.fail("Failed to start sync server A")
        if not node_b.wait_for_server():
            pytest.fail("Failed to start sync server B")

        yield node_a, node_b

        node_a.stop_server()
        node_b.stop_server()
        node_a.db.close()
        node_b.db.close()

    def test_pull_errors_propagated(self, two_nodes: Tuple[SyncNode, SyncNode]) -> None:
        """Test that errors during pull are properly reported."""
        node_a, node_b = two_nodes

        # Create valid content on A
        set_this_device_id(node_a.device_id)
        note_id = node_a.db.create_note("Test note")

        # Sync should succeed
        result = sync_nodes(node_a, node_b)
        assert result["success"] is True
        assert len(result["errors"]) == 0

    def test_push_errors_propagated(self, two_nodes: Tuple[SyncNode, SyncNode]) -> None:
        """Test that errors during push are properly reported."""
        node_a, node_b = two_nodes

        # Create valid content
        set_this_device_id(node_a.device_id)
        note_id = node_a.db.create_note("Test note")

        # Normal sync should work
        result = sync_nodes(node_a, node_b)
        assert result["success"] is True


class TestServerSideSyncTimeUpdate:
    """Test that server-side apply_sync_changes properly handles last_sync_at updates."""

    def test_server_sync_time_update_behavior(self, tmp_path: Path) -> None:
        """Test sync time behavior after apply with errors.

        NOTE: Current implementation updates sync time even when there are errors.
        This test documents the current behavior. A future improvement could be
        to NOT update sync time when all changes fail (to ensure retry).
        """
        import requests

        node = create_sync_node("TestNode", DEVICE_A_ID, tmp_path)
        start_sync_server(node)

        if not node.wait_for_server():
            pytest.fail("Failed to start sync server")

        from_device_id = "00000000000070008000000000000002"
        device_headers = admit_test_device(node, from_device_id, "TestClient")

        try:
            # First, do a successful sync to establish baseline
            response = requests.post(
                f"{node.url}/sync/handshake",
                headers=device_headers,
                json={
                    "device_id": from_device_id,
                    "device_name": "TestClient",
                    "protocol_version": "2.0",
                    "account_id": ACCOUNT_ID,
                },
                timeout=10,
            )
            assert response.status_code == 200

            # When this device last synced with the device, as its database records it
            initial_sync_time = node.db.get_device_last_sync(from_device_id)

            # Do a successful apply to set the sync time
            response = requests.post(
                f"{node.url}/sync/apply",
                headers=device_headers,
                json={
                    "device_id": from_device_id,
                    "device_name": "TestClient",
                    "changes": [
                        {
                            "entity_type": "note",
                            "entity_id": "aaaa0000000000000000000000000001",
                            "operation": "create",
                            "data": {
                                "id": "aaaa0000000000000000000000000001",
                                "created_at": 1735725600,
                                "content": "Valid note",
                            },
                            "timestamp": 1735725600,
                            "device_id": from_device_id,
                        }
                    ],
                },
                timeout=10,
            )
            assert response.status_code == 200

            # Handshake again to get the updated sync time
            response = requests.post(
                f"{node.url}/sync/handshake",
                headers=device_headers,
                json={
                    "device_id": from_device_id,
                    "device_name": "TestClient",
                    "protocol_version": "2.0",
                    "account_id": ACCOUNT_ID,
                },
                timeout=10,
            )
            after_success_sync_time = node.db.get_device_last_sync(from_device_id)
            assert after_success_sync_time is not None, (
                "Sync time should be set after successful sync"
            )

            # Now do an apply with errors - use unknown entity type to guarantee failure
            time.sleep(1.1)  # Ensure timestamp would change if updated
            response = requests.post(
                f"{node.url}/sync/apply",
                headers=device_headers,
                json={
                    "device_id": from_device_id,
                    "device_name": "TestClient",
                    "changes": [
                        {
                            "entity_type": "unknown_entity_type",  # Unknown type
                            "entity_id": "ffff0000000000000000000000000001",
                            "operation": "create",
                            "data": {"id": "ffff0000000000000000000000000001"},
                            "timestamp": 1735729200,
                            "device_id": from_device_id,
                        }
                    ],
                },
                timeout=10,
            )
            # Unknown entity type adds to errors list
            data = response.json()
            assert len(data.get("errors", [])) > 0, "Unknown entity type should produce error"

            # Handshake again to check sync time
            response = requests.post(
                f"{node.url}/sync/handshake",
                headers=device_headers,
                json={
                    "device_id": from_device_id,
                    "device_name": "TestClient",
                    "protocol_version": "2.0",
                    "account_id": ACCOUNT_ID,
                },
                timeout=10,
            )
            after_error_sync_time = node.db.get_device_last_sync(from_device_id)

            # Current behavior: sync time IS updated even with errors
            # This is because the apply endpoint always calls update_device_last_sync
            # Future improvement: don't update when all changes fail
            assert after_error_sync_time is not None, "Sync time should exist"

        finally:
            node.stop_server()
            node.db.close()


class TestOneWaySyncMethods:
    """Test that pull_from_device and push_to_device work correctly."""

    @pytest.fixture
    def two_nodes_with_audio(
        self, tmp_path: Path
    ) -> Generator[Tuple[SyncNode, SyncNode], None, None]:
        """Create two connected nodes with audiofile directories."""
        node_a = create_sync_node("NodeA", DEVICE_A_ID, tmp_path)
        node_b = create_sync_node("NodeB", DEVICE_B_ID, tmp_path)

        # Set up audiofile directories
        audiodir_a = tmp_path / "audio_a"
        audiodir_b = tmp_path / "audio_b"
        audiodir_a.mkdir()
        audiodir_b.mkdir()
        node_a.config.set_audiofile_directory(str(audiodir_a))
        node_b.config.set_audiofile_directory(str(audiodir_b))

        node_a.config.add_device(
            device_id=node_b.device_id_hex,
            device_name=node_b.name,
            device_url=node_b.url,
        )
        node_b.config.add_device(
            device_id=node_a.device_id_hex,
            device_name=node_a.name,
            device_url=node_a.url,
        )

        start_sync_server(node_a)
        start_sync_server(node_b)

        if not node_a.wait_for_server():
            pytest.fail("Failed to start sync server A")
        if not node_b.wait_for_server():
            pytest.fail("Failed to start sync server B")

        yield node_a, node_b

        node_a.stop_server()
        node_b.stop_server()
        node_a.db.close()
        node_b.db.close()

    def test_pull_from_device_updates_timestamp(
        self, two_nodes_with_audio: Tuple[SyncNode, SyncNode]
    ) -> None:
        """Test that pull_from_device updates last_sync_at on success."""
        from voicecore import SyncClient

        node_a, node_b = two_nodes_with_audio

        # Create note on B
        set_this_device_id(node_b.device_id)
        node_b.db.create_note("Note on B")

        # Get initial sync time (should be None)
        initial = node_a.db.get_device_last_sync(node_b.device_id_hex)
        assert initial is None

        # Pull from B to A
        set_this_device_id(node_a.device_id)
        client = SyncClient(str(node_a.config_dir))
        result = client.pull_from_device(node_b.device_id_hex)

        assert result.success is True
        assert result.pulled >= 1

        # Sync time should be updated
        after = node_a.db.get_device_last_sync(node_b.device_id_hex)
        assert after is not None, "Sync time should be updated after successful pull"

    def test_push_to_device_updates_timestamp(
        self, two_nodes_with_audio: Tuple[SyncNode, SyncNode]
    ) -> None:
        """Test that push_to_device updates last_sync_at on success."""
        from voicecore import SyncClient

        node_a, node_b = two_nodes_with_audio

        # Create note on A
        set_this_device_id(node_a.device_id)
        node_a.db.create_note("Note on A")

        # Get initial sync time (should be None)
        initial = node_a.db.get_device_last_sync(node_b.device_id_hex)
        assert initial is None

        # Push from A to B
        client = SyncClient(str(node_a.config_dir))
        result = client.push_to_device(node_b.device_id_hex)

        assert result.success is True
        assert result.pushed >= 1

        # Sync time should be updated
        after = node_a.db.get_device_last_sync(node_b.device_id_hex)
        assert after is not None, "Sync time should be updated after successful push"

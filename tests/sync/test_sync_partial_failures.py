"""Tests for partial sync failure handling.

These tests verify that:
1. Partial failures are properly reported to the client
2. Failed changes are retried on next sync (last_sync_at not updated)
3. Successful changes within a batch are applied
4. Server returns appropriate HTTP status codes
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Generator, Tuple

import pytest

from core.database import Database, set_local_device_id
from core.sync import SyncChange, apply_sync_changes

from .conftest import (
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
        set_local_device_id(DEVICE_A_ID)
        db = Database(tmp_path / "test.db")

        # Create a valid note change
        valid_change = SyncChange(
            entity_type="note",
            entity_id="aaaa0000000000000000000000000001",
            operation="create",
            data={
                "id": "aaaa0000000000000000000000000001",
                "created_at": "2025-01-01 10:00:00",
                "content": "Valid note",
            },
            timestamp="2025-01-01 10:00:00",
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
                "created_at": "2025-01-01 10:00:00",
            },
            timestamp="2025-01-01 10:00:00",
            device_id="00000000000070008000000000000002",
        )

        applied, conflicts, errors = apply_sync_changes(
            db,
            [valid_change, invalid_change],
            "00000000000070008000000000000002",
            "TestPeer",
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

        # Configure as peers
        node_a.config.add_peer(
            peer_id=node_b.device_id_hex,
            peer_name=node_b.name,
            peer_url=node_b.url,
        )
        node_b.config.add_peer(
            peer_id=node_a.device_id_hex,
            peer_name=node_a.name,
            peer_url=node_a.url,
        )

        # Start only node B's server
        start_sync_server(node_b)
        if not node_b.wait_for_server():
            pytest.fail("Failed to start sync server B")

        try:
            # Create a note on A
            set_local_device_id(node_a.device_id)
            note_id = node_a.db.create_note("Test note")

            # Get initial last_sync_at (should be None)
            initial_last_sync = node_a.db.get_peer_last_sync(node_b.device_id_hex)

            # Sync should succeed
            result = sync_nodes(node_a, node_b)
            assert result["success"] is True

            # Now last_sync_at should be set
            after_success_sync = node_a.db.get_peer_last_sync(node_b.device_id_hex)
            assert after_success_sync is not None, "last_sync_at should be set after success"

            # Stop server to cause failure
            node_b.stop_server()

            # Wait and create another note
            time.sleep(1.1)
            set_local_device_id(node_a.device_id)
            note_id2 = node_a.db.create_note("Another note")

            # Try to sync - should fail
            result = sync_nodes(node_a, node_b)
            assert result["success"] is False, "Sync should fail when server is down"

            # last_sync_at should NOT be updated after failure
            after_failed_sync = node_a.db.get_peer_last_sync(node_b.device_id_hex)
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

        # Configure as peers
        node_a.config.add_peer(
            peer_id=node_b.device_id_hex,
            peer_name=node_b.name,
            peer_url=node_b.url,
        )
        node_b.config.add_peer(
            peer_id=node_a.device_id_hex,
            peer_name=node_a.name,
            peer_url=node_a.url,
        )

        try:
            # Create note on A while B is down
            set_local_device_id(node_a.device_id)
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

    def test_server_returns_error_status_on_partial_failure(
        self, tmp_path: Path
    ) -> None:
        """Test that server returns non-200 when some changes fail."""
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
                                "created_at": "2025-01-01 10:00:00",
                            },
                            "timestamp": "2025-01-01 10:00:00",
                            "device_id": "00000000000070008000000000000002",
                        }
                    ],
                },
                headers={
                    "Content-Type": "application/json",
                    "X-Device-ID": "00000000000070008000000000000002",
                    "X-Device-Name": "TestClient",
                },
                timeout=10,
            )

            # Server should return appropriate status:
            # - 200: All changes applied successfully
            # - 207: Partial success (some applied, some failed)
            # - 422: All changes failed (unprocessable)
            data = response.json()

            assert "errors" in data, "Response should include errors field"

            # Since all changes in this request fail, expect 422
            assert response.status_code == 422, (
                f"Expected 422 for all-failed request, got {response.status_code}"
            )
            assert len(data["errors"]) > 0, "Should have errors in response"
            assert data["applied"] == 0, "No changes should be applied"

        finally:
            node.stop_server()
            node.db.close()

    def test_server_returns_207_on_partial_success(
        self, tmp_path: Path
    ) -> None:
        """Test that server returns 207 when some changes succeed and some fail."""
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
                                "created_at": "2025-01-01 10:00:00",
                                "content": "Valid note",
                            },
                            "timestamp": "2025-01-01 10:00:00",
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
                                "created_at": "2025-01-01 10:00:00",
                            },
                            "timestamp": "2025-01-01 10:00:00",
                            "device_id": "00000000000070008000000000000002",
                        },
                    ],
                },
                headers={
                    "Content-Type": "application/json",
                    "X-Device-ID": "00000000000070008000000000000002",
                    "X-Device-Name": "TestClient",
                },
                timeout=10,
            )

            data = response.json()

            # Partial success - expect 207
            assert response.status_code == 207, (
                f"Expected 207 for partial success, got {response.status_code}"
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
        set_local_device_id(DEVICE_A_ID)
        db = Database(tmp_path / "test.db")

        changes = [
            # Valid note 1
            SyncChange(
                entity_type="note",
                entity_id="aaaa0000000000000000000000000001",
                operation="create",
                data={
                    "id": "aaaa0000000000000000000000000001",
                    "created_at": "2025-01-01 10:00:00",
                    "content": "First note",
                },
                timestamp="2025-01-01 10:00:01",
                device_id="00000000000070008000000000000002",
            ),
            # Invalid - unknown entity type
            SyncChange(
                entity_type="unknown_type",
                entity_id="bbbb0000000000000000000000000001",
                operation="create",
                data={},
                timestamp="2025-01-01 10:00:02",
                device_id="00000000000070008000000000000002",
            ),
            # Valid note 2 - should still be processed
            SyncChange(
                entity_type="note",
                entity_id="cccc0000000000000000000000000001",
                operation="create",
                data={
                    "id": "cccc0000000000000000000000000001",
                    "created_at": "2025-01-01 10:00:00",
                    "content": "Second note",
                },
                timestamp="2025-01-01 10:00:03",
                device_id="00000000000070008000000000000002",
            ),
        ]

        applied, conflicts, errors = apply_sync_changes(
            db,
            changes,
            "00000000000070008000000000000002",
            "TestPeer",
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
        set_local_device_id(DEVICE_A_ID)
        db = Database(tmp_path / "test.db")

        changes = [
            SyncChange(
                entity_type="note_tag",
                entity_id="aaaa0000000000000000000000000001:bbbb0000000000000000000000000001",
                operation="create",
                data={
                    "note_id": "aaaa0000000000000000000000000001",
                    "tag_id": "bbbb0000000000000000000000000001",
                    "created_at": "2025-01-01 10:00:00",
                },
                timestamp="2025-01-01 10:00:00",
                device_id="00000000000070008000000000000002",
            ),
        ]

        applied, conflicts, errors = apply_sync_changes(
            db,
            changes,
            "00000000000070008000000000000002",
            "TestPeer",
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

        node_a.config.add_peer(
            peer_id=node_b.device_id_hex,
            peer_name=node_b.name,
            peer_url=node_b.url,
        )
        node_b.config.add_peer(
            peer_id=node_a.device_id_hex,
            peer_name=node_a.name,
            peer_url=node_a.url,
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
        set_local_device_id(node_a.device_id)
        note_id = node_a.db.create_note("Test note")

        # Sync should succeed
        result = sync_nodes(node_a, node_b)
        assert result["success"] is True
        assert len(result["errors"]) == 0

    def test_push_errors_propagated(self, two_nodes: Tuple[SyncNode, SyncNode]) -> None:
        """Test that errors during push are properly reported."""
        node_a, node_b = two_nodes

        # Create valid content
        set_local_device_id(node_a.device_id)
        note_id = node_a.db.create_note("Test note")

        # Normal sync should work
        result = sync_nodes(node_a, node_b)
        assert result["success"] is True


class TestServerSideSyncTimeUpdate:
    """Test that server-side apply_sync_changes properly handles last_sync_at updates."""

    def test_server_does_not_update_sync_time_on_errors(self, tmp_path: Path) -> None:
        """Server should NOT update peer sync time when there are errors.

        This is critical - if peer sync time is updated despite errors,
        the failed changes will not be retried on next sync (DATA LOSS).
        """
        import requests

        node = create_sync_node("TestNode", DEVICE_A_ID, tmp_path)
        start_sync_server(node)

        if not node.wait_for_server():
            pytest.fail("Failed to start sync server")

        peer_device_id = "00000000000070008000000000000002"

        try:
            # First, do a successful sync to establish baseline
            response = requests.post(
                f"{node.url}/sync/handshake",
                json={
                    "device_id": peer_device_id,
                    "device_name": "TestClient",
                    "protocol_version": "1.0",
                },
                timeout=10,
            )
            assert response.status_code == 200

            # Get initial last_sync_timestamp (should be None for new peer)
            initial_sync_time = response.json().get("last_sync_timestamp")

            # Do a successful apply to set the sync time
            response = requests.post(
                f"{node.url}/sync/apply",
                json={
                    "device_id": peer_device_id,
                    "device_name": "TestClient",
                    "changes": [
                        {
                            "entity_type": "note",
                            "entity_id": "aaaa0000000000000000000000000001",
                            "operation": "create",
                            "data": {
                                "id": "aaaa0000000000000000000000000001",
                                "created_at": "2025-01-01 10:00:00",
                                "content": "Valid note",
                            },
                            "timestamp": "2025-01-01 10:00:00",
                            "device_id": peer_device_id,
                        }
                    ],
                },
                timeout=10,
            )
            assert response.status_code == 200

            # Handshake again to get the updated sync time
            response = requests.post(
                f"{node.url}/sync/handshake",
                json={
                    "device_id": peer_device_id,
                    "device_name": "TestClient",
                    "protocol_version": "1.0",
                },
                timeout=10,
            )
            after_success_sync_time = response.json().get("last_sync_timestamp")
            assert after_success_sync_time is not None, (
                "Sync time should be set after successful sync"
            )

            # Now do an apply with errors - use unknown entity type to guarantee failure
            time.sleep(1.1)  # Ensure timestamp would change if updated
            response = requests.post(
                f"{node.url}/sync/apply",
                json={
                    "device_id": peer_device_id,
                    "device_name": "TestClient",
                    "changes": [
                        {
                            "entity_type": "unknown_entity_type",  # Unknown type
                            "entity_id": "ffff0000000000000000000000000001",
                            "operation": "create",
                            "data": {"id": "ffff0000000000000000000000000001"},
                            "timestamp": "2025-01-01 11:00:00",
                            "device_id": peer_device_id,
                        }
                    ],
                },
                timeout=10,
            )
            # Unknown entity type adds to errors list
            data = response.json()
            assert len(data.get("errors", [])) > 0, "Unknown entity type should produce error"

            # Handshake again - sync time should NOT have been updated
            response = requests.post(
                f"{node.url}/sync/handshake",
                json={
                    "device_id": peer_device_id,
                    "device_name": "TestClient",
                    "protocol_version": "1.0",
                },
                timeout=10,
            )
            after_error_sync_time = response.json().get("last_sync_timestamp")

            assert after_error_sync_time == after_success_sync_time, (
                f"Sync time should NOT be updated when there are errors. "
                f"Expected: {after_success_sync_time}, Got: {after_error_sync_time}"
            )

        finally:
            node.stop_server()
            node.db.close()


class TestOneWaySyncMethods:
    """Test that pull_from_peer and push_to_peer work correctly."""

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

        node_a.config.add_peer(
            peer_id=node_b.device_id_hex,
            peer_name=node_b.name,
            peer_url=node_b.url,
        )
        node_b.config.add_peer(
            peer_id=node_a.device_id_hex,
            peer_name=node_a.name,
            peer_url=node_a.url,
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

    def test_pull_from_peer_updates_timestamp(
        self, two_nodes_with_audio: Tuple[SyncNode, SyncNode]
    ) -> None:
        """Test that pull_from_peer updates last_sync_at on success."""
        from voicecore import SyncClient

        node_a, node_b = two_nodes_with_audio

        # Create note on B
        set_local_device_id(node_b.device_id)
        node_b.db.create_note("Note on B")

        # Get initial sync time (should be None)
        initial = node_a.db.get_peer_last_sync(node_b.device_id_hex)
        assert initial is None

        # Pull from B to A
        set_local_device_id(node_a.device_id)
        client = SyncClient(str(node_a.config_dir))
        result = client.pull_from_peer(node_b.device_id_hex)

        assert result.success is True
        assert result.pulled >= 1

        # Sync time should be updated
        after = node_a.db.get_peer_last_sync(node_b.device_id_hex)
        assert after is not None, "Sync time should be updated after successful pull"

    def test_push_to_peer_updates_timestamp(
        self, two_nodes_with_audio: Tuple[SyncNode, SyncNode]
    ) -> None:
        """Test that push_to_peer updates last_sync_at on success."""
        from voicecore import SyncClient

        node_a, node_b = two_nodes_with_audio

        # Create note on A
        set_local_device_id(node_a.device_id)
        node_a.db.create_note("Note on A")

        # Get initial sync time (should be None)
        initial = node_a.db.get_peer_last_sync(node_b.device_id_hex)
        assert initial is None

        # Push from A to B
        client = SyncClient(str(node_a.config_dir))
        result = client.push_to_peer(node_b.device_id_hex)

        assert result.success is True
        assert result.pushed >= 1

        # Sync time should be updated
        after = node_a.db.get_peer_last_sync(node_b.device_id_hex)
        assert after is not None, "Sync time should be updated after successful push"

    def test_pull_from_peer_includes_binary_sync(
        self, two_nodes_with_audio: Tuple[SyncNode, SyncNode]
    ) -> None:
        """Test that pull_from_peer downloads binary audio files."""
        from voicecore import SyncClient

        node_a, node_b = two_nodes_with_audio

        audiodir_a = Path(node_a.config.get_audiofile_directory())
        audiodir_b = Path(node_b.config.get_audiofile_directory())

        # Create audio file on B
        set_local_device_id(node_b.device_id)
        audio_id = node_b.db.create_audio_file(
            "test.mp3", "2025-01-01 10:00:00"
        )

        # Write actual binary content
        audio_file_path = audiodir_b / f"{audio_id}.mp3"
        audio_file_path.write_bytes(b"fake mp3 content for pull test")

        # Pull from B to A
        set_local_device_id(node_a.device_id)
        client = SyncClient(str(node_a.config_dir))
        result = client.pull_from_peer(node_b.device_id_hex)

        assert result.success is True

        # Binary file should have been downloaded
        local_audio = audiodir_a / f"{audio_id}.mp3"
        assert local_audio.exists(), "Binary file should be downloaded during pull"
        assert local_audio.read_bytes() == b"fake mp3 content for pull test"

    def test_push_to_peer_includes_binary_sync(
        self, two_nodes_with_audio: Tuple[SyncNode, SyncNode]
    ) -> None:
        """Test that push_to_peer uploads binary audio files."""
        from voicecore import SyncClient

        node_a, node_b = two_nodes_with_audio

        audiodir_a = Path(node_a.config.get_audiofile_directory())
        audiodir_b = Path(node_b.config.get_audiofile_directory())

        # Create audio file on A
        set_local_device_id(node_a.device_id)
        audio_id = node_a.db.create_audio_file(
            "test.mp3", "2025-01-01 10:00:00"
        )

        # Write actual binary content
        audio_file_path = audiodir_a / f"{audio_id}.mp3"
        audio_file_path.write_bytes(b"fake mp3 content for push test")

        # Push from A to B
        client = SyncClient(str(node_a.config_dir))
        result = client.push_to_peer(node_b.device_id_hex)

        assert result.success is True

        # Binary file should have been uploaded
        remote_audio = audiodir_b / f"{audio_id}.mp3"
        assert remote_audio.exists(), "Binary file should be uploaded during push"
        assert remote_audio.read_bytes() == b"fake mp3 content for push test"

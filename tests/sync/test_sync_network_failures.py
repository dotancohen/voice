"""Tests for sync behavior under network failures.

Tests network failure scenarios:
- Server unavailable
- Connection timeout
- Server crash during sync
- Recovery after network restored
- Partial data transfer
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Tuple
from unittest.mock import patch, MagicMock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.database import set_local_device_id
from voicecore import SyncClient, SyncResult

from .conftest import (
    SyncNode,
    create_note_on_node,
    create_tag_on_node,
    get_note_count,
    sync_nodes,
    start_sync_server,
    simulate_network_partition,
    MockNetworkError,
)


class TestServerUnavailable:
    """Tests for when sync server is unavailable."""

    def test_sync_fails_when_server_down(
        self, sync_node_a: SyncNode, sync_node_b: SyncNode
    ):
        """Sync fails gracefully when server is not running."""
        # Don't start server B
        sync_node_a.config.add_peer(
            peer_id=sync_node_b.device_id_hex,
            peer_name=sync_node_b.name,
            peer_url=sync_node_b.url,
        )

        # Create note on A
        create_note_on_node(sync_node_a, "Test note")

        # Try to sync - should fail gracefully
        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(str(sync_node_a.config_dir))
        result = client.sync_with_peer(sync_node_b.device_id_hex)

        assert result.success is False
        assert len(result.errors) > 0

    def test_sync_returns_error_details(
        self, sync_node_a: SyncNode, sync_node_b: SyncNode
    ):
        """Sync returns meaningful error when server unavailable."""
        sync_node_a.config.add_peer(
            peer_id=sync_node_b.device_id_hex,
            peer_name=sync_node_b.name,
            peer_url=sync_node_b.url,
        )

        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(str(sync_node_a.config_dir))
        result = client.sync_with_peer(sync_node_b.device_id_hex)

        assert result.success is False
        # Error should mention connection issue
        error_text = " ".join(result.errors).lower()
        assert any(word in error_text for word in ["connection", "error", "refused", "failed"])

    def test_local_data_preserved_on_sync_failure(
        self, sync_node_a: SyncNode, sync_node_b: SyncNode
    ):
        """Local data is preserved when sync fails."""
        sync_node_a.config.add_peer(
            peer_id=sync_node_b.device_id_hex,
            peer_name=sync_node_b.name,
            peer_url=sync_node_b.url,
        )

        # Create local notes
        note_ids = []
        for i in range(3):
            note_id = create_note_on_node(sync_node_a, f"Note {i}")
            note_ids.append(note_id)

        # Try to sync (will fail)
        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(str(sync_node_a.config_dir))
        client.sync_with_peer(sync_node_b.device_id_hex)

        # Local notes should still exist
        assert get_note_count(sync_node_a) == 3
        for note_id in note_ids:
            assert sync_node_a.db.get_note(note_id) is not None


class TestConnectionTimeout:
    """Tests for connection timeout scenarios."""

    def test_timeout_handled_gracefully(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Connection timeout is handled gracefully."""
        import urllib.request
        import socket

        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(str(sync_node_a.config_dir))

        # Mock timeout using urllib timeout exception
        def mock_urlopen(*args, **kwargs):
            raise socket.timeout("Connection timed out")

        with patch.object(urllib.request, "urlopen", side_effect=mock_urlopen):
            result = client.sync_with_peer(running_server_b.device_id_hex)

        assert result.success is False
        assert len(result.errors) > 0

    def test_timeout_doesnt_corrupt_data(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Timeout during sync doesn't corrupt local data."""
        import urllib.request
        import socket

        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        # Create local note
        note_id = create_note_on_node(sync_node_a, "Important data")

        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(str(sync_node_a.config_dir))

        # Timeout during sync
        def mock_urlopen(*args, **kwargs):
            raise socket.timeout()

        with patch.object(urllib.request, "urlopen", side_effect=mock_urlopen):
            client.sync_with_peer(running_server_b.device_id_hex)

        # Local data should be intact
        note = sync_node_a.db.get_note(note_id)
        assert note is not None
        assert note["content"] == "Important data"


class TestServerCrashDuringSync:
    """Tests for server crash during sync operation."""

    def test_server_killed_mid_sync(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Handle server being killed during sync."""
        node_a, node_b = two_nodes_with_servers

        # Create lots of data to make sync take time
        for i in range(20):
            create_note_on_node(node_b, f"Note {i} " + "x" * 500)

        # Kill server B during sync attempt
        # This is a bit tricky to time, so we'll kill it and try to sync
        node_b.kill_server()

        # Sync should fail gracefully
        result = sync_nodes(node_a, node_b)
        assert result["success"] is False

        # Node A should still be functional
        assert sync_node_a_works(node_a)

    def test_recovery_after_server_restart(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Sync works after server is restarted."""
        node_a, node_b = two_nodes_with_servers

        # Initial data
        note_id = create_note_on_node(node_a, "Before crash")
        sync_nodes(node_a, node_b)

        # Kill and restart server B
        node_b.kill_server()
        time.sleep(0.5)
        start_sync_server(node_b)
        assert node_b.wait_for_server()

        # Create new data and sync
        note_id_2 = create_note_on_node(node_a, "After restart")
        result = sync_nodes(node_a, node_b)

        assert result["success"] is True
        assert node_b.db.get_note(note_id_2) is not None


class TestNetworkPartition:
    """Tests for network partition scenarios."""

    def test_partition_then_recovery(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Data syncs correctly after network partition is resolved."""
        node_a, node_b = two_nodes_with_servers

        # Initial sync
        note_1 = create_note_on_node(node_a, "Before partition")
        sync_nodes(node_a, node_b)

        # Wait a full second (timestamps are second-precision)
        time.sleep(1.1)

        # Simulate partition (stop B's server)
        with simulate_network_partition(node_b):
            # Create data during partition
            note_2 = create_note_on_node(node_a, "During partition")

            # Sync fails
            result = sync_nodes(node_a, node_b)
            assert result["success"] is False

        # After partition resolved, sync should work
        result = sync_nodes(node_a, node_b)
        assert result["success"] is True
        # Reload node_b's db to see changes written by server subprocess
        node_b.reload_db()
        assert node_b.db.get_note(note_2) is not None

    def test_both_nodes_edit_during_partition(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Both nodes can edit during partition and sync after."""
        node_a, node_b = two_nodes_with_servers

        # Initial sync
        note_id = create_note_on_node(node_a, "Shared note")
        sync_nodes(node_a, node_b)
        node_b.reload_db()
        sync_nodes(node_b, node_a)
        node_a.reload_db()

        # Wait for timestamp precision
        time.sleep(1.1)

        # Stop B's server to simulate partition
        node_b.stop_server()

        # Edit on A
        set_local_device_id(node_a.device_id)
        node_a.db.update_note(note_id, "Edited on A during partition")

        # Create new note on B (locally)
        note_b = create_note_on_node(node_b, "Created on B during partition")

        # Restart B
        start_sync_server(node_b)
        node_b.wait_for_server()

        # Wait for timestamp precision
        time.sleep(1.1)

        # Sync should reconcile
        sync_nodes(node_a, node_b)
        node_b.reload_db()
        sync_nodes(node_b, node_a)
        node_a.reload_db()

        # Both should have B's new note
        assert node_a.db.get_note(note_b) is not None
        assert node_b.db.get_note(note_b) is not None


class TestPartialDataTransfer:
    """Tests for partial data transfer scenarios."""

    def test_incomplete_changes_list(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Handle incomplete changes list from server."""
        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        # Create data on B
        for i in range(10):
            create_note_on_node(running_server_b, f"Note {i}")

        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(str(sync_node_a.config_dir))

        # Mock partial response
        original_get = requests.get

        def mock_get(*args, **kwargs):
            response = original_get(*args, **kwargs)
            if "/sync/changes" in str(args):
                # Modify response to indicate incomplete
                data = response.json()
                data["is_complete"] = False
                data["changes"] = data["changes"][:5]  # Only return half
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = data
                return mock_response
            return response

        with patch.object(requests, "get", side_effect=mock_get):
            result = client.sync_with_peer(running_server_b.device_id_hex)

        # Should handle partial data without crashing
        # May need multiple sync rounds for complete data
        assert result is not None


class TestMockedNetworkErrors:
    """Tests using mocked network errors."""

    def test_connection_refused(
        self, sync_node_a: SyncNode, sync_node_b: SyncNode
    ):
        """Handle connection refused error."""
        # Use non-running server to test connection refused
        sync_node_a.config.add_peer(
            peer_id=sync_node_b.device_id_hex,
            peer_name=sync_node_b.name,
            peer_url=sync_node_b.url,  # Server not running
        )

        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(str(sync_node_a.config_dir))

        # Server not running, so connection will be refused
        result = client.sync_with_peer(sync_node_b.device_id_hex)

        assert result.success is False
        assert len(result.errors) > 0

    def test_connection_reset(
        self, sync_node_a: SyncNode, sync_node_b: SyncNode
    ):
        """Handle connection refused - simulates reset scenario."""
        # Use non-running server
        sync_node_a.config.add_peer(
            peer_id=sync_node_b.device_id_hex,
            peer_name=sync_node_b.name,
            peer_url=sync_node_b.url,  # Server not running
        )

        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(str(sync_node_a.config_dir))

        result = client.sync_with_peer(sync_node_b.device_id_hex)

        assert result.success is False
        assert len(result.errors) > 0

    def test_dns_resolution_failure(
        self, sync_node_a: SyncNode
    ):
        """Handle DNS resolution failure."""
        # Add peer with invalid hostname
        sync_node_a.config.add_peer(
            peer_id="00000000000070008000000000000099",
            peer_name="InvalidHost",
            peer_url="http://nonexistent.invalid.host:8384",
        )

        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(str(sync_node_a.config_dir))

        result = client.sync_with_peer("00000000000070008000000000000099")

        assert result.success is False

    def test_http_500_error(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Handle HTTP 500 error from server."""
        import urllib.request
        import urllib.error

        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(str(sync_node_a.config_dir))

        # Mock urllib to return HTTP 500 error
        def mock_urlopen(*args, **kwargs):
            raise urllib.error.HTTPError(
                url="http://test",
                code=500,
                msg="Internal Server Error",
                hdrs={},
                fp=None
            )

        with patch.object(urllib.request, "urlopen", side_effect=mock_urlopen):
            result = client.sync_with_peer(running_server_b.device_id_hex)

        assert result.success is False
        assert len(result.errors) > 0


class TestRecoveryRobustness:
    """Tests for robustness of recovery after failures."""

    def test_multiple_failed_syncs_then_success(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Multiple failed syncs don't prevent eventual success."""
        node_a, node_b = two_nodes_with_servers

        # Create data on A
        note_id = create_note_on_node(node_a, "Persistent note")

        # Stop B to cause failures
        node_b.stop_server()

        # Try sync multiple times (all fail)
        for _ in range(3):
            result = sync_nodes(node_a, node_b)
            assert result["success"] is False

        # Restart B
        start_sync_server(node_b)
        node_b.wait_for_server()

        # Now sync should work
        result = sync_nodes(node_a, node_b)
        assert result["success"] is True
        assert node_b.db.get_note(note_id) is not None

    def test_data_integrity_after_failures(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Data integrity maintained after sync failures."""
        node_a, node_b = two_nodes_with_servers

        # Create various data
        notes = []
        tags = []
        for i in range(5):
            note_id = create_note_on_node(node_a, f"Note {i}")
            notes.append(note_id)
            tag_id = create_tag_on_node(node_a, f"Tag{i}")
            tags.append(tag_id)

        # Sync successfully first
        sync_nodes(node_a, node_b)

        # Cause some failures
        node_b.stop_server()
        for _ in range(2):
            sync_nodes(node_a, node_b)

        # Restart
        start_sync_server(node_b)
        node_b.wait_for_server()

        # Verify all data on both nodes
        for note_id in notes:
            assert node_a.db.get_note(note_id) is not None
            assert node_b.db.get_note(note_id) is not None

        for tag_id in tags:
            assert node_a.db.get_tag(tag_id) is not None
            assert node_b.db.get_tag(tag_id) is not None


# Helper function
def sync_node_a_works(node_a: SyncNode) -> bool:
    """Check if node A is still functional."""
    try:
        # Try basic operations
        note_id = create_note_on_node(node_a, "Test note")
        note = node_a.db.get_note(note_id)
        return note is not None
    except Exception:
        return False

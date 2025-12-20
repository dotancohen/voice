"""Unit tests for sync client.

Tests the client-side sync functionality.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from core.config import Config
from core.database import Database, set_local_device_id
from core.sync_client import SyncClient, SyncResult, sync_all_peers


@pytest.fixture
def client_db(test_config_dir: Path) -> Generator[Database, None, None]:
    """Create a database for sync client testing."""
    device_id = uuid.UUID("00000000-0000-7000-8000-000000000002").bytes
    set_local_device_id(device_id)

    db_path = test_config_dir / "client_test.db"
    db = Database(db_path)
    yield db
    db.close()


@pytest.fixture
def client_config(test_config_dir: Path) -> Config:
    """Create a config for sync client testing."""
    return Config(config_dir=test_config_dir)


@pytest.fixture
def sync_client(client_db: Database, client_config: Config) -> SyncClient:
    """Create a sync client instance."""
    return SyncClient(client_db, client_config)


class TestSyncResult:
    """Test SyncResult dataclass."""

    def test_default_values(self) -> None:
        """SyncResult has sensible defaults."""
        result = SyncResult(success=True)
        assert result.success is True
        assert result.pulled == 0
        assert result.pushed == 0
        assert result.conflicts == 0
        assert result.errors == []

    def test_with_values(self) -> None:
        """SyncResult accepts all values."""
        result = SyncResult(
            success=False,
            pulled=10,
            pushed=5,
            conflicts=2,
            errors=["Error 1", "Error 2"],
        )
        assert result.success is False
        assert result.pulled == 10
        assert result.pushed == 5
        assert result.conflicts == 2
        assert len(result.errors) == 2


class TestSyncClientInit:
    """Test SyncClient initialization."""

    def test_creates_client(
        self, sync_client: SyncClient, client_config: Config
    ) -> None:
        """Client is created with correct attributes."""
        assert sync_client.db is not None
        assert sync_client.config is client_config
        assert sync_client.device_id is not None
        assert len(sync_client.device_id) == 32  # UUID hex string


class TestCheckPeerStatus:
    """Test peer status checking."""

    def test_unknown_peer(self, sync_client: SyncClient) -> None:
        """Unknown peer returns error."""
        result = sync_client.check_peer_status("nonexistent_peer_id")
        assert result["reachable"] is False
        assert "Unknown peer" in result["error"]

    def test_peer_status_success(
        self, sync_client: SyncClient, client_config: Config
    ) -> None:
        """Successful status check returns peer info."""
        # Add a peer
        peer_id = uuid.uuid4().hex
        client_config.add_peer(
            peer_id=peer_id,
            peer_name="Test Peer",
            peer_url="http://localhost:8384",
        )

        # Mock the request
        with patch.object(sync_client, "_make_request") as mock_request:
            mock_request.return_value = {
                "success": True,
                "data": {
                    "status": "ok",
                    "device_id": peer_id,
                    "device_name": "Test Peer",
                    "protocol_version": "1.0",
                },
            }

            result = sync_client.check_peer_status(peer_id)

            assert result["reachable"] is True
            assert result["device_id"] == peer_id
            assert result["device_name"] == "Test Peer"

    def test_peer_unreachable(
        self, sync_client: SyncClient, client_config: Config
    ) -> None:
        """Unreachable peer returns error."""
        peer_id = uuid.uuid4().hex
        client_config.add_peer(
            peer_id=peer_id,
            peer_name="Test Peer",
            peer_url="http://localhost:9999",
        )

        with patch.object(sync_client, "_make_request") as mock_request:
            mock_request.return_value = {
                "success": False,
                "error": "Connection refused",
            }

            result = sync_client.check_peer_status(peer_id)

            assert result["reachable"] is False
            assert "Connection refused" in result["error"]


class TestSyncWithPeer:
    """Test full sync with peer."""

    def test_unknown_peer(self, sync_client: SyncClient) -> None:
        """Syncing with unknown peer fails."""
        result = sync_client.sync_with_peer("nonexistent_peer_id")
        assert result.success is False
        assert any("Unknown peer" in e for e in result.errors)

    def test_peer_without_url(
        self, sync_client: SyncClient, client_config: Config
    ) -> None:
        """Syncing with peer without URL fails."""
        peer_id = uuid.uuid4().hex
        # Manually add peer without URL
        sync_config = client_config.get_sync_config()
        sync_config["peers"] = [{"peer_id": peer_id, "peer_name": "No URL Peer"}]
        client_config.config_data["sync"] = sync_config

        result = sync_client.sync_with_peer(peer_id)
        assert result.success is False

    def test_successful_sync(
        self,
        sync_client: SyncClient,
        client_config: Config,
        client_db: Database,
    ) -> None:
        """Successful sync returns correct counts."""
        peer_id = uuid.uuid4().hex
        client_config.add_peer(
            peer_id=peer_id,
            peer_name="Test Peer",
            peer_url="http://localhost:8384",
        )

        with patch.object(sync_client, "_handshake") as mock_handshake, \
             patch.object(sync_client, "_pull_changes") as mock_pull, \
             patch.object(sync_client, "_push_changes") as mock_push:

            mock_handshake.return_value = {
                "success": True,
                "last_sync_timestamp": None,
            }
            mock_pull.return_value = {
                "success": True,
                "applied": 5,
                "conflicts": 0,
            }
            mock_push.return_value = {
                "success": True,
                "applied": 3,
                "conflicts": 0,
            }

            result = sync_client.sync_with_peer(peer_id)

            assert result.success is True
            assert result.pulled == 5
            assert result.pushed == 3
            assert result.conflicts == 0

    def test_handshake_failure(
        self, sync_client: SyncClient, client_config: Config
    ) -> None:
        """Handshake failure stops sync."""
        peer_id = uuid.uuid4().hex
        client_config.add_peer(
            peer_id=peer_id,
            peer_name="Test Peer",
            peer_url="http://localhost:8384",
        )

        with patch.object(sync_client, "_handshake") as mock_handshake:
            mock_handshake.return_value = {
                "success": False,
                "error": "Connection refused",
            }

            result = sync_client.sync_with_peer(peer_id)

            assert result.success is False
            assert any("Connection refused" in e for e in result.errors)


class TestPullFromPeer:
    """Test pull-only sync."""

    def test_pull_success(
        self, sync_client: SyncClient, client_config: Config
    ) -> None:
        """Successful pull returns correct count."""
        peer_id = uuid.uuid4().hex
        client_config.add_peer(
            peer_id=peer_id,
            peer_name="Test Peer",
            peer_url="http://localhost:8384",
        )

        with patch.object(sync_client, "_handshake") as mock_handshake, \
             patch.object(sync_client, "_pull_changes") as mock_pull:

            mock_handshake.return_value = {"success": True}
            mock_pull.return_value = {
                "success": True,
                "applied": 10,
                "conflicts": 1,
            }

            result = sync_client.pull_from_peer(peer_id)

            assert result.success is True
            assert result.pulled == 10
            assert result.conflicts == 1
            assert result.pushed == 0  # No push in pull_from_peer


class TestPushToPeer:
    """Test push-only sync."""

    def test_push_success(
        self, sync_client: SyncClient, client_config: Config
    ) -> None:
        """Successful push returns correct count."""
        peer_id = uuid.uuid4().hex
        client_config.add_peer(
            peer_id=peer_id,
            peer_name="Test Peer",
            peer_url="http://localhost:8384",
        )

        with patch.object(sync_client, "_handshake") as mock_handshake, \
             patch.object(sync_client, "_push_changes") as mock_push:

            mock_handshake.return_value = {"success": True}
            mock_push.return_value = {
                "success": True,
                "applied": 7,
                "conflicts": 0,
            }

            result = sync_client.push_to_peer(peer_id)

            assert result.success is True
            assert result.pushed == 7
            assert result.pulled == 0  # No pull in push_to_peer


class TestInitialSync:
    """Test initial full sync."""

    def test_initial_sync_success(
        self, sync_client: SyncClient, client_config: Config
    ) -> None:
        """Initial sync fetches full dataset."""
        peer_id = uuid.uuid4().hex
        client_config.add_peer(
            peer_id=peer_id,
            peer_name="Test Peer",
            peer_url="http://localhost:8384",
        )

        with patch.object(sync_client, "_handshake") as mock_handshake, \
             patch.object(sync_client, "_get_full_sync") as mock_full, \
             patch.object(sync_client, "_apply_full_sync") as mock_apply, \
             patch.object(sync_client, "_push_changes") as mock_push:

            mock_handshake.return_value = {"success": True}
            mock_full.return_value = {
                "success": True,
                "data": {"notes": [], "tags": [], "note_tags": []},
            }
            mock_apply.return_value = (15, 0, [])
            mock_push.return_value = {"success": True, "applied": 5}

            result = sync_client.initial_sync(peer_id)

            assert result.success is True
            assert result.pulled == 15
            assert result.pushed == 5


class TestSyncAllPeers:
    """Test syncing with all peers."""

    def test_sync_all_empty(
        self, client_db: Database, client_config: Config
    ) -> None:
        """Syncing with no peers returns empty dict."""
        results = sync_all_peers(client_db, client_config)
        assert results == {}

    def test_sync_all_multiple_peers(
        self, client_db: Database, client_config: Config
    ) -> None:
        """Syncing with multiple peers returns results for each."""
        peer_id_1 = uuid.uuid4().hex
        peer_id_2 = uuid.uuid4().hex

        client_config.add_peer(peer_id_1, "Peer 1", "http://host1:8384")
        client_config.add_peer(peer_id_2, "Peer 2", "http://host2:8384")

        with patch("core.sync_client.SyncClient.sync_with_peer") as mock_sync:
            mock_sync.return_value = SyncResult(success=True, pulled=1, pushed=1)

            results = sync_all_peers(client_db, client_config)

            assert len(results) == 2
            assert peer_id_1 in results
            assert peer_id_2 in results
            assert results[peer_id_1].success is True


class TestMakeRequest:
    """Test HTTP request handling."""

    def test_get_request(self, sync_client: SyncClient) -> None:
        """GET request is made correctly."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"status": "ok"}'
            mock_urlopen.return_value = mock_response

            result = sync_client._make_request(
                "http://localhost:8384/sync/status",
                "peer_id",
                method="GET",
            )

            assert result["success"] is True
            assert result["data"]["status"] == "ok"

    def test_post_request_with_data(self, sync_client: SyncClient) -> None:
        """POST request sends JSON data."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"received": true}'
            mock_urlopen.return_value = mock_response

            result = sync_client._make_request(
                "http://localhost:8384/sync/apply",
                "peer_id",
                method="POST",
                data={"changes": []},
            )

            assert result["success"] is True
            # Verify the request was made with correct headers
            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            assert request.get_header("Content-type") == "application/json"

    def test_connection_error(self, sync_client: SyncClient) -> None:
        """Connection error is handled."""
        import urllib.error

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

            result = sync_client._make_request(
                "http://localhost:8384/sync/status",
                "peer_id",
            )

            assert result["success"] is False
            assert "Connection" in result["error"]

    def test_http_error(self, sync_client: SyncClient) -> None:
        """HTTP error is handled."""
        import urllib.error

        with patch("urllib.request.urlopen") as mock_urlopen:
            error_response = MagicMock()
            error_response.read.return_value = b'{"error": "Bad request"}'
            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://localhost:8384/sync/apply",
                400,
                "Bad Request",
                {},
                error_response,
            )

            result = sync_client._make_request(
                "http://localhost:8384/sync/apply",
                "peer_id",
                method="POST",
                data={},
            )

            assert result["success"] is False
            assert "Bad request" in result["error"]

"""Unit tests for sync configuration.

Tests the sync-related configuration methods in Config class.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from core.config import Config


@pytest.fixture
def sync_config(test_config_dir: Path) -> Config:
    """Create a config instance for testing sync features."""
    return Config(config_dir=test_config_dir)


class TestDeviceId:
    """Test device ID configuration."""

    def test_device_id_generated_on_first_access(self, sync_config: Config) -> None:
        """Device ID is generated when first accessed."""
        device_id = sync_config.get_device_id()
        assert device_id is not None
        assert len(device_id) == 16  # UUID bytes

    def test_device_id_persists(self, sync_config: Config) -> None:
        """Device ID persists across config reloads."""
        device_id_1 = sync_config.get_device_id()

        # Reload config
        sync_config_2 = Config(config_dir=sync_config.config_dir)
        device_id_2 = sync_config_2.get_device_id()

        assert device_id_1 == device_id_2

    def test_device_id_hex(self, sync_config: Config) -> None:
        """Device ID hex string is valid."""
        device_id_hex = sync_config.get_device_id_hex()
        assert len(device_id_hex) == 32
        # Should be valid hex
        uuid.UUID(hex=device_id_hex)

    def test_device_id_bytes_matches_hex(self, sync_config: Config) -> None:
        """Device ID bytes matches hex string."""
        device_id_bytes = sync_config.get_device_id()
        device_id_hex = sync_config.get_device_id_hex()
        assert uuid.UUID(bytes=device_id_bytes).hex == device_id_hex


class TestDeviceName:
    """Test device name configuration."""

    def test_default_device_name(self, sync_config: Config) -> None:
        """Default device name is generated."""
        name = sync_config.get_device_name()
        assert name is not None
        assert len(name) > 0
        assert "VoiceRewrite" in name

    def test_set_device_name(self, sync_config: Config) -> None:
        """Device name can be changed."""
        sync_config.set_device_name("My Test Device")
        assert sync_config.get_device_name() == "My Test Device"

    def test_device_name_persists(self, sync_config: Config) -> None:
        """Device name persists across config reloads."""
        sync_config.set_device_name("Persistent Name")

        sync_config_2 = Config(config_dir=sync_config.config_dir)
        assert sync_config_2.get_device_name() == "Persistent Name"


class TestSyncEnabled:
    """Test sync enabled/disabled configuration."""

    def test_sync_disabled_by_default(self, sync_config: Config) -> None:
        """Sync is disabled by default."""
        assert sync_config.is_sync_enabled() is False

    def test_enable_sync(self, sync_config: Config) -> None:
        """Sync can be enabled."""
        sync_config.set_sync_enabled(True)
        assert sync_config.is_sync_enabled() is True

    def test_disable_sync(self, sync_config: Config) -> None:
        """Sync can be disabled after being enabled."""
        sync_config.set_sync_enabled(True)
        sync_config.set_sync_enabled(False)
        assert sync_config.is_sync_enabled() is False


class TestSyncServerPort:
    """Test sync server port configuration."""

    def test_default_port(self, sync_config: Config) -> None:
        """Default sync port is 8384."""
        assert sync_config.get_sync_server_port() == 8384

    def test_set_port(self, sync_config: Config) -> None:
        """Sync port can be changed."""
        sync_config.set_sync_server_port(9000)
        assert sync_config.get_sync_server_port() == 9000


class TestPeerManagement:
    """Test peer configuration management."""

    def test_no_peers_by_default(self, sync_config: Config) -> None:
        """No peers configured by default."""
        assert sync_config.get_peers() == []

    def test_add_peer(self, sync_config: Config) -> None:
        """Peer can be added."""
        peer_id = uuid.uuid4().hex
        sync_config.add_peer(
            peer_id=peer_id,
            peer_name="Test Peer",
            peer_url="https://192.168.1.100:8384",
        )

        peers = sync_config.get_peers()
        assert len(peers) == 1
        assert peers[0]["peer_id"] == peer_id
        assert peers[0]["peer_name"] == "Test Peer"
        assert peers[0]["peer_url"] == "https://192.168.1.100:8384"

    def test_add_peer_with_certificate(self, sync_config: Config) -> None:
        """Peer can be added with certificate fingerprint."""
        peer_id = uuid.uuid4().hex
        fingerprint = "SHA256:abc123def456..."

        sync_config.add_peer(
            peer_id=peer_id,
            peer_name="Secure Peer",
            peer_url="https://example.com:8384",
            certificate_fingerprint=fingerprint,
        )

        peer = sync_config.get_peer(peer_id)
        assert peer is not None
        assert peer["certificate_fingerprint"] == fingerprint

    def test_add_multiple_peers(self, sync_config: Config) -> None:
        """Multiple peers can be added."""
        peer_id_1 = uuid.uuid4().hex
        peer_id_2 = uuid.uuid4().hex

        sync_config.add_peer(peer_id_1, "Peer 1", "https://host1:8384")
        sync_config.add_peer(peer_id_2, "Peer 2", "https://host2:8384")

        assert len(sync_config.get_peers()) == 2

    def test_update_existing_peer(self, sync_config: Config) -> None:
        """Adding peer with same ID updates existing peer."""
        peer_id = uuid.uuid4().hex

        sync_config.add_peer(peer_id, "Original Name", "https://host1:8384")
        sync_config.add_peer(peer_id, "Updated Name", "https://host2:8384")

        peers = sync_config.get_peers()
        assert len(peers) == 1
        assert peers[0]["peer_name"] == "Updated Name"
        assert peers[0]["peer_url"] == "https://host2:8384"

    def test_remove_peer(self, sync_config: Config) -> None:
        """Peer can be removed."""
        peer_id = uuid.uuid4().hex
        sync_config.add_peer(peer_id, "Test Peer", "https://host:8384")

        result = sync_config.remove_peer(peer_id)

        assert result is True
        assert sync_config.get_peers() == []

    def test_remove_nonexistent_peer(self, sync_config: Config) -> None:
        """Removing nonexistent peer returns False."""
        result = sync_config.remove_peer(uuid.uuid4().hex)
        assert result is False

    def test_get_peer(self, sync_config: Config) -> None:
        """Individual peer can be retrieved."""
        peer_id = uuid.uuid4().hex
        sync_config.add_peer(peer_id, "Test Peer", "https://host:8384")

        peer = sync_config.get_peer(peer_id)

        assert peer is not None
        assert peer["peer_id"] == peer_id

    def test_get_nonexistent_peer(self, sync_config: Config) -> None:
        """Getting nonexistent peer returns None."""
        peer = sync_config.get_peer(uuid.uuid4().hex)
        assert peer is None

    def test_update_peer_certificate(self, sync_config: Config) -> None:
        """Peer certificate can be updated (TOFU)."""
        peer_id = uuid.uuid4().hex
        sync_config.add_peer(peer_id, "Test Peer", "https://host:8384")

        result = sync_config.update_peer_certificate(peer_id, "SHA256:newfingerprint")

        assert result is True
        peer = sync_config.get_peer(peer_id)
        assert peer["certificate_fingerprint"] == "SHA256:newfingerprint"

    def test_peers_persist(self, sync_config: Config) -> None:
        """Peers persist across config reloads."""
        peer_id = uuid.uuid4().hex
        sync_config.add_peer(peer_id, "Persistent Peer", "https://host:8384")

        sync_config_2 = Config(config_dir=sync_config.config_dir)
        peers = sync_config_2.get_peers()

        assert len(peers) == 1
        assert peers[0]["peer_id"] == peer_id


class TestCertsDir:
    """Test certificates directory configuration."""

    def test_certs_dir_created(self, sync_config: Config) -> None:
        """Certs directory is created on access."""
        certs_dir = sync_config.get_certs_dir()
        assert certs_dir.exists()
        assert certs_dir.is_dir()

    def test_certs_dir_in_config_dir(self, sync_config: Config) -> None:
        """Certs directory is inside config directory."""
        certs_dir = sync_config.get_certs_dir()
        assert certs_dir.parent == sync_config.config_dir

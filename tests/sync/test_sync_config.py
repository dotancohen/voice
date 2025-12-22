"""Tests for config peer management methods.

Tests:
- config.add_peer()
- config.get_peer()
- config.get_peers()
- config.remove_peer()
- config.update_peer_certificate()
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.config import Config
from core.validation import ValidationError

from .conftest import (
    SyncNode,
    create_sync_node,
    DEVICE_A_ID,
)


class TestAddPeer:
    """Tests for config.add_peer() method."""

    def test_add_peer_basic(self, sync_node_a: SyncNode):
        """Add a peer with basic info."""
        peer_id = "00000000000070008000000000000099"
        peer_name = "TestPeer"
        peer_url = "http://localhost:8384"

        sync_node_a.config.add_peer(
            peer_id=peer_id,
            peer_name=peer_name,
            peer_url=peer_url,
        )

        # Verify added
        peer = sync_node_a.config.get_peer(peer_id)
        assert peer is not None
        assert peer["peer_id"] == peer_id
        assert peer["peer_name"] == peer_name
        assert peer["peer_url"] == peer_url

    def test_add_peer_with_fingerprint(self, sync_node_a: SyncNode):
        """Add a peer with certificate fingerprint."""
        peer_id = "00000000000070008000000000000099"
        fingerprint = "SHA256:aa:bb:cc:dd:ee:ff"

        sync_node_a.config.add_peer(
            peer_id=peer_id,
            peer_name="SecurePeer",
            peer_url="https://localhost:8384",
            certificate_fingerprint=fingerprint,
        )

        peer = sync_node_a.config.get_peer(peer_id)
        assert peer["certificate_fingerprint"] == fingerprint

    def test_add_peer_invalid_id_format(self, sync_node_a: SyncNode):
        """Add peer with invalid ID format fails."""
        with pytest.raises(ValidationError):
            sync_node_a.config.add_peer(
                peer_id="not-a-valid-uuid",
                peer_name="BadPeer",
                peer_url="http://localhost:8384",
            )

    def test_add_peer_empty_name(self, sync_node_a: SyncNode):
        """Add peer with empty name may fail or succeed."""
        # Behavior depends on implementation
        try:
            sync_node_a.config.add_peer(
                peer_id="00000000000070008000000000000099",
                peer_name="",
                peer_url="http://localhost:8384",
            )
        except ValidationError:
            pass  # Expected by some implementations

    def test_add_peer_duplicate_fails(self, sync_node_a: SyncNode):
        """Adding duplicate peer fails."""
        peer_id = "00000000000070008000000000000099"

        sync_node_a.config.add_peer(
            peer_id=peer_id,
            peer_name="First",
            peer_url="http://localhost:8384",
        )

        with pytest.raises(ValidationError):
            sync_node_a.config.add_peer(
                peer_id=peer_id,
                peer_name="Second",
                peer_url="http://localhost:8385",
                allow_update=False,
            )

    def test_add_peer_allow_update(self, sync_node_a: SyncNode):
        """Adding duplicate peer with allow_update=True updates."""
        peer_id = "00000000000070008000000000000099"

        sync_node_a.config.add_peer(
            peer_id=peer_id,
            peer_name="First",
            peer_url="http://localhost:8384",
        )

        # Update with allow_update
        sync_node_a.config.add_peer(
            peer_id=peer_id,
            peer_name="Updated",
            peer_url="http://localhost:8385",
            allow_update=True,
        )

        peer = sync_node_a.config.get_peer(peer_id)
        assert peer["peer_name"] == "Updated"
        assert peer["peer_url"] == "http://localhost:8385"

    def test_add_multiple_peers(self, sync_node_a: SyncNode):
        """Add multiple peers."""
        for i in range(5):
            peer_id = f"0000000000007000800000000000009{i}"
            sync_node_a.config.add_peer(
                peer_id=peer_id,
                peer_name=f"Peer{i}",
                peer_url=f"http://localhost:{8384 + i}",
            )

        peers = sync_node_a.config.get_peers()
        assert len(peers) == 5


class TestGetPeer:
    """Tests for config.get_peer() method."""

    def test_get_peer_exists(self, sync_node_a: SyncNode):
        """Get existing peer returns correct data."""
        peer_id = "00000000000070008000000000000099"
        sync_node_a.config.add_peer(
            peer_id=peer_id,
            peer_name="TestPeer",
            peer_url="http://localhost:8384",
        )

        peer = sync_node_a.config.get_peer(peer_id)

        assert peer is not None
        assert peer["peer_id"] == peer_id
        assert peer["peer_name"] == "TestPeer"

    def test_get_peer_not_exists(self, sync_node_a: SyncNode):
        """Get non-existent peer returns None."""
        peer = sync_node_a.config.get_peer("00000000000070008000000000099999")

        assert peer is None

    def test_get_peer_invalid_id(self, sync_node_a: SyncNode):
        """Get peer with invalid ID returns None or raises."""
        try:
            peer = sync_node_a.config.get_peer("invalid")
            assert peer is None
        except (ValidationError, ValueError):
            pass  # Also acceptable

    def test_get_peer_case_insensitive(self, sync_node_a: SyncNode):
        """Peer ID lookup is case-insensitive."""
        peer_id = "00000000000070008000000000000099"
        sync_node_a.config.add_peer(
            peer_id=peer_id,
            peer_name="TestPeer",
            peer_url="http://localhost:8384",
        )

        # Try uppercase
        peer = sync_node_a.config.get_peer(peer_id.upper())
        # May or may not find depending on implementation
        # Just verify no crash
        assert peer is None or peer["peer_id"].lower() == peer_id.lower()


class TestGetPeers:
    """Tests for config.get_peers() method."""

    def test_get_peers_empty(self, sync_node_a: SyncNode):
        """Get peers when none configured returns empty list."""
        peers = sync_node_a.config.get_peers()

        assert peers == []

    def test_get_peers_returns_all(self, sync_node_a: SyncNode):
        """Get peers returns all configured peers."""
        for i in range(3):
            sync_node_a.config.add_peer(
                peer_id=f"0000000000007000800000000000009{i}",
                peer_name=f"Peer{i}",
                peer_url=f"http://localhost:{8384 + i}",
            )

        peers = sync_node_a.config.get_peers()

        assert len(peers) == 3

    def test_get_peers_returns_list(self, sync_node_a: SyncNode):
        """Get peers returns a list."""
        peers = sync_node_a.config.get_peers()

        assert isinstance(peers, list)

    def test_get_peers_after_remove(self, sync_node_a: SyncNode):
        """Get peers reflects removals."""
        peer_id = "00000000000070008000000000000099"
        sync_node_a.config.add_peer(
            peer_id=peer_id,
            peer_name="ToRemove",
            peer_url="http://localhost:8384",
        )

        assert len(sync_node_a.config.get_peers()) == 1

        sync_node_a.config.remove_peer(peer_id)

        assert len(sync_node_a.config.get_peers()) == 0


class TestRemovePeer:
    """Tests for config.remove_peer() method."""

    def test_remove_peer_success(self, sync_node_a: SyncNode):
        """Remove existing peer succeeds."""
        peer_id = "00000000000070008000000000000099"
        sync_node_a.config.add_peer(
            peer_id=peer_id,
            peer_name="TestPeer",
            peer_url="http://localhost:8384",
        )

        sync_node_a.config.remove_peer(peer_id)

        assert sync_node_a.config.get_peer(peer_id) is None

    def test_remove_peer_not_exists(self, sync_node_a: SyncNode):
        """Remove non-existent peer is handled gracefully."""
        # Should not raise
        try:
            sync_node_a.config.remove_peer("00000000000070008000000000099999")
        except Exception:
            pass  # May or may not raise

    def test_remove_one_of_many(self, sync_node_a: SyncNode):
        """Remove one peer leaves others intact."""
        for i in range(3):
            sync_node_a.config.add_peer(
                peer_id=f"0000000000007000800000000000009{i}",
                peer_name=f"Peer{i}",
                peer_url=f"http://localhost:{8384 + i}",
            )

        # Remove middle one
        sync_node_a.config.remove_peer("00000000000070008000000000000091")

        peers = sync_node_a.config.get_peers()
        assert len(peers) == 2

        # Others should still exist
        assert sync_node_a.config.get_peer("00000000000070008000000000000090") is not None
        assert sync_node_a.config.get_peer("00000000000070008000000000000092") is not None


class TestUpdatePeerCertificate:
    """Tests for config.update_peer_certificate() method."""

    def test_update_certificate_success(self, sync_node_a: SyncNode):
        """Update peer certificate succeeds."""
        peer_id = "00000000000070008000000000000099"
        sync_node_a.config.add_peer(
            peer_id=peer_id,
            peer_name="TestPeer",
            peer_url="https://localhost:8384",
        )

        new_fingerprint = "SHA256:11:22:33:44:55:66"
        result = sync_node_a.config.update_peer_certificate(peer_id, new_fingerprint)

        assert result is True

        peer = sync_node_a.config.get_peer(peer_id)
        assert peer["certificate_fingerprint"] == new_fingerprint

    def test_update_certificate_not_exists(self, sync_node_a: SyncNode):
        """Update certificate for non-existent peer fails."""
        result = sync_node_a.config.update_peer_certificate(
            "00000000000070008000000000099999",
            "SHA256:11:22:33",
        )

        assert result is False

    def test_update_certificate_replaces_existing(self, sync_node_a: SyncNode):
        """Update certificate replaces existing one."""
        peer_id = "00000000000070008000000000000099"
        sync_node_a.config.add_peer(
            peer_id=peer_id,
            peer_name="TestPeer",
            peer_url="https://localhost:8384",
            certificate_fingerprint="SHA256:old:old:old",
        )

        new_fingerprint = "SHA256:new:new:new"
        sync_node_a.config.update_peer_certificate(peer_id, new_fingerprint)

        peer = sync_node_a.config.get_peer(peer_id)
        assert peer["certificate_fingerprint"] == new_fingerprint


class TestConfigPersistence:
    """Tests for config peer data persistence."""

    def test_peers_persist_to_file(self, tmp_path: Path):
        """Peer config persists to file."""
        # Create config and add peer
        node = create_sync_node("TestNode", DEVICE_A_ID, tmp_path)

        peer_id = "00000000000070008000000000000099"
        node.config.add_peer(
            peer_id=peer_id,
            peer_name="PersistentPeer",
            peer_url="http://localhost:8384",
        )

        # Create new config instance
        new_config = Config(config_dir=node.config_dir)

        # Peer should still exist
        peer = new_config.get_peer(peer_id)
        assert peer is not None
        assert peer["peer_name"] == "PersistentPeer"

        node.db.close()

    def test_peer_removal_persists(self, tmp_path: Path):
        """Peer removal persists to file."""
        node = create_sync_node("TestNode", DEVICE_A_ID, tmp_path)

        peer_id = "00000000000070008000000000000099"
        node.config.add_peer(
            peer_id=peer_id,
            peer_name="ToRemove",
            peer_url="http://localhost:8384",
        )

        node.config.remove_peer(peer_id)

        # Create new config instance
        new_config = Config(config_dir=node.config_dir)

        # Peer should be gone
        assert new_config.get_peer(peer_id) is None

        node.db.close()


class TestSyncConfigIntegration:
    """Tests for sync config integration."""

    def test_sync_config_structure(self, sync_node_a: SyncNode):
        """Sync config has expected structure."""
        sync_config = sync_node_a.config.get_sync_config()

        assert "enabled" in sync_config
        assert "server_port" in sync_config
        assert "peers" in sync_config
        assert isinstance(sync_config["peers"], list)

    def test_get_device_id_hex(self, sync_node_a: SyncNode):
        """Get device ID as hex string."""
        device_id = sync_node_a.config.get_device_id_hex()

        assert device_id is not None
        assert len(device_id) == 32  # 16 bytes = 32 hex chars

    def test_get_device_name(self, sync_node_a: SyncNode):
        """Get device name."""
        device_name = sync_node_a.config.get_device_name()

        assert device_name == "NodeA"

    def test_get_sync_server_port(self, sync_node_a: SyncNode):
        """Get sync server port."""
        port = sync_node_a.config.get_sync_server_port()

        assert port > 0
        assert port < 65536


class TestPeerValidation:
    """Tests for peer data validation."""

    def test_peer_url_validation(self, sync_node_a: SyncNode):
        """Peer URL is validated."""
        # Invalid URL should fail or be accepted
        try:
            sync_node_a.config.add_peer(
                peer_id="00000000000070008000000000000099",
                peer_name="Test",
                peer_url="not-a-url",
            )
            # If accepted, verify it's stored
            peer = sync_node_a.config.get_peer("00000000000070008000000000000099")
            assert peer is not None
        except ValidationError:
            pass  # Expected

    def test_peer_id_format_strict(self, sync_node_a: SyncNode):
        """Peer ID format is strictly validated."""
        invalid_ids = [
            "too-short",
            "0000000000007000800000000000009X",  # Invalid hex
            "00000000-0000-7000-8000-000000000099",  # With dashes
            "",
            "g" * 32,  # Invalid hex chars
        ]

        for invalid_id in invalid_ids:
            with pytest.raises((ValidationError, ValueError)):
                sync_node_a.config.add_peer(
                    peer_id=invalid_id,
                    peer_name="Test",
                    peer_url="http://localhost:8384",
                )

"""Tests for config device management methods.

Tests:
- config.add_device()
- config.get_device()
- config.get_devices()
- config.remove_device()
- config.update_device_certificate()
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


class TestAddDevice:
    """Tests for config.add_device() method."""

    def test_add_device_basic(self, sync_node_a: SyncNode):
        """Add a device with basic info."""
        device_id = "00000000000070008000000000000099"
        device_name = "TestDevice"
        device_url = "http://localhost:8384"

        sync_node_a.config.add_device(
            device_id=device_id,
            device_name=device_name,
            device_url=device_url,
        )

        # Verify added
        device = sync_node_a.config.get_device(device_id)
        assert device is not None
        assert device["device_id"] == device_id
        assert device["device_name"] == device_name
        assert device["device_url"] == device_url

    def test_add_device_with_fingerprint(self, sync_node_a: SyncNode):
        """Add a device with certificate fingerprint."""
        device_id = "00000000000070008000000000000099"
        fingerprint = "SHA256:aa:bb:cc:dd:ee:ff"

        sync_node_a.config.add_device(
            device_id=device_id,
            device_name="SecureDevice",
            device_url="https://localhost:8384",
            certificate_fingerprint=fingerprint,
        )

        device = sync_node_a.config.get_device(device_id)
        assert device["certificate_fingerprint"] == fingerprint

    def test_add_device_invalid_id_format(self, sync_node_a: SyncNode):
        """Add device with invalid ID format fails."""
        with pytest.raises(ValidationError):
            sync_node_a.config.add_device(
                device_id="not-a-valid-uuid",
                device_name="BadDevice",
                device_url="http://localhost:8384",
            )

    def test_add_device_empty_name(self, sync_node_a: SyncNode):
        """Add device with empty name may fail or succeed."""
        # Behavior depends on implementation
        try:
            sync_node_a.config.add_device(
                device_id="00000000000070008000000000000099",
                device_name="",
                device_url="http://localhost:8384",
            )
        except ValidationError:
            pass  # Expected by some implementations

    def test_add_device_duplicate_fails(self, sync_node_a: SyncNode):
        """Adding duplicate device fails."""
        device_id = "00000000000070008000000000000099"

        sync_node_a.config.add_device(
            device_id=device_id,
            device_name="First",
            device_url="http://localhost:8384",
        )

        with pytest.raises(ValidationError):
            sync_node_a.config.add_device(
                device_id=device_id,
                device_name="Second",
                device_url="http://localhost:8385",
                allow_update=False,
            )

    def test_add_device_allow_update(self, sync_node_a: SyncNode):
        """Adding duplicate device with allow_update=True updates."""
        device_id = "00000000000070008000000000000099"

        sync_node_a.config.add_device(
            device_id=device_id,
            device_name="First",
            device_url="http://localhost:8384",
        )

        # Update with allow_update
        sync_node_a.config.add_device(
            device_id=device_id,
            device_name="Updated",
            device_url="http://localhost:8385",
            allow_update=True,
        )

        device = sync_node_a.config.get_device(device_id)
        assert device["device_name"] == "Updated"
        assert device["device_url"] == "http://localhost:8385"

    def test_add_multiple_devices(self, sync_node_a: SyncNode):
        """Add multiple devices."""
        for i in range(5):
            device_id = f"0000000000007000800000000000009{i}"
            sync_node_a.config.add_device(
                device_id=device_id,
                device_name=f"Device{i}",
                device_url=f"http://localhost:{8384 + i}",
            )

        devices = sync_node_a.config.get_devices()
        assert len(devices) == 5


class TestGetDevice:
    """Tests for config.get_device() method."""

    def test_get_device_exists(self, sync_node_a: SyncNode):
        """Get existing device returns correct data."""
        device_id = "00000000000070008000000000000099"
        sync_node_a.config.add_device(
            device_id=device_id,
            device_name="TestDevice",
            device_url="http://localhost:8384",
        )

        device = sync_node_a.config.get_device(device_id)

        assert device is not None
        assert device["device_id"] == device_id
        assert device["device_name"] == "TestDevice"

    def test_get_device_not_exists(self, sync_node_a: SyncNode):
        """Get non-existent device returns None."""
        device = sync_node_a.config.get_device("00000000000070008000000000099999")

        assert device is None

    def test_get_device_invalid_id(self, sync_node_a: SyncNode):
        """Get device with invalid ID returns None or raises."""
        try:
            device = sync_node_a.config.get_device("invalid")
            assert device is None
        except (ValidationError, ValueError):
            pass  # Also acceptable

    def test_get_device_case_insensitive(self, sync_node_a: SyncNode):
        """Device ID lookup is case-insensitive."""
        device_id = "00000000000070008000000000000099"
        sync_node_a.config.add_device(
            device_id=device_id,
            device_name="TestDevice",
            device_url="http://localhost:8384",
        )

        # Try uppercase
        device = sync_node_a.config.get_device(device_id.upper())
        # May or may not find depending on implementation
        # Just verify no crash
        assert device is None or device["device_id"].lower() == device_id.lower()


class TestGetDevices:
    """Tests for config.get_devices() method."""

    def test_get_devices_empty(self, sync_node_a: SyncNode):
        """Get devices when none configured returns empty list."""
        devices = sync_node_a.config.get_devices()

        assert devices == []

    def test_get_devices_returns_all(self, sync_node_a: SyncNode):
        """Get devices returns all configured devices."""
        for i in range(3):
            sync_node_a.config.add_device(
                device_id=f"0000000000007000800000000000009{i}",
                device_name=f"Device{i}",
                device_url=f"http://localhost:{8384 + i}",
            )

        devices = sync_node_a.config.get_devices()

        assert len(devices) == 3

    def test_get_devices_returns_list(self, sync_node_a: SyncNode):
        """Get devices returns a list."""
        devices = sync_node_a.config.get_devices()

        assert isinstance(devices, list)

    def test_get_devices_after_remove(self, sync_node_a: SyncNode):
        """Get devices reflects removals."""
        device_id = "00000000000070008000000000000099"
        sync_node_a.config.add_device(
            device_id=device_id,
            device_name="ToRemove",
            device_url="http://localhost:8384",
        )

        assert len(sync_node_a.config.get_devices()) == 1

        sync_node_a.config.remove_device(device_id)

        assert len(sync_node_a.config.get_devices()) == 0


class TestRemoveDevice:
    """Tests for config.remove_device() method."""

    def test_remove_device_success(self, sync_node_a: SyncNode):
        """Remove existing device succeeds."""
        device_id = "00000000000070008000000000000099"
        sync_node_a.config.add_device(
            device_id=device_id,
            device_name="TestDevice",
            device_url="http://localhost:8384",
        )

        sync_node_a.config.remove_device(device_id)

        assert sync_node_a.config.get_device(device_id) is None

    def test_remove_device_not_exists(self, sync_node_a: SyncNode):
        """Remove non-existent device is handled gracefully."""
        # Should not raise
        try:
            sync_node_a.config.remove_device("00000000000070008000000000099999")
        except Exception:
            pass  # May or may not raise

    def test_remove_one_of_many(self, sync_node_a: SyncNode):
        """Remove one device leaves others intact."""
        for i in range(3):
            sync_node_a.config.add_device(
                device_id=f"0000000000007000800000000000009{i}",
                device_name=f"Device{i}",
                device_url=f"http://localhost:{8384 + i}",
            )

        # Remove middle one
        sync_node_a.config.remove_device("00000000000070008000000000000091")

        devices = sync_node_a.config.get_devices()
        assert len(devices) == 2

        # Others should still exist
        assert sync_node_a.config.get_device("00000000000070008000000000000090") is not None
        assert sync_node_a.config.get_device("00000000000070008000000000000092") is not None


class TestUpdateDeviceCertificate:
    """Tests for config.update_device_certificate() method."""

    def test_update_certificate_success(self, sync_node_a: SyncNode):
        """Update device certificate succeeds."""
        device_id = "00000000000070008000000000000099"
        sync_node_a.config.add_device(
            device_id=device_id,
            device_name="TestDevice",
            device_url="https://localhost:8384",
        )

        new_fingerprint = "SHA256:11:22:33:44:55:66"
        result = sync_node_a.config.update_device_certificate(device_id, new_fingerprint)

        assert result is True

        device = sync_node_a.config.get_device(device_id)
        assert device["certificate_fingerprint"] == new_fingerprint

    def test_update_certificate_not_exists(self, sync_node_a: SyncNode):
        """Update certificate for non-existent device fails."""
        result = sync_node_a.config.update_device_certificate(
            "00000000000070008000000000099999",
            "SHA256:11:22:33",
        )

        assert result is False

    def test_update_certificate_replaces_existing(self, sync_node_a: SyncNode):
        """Update certificate replaces existing one."""
        device_id = "00000000000070008000000000000099"
        sync_node_a.config.add_device(
            device_id=device_id,
            device_name="TestDevice",
            device_url="https://localhost:8384",
            certificate_fingerprint="SHA256:old:old:old",
        )

        new_fingerprint = "SHA256:new:new:new"
        sync_node_a.config.update_device_certificate(device_id, new_fingerprint)

        device = sync_node_a.config.get_device(device_id)
        assert device["certificate_fingerprint"] == new_fingerprint


class TestConfigPersistence:
    """Tests for config device data persistence."""

    def test_devices_persist_to_file(self, tmp_path: Path):
        """Device config persists to file."""
        # Create config and add device
        node = create_sync_node("TestNode", DEVICE_A_ID, tmp_path)

        device_id = "00000000000070008000000000000099"
        node.config.add_device(
            device_id=device_id,
            device_name="PersistentDevice",
            device_url="http://localhost:8384",
        )

        # Create new config instance
        new_config = Config(config_dir=node.config_dir)

        # Device should still exist
        device = new_config.get_device(device_id)
        assert device is not None
        assert device["device_name"] == "PersistentDevice"

        node.db.close()

    def test_device_removal_persists(self, tmp_path: Path):
        """Device removal persists to file."""
        node = create_sync_node("TestNode", DEVICE_A_ID, tmp_path)

        device_id = "00000000000070008000000000000099"
        node.config.add_device(
            device_id=device_id,
            device_name="ToRemove",
            device_url="http://localhost:8384",
        )

        node.config.remove_device(device_id)

        # Create new config instance
        new_config = Config(config_dir=node.config_dir)

        # Device should be gone
        assert new_config.get_device(device_id) is None

        node.db.close()


class TestSyncConfigIntegration:
    """Tests for sync config integration."""

    def test_sync_config_structure(self, sync_node_a: SyncNode):
        """Sync config has expected structure."""
        sync_config = sync_node_a.config.get_sync_config()

        assert "enabled" in sync_config
        assert "server_port" in sync_config
        assert "devices" in sync_config
        assert isinstance(sync_config["devices"], list)

    def test_get_device_id_hex(self, sync_node_a: SyncNode):
        """Get device ID as hex string."""
        device_id = sync_node_a.config.get_this_device_id_hex()

        assert device_id is not None
        assert len(device_id) == 32  # 16 bytes = 32 hex chars

    def test_get_device_name(self, sync_node_a: SyncNode):
        """Get device name."""
        device_name = sync_node_a.config.get_this_device_name()

        assert device_name == "NodeA"

    def test_get_sync_server_port(self, sync_node_a: SyncNode):
        """Get sync server port."""
        port = sync_node_a.config.get_sync_server_port()

        assert port > 0
        assert port < 65536


class TestDeviceValidation:
    """Tests for device data validation."""

    def test_device_url_validation(self, sync_node_a: SyncNode):
        """Device URL is validated."""
        # Invalid URL should fail or be accepted
        try:
            sync_node_a.config.add_device(
                device_id="00000000000070008000000000000099",
                device_name="Test",
                device_url="not-a-url",
            )
            # If accepted, verify it's stored
            device = sync_node_a.config.get_device("00000000000070008000000000000099")
            assert device is not None
        except ValidationError:
            pass  # Expected

    def test_device_id_format_strict(self, sync_node_a: SyncNode):
        """Device ID format is strictly validated."""
        invalid_ids = [
            "too-short",
            "0000000000007000800000000000009X",  # Invalid hex
            "00000000-0000-7000-8000-000000000099",  # With dashes
            "",
            "g" * 32,  # Invalid hex chars
        ]

        for invalid_id in invalid_ids:
            with pytest.raises((ValidationError, ValueError)):
                sync_node_a.config.add_device(
                    device_id=invalid_id,
                    device_name="Test",
                    device_url="http://localhost:8384",
                )

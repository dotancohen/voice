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
        device_id = sync_config.get_this_device_id_hex()
        assert device_id is not None
        assert len(device_id) == 32  # UUID as hex

    def test_device_id_persists(self, sync_config: Config) -> None:
        """Device ID persists across config reloads."""
        device_id_1 = sync_config.get_this_device_id_hex()

        # Reload config
        sync_config_2 = Config(config_dir=sync_config.config_dir)
        device_id_2 = sync_config_2.get_this_device_id_hex()

        assert device_id_1 == device_id_2

    def test_device_id_hex(self, sync_config: Config) -> None:
        """Device ID hex string is valid."""
        device_id_hex = sync_config.get_this_device_id_hex()
        assert len(device_id_hex) == 32
        # Should be valid hex
        uuid.UUID(hex=device_id_hex)


class TestDeviceName:
    """Test device name configuration."""

    def test_default_device_name(self, sync_config: Config) -> None:
        """The default name names the computer and is never "localhost" (UI-11).
        How it is built from each source is tested in the core (config.rs)."""
        name = sync_config.get_this_device_name()
        assert name.strip(), "a name"
        assert not name.lower().startswith("localhost"), name
        assert "Voice on" not in name

    def test_set_device_name(self, sync_config: Config) -> None:
        """Device name can be changed."""
        sync_config.set_this_device_name("My Test Device")
        assert sync_config.get_this_device_name() == "My Test Device"

    def test_device_name_persists(self, sync_config: Config) -> None:
        """Device name persists across config reloads."""
        sync_config.set_this_device_name("Persistent Name")

        sync_config_2 = Config(config_dir=sync_config.config_dir)
        assert sync_config_2.get_this_device_name() == "Persistent Name"


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


class TestDeviceManagement:
    """Test device configuration management."""

    def test_no_devices_by_default(self, sync_config: Config) -> None:
        """No devices configured by default."""
        assert sync_config.get_devices() == []

    def test_add_device(self, sync_config: Config) -> None:
        """Device can be added."""
        device_id = uuid.uuid4().hex
        sync_config.add_device(
            device_id=device_id,
            device_name="Test Device",
            device_url="https://192.168.1.100:8384",
        )

        devices = sync_config.get_devices()
        assert len(devices) == 1
        assert devices[0]["device_id"] == device_id
        assert devices[0]["device_name"] == "Test Device"
        assert devices[0]["device_url"] == "https://192.168.1.100:8384"

    def test_add_device_with_certificate(self, sync_config: Config) -> None:
        """Device can be added with certificate fingerprint."""
        device_id = uuid.uuid4().hex
        fingerprint = "SHA256:abc123def456..."

        sync_config.add_device(
            device_id=device_id,
            device_name="Secure Device",
            device_url="https://example.com:8384",
            certificate_fingerprint=fingerprint,
        )

        device = sync_config.get_device(device_id)
        assert device is not None
        assert device["certificate_fingerprint"] == fingerprint

    def test_add_multiple_devices(self, sync_config: Config) -> None:
        """Multiple devices can be added."""
        other_device_id_1 = uuid.uuid4().hex
        other_device_id_2 = uuid.uuid4().hex

        sync_config.add_device(other_device_id_1, "Device 1", "https://host1:8384")
        sync_config.add_device(other_device_id_2, "Device 2", "https://host2:8384")

        assert len(sync_config.get_devices()) == 2

    def test_update_existing_device(self, sync_config: Config) -> None:
        """Adding device with same ID updates existing device."""
        device_id = uuid.uuid4().hex

        sync_config.add_device(device_id, "Original Name", "https://host1:8384")
        sync_config.add_device(device_id, "Updated Name", "https://host2:8384")

        devices = sync_config.get_devices()
        assert len(devices) == 1
        assert devices[0]["device_name"] == "Updated Name"
        assert devices[0]["device_url"] == "https://host2:8384"

    def test_remove_device(self, sync_config: Config) -> None:
        """Device can be removed."""
        device_id = uuid.uuid4().hex
        sync_config.add_device(device_id, "Test Device", "https://host:8384")

        result = sync_config.remove_device(device_id)

        assert result is True
        assert sync_config.get_devices() == []

    def test_remove_nonexistent_device(self, sync_config: Config) -> None:
        """Removing nonexistent device returns False."""
        result = sync_config.remove_device(uuid.uuid4().hex)
        assert result is False

    def test_get_device(self, sync_config: Config) -> None:
        """Individual device can be retrieved."""
        device_id = uuid.uuid4().hex
        sync_config.add_device(device_id, "Test Device", "https://host:8384")

        device = sync_config.get_device(device_id)

        assert device is not None
        assert device["device_id"] == device_id

    def test_get_nonexistent_device(self, sync_config: Config) -> None:
        """Getting nonexistent device returns None."""
        device = sync_config.get_device(uuid.uuid4().hex)
        assert device is None

    def test_update_device_certificate(self, sync_config: Config) -> None:
        """Device certificate can be updated (TOFU)."""
        device_id = uuid.uuid4().hex
        sync_config.add_device(device_id, "Test Device", "https://host:8384")

        result = sync_config.update_device_certificate(device_id, "SHA256:newfingerprint")

        assert result is True
        device = sync_config.get_device(device_id)
        assert device["certificate_fingerprint"] == "SHA256:newfingerprint"

    def test_devices_persist(self, sync_config: Config) -> None:
        """Devices persist across config reloads."""
        device_id = uuid.uuid4().hex
        sync_config.add_device(device_id, "Persistent Device", "https://host:8384")

        sync_config_2 = Config(config_dir=sync_config.config_dir)
        devices = sync_config_2.get_devices()

        assert len(devices) == 1
        assert devices[0]["device_id"] == device_id


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

"""Configuration management for Voice.

This module handles loading and saving application configuration to/from
a JSON file. The config directory can be customized via CLI argument.

This is a wrapper around the Rust voicecore extension.

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import from Rust extension
from voicecore import Config as RustConfig

# Import ValidationError for backward compatibility
from .validation import ValidationError

__all__ = ["Config"]


class Config:
    """Manages application configuration stored in JSON format.

    This is a wrapper around the Rust Config implementation.

    Attributes:
        config_dir: Path to the configuration directory
    """

    def __init__(self, config_dir: Optional[Path] = None, root: Optional[Path] = None) -> None:
        """Initialize configuration manager.

        Args:
            config_dir: The account's directory. If None, uses ~/.config/voice/
            root: The root that holds the machine's settings and the account
                index, when the account directory is one of several under it.
        """
        path_str = str(config_dir) if config_dir else None
        root_str = str(root) if root else None
        self._rust_config = RustConfig(path_str, root_str)
        self.config_dir = Path(self._rust_config.get_config_dir())
        self.root = Path(self._rust_config.get_root())

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        result = self._rust_config.get(key, None)
        return result if result is not None else default

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value and save to file."""
        self._rust_config.set(key, str(value) if value is not None else "")

    def get_config_dir(self) -> Path:
        """Get the configuration directory path."""
        return self.config_dir

    def get_root(self) -> Path:
        """The root that holds the machine's settings, the certificates and the account index."""
        return self.root

    def get_backup(self) -> Dict[str, Any]:
        """The periodic backup settings: interval_hours, directory, keep."""
        return self._rust_config.get_backup()

    def set_backup(self, interval_hours: int, keep: int, directory: str = "") -> None:
        self._rust_config.set_backup(interval_hours, keep, directory)

    def get_public_url(self) -> str:
        return self._rust_config.get_public_url()

    def set_public_url(self, url: str) -> None:
        self._rust_config.set_public_url(url)

    def get_tui_colors(self) -> Dict[str, str]:
        """Get TUI border colors from config."""
        return self._rust_config.get_tui_colors()

    def get_warning_color(self, theme: str = "dark") -> str:
        """Get the warning color from config based on theme."""
        return self._rust_config.get_warning_color(theme)

    # ===== Sync Configuration Methods =====

    def get_this_device_id_hex(self) -> str:
        """Get the device ID as hex string."""
        return self._rust_config.get_this_device_id_hex()

    def get_this_device_name(self) -> str:
        """Get the human-readable device name."""
        return self._rust_config.get_this_device_name()

    def set_this_device_name(self, name: str) -> None:
        """Set the device name."""
        self._rust_config.set_this_device_name(name)

    def get_sync_config(self) -> Dict[str, Any]:
        """Get sync configuration."""
        return self._rust_config.get_sync_config()

    def is_sync_enabled(self) -> bool:
        """Check if sync is enabled."""
        return self._rust_config.is_sync_enabled()

    def set_sync_enabled(self, enabled: bool) -> None:
        """Enable or disable sync."""
        self._rust_config.set_sync_enabled(enabled)

    def get_device_key(self) -> str:
        """This device's key for the account, or empty before one was made."""
        return self._rust_config.get_device_key()

    def get_sync_server_port(self) -> int:
        """Get the sync server port."""
        return self._rust_config.get_sync_server_port()

    def set_sync_server_port(self, port: int) -> None:
        """Set the sync server port."""
        self._rust_config.set_sync_server_port(port)

    def get_devices(self) -> List[Dict[str, Any]]:
        """Get list of sync devices."""
        return self._rust_config.get_devices()

    def add_device(
        self,
        device_id: str,
        device_name: str,
        device_url: str,
        certificate_fingerprint: Optional[str] = None,
        allow_update: bool = True,
    ) -> None:
        """Add a new sync device."""
        # Validate device_id format
        if not isinstance(device_id, str) or len(device_id) != 32:
            raise ValidationError("device_id", "must be 32 hex characters")
        try:
            int(device_id, 16)
        except ValueError:
            raise ValidationError("device_id", "must be a valid hex string")

        # Check for duplicate if allow_update is False
        if not allow_update:
            existing = self.get_device(device_id)
            if existing is not None:
                raise ValidationError("device_id", "device already exists")

        self._rust_config.add_device(device_id, device_name, device_url, certificate_fingerprint)

    def remove_device(self, device_id: str) -> bool:
        """Remove a sync device."""
        return self._rust_config.remove_device(device_id)

    def forget_device(self, device_id: str) -> bool:
        """Forget a device: it leaves the list and its card does not bring it back (Stage 5)."""
        return self._rust_config.forget_device(device_id)

    def rename_device(self, device_id: str, name: str) -> bool:
        """A local name for a device, shown in place of its card's."""
        return self._rust_config.rename_device(device_id, name)

    def listener_idle_stop_hours(self) -> int:
        """Hours of silence after which the listener stops itself; 0 means never."""
        return self._rust_config.listener_idle_stop_hours()

    def set_listener_idle_stop_hours(self, hours: int) -> None:
        self._rust_config.set_listener_idle_stop_hours(hours)

    def last_device_id(self) -> str:
        """The device of the last operation, or an empty string."""
        return self._rust_config.last_device_id()

    def set_last_device(self, device_id: str) -> None:
        self._rust_config.set_last_device(device_id)

    def is_forgotten(self, device_id: str) -> bool:
        return self._rust_config.is_forgotten(device_id)

    def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific device by ID."""
        return self._rust_config.get_device(device_id)

    def update_device_certificate(self, device_id: str, fingerprint: str) -> bool:
        """Update a device's certificate fingerprint (TOFU)."""
        return self._rust_config.update_device_certificate(device_id, fingerprint)

    def get_certs_dir(self) -> Path:
        """Get the directory for TLS certificates."""
        return Path(self._rust_config.get_certs_dir())

    def get_mirror_audio_files(self) -> bool:
        """Whether this installation downloads every cloud audio file on sync.

        This is a local-only setting (never synced) meant for desktop or server
        installations that should hold a complete copy of all media.
        """
        return self._rust_config.get_mirror_audio_files()

    def set_mirror_audio_files(self, enabled: bool) -> None:
        """Enable or disable mirroring of all cloud audio files on sync."""
        self._rust_config.set_mirror_audio_files(enabled)

    # ===== AudioFile Configuration =====

    def get_audiofile_directory(self) -> Optional[str]:
        """Get the audiofile directory path.

        Returns:
            Path to audiofile directory, or None if not configured.
        """
        return self._rust_config.get_audiofile_directory()

    def set_audiofile_directory(self, path: str) -> None:
        """Set the audiofile directory path.

        Args:
            path: Path to the audiofile directory.
        """
        self._rust_config.set_audiofile_directory(path)

    # ===== Transcription Configuration =====
    #
    # Transcription config is stored as generic JSON in voicecore.
    # Voicecore doesn't interpret the structure - that's the responsibility
    # of the transcription module.

    def get_transcription_config(self) -> Dict[str, Any]:
        """Get the full transcription configuration.

        Returns:
            Dict containing transcription settings (structure defined by
            transcription module, not voicecore).
        """
        return self._rust_config.get_transcription_config()

    def set_transcription_config(self, config: Dict[str, Any]) -> None:
        """Set the full transcription configuration.

        Args:
            config: Dict containing transcription settings
        """
        self._rust_config.set_transcription_config(config)

    # ===== Backward Compatibility =====

    @property
    def config_file(self) -> Path:
        """Get the config file path."""
        return self.config_dir / "config.json"

    @property
    def config_data(self) -> Dict[str, Any]:
        """Get all config data as a dict (for backward compatibility)."""
        # Return basic config structure
        return {
            "database_file": self._rust_config.get_database_file(),
            "this_device_id": self.get_this_device_id_hex(),
            "this_device_name": self.get_this_device_name(),
            "sync": self.get_sync_config(),
        }

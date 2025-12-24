"""Configuration management for Voice.

This module handles loading and saving application configuration to/from
a JSON file. The config directory can be customized via CLI argument.

This is a wrapper around the Rust voice_core extension.

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import from Rust extension
from voice_core import Config as RustConfig

# Import ValidationError for backward compatibility
from .validation import ValidationError

__all__ = ["Config"]


class Config:
    """Manages application configuration stored in JSON format.

    This is a wrapper around the Rust Config implementation.

    Attributes:
        config_dir: Path to the configuration directory
    """

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        """Initialize configuration manager.

        Args:
            config_dir: Custom config directory path. If None, uses ~/.config/voice/
        """
        path_str = str(config_dir) if config_dir else None
        self._rust_config = RustConfig(path_str)
        self.config_dir = Path(self._rust_config.get_config_dir())

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

    def get_tui_colors(self) -> Dict[str, str]:
        """Get TUI border colors from config."""
        return self._rust_config.get_tui_colors()

    def get_warning_color(self, theme: str = "dark") -> str:
        """Get the warning color from config based on theme."""
        return self._rust_config.get_warning_color(theme)

    # ===== Sync Configuration Methods =====

    def get_device_id(self) -> bytes:
        """Get the device ID as bytes."""
        hex_id = self._rust_config.get_device_id_hex()
        return uuid.UUID(hex=hex_id).bytes

    def get_device_id_hex(self) -> str:
        """Get the device ID as hex string."""
        return self._rust_config.get_device_id_hex()

    def get_device_name(self) -> str:
        """Get the human-readable device name."""
        return self._rust_config.get_device_name()

    def set_device_name(self, name: str) -> None:
        """Set the device name."""
        self._rust_config.set_device_name(name)

    def get_sync_config(self) -> Dict[str, Any]:
        """Get sync configuration."""
        return self._rust_config.get_sync_config()

    def is_sync_enabled(self) -> bool:
        """Check if sync is enabled."""
        return self._rust_config.is_sync_enabled()

    def set_sync_enabled(self, enabled: bool) -> None:
        """Enable or disable sync."""
        self._rust_config.set_sync_enabled(enabled)

    def get_sync_server_port(self) -> int:
        """Get the sync server port."""
        return self._rust_config.get_sync_server_port()

    def set_sync_server_port(self, port: int) -> None:
        """Set the sync server port."""
        self._rust_config.set_sync_server_port(port)

    def get_peers(self) -> List[Dict[str, Any]]:
        """Get list of sync peers."""
        return self._rust_config.get_peers()

    def add_peer(
        self,
        peer_id: str,
        peer_name: str,
        peer_url: str,
        certificate_fingerprint: Optional[str] = None,
        allow_update: bool = True,
    ) -> None:
        """Add a new sync peer."""
        # Validate peer_id format
        if not isinstance(peer_id, str) or len(peer_id) != 32:
            raise ValidationError("peer_id", "must be 32 hex characters")
        try:
            int(peer_id, 16)
        except ValueError:
            raise ValidationError("peer_id", "must be a valid hex string")

        # Check for duplicate if allow_update is False
        if not allow_update:
            existing = self.get_peer(peer_id)
            if existing is not None:
                raise ValidationError("peer_id", "peer already exists")

        self._rust_config.add_peer(peer_id, peer_name, peer_url, certificate_fingerprint)

    def remove_peer(self, peer_id: str) -> bool:
        """Remove a sync peer."""
        return self._rust_config.remove_peer(peer_id)

    def get_peer(self, peer_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific peer by ID."""
        return self._rust_config.get_peer(peer_id)

    def update_peer_certificate(self, peer_id: str, fingerprint: str) -> bool:
        """Update a peer's certificate fingerprint (TOFU)."""
        return self._rust_config.update_peer_certificate(peer_id, fingerprint)

    def get_certs_dir(self) -> Path:
        """Get the directory for TLS certificates."""
        return Path(self._rust_config.get_certs_dir())

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
            "device_id": self.get_device_id_hex(),
            "device_name": self.get_device_name(),
            "sync": self.get_sync_config(),
        }

    def load_config(self) -> Dict[str, Any]:
        """Load configuration - returns config_data for compatibility."""
        return self.config_data

    def save_config(self, config: Dict[str, Any]) -> None:
        """Save configuration - delegates to Rust for individual keys."""
        # The Rust Config auto-saves, so this is a no-op
        pass

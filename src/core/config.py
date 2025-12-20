"""Configuration management for Voice Rewrite.

This module handles loading and saving application configuration to/from
a JSON file. The config directory can be customized via CLI argument.

Includes sync-related configuration:
- device_id: UUID7 identifying this device (generated on first run)
- device_name: Human-readable device name
- sync: Peer configuration and sync settings
"""

from __future__ import annotations

import json
import logging
import socket
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from uuid6 import uuid7

from .validation import ValidationError

logger = logging.getLogger(__name__)


class Config:
    """Manages application configuration stored in JSON format.

    Configuration is stored in <config_dir>/config.json. If the config file
    doesn't exist, it's created with default values.

    Attributes:
        config_dir: Path to the configuration directory
        config_file: Path to the configuration JSON file
        config_data: Dictionary containing all configuration values
    """

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        """Initialize configuration manager.

        Args:
            config_dir: Custom config directory path. If None, uses ~/.config/voicerewrite/
        """
        self.config_dir = config_dir or (Path.home() / ".config" / "voicerewrite")
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "config.json"
        self.config_data = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file.

        Creates default config if file doesn't exist.

        Returns:
            Dictionary containing configuration values.
        """
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                logger.info(f"Loaded config from {self.config_file}")
                return cast(Dict[str, Any], config)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse config file: {e}")
                logger.info("Using default configuration")
                return self._get_default_config()
        else:
            logger.info("Config file not found, creating default configuration")
            config = self._get_default_config()
            self.save_config(config)
            return config

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration values.

        Returns:
            Dictionary with default configuration.
        """
        return {
            "database_file": str(self.config_dir / "notes.db"),
            "default_interface": "gui",  # "gui", "cli", or "web"
            "window_geometry": None,
            "implementations": {},  # Future: component implementation selections
            "themes": {
                "colours": {
                    "warnings": "#FFFF00",  # Yellow for highlighting ambiguous tags
                    "tui_border_focused": "green",
                    "tui_border_unfocused": "blue",
                }
            },
            # Sync configuration
            "device_id": uuid7().hex,  # UUID7 for this device
            "device_name": self._get_default_device_name(),
            "sync": {
                "enabled": False,
                "server_port": 8384,  # Default sync server port
                "peers": [],  # List of peer configurations
            },
        }

    def _get_default_device_name(self) -> str:
        """Get a default device name based on hostname.

        Returns:
            Human-readable device name.
        """
        try:
            hostname = socket.gethostname()
            return f"VoiceRewrite on {hostname}"
        except Exception:
            return "VoiceRewrite Device"

    def save_config(self, config: Dict[str, Any]) -> None:
        """Save configuration to JSON file.

        Args:
            config: Dictionary containing configuration values to save.
        """
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            logger.info(f"Saved config to {self.config_file}")
        except (OSError, TypeError) as e:
            logger.error(f"Failed to save config: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value.

        Args:
            key: Configuration key to retrieve
            default: Default value if key doesn't exist

        Returns:
            Configuration value or default if not found.
        """
        return self.config_data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value and save to file.

        Args:
            key: Configuration key to set
            value: Value to store
        """
        self.config_data[key] = value
        self.save_config(self.config_data)

    def get_config_dir(self) -> Path:
        """Get the configuration directory path.

        Returns:
            Path object pointing to the config directory.
        """
        return self.config_dir

    def get_tui_colors(self) -> Dict[str, str]:
        """Get TUI border colors from config.

        Returns:
            Dictionary with 'focused' and 'unfocused' border colors.
        """
        try:
            themes = self.config_data.get("themes", {})
            colours = themes.get("colours", {})
            return {
                "focused": colours.get("tui_border_focused", "green"),
                "unfocused": colours.get("tui_border_unfocused", "blue"),
            }
        except (AttributeError, TypeError):
            return {"focused": "green", "unfocused": "blue"}

    def get_warning_color(self, theme: str = "dark") -> str:
        """Get the warning color from config based on theme.

        Args:
            theme: UI theme ("dark" or "light")

        Returns:
            Hex color string for warnings (yellow for dark, orange for light).

        Priority (highest to lowest):
            1. Theme-specific key (warnings_dark or warnings_light)
            2. Generic key (warnings)
            3. Built-in default (#FFFF00 for dark, #FF8C00 for light)
        """
        try:
            themes = self.config_data.get("themes", {})
            colours = themes.get("colours", {})

            # Theme-specific keys take precedence
            if theme == "light":
                if "warnings_light" in colours:
                    return cast(str, colours["warnings_light"])
            else:
                if "warnings_dark" in colours:
                    return cast(str, colours["warnings_dark"])

            # Fall back to generic "warnings" key
            if "warnings" in colours:
                return cast(str, colours["warnings"])

            # Built-in defaults
            return "#FF8C00" if theme == "light" else "#FFFF00"
        except (AttributeError, TypeError):
            # Fallback defaults
            return "#FF8C00" if theme == "light" else "#FFFF00"

    # ===== Sync Configuration Methods =====

    def get_device_id(self) -> bytes:
        """Get the device ID as bytes.

        Returns:
            16-byte UUID identifying this device.
        """
        device_id_hex = self.config_data.get("device_id")
        if not device_id_hex:
            # Generate and save new device ID
            device_id_hex = uuid7().hex
            self.config_data["device_id"] = device_id_hex
            self.save_config(self.config_data)
        return uuid.UUID(hex=device_id_hex).bytes

    def get_device_id_hex(self) -> str:
        """Get the device ID as hex string.

        Returns:
            32-character hex string identifying this device.
        """
        device_id_hex = self.config_data.get("device_id")
        if not device_id_hex:
            # Generate and save new device ID
            device_id_hex = uuid7().hex
            self.config_data["device_id"] = device_id_hex
            self.save_config(self.config_data)
        return device_id_hex

    def get_device_name(self) -> str:
        """Get the human-readable device name.

        Returns:
            Device name string.
        """
        name = self.config_data.get("device_name")
        if not name:
            name = self._get_default_device_name()
            self.config_data["device_name"] = name
            self.save_config(self.config_data)
        return name

    def set_device_name(self, name: str) -> None:
        """Set the device name.

        Args:
            name: New device name.
        """
        self.config_data["device_name"] = name
        self.save_config(self.config_data)

    def get_sync_config(self) -> Dict[str, Any]:
        """Get sync configuration.

        Returns:
            Dictionary with sync settings.
        """
        sync_config = self.config_data.get("sync", {})
        # Ensure defaults
        if "enabled" not in sync_config:
            sync_config["enabled"] = False
        if "server_port" not in sync_config:
            sync_config["server_port"] = 8384
        if "peers" not in sync_config:
            sync_config["peers"] = []
        return sync_config

    def is_sync_enabled(self) -> bool:
        """Check if sync is enabled.

        Returns:
            True if sync is enabled.
        """
        return self.get_sync_config().get("enabled", False)

    def set_sync_enabled(self, enabled: bool) -> None:
        """Enable or disable sync.

        Args:
            enabled: Whether to enable sync.
        """
        sync_config = self.get_sync_config()
        sync_config["enabled"] = enabled
        self.config_data["sync"] = sync_config
        self.save_config(self.config_data)

    def get_sync_server_port(self) -> int:
        """Get the sync server port.

        Returns:
            Port number for sync server.
        """
        return self.get_sync_config().get("server_port", 8384)

    def set_sync_server_port(self, port: int) -> None:
        """Set the sync server port.

        Args:
            port: Port number for sync server.
        """
        sync_config = self.get_sync_config()
        sync_config["server_port"] = port
        self.config_data["sync"] = sync_config
        self.save_config(self.config_data)

    def get_peers(self) -> List[Dict[str, Any]]:
        """Get list of sync peers.

        Returns:
            List of peer configuration dictionaries.
        """
        return self.get_sync_config().get("peers", [])

    def add_peer(
        self,
        peer_id: str,
        peer_name: str,
        peer_url: str,
        certificate_fingerprint: Optional[str] = None,
        allow_update: bool = True,
    ) -> None:
        """Add a new sync peer.

        Args:
            peer_id: UUID hex string of the peer device (32 hex chars).
            peer_name: Human-readable name of the peer.
            peer_url: URL to connect to the peer.
            certificate_fingerprint: Optional TLS certificate fingerprint (TOFU).
            allow_update: If True, update existing peer. If False, raise error.

        Raises:
            ValidationError: If peer_id is invalid or peer exists and allow_update=False.
        """
        # Validate peer_id format
        if not isinstance(peer_id, str) or len(peer_id) != 32:
            raise ValidationError("peer_id", "must be 32 hex characters")
        try:
            int(peer_id, 16)
        except ValueError:
            raise ValidationError("peer_id", "must be a valid hex string")

        sync_config = self.get_sync_config()
        peers = sync_config.get("peers", [])

        # Check if peer already exists
        for peer in peers:
            if peer.get("peer_id") == peer_id:
                if not allow_update:
                    raise ValidationError("peer_id", "peer already exists")
                # Update existing peer
                peer["peer_name"] = peer_name
                peer["peer_url"] = peer_url
                if certificate_fingerprint:
                    peer["certificate_fingerprint"] = certificate_fingerprint
                self.config_data["sync"] = sync_config
                self.save_config(self.config_data)
                return

        # Add new peer
        peers.append({
            "peer_id": peer_id,
            "peer_name": peer_name,
            "peer_url": peer_url,
            "certificate_fingerprint": certificate_fingerprint,
        })
        sync_config["peers"] = peers
        self.config_data["sync"] = sync_config
        self.save_config(self.config_data)

    def remove_peer(self, peer_id: str) -> bool:
        """Remove a sync peer.

        Args:
            peer_id: UUID hex string of the peer to remove.

        Returns:
            True if peer was removed, False if not found.
        """
        sync_config = self.get_sync_config()
        peers = sync_config.get("peers", [])
        original_count = len(peers)
        peers = [p for p in peers if p.get("peer_id") != peer_id]
        sync_config["peers"] = peers
        self.config_data["sync"] = sync_config
        self.save_config(self.config_data)
        return len(peers) < original_count

    def get_peer(self, peer_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific peer by ID.

        Args:
            peer_id: UUID hex string of the peer.

        Returns:
            Peer configuration dictionary or None if not found.
        """
        for peer in self.get_peers():
            if peer.get("peer_id") == peer_id:
                return peer
        return None

    def update_peer_certificate(self, peer_id: str, fingerprint: str) -> bool:
        """Update a peer's certificate fingerprint (TOFU).

        Args:
            peer_id: UUID hex string of the peer.
            fingerprint: New certificate fingerprint.

        Returns:
            True if peer was updated, False if not found.
        """
        sync_config = self.get_sync_config()
        peers = sync_config.get("peers", [])
        for peer in peers:
            if peer.get("peer_id") == peer_id:
                peer["certificate_fingerprint"] = fingerprint
                self.config_data["sync"] = sync_config
                self.save_config(self.config_data)
                return True
        return False

    def get_certs_dir(self) -> Path:
        """Get the directory for TLS certificates.

        Returns:
            Path to certificates directory.
        """
        certs_dir = self.config_dir / "certs"
        certs_dir.mkdir(parents=True, exist_ok=True)
        return certs_dir

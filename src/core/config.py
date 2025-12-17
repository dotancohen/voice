"""Configuration management for Voice Rewrite.

This module handles loading and saving application configuration to/from
a JSON file. The config directory can be customized via CLI argument.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

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
                return config
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
            "window_geometry": None,
            "implementations": {},  # Future: component implementation selections
            "themes": {
                "colours": {
                    "warnings": "#FFFF00"  # Yellow for highlighting ambiguous tags
                }
            },
        }

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

    def get_warning_color(self) -> str:
        """Get the warning color from config.

        Returns:
            Hex color string for warnings (default: "#FFFF00" yellow).
        """
        try:
            return self.config_data.get("themes", {}).get("colours", {}).get("warnings", "#FFFF00")
        except (AttributeError, TypeError):
            return "#FFFF00"

"""Unit tests for configuration management.

Tests all methods in src/core/config.py including:
- Config initialization
- Loading and saving config
- Get/set operations for known keys
- Default values

Note: The Rust-based Config only supports a fixed set of known keys:
- database_file, default_interface, device_name, server_certificate_fingerprint
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import Config


class TestConfigInit:
    """Test configuration initialization."""

    def test_creates_default_config_dir(self, tmp_path: Path) -> None:
        """Test that default config directory is created."""
        config = Config()
        assert config.config_dir.exists()
        assert config.config_dir.is_dir()

    def test_creates_custom_config_dir(self, test_config_dir: Path) -> None:
        """Test that custom config directory is created."""
        config = Config(config_dir=test_config_dir)
        assert config.config_dir == test_config_dir
        assert test_config_dir.exists()

    def test_creates_config_file(self, test_config_dir: Path) -> None:
        """Test that config file is created if it doesn't exist."""
        config = Config(config_dir=test_config_dir)
        assert config.config_file.exists()
        assert config.config_file.name == "config.json"


class TestLoadConfig:
    """Test configuration loading."""

    def test_loads_existing_config(self, test_config_dir: Path) -> None:
        """Test loading existing configuration with known keys."""
        # Create a config file manually with known keys
        config_file = test_config_dir / "config.json"
        test_data = {
            "database_file": str(test_config_dir / "test.db"),
            "default_interface": "tui"
        }
        with open(config_file, "w") as f:
            json.dump(test_data, f)

        config = Config(config_dir=test_config_dir)
        assert config.get("database_file") == str(test_config_dir / "test.db")
        assert config.get("default_interface") == "tui"

    def test_creates_default_config_if_missing(self, test_config_dir: Path) -> None:
        """Test that default config is created if file doesn't exist."""
        config = Config(config_dir=test_config_dir)
        assert config.get("database_file") is not None
        # window_geometry is not a known key, should return None
        assert config.get("window_geometry") is None

    def test_handles_invalid_json(self, test_config_dir: Path) -> None:
        """Test that invalid JSON falls back to default config."""
        config_file = test_config_dir / "config.json"
        with open(config_file, "w") as f:
            f.write("{invalid json")

        config = Config(config_dir=test_config_dir)
        # Should load default config
        assert config.get("database_file") is not None


class TestSaveConfig:
    """Test configuration saving with known keys."""

    def test_saves_known_key_to_file(self, test_config_dir: Path) -> None:
        """Test that known config keys are saved to JSON file."""
        config = Config(config_dir=test_config_dir)
        config.set("device_name", "Test Device")

        # Read file directly
        with open(config.config_file, "r") as f:
            data = json.load(f)

        assert data["device_name"] == "Test Device"

    def test_saved_config_is_loadable(self, test_config_dir: Path) -> None:
        """Test that saved config can be loaded again."""
        config1 = Config(config_dir=test_config_dir)
        config1.set("device_name", "Persistent Device")

        # Create new config instance (simulates app restart)
        config2 = Config(config_dir=test_config_dir)
        assert config2.get("device_name") == "Persistent Device"

    def test_unknown_key_raises_error(self, test_config_dir: Path) -> None:
        """Test that setting unknown keys raises an error."""
        config = Config(config_dir=test_config_dir)
        with pytest.raises(Exception):  # PyConfigError
            config.set("unknown_key", "value")


class TestGetSet:
    """Test get and set methods with known keys."""

    def test_get_returns_value(self, test_config: Config) -> None:
        """Test that get returns stored value for known keys."""
        test_config.set("device_name", "Test Value")
        assert test_config.get("device_name") == "Test Value"

    def test_get_returns_default_for_missing_key(self, test_config: Config) -> None:
        """Test that get returns default for unknown key."""
        assert test_config.get("nonexistent") is None
        assert test_config.get("nonexistent", "default") == "default"

    def test_set_updates_value(self, test_config: Config) -> None:
        """Test that set updates existing value."""
        test_config.set("device_name", "value1")
        assert test_config.get("device_name") == "value1"

        test_config.set("device_name", "value2")
        assert test_config.get("device_name") == "value2"


class TestGetConfigDir:
    """Test get_config_dir method."""

    def test_returns_config_dir(self, test_config: Config) -> None:
        """Test that get_config_dir returns correct path."""
        config_dir = test_config.get_config_dir()
        assert config_dir == test_config.config_dir
        assert config_dir.exists()
        assert config_dir.is_dir()


class TestGetWarningColor:
    """Test get_warning_color method."""

    def test_returns_warning_color_from_config(self, test_config: Config) -> None:
        """Test that warning color is returned from config."""
        color = test_config.get_warning_color()
        assert color == "#FFFF00"  # Default yellow

    def test_returns_default_if_themes_missing(self, test_config_dir: Path) -> None:
        """Test that default color is returned if themes is missing."""
        # Create config without themes
        config_file = test_config_dir / "config.json"
        with open(config_file, "w") as f:
            json.dump({"database_file": "test.db"}, f)

        config = Config(config_dir=test_config_dir)
        assert config.get_warning_color() == "#FFFF00"

    def test_dark_theme_returns_default(self, test_config: Config) -> None:
        """Test that dark theme returns default warning color."""
        assert test_config.get_warning_color("dark") == "#FFFF00"

    def test_light_theme_returns_default(self, test_config: Config) -> None:
        """Test that light theme returns default warning color."""
        # Light theme also uses warnings since warnings_light isn't set
        assert test_config.get_warning_color("light") == "#FFFF00"


class TestDefaultConfig:
    """Test default configuration values."""

    def test_database_file_exists(self, test_config: Config) -> None:
        """Test that database_file is set in default config."""
        db_file = test_config.get("database_file")
        assert db_file is not None
        assert len(db_file) > 0

    def test_device_id_exists(self, test_config: Config) -> None:
        """Test that device_id is generated."""
        device_id = test_config.get_device_id_hex()
        assert device_id is not None
        assert len(device_id) == 32  # UUID hex without hyphens

    def test_device_name_exists(self, test_config: Config) -> None:
        """Test that device_name is set."""
        device_name = test_config.get_device_name()
        assert device_name is not None
        assert len(device_name) > 0

    def test_database_file_path_is_absolute(self, test_config: Config) -> None:
        """Test that database file path is absolute."""
        db_file = test_config.get("database_file")
        assert db_file is not None
        db_path = Path(db_file)
        assert db_path.is_absolute()

"""Unit tests for configuration management.

Tests all methods in src/core/config.py including:
- Config initialization
- Loading and saving config
- Get/set operations
- Default values
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
        """Test loading existing configuration."""
        # Create a config file manually
        config_file = test_config_dir / "config.json"
        test_data = {
            "database_file": str(test_config_dir / "test.db"),
            "custom_key": "custom_value"
        }
        with open(config_file, "w") as f:
            json.dump(test_data, f)

        config = Config(config_dir=test_config_dir)
        assert config.get("custom_key") == "custom_value"
        assert config.get("database_file") == str(test_config_dir / "test.db")

    def test_creates_default_config_if_missing(self, test_config_dir: Path) -> None:
        """Test that default config is created if file doesn't exist."""
        config = Config(config_dir=test_config_dir)
        assert config.get("database_file") is not None
        assert config.get("window_geometry") is None
        assert config.get("implementations") == {}

    def test_handles_invalid_json(self, test_config_dir: Path) -> None:
        """Test that invalid JSON falls back to default config."""
        config_file = test_config_dir / "config.json"
        with open(config_file, "w") as f:
            f.write("{invalid json")

        config = Config(config_dir=test_config_dir)
        # Should load default config
        assert config.get("database_file") is not None


class TestSaveConfig:
    """Test configuration saving."""

    def test_saves_config_to_file(self, test_config_dir: Path) -> None:
        """Test that config is saved to JSON file."""
        config = Config(config_dir=test_config_dir)
        config.set("test_key", "test_value")

        # Read file directly
        with open(config.config_file, "r") as f:
            data = json.load(f)

        assert data["test_key"] == "test_value"

    def test_saved_config_is_loadable(self, test_config_dir: Path) -> None:
        """Test that saved config can be loaded again."""
        config1 = Config(config_dir=test_config_dir)
        config1.set("persistent_key", "persistent_value")

        # Create new config instance (simulates app restart)
        config2 = Config(config_dir=test_config_dir)
        assert config2.get("persistent_key") == "persistent_value"


class TestGetSet:
    """Test get and set methods."""

    def test_get_returns_value(self, test_config: Config) -> None:
        """Test that get returns stored value."""
        test_config.set("key", "value")
        assert test_config.get("key") == "value"

    def test_get_returns_default_for_missing_key(self, test_config: Config) -> None:
        """Test that get returns default for missing key."""
        assert test_config.get("nonexistent") is None
        assert test_config.get("nonexistent", "default") == "default"

    def test_set_updates_value(self, test_config: Config) -> None:
        """Test that set updates existing value."""
        test_config.set("key", "value1")
        assert test_config.get("key") == "value1"

        test_config.set("key", "value2")
        assert test_config.get("key") == "value2"

    def test_set_creates_new_key(self, test_config: Config) -> None:
        """Test that set creates new key if it doesn't exist."""
        assert test_config.get("new_key") is None
        test_config.set("new_key", "new_value")
        assert test_config.get("new_key") == "new_value"


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

    def test_returns_default_if_missing(self, test_config_dir: Path) -> None:
        """Test that default color is returned if config is missing key."""
        # Create config without themes
        config_file = test_config_dir / "config.json"
        with open(config_file, "w") as f:
            json.dump({"database_file": "test.db"}, f)

        config = Config(config_dir=test_config_dir)
        assert config.get_warning_color() == "#FFFF00"

    def test_returns_custom_warning_color(self, test_config: Config) -> None:
        """Test that custom warning color can be set and retrieved."""
        test_config.config_data["themes"] = {
            "colours": {"warnings": "#FF0000"}
        }
        assert test_config.get_warning_color() == "#FF0000"


class TestDefaultConfig:
    """Test default configuration values."""

    def test_default_config_structure(self, test_config: Config) -> None:
        """Test that default config has expected structure."""
        assert "database_file" in test_config.config_data
        assert "window_geometry" in test_config.config_data
        assert "implementations" in test_config.config_data
        assert "themes" in test_config.config_data

    def test_default_themes_structure(self, test_config: Config) -> None:
        """Test that default themes structure is correct."""
        themes = test_config.get("themes")
        assert themes is not None
        assert "colours" in themes
        assert "warnings" in themes["colours"]
        assert themes["colours"]["warnings"] == "#FFFF00"

    def test_database_file_path_is_absolute(self, test_config: Config) -> None:
        """Test that database file path is absolute."""
        db_file = test_config.get("database_file")
        assert db_file is not None
        db_path = Path(db_file)
        assert db_path.is_absolute()

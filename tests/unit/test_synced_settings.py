"""Tests for settings that follow the user across devices."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import Config
from core.database import Database
from core.synced_settings import (
    KEY_PREFERRED_LANGUAGES,
    provider_api_key_setting,
    reconcile_transcription_settings,
    set_synced_setting,
)


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(config_dir=tmp_path / "cfg")


@pytest.fixture
def db() -> Database:
    d = Database(":memory:")
    yield d
    d.close()


class TestReconcile:
    def test_local_values_seed_the_database(self, cfg, db):
        cfg.set_transcription_config({
            "preferred_languages": ["he", "en"],
            "providers": {"assemblyai": {"api_key": "מפתח"}},
        })
        tcfg = reconcile_transcription_settings(cfg, db)
        assert json.loads(db.get_setting(KEY_PREFERRED_LANGUAGES)) == ["he", "en"]
        assert db.get_setting(provider_api_key_setting("assemblyai")) == "מפתח"
        assert tcfg["preferred_languages"] == ["he", "en"]

    def test_synced_values_win_over_the_local_file(self, cfg, db):
        cfg.set_transcription_config({
            "preferred_languages": ["en"],
            "providers": {"assemblyai": {"api_key": "ישן"}},
        })
        db.set_setting(KEY_PREFERRED_LANGUAGES, '["he", "ar"]')
        db.set_setting(provider_api_key_setting("assemblyai"), "חדש")
        reconcile_transcription_settings(cfg, db)
        tcfg = cfg.get_transcription_config()
        assert tcfg["preferred_languages"] == ["he", "ar"]
        assert tcfg["providers"]["assemblyai"]["api_key"] == "חדש"

    def test_provider_unknown_locally_is_added(self, cfg, db):
        db.set_setting(provider_api_key_setting("speechtext_ai"), "סודי")
        reconcile_transcription_settings(cfg, db)
        assert cfg.get_transcription_config()["providers"]["speechtext_ai"]["api_key"] == "סודי"

    def test_local_only_keys_are_not_synced(self, cfg, db):
        cfg.set_transcription_config({
            "providers": {"local_whisper": {"model_path": "/models/ggml-small.bin"}},
        })
        reconcile_transcription_settings(cfg, db)
        assert db.get_all_settings() == {}

    def test_nothing_to_do_is_harmless(self, cfg, db):
        assert reconcile_transcription_settings(cfg, db) is not None
        assert db.get_all_settings() == {}


class TestSetSyncedSetting:
    def test_languages_written_to_both(self, cfg, db):
        set_synced_setting(cfg, db, KEY_PREFERRED_LANGUAGES, '["he"]')
        assert db.get_setting(KEY_PREFERRED_LANGUAGES) == '["he"]'
        assert cfg.get_transcription_config()["preferred_languages"] == ["he"]

    def test_comma_list_is_accepted(self, cfg, db):
        set_synced_setting(cfg, db, KEY_PREFERRED_LANGUAGES, "he, en")
        assert cfg.get_transcription_config()["preferred_languages"] == ["he", "en"]

    def test_invalid_languages_rejected(self, cfg, db):
        with pytest.raises(ValueError):
            set_synced_setting(cfg, db, KEY_PREFERRED_LANGUAGES, '{"not": "a list"}')

    def test_api_key_written_to_both(self, cfg, db):
        set_synced_setting(cfg, db, provider_api_key_setting("assemblyai"), "מפתח")
        assert cfg.get_transcription_config()["providers"]["assemblyai"]["api_key"] == "מפתח"
        assert db.get_setting(provider_api_key_setting("assemblyai")) == "מפתח"

    def test_other_keys_only_in_database(self, cfg, db):
        set_synced_setting(cfg, db, "ui.something", "ערך")
        assert db.get_setting("ui.something") == "ערך"

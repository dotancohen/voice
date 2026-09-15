"""Conflict resolution over the sync feed, with two real databases.

The server endpoints themselves are tested against the Rust server in
`tests/sync/test_sync_server.py`.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Generator, Tuple

import pytest
from uuid6 import uuid7

from core.config import Config
from core.conflicts import ConflictManager, has_conflict_markers
from core.database import Database, set_this_device_id
from core.validation import uuid_to_hex


@pytest.fixture
def device_a(test_config_dir: Path) -> Tuple[Database, Config]:
    """Create device A (first device)."""
    device_id = uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes
    set_this_device_id(device_id)

    config_dir = test_config_dir / "device_a"
    config_dir.mkdir(parents=True, exist_ok=True)

    config = Config(config_dir=config_dir)
    db_path = config_dir / "notes.db"
    db = Database(db_path)

    return db, config


@pytest.fixture
def device_b(test_config_dir: Path) -> Tuple[Database, Config]:
    """Create device B (second device)."""
    device_id = uuid.UUID("00000000-0000-7000-8000-00000000000b").bytes
    set_this_device_id(device_id)

    config_dir = test_config_dir / "device_b"
    config_dir.mkdir(parents=True, exist_ok=True)

    config = Config(config_dir=config_dir)
    db_path = config_dir / "notes.db"
    db = Database(db_path)

    return db, config


class TestConflictResolution:
    """Conflict resolution workflow over the sync feed."""

    REMOTE = "0000000000007000800000000000000b"

    def _conflicted_note(self, db: Database):
        """A note edited here and, concurrently, on a remote device."""
        from voicecore import apply_sync_changes

        set_this_device_id(uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes)
        remote = Database(":memory:")
        note_id = db.create_note("גרסה מקורית")
        changes = db.get_changes_after_seq(0, None, 100000)["changes"]
        for c in changes:
            c.setdefault("device_id", "0000000000007000800000000000000a")
        apply_sync_changes(remote._rust_db, changes, "0000000000007000800000000000000a", "Local")
        db.update_note(note_id, "גרסה מקומית")
        remote.update_note(note_id, "גרסה מרוחקת")
        changes = remote.get_changes_after_seq(0, None, 100000)["changes"]
        for c in changes:
            c.setdefault("device_id", self.REMOTE)
        result = apply_sync_changes(db._rust_db, changes, self.REMOTE, "Remote")
        remote.close()
        assert result["conflicts"] == 1
        return note_id

    def test_concurrent_edit_keeps_both_versions(
        self, device_a: Tuple[Database, Config]
    ) -> None:
        db, config = device_a
        note_id = self._conflicted_note(db)
        text = db.get_note(note_id)["content"]
        assert "גרסה מקומית" in text and "גרסה מרוחקת" in text
        assert has_conflict_markers(text)
        mgr = ConflictManager(db)
        assert mgr.get_unresolved_count()["total"] == 1
        c = mgr.get_conflicts()[0]
        # Both databases live in this process and share its device name
        assert "unknown device" not in (c.device_a_label, c.device_b_label)

    def test_resolve_by_accepting_merge(
        self, device_a: Tuple[Database, Config]
    ) -> None:
        db, config = device_a
        note_id = self._conflicted_note(db)
        mgr = ConflictManager(db)
        assert mgr.accept(mgr.get_conflicts()[0].id) is True
        assert mgr.get_unresolved_count()["total"] == 0
        assert has_conflict_markers(db.get_note(note_id)["content"])

    def test_resolve_by_editing(
        self, device_a: Tuple[Database, Config]
    ) -> None:
        db, config = device_a
        note_id = self._conflicted_note(db)
        mgr = ConflictManager(db)
        assert mgr.resolve_with_content(mgr.get_conflicts()[0].id, "גרסה מאוחדת") is True
        assert db.get_note(note_id)["content"] == "גרסה מאוחדת"
        assert mgr.get_unresolved_count()["total"] == 0

    def test_edit_vs_delete_restores_note(
        self, device_a: Tuple[Database, Config]
    ) -> None:
        from voicecore import apply_sync_changes

        db, config = device_a
        set_this_device_id(uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes)
        remote = Database(":memory:")
        note_id = db.create_note("תוכן")
        changes = db.get_changes_after_seq(0, None, 100000)["changes"]
        for c in changes:
            c.setdefault("device_id", "0000000000007000800000000000000a")
        apply_sync_changes(remote._rust_db, changes, "0000000000007000800000000000000a", "Local")
        db.delete_note(note_id)
        remote.update_note(note_id, "תוכן לשחזור")
        changes = remote.get_changes_after_seq(0, None, 100000)["changes"]
        for c in changes:
            c.setdefault("device_id", self.REMOTE)
        apply_sync_changes(db._rust_db, changes, self.REMOTE, "Remote")
        remote.close()

        note = db.get_note(note_id)
        assert note is not None
        assert note["content"] == "תוכן לשחזור"
        assert note.get("deleted_at") is None
        assert "delete" in ConflictManager(db).get_note_conflict_types(note_id)

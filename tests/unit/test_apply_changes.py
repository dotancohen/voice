"""Applying a batch of changes through the core, driven from Python.

These cover the feed (`get_changes_since`), the apply path, and the rule that a
delete never destroys an edit it did not see (HEAD-6, CONF-10). They use a
second real database rather than hand-written rows where the rule needs it,
because the value of a field travels as a version and a bare row is only a hint
(VER-4).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Generator

import pytest

from core.database import Database, set_local_device_id
from tests.sync_support import SyncChange, apply_sync_changes, get_changes_since

LOCAL_DEVICE = uuid.UUID("00000000-0000-7000-8000-000000000001")
PEER_DEVICE = uuid.UUID("00000000-0000-7000-8000-000000000002")


@pytest.fixture
def sync_db(test_config_dir: Path) -> Generator[Database, None, None]:
    """The local device's database."""
    set_local_device_id(LOCAL_DEVICE.bytes)
    db = Database(test_config_dir / "sync_test.db")
    yield db
    db.close()


@pytest.fixture
def peer_db(test_config_dir: Path) -> Generator[Database, None, None]:
    """A second device, so that sync can be tested as it really happens."""
    set_local_device_id(PEER_DEVICE.bytes)
    db = Database(test_config_dir / "sync_peer.db")
    yield db
    db.close()
    set_local_device_id(LOCAL_DEVICE.bytes)


def on_device(device: uuid.UUID) -> None:
    """Write as this device from here on.

    The device identity is process-wide, so a test with two databases has to
    say which one is acting before every write.
    """
    set_local_device_id(device.bytes)


def push(
    source: Database,
    source_device: uuid.UUID,
    target: Database,
    target_device: uuid.UUID,
    cursor: object = None,
) -> tuple:
    """Send everything the source has learned since `cursor` to the target.

    Returns (applied, conflicts, errors, cursor for the next push).
    """
    on_device(source_device)
    changes, next_cursor = get_changes_since(source, cursor)
    on_device(target_device)
    applied, conflicts, errors = apply_sync_changes(
        target, changes, source_device.hex, "Test Peer"
    )
    return applied, conflicts, errors, next_cursor


class TestGetChangesSince:
    """Reading the feed."""

    def test_returns_only_the_system_tags_for_empty_db(self, sync_db: Database) -> None:
        """A database with nothing of the user's in it offers nothing of the
        user's, though the tags it was created with are there."""
        changes, _ = get_changes_since(sync_db, None)
        assert [c for c in changes if c.entity_type == "note"] == []
        assert all(
            c.entity_type != "tag" or c.data["name"].startswith("_") for c in changes
        )

    def test_returns_note_changes(self, sync_db: Database) -> None:
        """A created note is in the feed as a create."""
        sync_db.create_note("Test content")
        changes, _ = get_changes_since(sync_db, None)

        note_change = next((c for c in changes if c.entity_type == "note"), None)
        assert note_change is not None
        assert note_change.operation == "create"


class TestApplySyncChanges:
    """Applying rows from a peer."""

    def test_applies_new_note(self, sync_db: Database) -> None:
        """A note the peer created appears here."""
        note_id = uuid.uuid4().hex
        peer_id = uuid.uuid4().hex

        changes = [
            SyncChange(
                entity_type="note",
                entity_id=note_id,
                operation="create",
                data={
                    "id": note_id,
                    "created_at": 1736935200,
                    "content": "Remote note",
                    "modified_at": None,
                    "deleted_at": None,
                },
                timestamp=1736935200,
                device_id=peer_id,
            )
        ]

        applied, conflicts, errors = apply_sync_changes(
            sync_db, changes, peer_id, "Test Peer"
        )

        assert applied == 1
        assert conflicts == 0
        assert errors == []
        note = sync_db.get_note(note_id)
        assert note is not None
        assert note["content"] == "Remote note"

    def test_applies_new_tag(self, sync_db: Database) -> None:
        """A tag the peer created appears here."""
        tag_id = uuid.uuid4().hex
        peer_id = uuid.uuid4().hex

        changes = [
            SyncChange(
                entity_type="tag",
                entity_id=tag_id,
                operation="create",
                data={
                    "id": tag_id,
                    "name": "RemoteTag",
                    "parent_id": None,
                    "created_at": 1736935200,
                    "modified_at": None,
                },
                timestamp=1736935200,
                device_id=peer_id,
            )
        ]

        applied, conflicts, errors = apply_sync_changes(
            sync_db, changes, peer_id, "Test Peer"
        )

        assert applied == 1
        assert conflicts == 0
        tag = sync_db.get_tag(tag_id)
        assert tag is not None
        assert tag["name"] == "RemoteTag"


class TestApplySyncChangesDeleteConflicts:
    """A delete that did not see an edit never destroys the edit."""

    def test_edit_arriving_after_a_local_delete_keeps_the_note(
        self, sync_db: Database, peer_db: Database
    ) -> None:
        """Here the note is deleted, there it is edited: the edit wins."""
        on_device(LOCAL_DEVICE)
        note_id = sync_db.create_note("תוכן מקורי")
        _, _, _, to_peer = push(sync_db, LOCAL_DEVICE, peer_db, PEER_DEVICE)
        _, _, _, to_local = push(peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE)

        on_device(LOCAL_DEVICE)
        sync_db.delete_note(note_id)
        on_device(PEER_DEVICE)
        peer_db.update_note(note_id, "עריכה חשובה מאוד")

        _, conflicts, errors, _ = push(
            peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE, to_local
        )

        assert errors == []
        assert conflicts == 1
        on_device(LOCAL_DEVICE)
        note = sync_db.get_note_raw(note_id)
        assert note is not None
        assert note["deleted_at"] is None, "The edit must keep the note alive"
        assert note["content"] == "עריכה חשובה מאוד"
        assert sync_db.get_note_conflict_types(note_id) == ["delete"]

        # And the device that deleted tells the other, so both agree.
        push(sync_db, LOCAL_DEVICE, peer_db, PEER_DEVICE, to_peer)
        on_device(PEER_DEVICE)
        peer_note = peer_db.get_note_raw(note_id)
        assert peer_note is not None
        assert peer_note["deleted_at"] is None
        assert peer_note["content"] == "עריכה חשובה מאוד"
        assert peer_db.get_note_conflict_types(note_id) == ["delete"]

    def test_delete_arriving_after_a_local_edit_keeps_the_note(
        self, sync_db: Database, peer_db: Database
    ) -> None:
        """The same disagreement seen from the other side."""
        on_device(LOCAL_DEVICE)
        note_id = sync_db.create_note("תוכן מקורי")
        push(sync_db, LOCAL_DEVICE, peer_db, PEER_DEVICE)
        _, _, _, to_local = push(peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE)

        on_device(LOCAL_DEVICE)
        sync_db.update_note(note_id, "עריכה מקומית חשובה")
        on_device(PEER_DEVICE)
        peer_db.delete_note(note_id)

        _, conflicts, errors, _ = push(
            peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE, to_local
        )

        assert errors == []
        assert conflicts == 1
        on_device(LOCAL_DEVICE)
        note = sync_db.get_note_raw(note_id)
        assert note is not None
        assert note["deleted_at"] is None, "The local edit must survive"
        assert note["content"] == "עריכה מקומית חשובה"

    def test_delete_of_an_unedited_note_propagates(
        self, sync_db: Database, peer_db: Database
    ) -> None:
        """Nobody edited it, so the delete simply travels."""
        on_device(LOCAL_DEVICE)
        note_id = sync_db.create_note("פתק לא ערוך")
        push(sync_db, LOCAL_DEVICE, peer_db, PEER_DEVICE)
        _, _, _, to_local = push(peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE)

        on_device(PEER_DEVICE)
        peer_db.delete_note(note_id)

        _, conflicts, errors, _ = push(
            peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE, to_local
        )

        assert errors == []
        assert conflicts == 0
        on_device(LOCAL_DEVICE)
        note = sync_db.get_note_raw(note_id)
        assert note is not None
        assert note["deleted_at"] is not None, "The delete should have arrived"
        assert sync_db.get_note(note_id) is None

    def test_a_second_delete_after_seeing_the_edit_is_obeyed(
        self, sync_db: Database, peer_db: Database
    ) -> None:
        """The user who wanted the note gone deletes again, and it goes.

        This is the way out of a delete conflict: the second delete records
        what the user saw, which now includes the edit, so no resurrection.
        """
        on_device(LOCAL_DEVICE)
        note_id = sync_db.create_note("תוכן מקורי")
        _, _, _, to_peer = push(sync_db, LOCAL_DEVICE, peer_db, PEER_DEVICE)
        _, _, _, to_local = push(peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE)

        on_device(LOCAL_DEVICE)
        sync_db.delete_note(note_id)
        on_device(PEER_DEVICE)
        peer_db.update_note(note_id, "עריכה חשובה מאוד")

        push(peer_db, PEER_DEVICE, sync_db, LOCAL_DEVICE, to_local)
        _, _, _, to_peer = push(sync_db, LOCAL_DEVICE, peer_db, PEER_DEVICE, to_peer)

        # The note is alive on both. Delete it again, having seen the edit.
        on_device(LOCAL_DEVICE)
        sync_db.delete_note(note_id)
        _, conflicts, errors, _ = push(
            sync_db, LOCAL_DEVICE, peer_db, PEER_DEVICE, to_peer
        )

        assert errors == []
        assert conflicts == 0
        on_device(PEER_DEVICE)
        peer_note = peer_db.get_note_raw(note_id)
        assert peer_note is not None
        assert peer_note["deleted_at"] is not None, "The second delete stands"


class TestGetFullDataset:
    """The whole database as one document, kept for tools."""

    def test_returns_all_data(self, sync_db: Database) -> None:
        note_id = sync_db.create_note("Test note")
        tag_id = sync_db.create_tag("TestTag")

        data = sync_db.get_full_dataset()

        assert "notes" in data
        assert "tags" in data
        assert "note_tags" in data
        assert len(data["notes"]) == 1
        # Every database is created with the system tags, so count only the
        # tag this test made.
        user_tags = [t for t in data["tags"] if not t["name"].startswith("_")]
        assert [t["id"] for t in user_tags] == [tag_id]
        assert data["notes"][0]["id"] == note_id

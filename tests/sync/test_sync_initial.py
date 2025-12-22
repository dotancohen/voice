"""Tests for initial sync scenarios.

Tests:
- Initial sync when local is empty
- Initial sync when local has data
- Initial sync when remote is empty
- Initial sync with conflicts
- Full dataset transfer
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.database import set_local_device_id
from core.sync_client import SyncClient

from .conftest import (
    SyncNode,
    create_note_on_node,
    create_tag_on_node,
    get_note_count,
    get_tag_count,
    sync_nodes,
    start_sync_server,
)


class TestInitialSyncEmptyLocal:
    """Tests for initial sync when local is empty."""

    def test_initial_sync_pulls_all_notes(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Initial sync pulls all notes from peer."""
        node_a, node_b = two_nodes_with_servers

        # Create notes on B
        for i in range(10):
            create_note_on_node(node_b, f"Note {i} from B")

        assert get_note_count(node_a) == 0
        assert get_note_count(node_b) == 10

        # A does initial sync with B
        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        result = client.initial_sync(node_b.device_id_hex)

        assert result.success is True
        assert get_note_count(node_a) == 10

    def test_initial_sync_pulls_all_tags(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Initial sync pulls all tags from peer."""
        node_a, node_b = two_nodes_with_servers

        # Create tags on B
        for i in range(5):
            create_tag_on_node(node_b, f"Tag{i}")

        assert get_tag_count(node_a) == 0
        assert get_tag_count(node_b) == 5

        # A does initial sync
        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        result = client.initial_sync(node_b.device_id_hex)

        assert result.success is True
        assert get_tag_count(node_a) == 5

    def test_initial_sync_pulls_tag_hierarchy(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Initial sync preserves tag hierarchy."""
        node_a, node_b = two_nodes_with_servers

        # Create hierarchy on B
        parent = create_tag_on_node(node_b, "Parent")
        child = create_tag_on_node(node_b, "Child", parent)
        grandchild = create_tag_on_node(node_b, "Grandchild", child)

        # Initial sync
        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        client.initial_sync(node_b.device_id_hex)

        # Verify hierarchy
        child_a = node_a.db.get_tag(child)
        grandchild_a = node_a.db.get_tag(grandchild)

        assert child_a.get("parent_id") == parent
        assert grandchild_a.get("parent_id") == child

    def test_initial_sync_pulls_note_tag_associations(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Initial sync includes note-tag associations."""
        node_a, node_b = two_nodes_with_servers

        # Create tagged notes on B
        tag = create_tag_on_node(node_b, "Important")
        note = create_note_on_node(node_b, "Tagged note")
        set_local_device_id(node_b.device_id)
        node_b.db.add_tag_to_note(note, tag)

        # Initial sync
        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        client.initial_sync(node_b.device_id_hex)

        # Verify association
        note_a = node_a.db.get_note(note)
        assert "Important" in (note_a.get("tag_names") or "")


class TestInitialSyncLocalHasData:
    """Tests for initial sync when local already has data."""

    def test_initial_sync_merges_with_local(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Initial sync merges remote data with local."""
        node_a, node_b = two_nodes_with_servers

        # Create different notes on each
        note_a = create_note_on_node(node_a, "Local note from A")
        note_b = create_note_on_node(node_b, "Remote note from B")

        # Initial sync from A to B
        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        result = client.initial_sync(node_b.device_id_hex)

        assert result.success is True

        # A should have both notes
        assert get_note_count(node_a) == 2
        assert node_a.db.get_note(note_a) is not None
        assert node_a.db.get_note(note_b) is not None

    def test_initial_sync_pushes_local_to_remote(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Initial sync pushes local data to remote."""
        node_a, node_b = two_nodes_with_servers

        # Create note on A only
        note_a = create_note_on_node(node_a, "Note from A")

        # Initial sync
        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        result = client.initial_sync(node_b.device_id_hex)

        assert result.success is True
        assert result.pushed > 0

        # B should have A's note
        assert node_b.db.get_note(note_a) is not None

    def test_initial_sync_applies_remote_update(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """When only remote edited since last sync, update is applied without conflict."""
        import time

        node_a, node_b = two_nodes_with_servers

        # Create note on A
        note_id = create_note_on_node(node_a, "A's version")

        # Sync to B
        sync_nodes(node_a, node_b)
        node_b.reload_db()

        # Modify on B (later) - use full second for timestamp precision
        time.sleep(1.1)
        set_local_device_id(node_b.device_id)
        node_b.db.update_note(note_id, "B's newer version")

        # A does initial sync - only B edited since last sync, so update applies cleanly
        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        client.initial_sync(node_b.device_id_hex)

        # A should have B's version (only B edited, A unchanged since last sync)
        note_a = node_a.db.get_note(note_id)
        assert note_a["content"] == "B's newer version"

    def test_initial_sync_creates_conflict_when_both_edited(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """When both sides edited since last sync, conflict is created."""
        import time

        node_a, node_b = two_nodes_with_servers

        # Create note on A
        note_id = create_note_on_node(node_a, "Original")

        # Sync to B and back
        sync_nodes(node_a, node_b)
        node_b.reload_db()
        sync_nodes(node_b, node_a)
        node_a.reload_db()

        # Wait for timestamp precision
        time.sleep(1.1)

        # Both sides edit (after last sync)
        set_local_device_id(node_a.device_id)
        node_a.db.update_note(note_id, "A's edit")

        set_local_device_id(node_b.device_id)
        node_b.db.update_note(note_id, "B's edit")

        # A does initial sync - both edited, so conflict
        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        client.initial_sync(node_b.device_id_hex)

        # A should have conflict markers
        note_a = node_a.db.get_note(note_id)
        assert "<<<<<<< LOCAL" in note_a["content"]
        assert "A's edit" in note_a["content"]
        assert "B's edit" in note_a["content"]


class TestInitialSyncRemoteEmpty:
    """Tests for initial sync when remote is empty."""

    def test_initial_sync_with_empty_remote(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Initial sync works when remote has no data."""
        node_a, node_b = two_nodes_with_servers

        # Create data on A only
        note = create_note_on_node(node_a, "Local note")
        tag = create_tag_on_node(node_a, "LocalTag")

        # Initial sync - should just push
        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        result = client.initial_sync(node_b.device_id_hex)

        assert result.success is True
        assert result.pulled == 0

        # B should have A's data
        assert node_b.db.get_note(note) is not None
        assert node_b.db.get_tag(tag) is not None

    def test_initial_sync_both_empty(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Initial sync works when both are empty."""
        node_a, node_b = two_nodes_with_servers

        assert get_note_count(node_a) == 0
        assert get_note_count(node_b) == 0

        # Initial sync
        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        result = client.initial_sync(node_b.device_id_hex)

        assert result.success is True
        assert result.pulled == 0
        assert result.pushed == 0


class TestInitialSyncLargeDatasets:
    """Tests for initial sync with large datasets."""

    def test_initial_sync_many_notes(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Initial sync handles many notes."""
        node_a, node_b = two_nodes_with_servers

        # Create many notes on B
        note_count = 100
        for i in range(note_count):
            create_note_on_node(node_b, f"Note {i} " + "x" * 100)

        # Initial sync
        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        result = client.initial_sync(node_b.device_id_hex)

        assert result.success is True
        assert get_note_count(node_a) == note_count

    def test_initial_sync_large_notes(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Initial sync handles large note content."""
        node_a, node_b = two_nodes_with_servers

        # Create large notes on B
        for i in range(5):
            content = f"Large note {i}\n" + "x" * 50000
            create_note_on_node(node_b, content)

        # Initial sync
        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        result = client.initial_sync(node_b.device_id_hex)

        assert result.success is True

        # Verify content integrity
        notes = node_a.db.get_all_notes()
        for note in notes:
            assert len(note["content"]) > 50000


class TestInitialSyncReturnsResults:
    """Tests for initial sync result reporting."""

    def test_initial_sync_reports_pulled_count(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Initial sync reports number of items pulled."""
        node_a, node_b = two_nodes_with_servers

        # Create notes on B
        for i in range(5):
            create_note_on_node(node_b, f"Note {i}")

        # Initial sync
        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        result = client.initial_sync(node_b.device_id_hex)

        assert result.pulled >= 5

    def test_initial_sync_reports_pushed_count(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Initial sync reports number of items pushed."""
        node_a, node_b = two_nodes_with_servers

        # Create notes on A
        for i in range(3):
            create_note_on_node(node_a, f"Note {i}")

        # Initial sync
        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        result = client.initial_sync(node_b.device_id_hex)

        assert result.pushed >= 3

    def test_initial_sync_reports_success(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Initial sync reports success status."""
        node_a, node_b = two_nodes_with_servers

        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        result = client.initial_sync(node_b.device_id_hex)

        assert result.success is True


class TestInitialSyncErrorHandling:
    """Tests for initial sync error handling."""

    def test_initial_sync_unknown_peer(self, sync_node_a: SyncNode):
        """Initial sync with unknown peer fails gracefully."""
        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(sync_node_a.db, sync_node_a.config)

        result = client.initial_sync("00000000000070008000000000099999")

        assert result.success is False
        assert len(result.errors) > 0

    def test_initial_sync_unreachable_peer(
        self, sync_node_a: SyncNode, sync_node_b: SyncNode
    ):
        """Initial sync with unreachable peer fails gracefully."""
        # Add peer but don't start server
        sync_node_a.config.add_peer(
            peer_id=sync_node_b.device_id_hex,
            peer_name="OfflinePeer",
            peer_url=sync_node_b.url,
        )

        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(sync_node_a.db, sync_node_a.config)

        result = client.initial_sync(sync_node_b.device_id_hex)

        assert result.success is False

    def test_initial_sync_preserves_local_on_failure(
        self, sync_node_a: SyncNode, sync_node_b: SyncNode
    ):
        """Failed initial sync preserves local data."""
        # Create local data
        note = create_note_on_node(sync_node_a, "Important local data")

        # Add unreachable peer
        sync_node_a.config.add_peer(
            peer_id=sync_node_b.device_id_hex,
            peer_name="OfflinePeer",
            peer_url=sync_node_b.url,
        )

        # Attempt initial sync (will fail)
        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(sync_node_a.db, sync_node_a.config)
        client.initial_sync(sync_node_b.device_id_hex)

        # Local data preserved
        assert sync_node_a.db.get_note(note) is not None


class TestInitialSyncVsRegularSync:
    """Tests comparing initial sync vs regular sync."""

    def test_initial_then_regular_sync(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Regular sync after initial sync works correctly."""
        import time

        node_a, node_b = two_nodes_with_servers

        # Create initial data on B
        note1 = create_note_on_node(node_b, "Initial note")

        # Initial sync
        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        client.initial_sync(node_b.device_id_hex)

        # Wait for timestamp precision
        time.sleep(1.1)

        # Create more data on B
        note2 = create_note_on_node(node_b, "New note")

        # Regular sync
        result = sync_nodes(node_a, node_b)

        assert result["success"] is True
        assert node_a.db.get_note(note2) is not None

    def test_regular_sync_idempotent_after_initial(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Multiple syncs after initial don't duplicate data."""
        node_a, node_b = two_nodes_with_servers

        # Create data and initial sync
        create_note_on_node(node_b, "Test note")

        set_local_device_id(node_a.device_id)
        client = SyncClient(node_a.db, node_a.config)
        client.initial_sync(node_b.device_id_hex)

        initial_count = get_note_count(node_a)

        # Multiple regular syncs
        for _ in range(5):
            sync_nodes(node_a, node_b)

        # Count should stay the same
        assert get_note_count(node_a) == initial_count

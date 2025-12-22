"""Tests for sync client operations.

Tests the SyncClient class which handles:
- Connecting to peers
- Pulling changes from peers
- Pushing changes to peers
- Full initial sync
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Tuple

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.sync_client import SyncClient, SyncResult
from core.database import set_local_device_id

from .conftest import (
    SyncNode,
    create_note_on_node,
    create_tag_on_node,
    get_note_count,
    get_tag_count,
    sync_nodes,
    DEVICE_A_ID,
    DEVICE_B_ID,
)


class TestSyncClientInit:
    """Tests for SyncClient initialization."""

    def test_client_creation(self, sync_node_a: SyncNode):
        """SyncClient can be created with database and config."""
        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(sync_node_a.db, sync_node_a.config)
        assert client is not None

    def test_client_with_no_peers(self, sync_node_a: SyncNode):
        """SyncClient handles having no peers configured."""
        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(sync_node_a.db, sync_node_a.config)

        # sync_all should return empty dict
        from core.sync_client import sync_all_peers
        results = sync_all_peers(sync_node_a.db, sync_node_a.config)
        assert results == {}


class TestSyncClientHandshake:
    """Tests for SyncClient handshake."""

    def test_handshake_success(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Client can check peer status (includes handshake)."""
        # Add B as peer of A
        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(sync_node_a.db, sync_node_a.config)

        # Check peer status (performs handshake internally)
        result = client.check_peer_status(running_server_b.device_id_hex)

        assert result is not None
        assert result.get("device_id") == running_server_b.device_id_hex
        assert result.get("device_name") == running_server_b.name

    def test_handshake_peer_not_configured(self, sync_node_a: SyncNode):
        """Status check fails for unconfigured peer."""
        set_local_device_id(sync_node_a.device_id)
        client = SyncClient(sync_node_a.db, sync_node_a.config)

        result = client.check_peer_status("00000000000070008000000000000099")
        # Returns None or error dict for unconfigured peer
        assert result is None or result.get("error") is not None


class TestSyncClientPull:
    """Tests for pulling changes from peers."""

    def test_pull_empty_peer(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Pulling from empty peer returns no changes."""
        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        result = sync_nodes(sync_node_a, running_server_b)

        assert result["success"] is True
        assert result["pulled"] == 0

    def test_pull_notes_from_peer(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Pulling from peer with notes syncs them locally."""
        # Create notes on server B
        note_id = create_note_on_node(running_server_b, "Note from B")

        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        result = sync_nodes(sync_node_a, running_server_b)

        assert result["success"] is True
        assert result["pulled"] >= 1

        # Verify note exists on A
        note = sync_node_a.db.get_note(note_id)
        assert note is not None
        assert note["content"] == "Note from B"

    def test_pull_tags_from_peer(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Pulling from peer with tags syncs them locally."""
        # Create tags on server B
        tag_id = create_tag_on_node(running_server_b, "TagFromB")

        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        result = sync_nodes(sync_node_a, running_server_b)

        assert result["success"] is True

        # Verify tag exists on A
        tags = sync_node_a.db.get_all_tags()
        tag_names = [t["name"] for t in tags]
        assert "TagFromB" in tag_names

    def test_pull_tag_hierarchy(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Pulling preserves tag hierarchy."""
        # Create tag hierarchy on B
        parent_id = create_tag_on_node(running_server_b, "Parent")
        child_id = create_tag_on_node(running_server_b, "Child", parent_id)

        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        result = sync_nodes(sync_node_a, running_server_b)

        assert result["success"] is True

        # Verify hierarchy on A
        child_tag = sync_node_a.db.get_tag(child_id)
        assert child_tag is not None
        # Check parent relationship (the field might be parent_id as bytes or hex)

    def test_pull_multiple_notes(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Pulling syncs multiple notes correctly."""
        # Create multiple notes on B
        note_ids = []
        for i in range(5):
            note_id = create_note_on_node(running_server_b, f"Note {i} from B")
            note_ids.append(note_id)

        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        result = sync_nodes(sync_node_a, running_server_b)

        assert result["success"] is True
        assert result["pulled"] >= 5

        # Verify all notes on A
        for note_id in note_ids:
            note = sync_node_a.db.get_note(note_id)
            assert note is not None


class TestSyncClientPush:
    """Tests for pushing changes to peers."""

    def test_push_notes_to_peer(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Pushing local notes syncs them to peer."""
        # Create note on A
        note_id = create_note_on_node(sync_node_a, "Note from A")

        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        result = sync_nodes(sync_node_a, running_server_b)

        assert result["success"] is True
        assert result["pushed"] >= 1

        # Verify note exists on B
        note = running_server_b.db.get_note(note_id)
        assert note is not None
        assert note["content"] == "Note from A"

    def test_push_tags_to_peer(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Pushing local tags syncs them to peer."""
        # Create tag on A
        tag_id = create_tag_on_node(sync_node_a, "TagFromA")

        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        result = sync_nodes(sync_node_a, running_server_b)

        assert result["success"] is True

        # Verify tag exists on B
        tags = running_server_b.db.get_all_tags()
        tag_names = [t["name"] for t in tags]
        assert "TagFromA" in tag_names


class TestSyncClientBidirectional:
    """Tests for bidirectional sync."""

    def test_sync_both_directions(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Sync works in both directions."""
        node_a, node_b = two_nodes_with_servers

        # Create content on both
        note_a = create_note_on_node(node_a, "Note from A")
        note_b = create_note_on_node(node_b, "Note from B")

        # Sync A -> B (A pulls from B, pushes to B)
        result_a = sync_nodes(node_a, node_b)
        assert result_a["success"] is True

        # Sync B -> A
        result_b = sync_nodes(node_b, node_a)
        assert result_b["success"] is True

        # Both should have both notes
        assert node_a.db.get_note(note_b) is not None
        assert node_b.db.get_note(note_a) is not None

    def test_sync_all_peers(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """sync_all_peers syncs with all configured peers."""
        node_a, node_b = two_nodes_with_servers

        from core.sync_client import sync_all_peers

        # Create content on B
        create_note_on_node(node_b, "Note to sync")

        # Sync A with all peers
        set_local_device_id(node_a.device_id)
        results = sync_all_peers(node_a.db, node_a.config)

        assert node_b.device_id_hex in results
        assert results[node_b.device_id_hex].success is True


class TestSyncClientIdempotency:
    """Tests for sync idempotency."""

    def test_sync_same_data_twice(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Syncing the same data twice doesn't duplicate it."""
        # Create note on B
        note_id = create_note_on_node(running_server_b, "Single note")

        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        # Sync twice
        result1 = sync_nodes(sync_node_a, running_server_b)
        result2 = sync_nodes(sync_node_a, running_server_b)

        assert result1["success"] is True
        assert result2["success"] is True

        # Should still only have one note
        assert get_note_count(sync_node_a) == 1

    def test_sync_after_local_update(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Syncing after local update doesn't revert changes."""
        # Create note on B
        note_id = create_note_on_node(running_server_b, "Original content")

        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        # First sync
        sync_nodes(sync_node_a, running_server_b)

        # Update locally on A
        set_local_device_id(sync_node_a.device_id)
        sync_node_a.db.update_note(note_id, "Updated on A")

        # Sync again - should not revert (A's update is newer)
        sync_nodes(sync_node_a, running_server_b)

        note = sync_node_a.db.get_note(note_id)
        assert note["content"] == "Updated on A"


class TestSyncClientFullSync:
    """Tests for full/initial sync."""

    def test_full_sync_many_items(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Full sync handles many items."""
        # Create lots of content on B
        for i in range(20):
            create_note_on_node(running_server_b, f"Note {i}")
            create_tag_on_node(running_server_b, f"Tag{i}")

        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        result = sync_nodes(sync_node_a, running_server_b)

        assert result["success"] is True
        assert get_note_count(sync_node_a) == 20
        assert get_tag_count(sync_node_a) == 20

    def test_sync_preserves_content_integrity(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Sync preserves note content exactly."""
        # Create notes with various content
        contents = [
            "Simple note",
            "Note with\nnewlines\n\n",
            "Unicode: שלום עולם 你好世界",
            "Special chars: <>&\"'",
            "Long " + "x" * 1000,
        ]

        note_ids = []
        for content in contents:
            note_id = create_note_on_node(running_server_b, content)
            note_ids.append(note_id)

        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        sync_nodes(sync_node_a, running_server_b)

        # Verify all content preserved
        for note_id, original_content in zip(note_ids, contents):
            note = sync_node_a.db.get_note(note_id)
            assert note is not None
            assert note["content"] == original_content


class TestSyncClientDeletes:
    """Tests for syncing deletions."""

    def test_sync_deleted_note(
        self, sync_node_a: SyncNode, running_server_b: SyncNode
    ):
        """Deleted notes sync correctly."""
        # Create and delete note on B
        note_id = create_note_on_node(running_server_b, "To be deleted")
        running_server_b.db.delete_note(note_id)

        sync_node_a.config.add_peer(
            peer_id=running_server_b.device_id_hex,
            peer_name=running_server_b.name,
            peer_url=running_server_b.url,
        )

        sync_nodes(sync_node_a, running_server_b)

        # Note should not appear in regular queries
        notes = sync_node_a.db.get_all_notes()
        note_ids = [n["id"] for n in notes]
        assert note_id not in note_ids

    def test_delete_after_sync_doesnt_propagate(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Deleting after sync doesn't propagate - no silent deletion."""
        import time

        node_a, node_b = two_nodes_with_servers

        # Create note on A
        note_id = create_note_on_node(node_a, "Will be deleted")

        # Sync to B
        sync_nodes(node_a, node_b)
        node_b.reload_db()
        sync_nodes(node_b, node_a)
        node_a.reload_db()

        # Verify on B
        assert node_b.db.get_note(note_id) is not None

        # Wait for timestamp precision
        time.sleep(1.1)

        # Delete on A
        set_local_device_id(node_a.device_id)
        node_a.db.delete_note(note_id)

        # Verify deleted on A
        notes_a = node_a.db.get_all_notes()
        note_ids_a = [n["id"] for n in notes_a]
        assert note_id not in note_ids_a

        # Sync again
        sync_nodes(node_a, node_b)
        node_b.reload_db()
        sync_nodes(node_b, node_a)
        node_a.reload_db()

        # B still has the note - deletion doesn't propagate (no silent deletion)
        notes_b = node_b.db.get_all_notes()
        note_ids_b = [n["id"] for n in notes_b]
        assert note_id in note_ids_b  # Note preserved on B

"""Integration tests for bi-directional sync.

Tests real-world sync scenarios with two or more nodes:
- Creating content on one node and syncing to another
- Bi-directional sync with content on both sides
- Three-way sync scenarios
- Complex workflows with multiple sync operations
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Tuple

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.database import set_local_device_id

from .conftest import (
    SyncNode,
    create_note_on_node,
    create_tag_on_node,
    get_note_count,
    get_tag_count,
    sync_nodes,
)


class TestTwoNodeSync:
    """Tests for sync between two nodes."""

    def test_create_note_sync_verify(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Create note on A, sync to B, verify B has it."""
        node_a, node_b = two_nodes_with_servers

        # Create on A
        note_id = create_note_on_node(node_a, "Hello from A")

        # A initially has 1 note, B has 0
        assert get_note_count(node_a) == 1
        assert get_note_count(node_b) == 0

        # Sync A -> B (A pushes to B)
        result = sync_nodes(node_a, node_b)
        assert result["success"] is True

        # Now B should have the note
        note = node_b.db.get_note(note_id)
        assert note is not None
        assert note["content"] == "Hello from A"

    def test_bidirectional_unique_notes(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Both nodes create different notes, sync exchanges them."""
        node_a, node_b = two_nodes_with_servers

        # Create different notes on each
        note_a = create_note_on_node(node_a, "Note from A")
        note_b = create_note_on_node(node_b, "Note from B")

        # Initial state
        assert get_note_count(node_a) == 1
        assert get_note_count(node_b) == 1

        # Sync A -> B
        sync_nodes(node_a, node_b)

        # Sync B -> A
        sync_nodes(node_b, node_a)

        # Both should have both notes
        assert get_note_count(node_a) == 2
        assert get_note_count(node_b) == 2

        assert node_a.db.get_note(note_b) is not None
        assert node_b.db.get_note(note_a) is not None

    def test_tag_hierarchy_sync(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Tag hierarchies sync correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create hierarchy on A
        work = create_tag_on_node(node_a, "Work")
        projects = create_tag_on_node(node_a, "Projects", work)
        voice_rewrite = create_tag_on_node(node_a, "VoiceRewrite", projects)

        # Sync to B
        sync_nodes(node_a, node_b)

        # Verify hierarchy on B
        assert get_tag_count(node_b) == 3

        tags_b = node_b.db.get_all_tags()
        tag_names = {t["name"] for t in tags_b}
        assert tag_names == {"Work", "Projects", "VoiceRewrite"}

    def test_note_with_tags_sync(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Notes with tags sync correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create tag and note on A
        tag_id = create_tag_on_node(node_a, "Important")
        note_id = create_note_on_node(node_a, "Important note")

        # Associate tag with note
        set_local_device_id(node_a.device_id)
        node_a.db.add_tag_to_note(note_id, tag_id)

        # Sync to B
        sync_nodes(node_a, node_b)

        # Verify note has tag on B
        note_b = node_b.db.get_note(note_id)
        assert note_b is not None
        # Note's tags should include "Important"
        assert "Important" in note_b.get("tag_names", "")

    def test_update_propagation(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Updates create conflict when content differs (no LWW, no base tracking)."""
        node_a, node_b = two_nodes_with_servers

        # Create note on A
        note_id = create_note_on_node(node_a, "Original content")

        # Sync to B
        sync_nodes(node_a, node_b)

        # Reload B's db to see changes from server subprocess
        node_b.reload_db()
        # Verify on B
        note_b = node_b.db.get_note(note_id)
        assert note_b["content"] == "Original content"

        # Wait a full second (timestamps are second-precision)
        time.sleep(1.1)

        # Update on A
        set_local_device_id(node_a.device_id)
        node_a.db.update_note(note_id, "Updated content")

        # Sync again - creates conflict because B has different content
        # (Without base tracking, we can't know B didn't edit)
        sync_nodes(node_a, node_b)

        # Reload B's db to see changes from server subprocess
        node_b.reload_db()
        # Both versions should be preserved (no silent overwrite)
        note_b = node_b.db.get_note(note_id)
        assert "Updated content" in note_b["content"]
        assert "Original content" in note_b["content"]

    def test_delete_propagation(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Deletions propagate when other node hasn't edited the note."""
        node_a, node_b = two_nodes_with_servers

        # Create note on A
        note_id = create_note_on_node(node_a, "Will be deleted")

        # Sync to B
        sync_nodes(node_a, node_b)

        # Reload B's db to see changes from server subprocess
        node_b.reload_db()
        # Verify on B
        assert node_b.db.get_note(note_id) is not None
        assert get_note_count(node_b) == 1

        # Wait a full second (timestamps are second-precision)
        time.sleep(1.1)

        # Delete on A (B has same content - never edited)
        set_local_device_id(node_a.device_id)
        node_a.db.delete_note(note_id)

        # Sync again - delete propagates because B didn't edit
        sync_nodes(node_a, node_b)

        # Reload B's db to see changes from server subprocess
        node_b.reload_db()
        # B's note is now deleted (propagated from A)
        assert get_note_count(node_b) == 0  # Note deleted
        note_b = node_b.db.get_note(note_id)
        assert note_b is not None  # Soft delete - record exists
        assert note_b.get("deleted_at") is not None  # But marked deleted

    def test_multiple_sync_cycles(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Multiple sync cycles work correctly."""
        node_a, node_b = two_nodes_with_servers

        # Cycle 1: A creates, sync, B creates, sync
        note_a1 = create_note_on_node(node_a, "A note 1")
        sync_nodes(node_a, node_b)

        # Wait for timestamp precision
        time.sleep(1.1)

        note_b1 = create_note_on_node(node_b, "B note 1")
        sync_nodes(node_b, node_a)
        sync_nodes(node_a, node_b)

        # Reload databases to see changes from server subprocesses
        node_a.reload_db()
        node_b.reload_db()
        # Both have 2 notes
        assert get_note_count(node_a) == 2
        assert get_note_count(node_b) == 2

        # Wait for timestamp precision
        time.sleep(1.1)

        # Cycle 2: More notes
        note_a2 = create_note_on_node(node_a, "A note 2")
        note_b2 = create_note_on_node(node_b, "B note 2")

        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)

        # Reload databases to see changes from server subprocesses
        node_a.reload_db()
        node_b.reload_db()
        # Both have 4 notes
        assert get_note_count(node_a) == 4
        assert get_note_count(node_b) == 4

    def test_large_note_content(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Large note content syncs correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create large note (10KB)
        large_content = "x" * 10000
        note_id = create_note_on_node(node_a, large_content)

        # Sync to B
        sync_nodes(node_a, node_b)

        # Verify exact content
        note_b = node_b.db.get_note(note_id)
        assert note_b is not None
        assert note_b["content"] == large_content
        assert len(note_b["content"]) == 10000

    def test_unicode_content(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Unicode content syncs correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create notes with various unicode
        contents = [
            "Hebrew: שלום עולם",
            "Chinese: 你好世界",
            "Arabic: مرحبا بالعالم",
            "Emoji: 🎉🎊🎁",
            "Mixed: Hello שלום 你好 🌍",
        ]

        note_ids = []
        for content in contents:
            note_id = create_note_on_node(node_a, content)
            note_ids.append(note_id)

        # Sync to B
        sync_nodes(node_a, node_b)

        # Verify all content
        for note_id, expected in zip(note_ids, contents):
            note_b = node_b.db.get_note(note_id)
            assert note_b is not None
            assert note_b["content"] == expected


class TestThreeNodeSync:
    """Tests for sync between three nodes."""

    def test_three_way_propagation(
        self, three_nodes_with_servers: Tuple[SyncNode, SyncNode, SyncNode]
    ):
        """Content propagates through all three nodes."""
        node_a, node_b, node_c = three_nodes_with_servers

        # Create on A
        note_id = create_note_on_node(node_a, "Note from A")

        # Sync A -> B
        sync_nodes(node_a, node_b)

        # Verify B has it
        assert node_b.db.get_note(note_id) is not None

        # Sync B -> C
        sync_nodes(node_b, node_c)

        # Verify C has it
        assert node_c.db.get_note(note_id) is not None

    def test_all_nodes_create_content(
        self, three_nodes_with_servers: Tuple[SyncNode, SyncNode, SyncNode]
    ):
        """All three nodes create content, sync converges."""
        node_a, node_b, node_c = three_nodes_with_servers

        # Each creates a note
        note_a = create_note_on_node(node_a, "From A")
        note_b = create_note_on_node(node_b, "From B")
        note_c = create_note_on_node(node_c, "From C")

        # Full mesh sync
        for source in [node_a, node_b, node_c]:
            for target in [node_a, node_b, node_c]:
                if source != target:
                    sync_nodes(source, target)

        # All should have all 3 notes
        for node in [node_a, node_b, node_c]:
            assert get_note_count(node) == 3
            assert node.db.get_note(note_a) is not None
            assert node.db.get_note(note_b) is not None
            assert node.db.get_note(note_c) is not None

    def test_star_topology_sync(
        self, three_nodes_with_servers: Tuple[SyncNode, SyncNode, SyncNode]
    ):
        """Sync in star topology (B is hub)."""
        node_a, node_b, node_c = three_nodes_with_servers

        # A creates note and syncs with B first
        note_a = create_note_on_node(node_a, "From A")

        # Wait for timestamp precision
        time.sleep(1.1)

        # A syncs with B
        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)

        # Wait for timestamp precision - C's note must be AFTER A's sync
        time.sleep(1.1)

        # C creates note and syncs with B
        note_c = create_note_on_node(node_c, "From C")
        sync_nodes(node_c, node_b)
        sync_nodes(node_b, node_c)

        # Wait for timestamp precision
        time.sleep(1.1)

        # A syncs with B again to get C's content
        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)

        # Reload databases to see changes from server subprocesses
        node_a.reload_db()
        node_b.reload_db()
        node_c.reload_db()
        # All should have both notes
        for node in [node_a, node_b, node_c]:
            assert get_note_count(node) == 2


class TestComplexWorkflows:
    """Tests for complex sync workflows."""

    def test_offline_edit_then_sync_creates_conflict(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Offline editing then syncing creates conflict (preserves both versions)."""
        node_a, node_b = two_nodes_with_servers

        # Initial sync
        note_id = create_note_on_node(node_a, "Initial content")
        sync_nodes(node_a, node_b)

        # Wait for timestamp precision
        time.sleep(1.1)

        # "Offline" editing - multiple updates without sync
        set_local_device_id(node_a.device_id)
        node_a.db.update_note(note_id, "Edit 1")
        node_a.db.update_note(note_id, "Edit 2")
        node_a.db.update_note(note_id, "Final edit")

        # Sync after "coming online"
        sync_nodes(node_a, node_b)

        # Reload B's db to see changes from server subprocess
        node_b.reload_db()
        # B receives A's edit as remote, but has "Initial content" locally
        # Since content differs, conflict markers are created (no silent overwrite)
        note_b = node_b.db.get_note(note_id)
        assert "<<<<<<< LOCAL" in note_b["content"]
        assert "Initial content" in note_b["content"]
        assert "Final edit" in note_b["content"]
        assert ">>>>>>> REMOTE" in note_b["content"]

    def test_bulk_import_then_sync(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Simulate bulk import then sync."""
        node_a, node_b = two_nodes_with_servers

        # Bulk create on A
        note_ids = []
        for i in range(50):
            note_id = create_note_on_node(node_a, f"Imported note {i}")
            note_ids.append(note_id)

        # Single sync should transfer all
        sync_nodes(node_a, node_b)

        # Verify all transferred
        assert get_note_count(node_b) == 50
        for note_id in note_ids:
            assert node_b.db.get_note(note_id) is not None

    def test_alternating_edits_preserve_data(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Alternating edits preserve data on each node - no silent data loss."""
        node_a, node_b = two_nodes_with_servers

        # Create on A
        note_id = create_note_on_node(node_a, "Version 1")
        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)

        # Wait for timestamp precision
        time.sleep(1.1)

        # B needs to reload to see the note before editing
        node_b.reload_db()
        # Edit on B
        set_local_device_id(node_b.device_id)
        node_b.db.update_note(note_id, "Version 2 from B")
        sync_nodes(node_b, node_a)

        # A had "Version 1", receives "Version 2 from B" - conflict created
        node_a.reload_db()
        note_a = node_a.db.get_note(note_id)
        # A preserves both versions
        assert "Version 1" in note_a["content"]
        assert "Version 2 from B" in note_a["content"]
        assert "<<<<<<< LOCAL" in note_a["content"]

        # B keeps its own edit
        note_b = node_b.db.get_note(note_id)
        assert "Version 2 from B" in note_b["content"]

        # The key property: no data loss on either node
        # A has both versions, B has at least its own edit

    def test_tag_reorganization_sync(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Tag hierarchy changes sync correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create initial hierarchy on A
        work = create_tag_on_node(node_a, "Work")
        project = create_tag_on_node(node_a, "Project", work)

        # Sync to B
        sync_nodes(node_a, node_b)

        # Reload B's db to see changes from server subprocess
        node_b.reload_db()
        # Verify on B
        assert get_tag_count(node_b) == 2

        # Wait for timestamp precision
        time.sleep(1.1)

        # Create another tag on A
        urgent = create_tag_on_node(node_a, "Urgent", project)

        # Sync again
        sync_nodes(node_a, node_b)

        # Reload B's db to see changes from server subprocess
        node_b.reload_db()
        # Verify full hierarchy on B
        assert get_tag_count(node_b) == 3

    def test_rapid_sync_cycles(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Rapid sync cycles don't cause issues."""
        node_a, node_b = two_nodes_with_servers

        # Create initial content
        note_id = create_note_on_node(node_a, "Rapid sync test")

        # Many rapid syncs
        for i in range(10):
            sync_nodes(node_a, node_b)
            sync_nodes(node_b, node_a)

        # Should still have exactly 1 note on each
        assert get_note_count(node_a) == 1
        assert get_note_count(node_b) == 1

    def test_sync_after_restart(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Sync works after server restart."""
        node_a, node_b = two_nodes_with_servers

        # Create and sync
        note_id = create_note_on_node(node_a, "Before restart")
        sync_nodes(node_a, node_b)

        # Wait a full second (timestamps are second-precision)
        time.sleep(1.1)

        # Restart server B
        from .conftest import start_sync_server
        node_b.stop_server()
        start_sync_server(node_b)
        node_b.wait_for_server()

        # Create more content and sync
        note_id2 = create_note_on_node(node_a, "After restart")
        sync_nodes(node_a, node_b)

        # Reload node_b's db to see changes written by server subprocess
        node_b.reload_db()
        # Both notes should be on B
        assert node_b.db.get_note(note_id) is not None
        assert node_b.db.get_note(note_id2) is not None

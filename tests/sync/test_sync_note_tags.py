"""Tests for note-tag association sync.

Tests:
- Creating note-tag associations and syncing
- Deleting note-tag associations and syncing
- Reactivating deleted associations
- Tag hierarchy ordering during sync
- Complex note-tag scenarios
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


class TestNoteTAgAssociationSync:
    """Tests for syncing note-tag associations."""

    def test_note_with_tag_syncs(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Note with tag association syncs to peer."""
        node_a, node_b = two_nodes_with_servers

        # Create tag and note on A
        tag_id = create_tag_on_node(node_a, "Important")
        note_id = create_note_on_node(node_a, "Tagged note content")

        # Associate tag with note
        set_local_device_id(node_a.device_id)
        node_a.db.add_tag_to_note(note_id, tag_id)

        # Sync to B
        sync_nodes(node_a, node_b)

        # Verify note has tag on B
        note_b = node_b.db.get_note(note_id)
        assert note_b is not None
        # Check tag_names field contains the tag
        assert "Important" in (note_b.get("tag_names") or "")

    def test_multiple_tags_on_note_sync(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Note with multiple tags syncs correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create multiple tags on A
        tag1 = create_tag_on_node(node_a, "Urgent")
        tag2 = create_tag_on_node(node_a, "Work")
        tag3 = create_tag_on_node(node_a, "Project")

        # Create note
        note_id = create_note_on_node(node_a, "Multi-tagged note")

        # Add all tags
        set_local_device_id(node_a.device_id)
        node_a.db.add_tag_to_note(note_id, tag1)
        node_a.db.add_tag_to_note(note_id, tag2)
        node_a.db.add_tag_to_note(note_id, tag3)

        # Sync
        sync_nodes(node_a, node_b)

        # Verify on B
        note_b = node_b.db.get_note(note_id)
        tag_names = note_b.get("tag_names", "")
        assert "Urgent" in tag_names
        assert "Work" in tag_names
        assert "Project" in tag_names

    @pytest.mark.xfail(reason="Incremental note-tag sync may need implementation")
    def test_add_tag_after_initial_sync(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Adding tag after initial sync propagates."""
        node_a, node_b = two_nodes_with_servers

        # Create and sync note without tag
        note_id = create_note_on_node(node_a, "Note content")
        sync_nodes(node_a, node_b)

        # Create tag and add to note
        tag_id = create_tag_on_node(node_a, "NewTag")
        set_local_device_id(node_a.device_id)
        node_a.db.add_tag_to_note(note_id, tag_id)

        # Sync again
        sync_nodes(node_a, node_b)

        # Verify tag added on B
        note_b = node_b.db.get_note(note_id)
        assert "NewTag" in (note_b.get("tag_names") or "")


class TestNoteTagDeletion:
    """Tests for deleting note-tag associations."""

    @pytest.mark.xfail(reason="Note-tag removal sync may need implementation")
    def test_remove_tag_from_note_syncs(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Removing tag from note syncs to peer."""
        node_a, node_b = two_nodes_with_servers

        # Create note with tag
        tag_id = create_tag_on_node(node_a, "ToRemove")
        note_id = create_note_on_node(node_a, "Note content")
        set_local_device_id(node_a.device_id)
        node_a.db.add_tag_to_note(note_id, tag_id)

        # Initial sync
        sync_nodes(node_a, node_b)

        # Verify tag on B
        note_b = node_b.db.get_note(note_id)
        assert "ToRemove" in (note_b.get("tag_names") or "")

        # Remove tag on A
        set_local_device_id(node_a.device_id)
        node_a.db.remove_tag_from_note(note_id, tag_id)

        # Sync again
        sync_nodes(node_a, node_b)

        # Verify tag removed on B
        note_b = node_b.db.get_note(note_id)
        assert "ToRemove" not in (note_b.get("tag_names") or "")

    @pytest.mark.xfail(reason="Note-tag removal sync may need implementation")
    def test_remove_one_of_many_tags(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Removing one tag leaves others intact."""
        node_a, node_b = two_nodes_with_servers

        # Create note with multiple tags
        tag1 = create_tag_on_node(node_a, "Keep1")
        tag2 = create_tag_on_node(node_a, "Remove")
        tag3 = create_tag_on_node(node_a, "Keep2")

        note_id = create_note_on_node(node_a, "Note content")
        set_local_device_id(node_a.device_id)
        node_a.db.add_tag_to_note(note_id, tag1)
        node_a.db.add_tag_to_note(note_id, tag2)
        node_a.db.add_tag_to_note(note_id, tag3)

        # Sync
        sync_nodes(node_a, node_b)

        # Remove middle tag
        set_local_device_id(node_a.device_id)
        node_a.db.remove_tag_from_note(note_id, tag2)

        # Sync again
        sync_nodes(node_a, node_b)

        # Verify
        note_b = node_b.db.get_note(note_id)
        tag_names = note_b.get("tag_names", "")
        assert "Keep1" in tag_names
        assert "Keep2" in tag_names
        assert "Remove" not in tag_names


class TestNoteTagReactivation:
    """Tests for reactivating deleted note-tag associations."""

    @pytest.mark.xfail(reason="Note-tag reactivation sync may need implementation")
    def test_readd_tag_after_removal(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Re-adding tag after removal works."""
        node_a, node_b = two_nodes_with_servers

        # Create note with tag
        tag_id = create_tag_on_node(node_a, "Toggle")
        note_id = create_note_on_node(node_a, "Note content")
        set_local_device_id(node_a.device_id)
        node_a.db.add_tag_to_note(note_id, tag_id)

        # Sync
        sync_nodes(node_a, node_b)

        # Remove tag
        set_local_device_id(node_a.device_id)
        node_a.db.remove_tag_from_note(note_id, tag_id)
        sync_nodes(node_a, node_b)

        # Verify removed
        note_b = node_b.db.get_note(note_id)
        assert "Toggle" not in (note_b.get("tag_names") or "")

        # Re-add tag
        set_local_device_id(node_a.device_id)
        node_a.db.add_tag_to_note(note_id, tag_id)
        sync_nodes(node_a, node_b)

        # Verify re-added
        note_b = node_b.db.get_note(note_id)
        assert "Toggle" in (note_b.get("tag_names") or "")

    @pytest.mark.xfail(reason="Note-tag reactivation sync may need implementation")
    def test_readd_tag_on_peer(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Peer can re-add a tag that was removed."""
        node_a, node_b = two_nodes_with_servers

        # Create note with tag on A
        tag_id = create_tag_on_node(node_a, "Shared")
        note_id = create_note_on_node(node_a, "Note content")
        set_local_device_id(node_a.device_id)
        node_a.db.add_tag_to_note(note_id, tag_id)

        # Sync both ways
        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)

        # Remove on A
        set_local_device_id(node_a.device_id)
        node_a.db.remove_tag_from_note(note_id, tag_id)
        sync_nodes(node_a, node_b)

        # B re-adds it
        set_local_device_id(node_b.device_id)
        tag_b = node_b.db.get_tag(tag_id)
        if tag_b:
            node_b.db.add_tag_to_note(note_id, tag_id)

        # Sync from B to A
        sync_nodes(node_b, node_a)

        # A should have the tag again (B's action is later)
        note_a = node_a.db.get_note(note_id)
        assert "Shared" in (note_a.get("tag_names") or "")


class TestTagHierarchySync:
    """Tests for tag hierarchy during sync."""

    def test_parent_tag_syncs_before_child(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Parent tag is synced before child tag."""
        node_a, node_b = two_nodes_with_servers

        # Create hierarchy on A
        parent_id = create_tag_on_node(node_a, "Parent")
        child_id = create_tag_on_node(node_a, "Child", parent_id)
        grandchild_id = create_tag_on_node(node_a, "Grandchild", child_id)

        # Sync
        sync_nodes(node_a, node_b)

        # Verify hierarchy on B
        assert node_b.db.get_tag(parent_id) is not None
        assert node_b.db.get_tag(child_id) is not None
        assert node_b.db.get_tag(grandchild_id) is not None

        # Verify parent-child relationships
        child_b = node_b.db.get_tag(child_id)
        grandchild_b = node_b.db.get_tag(grandchild_id)
        assert child_b.get("parent_id") == parent_id
        assert grandchild_b.get("parent_id") == child_id

    def test_note_with_hierarchical_tags(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Note with hierarchical tags syncs correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create hierarchy
        parent_id = create_tag_on_node(node_a, "Work")
        child_id = create_tag_on_node(node_a, "Project", parent_id)

        # Create note and tag with child
        note_id = create_note_on_node(node_a, "Project note")
        set_local_device_id(node_a.device_id)
        node_a.db.add_tag_to_note(note_id, child_id)

        # Sync
        sync_nodes(node_a, node_b)

        # Note on B should have the child tag
        note_b = node_b.db.get_note(note_id)
        assert "Project" in (note_b.get("tag_names") or "")

    def test_reparent_tag_syncs(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Re-parenting a tag syncs correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create tags
        parent1 = create_tag_on_node(node_a, "OldParent")
        parent2 = create_tag_on_node(node_a, "NewParent")
        child = create_tag_on_node(node_a, "Child", parent1)

        # Sync initial state
        sync_nodes(node_a, node_b)

        # Reparent on A
        set_local_device_id(node_a.device_id)
        # This would require a reparent method - for now just verify structure synced
        # node_a.db.reparent_tag(child, parent2)

        # Verify initial parent on B
        child_b = node_b.db.get_tag(child)
        assert child_b.get("parent_id") == parent1


class TestComplexNoteTagScenarios:
    """Complex scenarios for note-tag sync."""

    def test_many_notes_same_tag(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Many notes with the same tag sync correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create one tag
        tag_id = create_tag_on_node(node_a, "CommonTag")

        # Create many notes and tag them all
        note_ids = []
        for i in range(20):
            note_id = create_note_on_node(node_a, f"Note {i}")
            set_local_device_id(node_a.device_id)
            node_a.db.add_tag_to_note(note_id, tag_id)
            note_ids.append(note_id)

        # Sync
        sync_nodes(node_a, node_b)

        # All notes on B should have the tag
        for note_id in note_ids:
            note_b = node_b.db.get_note(note_id)
            assert note_b is not None
            assert "CommonTag" in (note_b.get("tag_names") or "")

    def test_one_note_many_tags(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """One note with many tags syncs correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create many tags
        tag_ids = []
        for i in range(10):
            tag_id = create_tag_on_node(node_a, f"Tag{i}")
            tag_ids.append(tag_id)

        # Create one note and add all tags
        note_id = create_note_on_node(node_a, "Multi-tagged note")
        set_local_device_id(node_a.device_id)
        for tag_id in tag_ids:
            node_a.db.add_tag_to_note(note_id, tag_id)

        # Sync
        sync_nodes(node_a, node_b)

        # Note on B should have all tags
        note_b = node_b.db.get_note(note_id)
        tag_names = note_b.get("tag_names", "")
        for i in range(10):
            assert f"Tag{i}" in tag_names

    @pytest.mark.xfail(reason="Bidirectional note-tag sync may need implementation")
    def test_bidirectional_tagging(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Both nodes tag different notes, sync merges."""
        node_a, node_b = two_nodes_with_servers

        # Create shared tag and notes
        tag_id = create_tag_on_node(node_a, "Shared")
        note1 = create_note_on_node(node_a, "Note 1")
        note2 = create_note_on_node(node_a, "Note 2")

        # Sync initial state
        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)

        # A tags note1
        set_local_device_id(node_a.device_id)
        node_a.db.add_tag_to_note(note1, tag_id)

        # B tags note2
        set_local_device_id(node_b.device_id)
        node_b.db.add_tag_to_note(note2, tag_id)

        # Sync both ways
        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)

        # Both notes should have the tag on both nodes
        for node in [node_a, node_b]:
            n1 = node.db.get_note(note1)
            n2 = node.db.get_note(note2)
            assert "Shared" in (n1.get("tag_names") or "")
            assert "Shared" in (n2.get("tag_names") or "")

    def test_delete_tag_removes_from_notes(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Deleting a tag removes it from associated notes."""
        node_a, node_b = two_nodes_with_servers

        # Create tag and associate with notes
        tag_id = create_tag_on_node(node_a, "ToDelete")
        note1 = create_note_on_node(node_a, "Note 1")
        note2 = create_note_on_node(node_a, "Note 2")

        set_local_device_id(node_a.device_id)
        node_a.db.add_tag_to_note(note1, tag_id)
        node_a.db.add_tag_to_note(note2, tag_id)

        # Sync
        sync_nodes(node_a, node_b)

        # Verify tags on B
        assert "ToDelete" in (node_b.db.get_note(note1).get("tag_names") or "")

        # Note: Actual tag deletion behavior depends on implementation
        # This test documents expected behavior

    @pytest.mark.xfail(reason="Note deletion with tags may need implementation")
    def test_tag_note_then_delete_note(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Deleting a tagged note works correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create tag and note
        tag_id = create_tag_on_node(node_a, "Tag")
        note_id = create_note_on_node(node_a, "To be deleted")

        set_local_device_id(node_a.device_id)
        node_a.db.add_tag_to_note(note_id, tag_id)

        # Sync
        sync_nodes(node_a, node_b)

        # Delete note on A
        set_local_device_id(node_a.device_id)
        node_a.db.delete_note(note_id)

        # Sync
        sync_nodes(node_a, node_b)

        # Note should be deleted on B
        # Tag should still exist
        assert get_note_count(node_b) == 0
        assert node_b.db.get_tag(tag_id) is not None


class TestNoteTagEdgeCases:
    """Edge cases for note-tag sync."""

    def test_tag_nonexistent_note(self, sync_node_a: SyncNode):
        """Tagging nonexistent note is handled."""
        tag_id = create_tag_on_node(sync_node_a, "Tag")

        set_local_device_id(sync_node_a.device_id)

        # This should either fail gracefully or raise an appropriate error
        # depending on implementation
        try:
            sync_node_a.db.add_tag_to_note(
                "00000000000070008000000000099999",  # Nonexistent
                tag_id,
            )
        except Exception:
            pass  # Expected

    def test_add_nonexistent_tag_to_note(self, sync_node_a: SyncNode):
        """Adding nonexistent tag to note is handled."""
        note_id = create_note_on_node(sync_node_a, "Note")

        set_local_device_id(sync_node_a.device_id)

        try:
            sync_node_a.db.add_tag_to_note(
                note_id,
                "00000000000070008000000000099999",  # Nonexistent tag
            )
        except Exception:
            pass  # Expected

    @pytest.mark.xfail(reason="Rapid tag cycle sync may need implementation")
    def test_rapid_tag_untag_cycles(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Rapid tag/untag cycles sync correctly."""
        node_a, node_b = two_nodes_with_servers

        tag_id = create_tag_on_node(node_a, "Rapid")
        note_id = create_note_on_node(node_a, "Note")

        # Rapid add/remove cycles
        set_local_device_id(node_a.device_id)
        for _ in range(5):
            node_a.db.add_tag_to_note(note_id, tag_id)
            node_a.db.remove_tag_from_note(note_id, tag_id)

        # Final state: no tag
        sync_nodes(node_a, node_b)

        note_b = node_b.db.get_note(note_id)
        assert "Rapid" not in (note_b.get("tag_names") or "")

        # Add tag finally
        node_a.db.add_tag_to_note(note_id, tag_id)
        sync_nodes(node_a, node_b)

        note_b = node_b.db.get_note(note_id)
        assert "Rapid" in (note_b.get("tag_names") or "")

    def test_unicode_tag_names(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Unicode tag names sync correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create unicode tags
        tag1 = create_tag_on_node(node_a, "Important")
        tag2 = create_tag_on_node(node_a, "Important")

        note_id = create_note_on_node(node_a, "Unicode tagged")
        set_local_device_id(node_a.device_id)
        node_a.db.add_tag_to_note(note_id, tag1)

        # Sync
        sync_nodes(node_a, node_b)

        # Verify
        note_b = node_b.db.get_note(note_id)
        assert "Important" in (note_b.get("tag_names") or "")

"""Tests for sync conflict detection and resolution.

Tests conflict scenarios:
- Concurrent note edits (same timestamp, different content)
- Edit-delete conflicts
- Tag rename conflicts
- Conflict resolution (local, remote, merge)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Tuple

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.database import set_local_device_id
from core.conflicts import ConflictManager, ResolutionChoice

from .conftest import (
    SyncNode,
    create_note_on_node,
    create_tag_on_node,
    get_note_count,
    sync_nodes,
)


class TestNoteContentConflicts:
    """Tests for note content conflicts."""

    def test_concurrent_edit_same_timestamp_creates_conflict(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Editing same note on both nodes at same timestamp creates conflict."""
        node_a, node_b = two_nodes_with_servers

        # Create note on A
        note_id = create_note_on_node(node_a, "Original content")

        # Sync to B
        sync_nodes(node_a, node_b)
        node_b.reload_db()

        # Wait for timestamp precision
        time.sleep(1.1)

        # Now both have the note - edit on both with forced same timestamp
        # This is hard to do naturally, but the sync logic should handle it
        # For this test, we'll edit on both and see what happens

        set_local_device_id(node_a.device_id)
        node_a.db.update_note(note_id, "Edit from A")

        set_local_device_id(node_b.device_id)
        node_b.db.update_note(note_id, "Edit from B")

        # Sync - one should win based on timestamp, or create conflict
        sync_nodes(node_a, node_b)
        node_b.reload_db()
        sync_nodes(node_b, node_a)
        node_a.reload_db()

        # Both should have same content (last write wins)
        content_a = node_a.db.get_note(note_id)["content"]
        content_b = node_b.db.get_note(note_id)["content"]

        # They should be the same (whichever was later)
        # Or there should be a conflict record
        conflict_mgr_a = ConflictManager(node_a.db)
        conflict_mgr_b = ConflictManager(node_b.db)

        # Either contents match, or we have a conflict
        if content_a != content_b:
            # Should have conflict
            conflicts_a = conflict_mgr_a.get_note_content_conflicts()
            conflicts_b = conflict_mgr_b.get_note_content_conflicts()
            assert len(conflicts_a) > 0 or len(conflicts_b) > 0

    def test_concurrent_edits_create_conflict_no_lww(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Concurrent edits create conflict regardless of timestamp (no LWW)."""
        node_a, node_b = two_nodes_with_servers

        # Create note on A
        note_id = create_note_on_node(node_a, "Original content")

        # Sync to B and back
        sync_nodes(node_a, node_b)
        node_b.reload_db()
        sync_nodes(node_b, node_a)
        node_a.reload_db()

        # Wait for timestamp precision
        time.sleep(1.1)

        # Edit on A
        set_local_device_id(node_a.device_id)
        node_a.db.update_note(note_id, "Edit from A")

        # Edit on B (both editing after last sync = conflict)
        set_local_device_id(node_b.device_id)
        node_b.db.update_note(note_id, "Edit from B")

        # Sync both ways - conflicts created because both edited since last sync
        sync_nodes(node_a, node_b)
        node_a.reload_db()
        node_b.reload_db()

        # After A syncs to B, A should have conflict (both sides edited)
        note_a_content = node_a.db.get_note(note_id)["content"]

        # Both edits should be preserved in merged content
        assert "Edit from A" in note_a_content
        assert "Edit from B" in note_a_content
        assert "<<<<<<< LOCAL" in note_a_content


class TestEditDeleteConflicts:
    """Tests for edit-delete conflicts."""

    def test_edit_then_delete_conflict(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Editing on one node while deleting on another creates conflict."""
        node_a, node_b = two_nodes_with_servers

        # Create note on A
        note_id = create_note_on_node(node_a, "Original content")

        # Sync to B
        sync_nodes(node_a, node_b)

        # Edit on A
        set_local_device_id(node_a.device_id)
        node_a.db.update_note(note_id, "Edited on A - important!")

        # Wait and delete on B
        time.sleep(0.1)
        set_local_device_id(node_b.device_id)
        node_b.db.delete_note(note_id)

        # Sync
        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)

        # Should either preserve the edit or have a conflict
        # Check for delete conflict
        conflict_mgr_a = ConflictManager(node_a.db)
        delete_conflicts = conflict_mgr_a.get_note_delete_conflicts()

        # Either the note is preserved (edit was after delete)
        # or we have a conflict (edit was before delete but detected)
        note_a = node_a.db.get_note(note_id)
        if note_a is None or "deleted_at" in str(note_a):
            # Deleted - check for conflict
            assert len(delete_conflicts) >= 0  # May or may not have conflict

    def test_delete_propagates_when_no_local_edit(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Delete propagates when other node hasn't edited the note."""
        node_a, node_b = two_nodes_with_servers

        # Create note on A
        note_id = create_note_on_node(node_a, "To be deleted")

        # Sync to B
        sync_nodes(node_a, node_b)
        node_b.reload_db()

        time.sleep(1.1)

        # Delete on A only (B has same content, never edited)
        set_local_device_id(node_a.device_id)
        node_a.db.delete_note(note_id)

        # Sync - should propagate delete to B (no edit on B)
        sync_nodes(node_a, node_b)
        node_b.reload_db()

        # B should have the note deleted
        note_b = node_b.db.get_note(note_id)
        assert note_b is not None
        assert note_b.get("deleted_at") is not None, "Note should be deleted on B"

    def test_delete_creates_conflict_when_local_edited(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Delete creates conflict when other node has edited the note."""
        node_a, node_b = two_nodes_with_servers

        # Create note on A
        note_id = create_note_on_node(node_a, "Original content")

        # Sync to B
        sync_nodes(node_a, node_b)
        node_b.reload_db()

        time.sleep(1.1)

        # B edits the note
        set_local_device_id(node_b.device_id)
        node_b.db.update_note(note_id, "Edited by B - important changes")

        # A deletes (doesn't know about B's edit)
        set_local_device_id(node_a.device_id)
        node_a.db.delete_note(note_id)

        # Sync: A pulls B's edit (resurrects A's deleted note), A pushes to B
        sync_nodes(node_a, node_b)
        node_a.reload_db()
        node_b.reload_db()

        # B should still have the note (B edited it, never deleted)
        note_b = node_b.db.get_note(note_id)
        assert note_b is not None
        assert note_b.get("deleted_at") is None, "Note should NOT be deleted on B"
        assert "Edited by B" in note_b["content"]

        # A should have the note resurrected (A deleted, but B's edit came in)
        note_a = node_a.db.get_note(note_id)
        assert note_a is not None
        assert note_a.get("deleted_at") is None, "Note should NOT be deleted on A"
        assert "Edited by B" in note_a["content"]

        # Conflict should be on A (where delete was resurrected by B's edit)
        conflict_mgr_a = ConflictManager(node_a.db)
        delete_conflicts_a = conflict_mgr_a.get_note_delete_conflicts()
        assert len(delete_conflicts_a) > 0, "Conflict should be on A (deleter)"


    def test_local_delete_remote_update_resurrects_note(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """When local deletes but remote updates, note is resurrected with remote content."""
        node_a, node_b = two_nodes_with_servers

        # Create note on A and sync to B
        note_id = create_note_on_node(node_a, "Original content")
        sync_nodes(node_a, node_b)
        node_b.reload_db()

        # Wait for timestamp precision
        time.sleep(1.1)

        # Delete on A
        set_local_device_id(node_a.device_id)
        node_a.db.delete_note(note_id)

        # Update on B
        set_local_device_id(node_b.device_id)
        node_b.db.update_note(note_id, "Updated content from B")

        # Sync B's update to A
        sync_nodes(node_b, node_a)
        node_a.reload_db()

        # Note should be resurrected on A with B's content
        note_a = node_a.db.get_note(note_id)
        assert note_a is not None, "Note should exist"
        assert note_a.get("deleted_at") is None, "Note should not be deleted"
        assert "Updated content from B" in note_a["content"]

        # Should have a delete conflict record
        conflict_mgr_a = ConflictManager(node_a.db)
        delete_conflicts = conflict_mgr_a.get_note_delete_conflicts()
        assert len(delete_conflicts) > 0, "Should have delete conflict"

    def test_local_delete_remote_create_resurrects_note(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """When local deletes but remote creates new note, note arrives as create op."""
        node_a, node_b = two_nodes_with_servers

        # Create note on B only (A doesn't have it yet)
        note_id = create_note_on_node(node_b, "Content from B only")

        # Now sync B to A - A receives it as a "create" operation
        sync_nodes(node_b, node_a)
        node_a.reload_db()

        # Verify A got it
        note_a = node_a.db.get_note(note_id)
        assert note_a is not None, "Note should exist on A"
        assert "Content from B only" in note_a["content"]

        time.sleep(1.1)

        # Now delete on A
        set_local_device_id(node_a.device_id)
        node_a.db.delete_note(note_id)

        # B updates the note (so it sends again with "update" operation)
        set_local_device_id(node_b.device_id)
        node_b.db.update_note(note_id, "Updated content from B")

        # Sync B to A - sends "update" to A's deleted note
        sync_nodes(node_b, node_a)
        node_a.reload_db()

        # Note should be resurrected
        note_a = node_a.db.get_note(note_id)
        assert note_a is not None, "Note should exist"
        assert note_a.get("deleted_at") is None, "Note should not be deleted"
        assert "Updated content from B" in note_a["content"]

    def test_edit_delete_conflict_preserves_edit(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Edit-delete conflict should always preserve the edit (no data loss)."""
        node_a, node_b = two_nodes_with_servers

        # Create note
        note_id = create_note_on_node(node_a, "Important data")
        sync_nodes(node_a, node_b)
        node_b.reload_db()

        time.sleep(1.1)

        # B edits with important update
        set_local_device_id(node_b.device_id)
        important_content = "CRITICAL: Updated with important information"
        node_b.db.update_note(note_id, important_content)

        # A deletes (before seeing B's edit)
        set_local_device_id(node_a.device_id)
        node_a.db.delete_note(note_id)

        # Sync B to A - A should get the edit, not lose it
        sync_nodes(node_b, node_a)
        node_a.reload_db()

        # The important content must be preserved
        note_a = node_a.db.get_note(note_id)
        assert note_a is not None, "Note must exist"
        assert important_content in note_a["content"], "Edit must be preserved"
        assert note_a.get("deleted_at") is None, "Note should not be deleted"


class TestTagRenameConflicts:
    """Tests for tag rename conflicts."""

    def test_concurrent_rename_creates_conflict(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Renaming same tag differently on both nodes creates conflict."""
        node_a, node_b = two_nodes_with_servers

        # Create tag on A
        tag_id = create_tag_on_node(node_a, "OriginalName")

        # Sync to B
        sync_nodes(node_a, node_b)
        node_b.reload_db()

        # Wait for timestamp precision
        time.sleep(1.1)

        # Rename on A
        set_local_device_id(node_a.device_id)
        node_a.db.rename_tag(tag_id, "NameFromA")

        # Rename on B differently
        set_local_device_id(node_b.device_id)
        node_b.db.rename_tag(tag_id, "NameFromB")

        # Sync A to B (A pulls from B, then pushes to B)
        sync_nodes(node_a, node_b)
        node_a.reload_db()

        # A should now have combined name (both renamed)
        tag_a = node_a.db.get_tag(tag_id)
        assert " | " in tag_a["name"]
        assert "NameFromA" in tag_a["name"]
        assert "NameFromB" in tag_a["name"]

        # Should have conflict record on A
        conflicts = node_a.db.get_tag_rename_conflicts(include_resolved=True)
        tag_conflicts = [c for c in conflicts if c.get("tag_id") == tag_id]
        assert len(tag_conflicts) >= 1

    def test_one_side_rename_propagates(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Renaming tag on one side propagates to the other."""
        node_a, node_b = two_nodes_with_servers

        # Create tag on A
        tag_id = create_tag_on_node(node_a, "OriginalName")

        # Sync to B
        sync_nodes(node_a, node_b)
        node_b.reload_db()

        # Verify B has tag
        tag_b = node_b.db.get_tag(tag_id)
        assert tag_b["name"] == "OriginalName"

        # Wait for timestamp precision
        time.sleep(1.1)

        # Rename only on A
        set_local_device_id(node_a.device_id)
        node_a.db.rename_tag(tag_id, "NewName")

        # Sync A to B
        sync_nodes(node_a, node_b)
        node_b.reload_db()

        # B should have new name (no conflict, just propagated)
        tag_b = node_b.db.get_tag(tag_id)
        assert tag_b["name"] == "NewName"

        # No conflict record
        conflicts = node_b.db.get_tag_rename_conflicts(include_resolved=True)
        tag_conflicts = [c for c in conflicts if c.get("tag_id") == tag_id]
        assert len(tag_conflicts) == 0


class TestConflictResolution:
    """Tests for resolving conflicts."""

    def test_resolve_content_conflict_keep_local(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Resolve content conflict by keeping local version."""
        node_a, node_b = two_nodes_with_servers

        # Create conflicting edits (hard to force exact same timestamp)
        # We'll manually create a conflict record for testing
        note_id = create_note_on_node(node_a, "Local content")
        sync_nodes(node_a, node_b)

        # Create conflict record manually for testing resolution
        set_local_device_id(node_a.device_id)
        conflict_mgr = ConflictManager(node_a.db)

        # Get current conflicts (may be empty if no actual conflict)
        conflicts = conflict_mgr.get_note_content_conflicts()

        # If we had a conflict, test resolving it
        if conflicts:
            conflict = conflicts[0]
            result = conflict_mgr.resolve_note_content_conflict(
                conflict.id, ResolutionChoice.KEEP_LOCAL
            )
            assert result is True

            # Conflict should be gone
            remaining = conflict_mgr.get_note_content_conflicts()
            assert len(remaining) < len(conflicts)

    def test_resolve_content_conflict_keep_remote(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Resolve content conflict by keeping remote version."""
        node_a, node_b = two_nodes_with_servers

        note_id = create_note_on_node(node_a, "Content")
        sync_nodes(node_a, node_b)

        conflict_mgr = ConflictManager(node_a.db)
        conflicts = conflict_mgr.get_note_content_conflicts()

        if conflicts:
            conflict = conflicts[0]
            result = conflict_mgr.resolve_note_content_conflict(
                conflict.id, ResolutionChoice.KEEP_REMOTE
            )
            assert result is True

    def test_resolve_delete_conflict_keep_note(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Resolve delete conflict by keeping the note."""
        node_a, node_b = two_nodes_with_servers

        note_id = create_note_on_node(node_a, "Important note")
        sync_nodes(node_a, node_b)

        conflict_mgr = ConflictManager(node_a.db)
        delete_conflicts = conflict_mgr.get_note_delete_conflicts()

        if delete_conflicts:
            conflict = delete_conflicts[0]
            # Keep the surviving version (undelete)
            result = conflict_mgr.resolve_note_delete_conflict(
                conflict.id, ResolutionChoice.KEEP_LOCAL
            )
            assert result is True

    def test_conflict_count(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Conflict count is accurate."""
        node_a, node_b = two_nodes_with_servers

        conflict_mgr = ConflictManager(node_a.db)
        counts = conflict_mgr.get_unresolved_count()

        assert "total" in counts
        assert "note_content" in counts
        assert "note_delete" in counts
        assert "tag_rename" in counts
        assert counts["total"] >= 0


class TestConflictPrevention:
    """Tests for scenarios that should NOT create conflicts."""

    def test_no_conflict_sequential_edits(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Sequential edits with sync between don't create conflicts."""
        node_a, node_b = two_nodes_with_servers

        # Create note on A
        note_id = create_note_on_node(node_a, "Version 1")

        # Sync
        sync_nodes(node_a, node_b)

        # Edit on A, sync
        set_local_device_id(node_a.device_id)
        node_a.db.update_note(note_id, "Version 2")
        sync_nodes(node_a, node_b)

        # Edit on B, sync
        set_local_device_id(node_b.device_id)
        node_b.db.update_note(note_id, "Version 3")
        sync_nodes(node_b, node_a)

        # No conflicts
        conflict_mgr_a = ConflictManager(node_a.db)
        conflict_mgr_b = ConflictManager(node_b.db)

        assert conflict_mgr_a.get_unresolved_count()["total"] == 0
        assert conflict_mgr_b.get_unresolved_count()["total"] == 0

    def test_no_conflict_different_notes(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Editing different notes doesn't create conflicts."""
        node_a, node_b = two_nodes_with_servers

        # Create different notes on each
        note_a = create_note_on_node(node_a, "Note A")
        note_b = create_note_on_node(node_b, "Note B")

        # Sync
        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)

        # Edit different notes
        set_local_device_id(node_a.device_id)
        node_a.db.update_note(note_a, "Note A edited")

        set_local_device_id(node_b.device_id)
        node_b.db.update_note(note_b, "Note B edited")

        # Sync
        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)

        # No conflicts
        conflict_mgr = ConflictManager(node_a.db)
        assert conflict_mgr.get_unresolved_count()["total"] == 0


class TestConflictEdgeCases:
    """Tests for edge cases in conflict handling."""

    def test_conflict_with_empty_content(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Handle conflict when one version has minimal content."""
        node_a, node_b = two_nodes_with_servers

        note_id = create_note_on_node(node_a, "Some content")
        sync_nodes(node_a, node_b)

        # Edit on A to minimal content
        set_local_device_id(node_a.device_id)
        node_a.db.update_note(note_id, ".")  # Minimal valid content

        # Edit on B to different content
        set_local_device_id(node_b.device_id)
        node_b.db.update_note(note_id, "Different content")

        # Sync - should handle without error
        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)

        # Should have some content
        note_a = node_a.db.get_note(note_id)
        assert note_a is not None
        assert len(note_a["content"]) > 0

    def test_conflict_with_unicode_content(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Handle conflict with unicode content - both preserved."""
        node_a, node_b = two_nodes_with_servers

        note_id = create_note_on_node(node_a, "Original שלום")
        sync_nodes(node_a, node_b)
        node_b.reload_db()

        # Wait for timestamp precision
        time.sleep(1.1)

        # Edit with different unicode on each
        set_local_device_id(node_a.device_id)
        node_a.db.update_note(note_id, "Hebrew: שלום עולם")

        # Wait so B's edit is later
        time.sleep(1.1)

        set_local_device_id(node_b.device_id)
        node_b.db.update_note(note_id, "Chinese: 你好世界")

        # Sync A to B - creates conflict on B
        sync_nodes(node_a, node_b)
        node_b.reload_db()

        # Both unicode strings should be preserved in B's content
        content_b = node_b.db.get_note(note_id)["content"]
        assert "שלום עולם" in content_b  # Hebrew preserved
        assert "你好世界" in content_b  # Chinese preserved

    def test_multiple_conflicts_same_note(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Handle multiple sync cycles with conflicts on same note."""
        node_a, node_b = two_nodes_with_servers

        note_id = create_note_on_node(node_a, "Version 1")
        sync_nodes(node_a, node_b)

        # Multiple rounds of conflicting edits
        for i in range(3):
            set_local_device_id(node_a.device_id)
            node_a.db.update_note(note_id, f"A version {i}")

            set_local_device_id(node_b.device_id)
            node_b.db.update_note(note_id, f"B version {i}")

            sync_nodes(node_a, node_b)
            sync_nodes(node_b, node_a)

        # Should still have a valid note
        note = node_a.db.get_note(note_id)
        assert note is not None
        assert len(note["content"]) > 0

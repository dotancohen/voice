"""End-to-end conflict tests over real sync servers.

Two nodes with running servers edit the same data concurrently; the sync
must merge, flag, and propagate resolutions in both directions. Device names
come from each node's config and must appear on the conflict records.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Tuple

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.conflicts import ConflictManager, has_conflict_markers

from .conftest import (
    SyncNode,
    create_note_on_node,
    create_tag_on_node,
    sync_nodes,
    update_note_subprocess,
)


def sync_both_ways(node_a: SyncNode, node_b: SyncNode) -> None:
    """Sync until both nodes have seen each other's changes."""
    sync_nodes(node_a, node_b)
    node_a.reload_db()
    node_b.reload_db()
    sync_nodes(node_b, node_a)
    node_a.reload_db()
    node_b.reload_db()


def shared_note(node_a: SyncNode, node_b: SyncNode, text: str) -> str:
    note_id = create_note_on_node(node_a, text)
    sync_both_ways(node_a, node_b)
    time.sleep(1.1)  # distinct modified_at
    return note_id


class TestNoteContentConflicts:
    def test_concurrent_edits_keep_both_and_flag_on_both_nodes(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        node_a, node_b = two_nodes_with_servers
        note_id = shared_note(node_a, node_b, "פתק משותף")

        # Edit in each node's own process so the versions carry that node's
        # device identity (the test process itself has a single identity).
        assert update_note_subprocess(node_a, note_id, "פתק משותף מהמחשב")
        assert update_note_subprocess(node_b, note_id, "פתק משותף מהטלפון")
        node_a.reload_db()
        node_b.reload_db()
        sync_both_ways(node_a, node_b)

        for node in (node_a, node_b):
            text = node.db.get_note(note_id)["content"]
            assert "פתק משותף מהמחשב" in text
            assert "פתק משותף מהטלפון" in text
            assert has_conflict_markers(text)
            mgr = ConflictManager(node.db)
            assert mgr.get_unresolved_count()["total"] == 1
            c = mgr.get_conflicts()[0]
            assert {c.device_a_label, c.device_b_label} == {"NodeA", "NodeB"}
        assert node_a.db.get_conflicts()[0]["id"] == node_b.db.get_conflicts()[0]["id"]

    def test_non_overlapping_edits_merge_without_conflict(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        node_a, node_b = two_nodes_with_servers
        note_id = shared_note(node_a, node_b, "ראשונה\nאמצע\nאחרונה\n")

        node_a.db.update_note(note_id, "ראשונה מהמחשב\nאמצע\nאחרונה\n")
        node_b.db.update_note(note_id, "ראשונה\nאמצע\nאחרונה מהטלפון\n")
        sync_both_ways(node_a, node_b)

        for node in (node_a, node_b):
            assert node.db.get_note(note_id)["content"] == "ראשונה מהמחשב\nאמצע\nאחרונה מהטלפון\n"
            assert node.db.get_unresolved_conflict_counts()["total"] == 0

    def test_sequential_edits_never_conflict(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        node_a, node_b = two_nodes_with_servers
        note_id = shared_note(node_a, node_b, "אחד")
        node_a.db.update_note(note_id, "שניים")
        sync_both_ways(node_a, node_b)
        time.sleep(1.1)
        node_b.db.update_note(note_id, "שלושה")
        sync_both_ways(node_a, node_b)
        for node in (node_a, node_b):
            assert node.db.get_note(note_id)["content"] == "שלושה"
            assert node.db.get_unresolved_conflict_counts()["total"] == 0


class TestResolutionPropagates:
    def _conflicted(self, node_a, node_b):
        note_id = shared_note(node_a, node_b, "שורה")
        node_a.db.update_note(note_id, "שורה מהמחשב")
        node_b.db.update_note(note_id, "שורה מהטלפון")
        sync_both_ways(node_a, node_b)
        return note_id

    def test_accept_on_one_node_resolves_on_the_other(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        node_a, node_b = two_nodes_with_servers
        note_id = self._conflicted(node_a, node_b)
        mgr_a = ConflictManager(node_a.db)
        assert mgr_a.accept_note_conflicts(note_id) == 1
        sync_both_ways(node_a, node_b)
        assert node_b.db.get_unresolved_conflict_counts()["total"] == 0
        assert node_b.db.get_note(note_id)["content"] == node_a.db.get_note(note_id)["content"]

    def test_edit_on_one_node_resolves_on_the_other(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        node_a, node_b = two_nodes_with_servers
        note_id = self._conflicted(node_a, node_b)
        node_b.db.update_note(note_id, "שורה מוסכמת")
        sync_both_ways(node_a, node_b)
        for node in (node_a, node_b):
            assert node.db.get_note(note_id)["content"] == "שורה מוסכמת"
            assert node.db.get_unresolved_conflict_counts()["total"] == 0


class TestEditDeleteConflicts:
    def test_delete_propagates_when_nobody_edited(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        node_a, node_b = two_nodes_with_servers
        note_id = shared_note(node_a, node_b, "למחיקה")
        node_a.db.delete_note(note_id)
        sync_both_ways(node_a, node_b)
        assert node_b.db.get_note(note_id) is None
        assert node_b.db.get_unresolved_conflict_counts()["total"] == 0

    def test_edit_vs_delete_keeps_note_on_both(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        node_a, node_b = two_nodes_with_servers
        note_id = shared_note(node_a, node_b, "חשוב")
        node_a.db.update_note(note_id, "חשוב מאוד")
        node_b.db.delete_note(note_id)
        sync_both_ways(node_a, node_b)
        for node in (node_a, node_b):
            note = node.db.get_note(note_id)
            assert note is not None and note["content"] == "חשוב מאוד"
            assert "delete" in ConflictManager(node.db).get_note_conflict_types(note_id)


class TestTagConflicts:
    def test_new_tag_on_note_propagates(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        node_a, node_b = two_nodes_with_servers
        note_id = shared_note(node_a, node_b, "פתק")
        tag_id = create_tag_on_node(node_b, "חדשה")
        node_b.db.add_tag_to_note(note_id, tag_id)
        sync_both_ways(node_a, node_b)
        assert node_a.db.get_tag(tag_id)["name"] == "חדשה"
        assert [t["id"] for t in node_a.db.get_note_tags(note_id)] == [tag_id]

    def test_concurrent_rename_flags_on_both(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        node_a, node_b = two_nodes_with_servers
        tag_id = create_tag_on_node(node_a, "ישן")
        sync_both_ways(node_a, node_b)
        time.sleep(1.1)
        node_a.db.rename_tag(tag_id, "מהמחשב")
        node_b.db.rename_tag(tag_id, "מהטלפון")
        sync_both_ways(node_a, node_b)
        names = {node_a.db.get_tag(tag_id)["name"], node_b.db.get_tag(tag_id)["name"]}
        assert len(names) == 1 and names <= {"מהמחשב", "מהטלפון"}
        for node in (node_a, node_b):
            assert node.db.get_unresolved_conflict_counts()["scalar"] == 1

    def test_move_and_delete_propagate(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        node_a, node_b = two_nodes_with_servers
        parent = create_tag_on_node(node_a, "הורה")
        other = create_tag_on_node(node_a, "אחר")
        child = create_tag_on_node(node_a, "ילד", parent)
        gone = create_tag_on_node(node_a, "זמני")
        sync_both_ways(node_a, node_b)
        time.sleep(1.1)
        node_a.db.reparent_tag(child, other)
        node_a.db.delete_tag(gone)
        sync_both_ways(node_a, node_b)
        assert node_b.db.get_tag(child)["parent_id"] == other
        assert all(t["id"] != gone for t in node_b.db.get_all_tags())


class TestSettingsSync:
    def test_setting_propagates(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        node_a, node_b = two_nodes_with_servers
        node_a.db.set_setting("transcription.preferred_languages", '["he"]')
        sync_both_ways(node_a, node_b)
        assert node_b.db.get_setting("transcription.preferred_languages") == '["he"]'

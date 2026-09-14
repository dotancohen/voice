"""Unit tests for versioned-field conflict handling.

Two databases in one process exchange their sync feeds directly (no server),
exactly as two devices would, and the tests check that:

- concurrent edits are merged, and overlapping edits keep both versions;
- every conflict is recorded on every device and resolved everywhere;
- deletes never win over edits, links never vanish silently;
- tag renames, moves and deletes, note-tag links and transcriptions are
  versioned and merged the same way.

Hebrew text throughout: this is a Hebrew-first application.
"""

from __future__ import annotations

from typing import Tuple

import pytest
from voicecore import apply_sync_changes

from core.conflicts import (
    KIND_DELETE,
    KIND_MEMBERSHIP,
    KIND_SCALAR,
    KIND_TEXT,
    MARKER_A,
    MARKER_B,
    MARKER_SEP,
    Conflict,
    ConflictManager,
    FieldVersion,
    MergeResult,
    auto_merge_if_possible,
    diff3_merge,
    get_diff_preview,
    has_conflict_markers,
)
from core.database import Database

DEV_A = "0000000000007000800000000000000a"
DEV_B = "0000000000007000800000000000000b"


def push_all(src: Database, dst: Database, device_id: str) -> dict:
    """Push everything src has to dst, as device_id."""
    changes = src.get_changes_after_seq(0, None, 100000)["changes"]
    for c in changes:
        c.setdefault("device_id", device_id)
    return apply_sync_changes(dst._rust_db, changes, device_id, "Device " + device_id[-1].upper())


def exchange(a: Database, b: Database) -> None:
    push_all(a, b, DEV_A)
    push_all(b, a, DEV_B)


@pytest.fixture
def pair() -> Tuple[Database, Database]:
    a = Database(":memory:")
    b = Database(":memory:")
    yield a, b
    a.close()
    b.close()


def content(db: Database, note_id: str) -> str:
    return db.get_note(note_id)["content"]


# ---------------------------------------------------------------------------
# Note content
# ---------------------------------------------------------------------------


class TestNoteContentMerge:
    def test_edit_propagates(self, pair):
        a, b = pair
        note_id = a.create_note("שלום")
        exchange(a, b)
        a.update_note(note_id, "שלום עולם")
        exchange(a, b)
        assert content(b, note_id) == "שלום עולם"
        assert b.get_unresolved_conflict_counts()["total"] == 0

    def test_non_overlapping_edits_merge_cleanly(self, pair):
        a, b = pair
        note_id = a.create_note("ראשונה\nאמצע\nאחרונה\n")
        exchange(a, b)
        a.update_note(note_id, "ראשונה מהמחשב\nאמצע\nאחרונה\n")
        b.update_note(note_id, "ראשונה\nאמצע\nאחרונה מהטלפון\n")
        exchange(a, b)
        exchange(a, b)
        for db in (a, b):
            assert content(db, note_id) == "ראשונה מהמחשב\nאמצע\nאחרונה מהטלפון\n"
            assert db.get_unresolved_conflict_counts()["total"] == 0

    def test_overlapping_edits_keep_both_and_flag(self, pair):
        a, b = pair
        note_id = a.create_note("משפט אחד")
        exchange(a, b)
        a.update_note(note_id, "משפט אחד מהמחשב")
        b.update_note(note_id, "משפט אחד מהטלפון")
        exchange(a, b)
        exchange(a, b)
        for db in (a, b):
            text = content(db, note_id)
            assert "משפט אחד מהמחשב" in text
            assert "משפט אחד מהטלפון" in text
            assert MARKER_A in text and MARKER_SEP in text and MARKER_B in text
            assert has_conflict_markers(text)
            counts = db.get_unresolved_conflict_counts()
            assert counts[KIND_TEXT] == 1
            assert counts["total"] == 1
            assert ConflictManager(db).get_note_conflict_types(note_id) == ["content"]
        # Both devices record the same conflict
        assert a.get_conflicts()[0]["id"] == b.get_conflicts()[0]["id"]

    def test_no_silent_overwrite_when_pull_arrives_before_local_push(self, pair):
        """A's unsynced edit must survive a pull from B (no last-write-wins)."""
        a, b = pair
        note_id = a.create_note("בסיס\nאמצע\nסוף\n")
        exchange(a, b)
        b.update_note(note_id, "בסיס\nאמצע\nסוף מהטלפון\n")
        a.update_note(note_id, "בסיס מהמחשב\nאמצע\nסוף\n")
        push_all(b, a, DEV_B)
        assert content(a, note_id) == "בסיס מהמחשב\nאמצע\nסוף מהטלפון\n"

    def test_third_device_converges(self, pair):
        a, b = pair
        c = Database(":memory:")
        try:
            note_id = a.create_note("טקסט")
            exchange(a, b)
            exchange(a, c)
            a.update_note(note_id, "טקסט א")
            b.update_note(note_id, "טקסט ב")
            exchange(a, b)
            exchange(a, c)
            exchange(b, c)
            exchange(a, b)
            texts = {content(db, note_id) for db in (a, b, c)}
            assert len(texts) == 1, texts
            ids = {db.get_conflicts()[0]["id"] for db in (a, b, c)}
            assert len(ids) == 1
        finally:
            c.close()


class TestConflictResolution:
    def _conflicted(self, pair):
        a, b = pair
        note_id = a.create_note("שורה")
        exchange(a, b)
        a.update_note(note_id, "שורה מהמחשב")
        b.update_note(note_id, "שורה מהטלפון")
        exchange(a, b)
        exchange(a, b)
        return a, b, note_id

    def test_accept_resolves_here_and_on_peer(self, pair):
        a, b, note_id = self._conflicted(pair)
        mgr = ConflictManager(a)
        conflict = mgr.get_conflicts()[0]
        assert mgr.accept(conflict.id)
        assert mgr.get_unresolved_count()["total"] == 0
        # The text keeps the markers: the user accepted it as it is
        assert has_conflict_markers(content(a, note_id))
        exchange(a, b)
        assert b.get_unresolved_conflict_counts()["total"] == 0
        assert content(b, note_id) == content(a, note_id)
        assert mgr.get_conflict(conflict.id).is_resolved

    def test_saving_note_resolves_and_propagates(self, pair):
        a, b, note_id = self._conflicted(pair)
        a.update_note(note_id, "שורה מהמחשב ומהטלפון")
        assert a.get_unresolved_conflict_counts()["total"] == 0
        exchange(a, b)
        assert content(b, note_id) == "שורה מהמחשב ומהטלפון"
        assert b.get_unresolved_conflict_counts()["total"] == 0

    def test_resolve_with_content(self, pair):
        a, b, note_id = self._conflicted(pair)
        mgr = ConflictManager(a)
        ok, conflict, err = mgr.find_and_resolve_conflict(mgr.get_conflicts()[0].id[:8], "שורה מוסכמת")
        assert ok and err is None
        assert content(a, note_id) == "שורה מוסכמת"
        exchange(a, b)
        assert content(b, note_id) == "שורה מוסכמת"

    def test_resolve_twice_is_rejected(self, pair):
        a, _b, _note_id = self._conflicted(pair)
        mgr = ConflictManager(a)
        cid = mgr.get_conflicts()[0].id
        assert mgr.accept(cid)
        ok, conflict, err = mgr.find_and_resolve_conflict(cid)
        assert not ok and "already resolved" in err

    def test_unknown_conflict(self, pair):
        a, _b = pair
        ok, conflict, err = ConflictManager(a).find_and_resolve_conflict("ffff")
        assert not ok and conflict is None and "not found" in err

    def test_accept_note_conflicts_accepts_every_conflict_of_the_note(self, pair):
        a, b, note_id = self._conflicted(pair)
        # Add a tag-link conflict on the same note
        tag_id = a.create_tag("תגית")
        a.add_tag_to_note(note_id, tag_id)
        exchange(a, b)
        a.remove_tag_from_note(note_id, tag_id)
        b.remove_tag_from_note(note_id, tag_id)
        b.add_tag_to_note(note_id, tag_id)
        exchange(a, b)
        mgr = ConflictManager(a)
        kinds = set(mgr.get_note_conflict_types(note_id))
        assert kinds == {"content", "tag"}
        assert len(mgr.get_note_conflicts(note_id)) == 2
        assert mgr.accept_note_conflicts(note_id) == 2
        assert mgr.get_note_conflict_types(note_id) == []

    def test_conflict_versions_and_history(self, pair):
        a, _b, note_id = self._conflicted(pair)
        mgr = ConflictManager(a)
        conflict = mgr.get_conflicts()[0]
        versions = mgr.get_conflict_versions(conflict)
        assert versions.base.content == "שורה"
        assert {versions.version_a.content, versions.version_b.content} == {"שורה מהמחשב", "שורה מהטלפון"}
        assert has_conflict_markers(versions.merge.content)
        history = mgr.get_field_history("note", note_id, "content")
        assert [v.content for v in history][:1] == ["שורה"]
        assert len(history) >= 4  # root, two edits, merge
        assert all(isinstance(v, FieldVersion) for v in history)

    def test_describe_names_devices(self, pair):
        a, _b, note_id = self._conflicted(pair)
        mgr = ConflictManager(a)
        conflict = mgr.get_conflicts()[0]
        text = conflict.describe()
        assert "Note content edited on both" in text
        assert conflict.display_kind == "content"
        assert conflict.note_id == note_id
        banner = mgr.describe_note_conflicts(note_id)
        assert "CONFLICT (content)" in banner
        d = conflict.to_dict()
        assert d["kind"] == KIND_TEXT and d["note_id"] == note_id


# ---------------------------------------------------------------------------
# Deletes
# ---------------------------------------------------------------------------


class TestDeleteConflicts:
    def test_plain_delete_propagates(self, pair):
        a, b = pair
        note_id = a.create_note("למחיקה")
        exchange(a, b)
        a.delete_note(note_id)
        exchange(a, b)
        assert b.get_note(note_id) is None
        assert b.get_note_raw(note_id)["deleted_at"] is not None
        assert b.get_unresolved_conflict_counts()["total"] == 0

    def test_edit_vs_delete_keeps_the_note_and_flags(self, pair):
        a, b = pair
        note_id = a.create_note("חשוב")
        exchange(a, b)
        a.update_note(note_id, "חשוב מאוד")
        b.delete_note(note_id)
        exchange(a, b)
        exchange(a, b)
        for db in (a, b):
            note = db.get_note(note_id)
            assert note is not None, "the edit must not be lost"
            assert note["content"] == "חשוב מאוד"
            assert db.get_unresolved_conflict_counts()[KIND_DELETE] == 1
            assert "delete" in ConflictManager(db).get_note_conflict_types(note_id)

    def test_delete_conflict_accept_then_delete_again(self, pair):
        a, b = pair
        note_id = a.create_note("חשוב")
        exchange(a, b)
        a.update_note(note_id, "חשוב מאוד")
        b.delete_note(note_id)
        exchange(a, b)
        exchange(a, b)
        mgr = ConflictManager(b)
        assert mgr.accept_note_conflicts(note_id) == 1
        # The user on B, having seen the edit, deletes again: a normal delete
        b.delete_note(note_id)
        exchange(a, b)
        assert a.get_note(note_id) is None
        assert a.get_unresolved_conflict_counts()["total"] == 0


# ---------------------------------------------------------------------------
# Tags, note-tag links
# ---------------------------------------------------------------------------


class TestTagSync:
    def test_new_tag_and_link_propagate_together(self, pair):
        a, b = pair
        note_id = a.create_note("פתק")
        exchange(a, b)
        tag_id = b.create_tag("עבודה")
        b.add_tag_to_note(note_id, tag_id)
        exchange(a, b)
        assert a.get_tag(tag_id)["name"] == "עבודה"
        assert [t["id"] for t in a.get_note_tags(note_id)] == [tag_id]

    def test_remove_tag_propagates(self, pair):
        a, b = pair
        note_id = a.create_note("פתק")
        tag_id = a.create_tag("עבודה")
        a.add_tag_to_note(note_id, tag_id)
        exchange(a, b)
        a.remove_tag_from_note(note_id, tag_id)
        exchange(a, b)
        assert b.get_note_tags(note_id) == []
        assert b.get_unresolved_conflict_counts()["total"] == 0

    def test_remove_vs_readd_keeps_link_and_flags(self, pair):
        a, b = pair
        note_id = a.create_note("פתק")
        tag_id = a.create_tag("עבודה")
        a.add_tag_to_note(note_id, tag_id)
        exchange(a, b)
        a.remove_tag_from_note(note_id, tag_id)
        b.remove_tag_from_note(note_id, tag_id)
        b.add_tag_to_note(note_id, tag_id)
        exchange(a, b)
        exchange(a, b)
        for db in (a, b):
            assert [t["id"] for t in db.get_note_tags(note_id)] == [tag_id]
            assert db.get_unresolved_conflict_counts()[KIND_MEMBERSHIP] == 1
            assert "tag" in ConflictManager(db).get_note_conflict_types(note_id)

    def test_rename_propagates(self, pair):
        a, b = pair
        tag_id = a.create_tag("ישן")
        exchange(a, b)
        a.rename_tag(tag_id, "חדש")
        exchange(a, b)
        assert b.get_tag(tag_id)["name"] == "חדש"

    def test_rename_on_both_keeps_one_and_flags(self, pair):
        a, b = pair
        tag_id = a.create_tag("ישן")
        exchange(a, b)
        a.rename_tag(tag_id, "מהמחשב")
        b.rename_tag(tag_id, "מהטלפון")
        exchange(a, b)
        exchange(a, b)
        names = {a.get_tag(tag_id)["name"], b.get_tag(tag_id)["name"]}
        assert len(names) == 1, "both devices converge on the same name"
        assert names <= {"מהמחשב", "מהטלפון"}
        for db in (a, b):
            assert db.get_unresolved_conflict_counts()[KIND_SCALAR] == 1
            c = ConflictManager(db).get_entity_conflicts("tag", tag_id)[0]
            assert c.field == "name"
            versions = ConflictManager(db).get_conflict_versions(c)
            assert {versions.version_a.content, versions.version_b.content} == {"מהמחשב", "מהטלפון"}

    def test_move_propagates(self, pair):
        a, b = pair
        parent = a.create_tag("הורה")
        other = a.create_tag("הורה אחר")
        child = a.create_tag("ילד", parent_id=parent)
        exchange(a, b)
        a.reparent_tag(child, other)
        exchange(a, b)
        assert b.get_tag(child)["parent_id"] == other

    def test_delete_tag_propagates(self, pair):
        a, b = pair
        tag_id = a.create_tag("זמני")
        exchange(a, b)
        a.delete_tag(tag_id)
        exchange(a, b)
        assert all(t["id"] != tag_id for t in b.get_all_tags())

    def test_delete_vs_rename_keeps_tag_and_flags(self, pair):
        a, b = pair
        tag_id = a.create_tag("תגית")
        exchange(a, b)
        a.rename_tag(tag_id, "תגית חשובה")
        b.delete_tag(tag_id)
        exchange(a, b)
        exchange(a, b)
        for db in (a, b):
            tag = db.get_tag(tag_id)
            assert tag is not None and tag["name"] == "תגית חשובה"
            assert db.get_unresolved_conflict_counts()[KIND_DELETE] == 1


# ---------------------------------------------------------------------------
# Transcriptions
# ---------------------------------------------------------------------------


class TestTranscriptionSync:
    def _note_with_transcription(self, a, b):
        note_id = a.create_note("הקלטה")
        audio_id = a.create_audio_file("recording.mp3")
        a.attach_to_note(note_id, audio_id, "audio_file")
        tr_id = a.create_transcription(audio_id, "טקסט מתומלל", "whisper")
        exchange(a, b)
        return note_id, audio_id, tr_id

    def test_edit_propagates(self, pair):
        a, b = pair
        _note_id, _audio_id, tr_id = self._note_with_transcription(a, b)
        a.update_transcription(tr_id, "טקסט מתומלל ומתוקן", state="original verified")
        exchange(a, b)
        tr = b.get_transcription(tr_id)
        assert tr["content"] == "טקסט מתומלל ומתוקן"
        assert "verified" in tr["state"]

    def test_edit_on_both_sides_is_flagged_on_the_note(self, pair):
        a, b = pair
        note_id, _audio_id, tr_id = self._note_with_transcription(a, b)
        a.update_transcription(tr_id, "טקסט מתומלל מהמחשב")
        b.update_transcription(tr_id, "טקסט מתומלל מהטלפון")
        exchange(a, b)
        exchange(a, b)
        for db in (a, b):
            text = db.get_transcription(tr_id)["content"]
            assert "מהמחשב" in text and "מהטלפון" in text and has_conflict_markers(text)
            mgr = ConflictManager(db)
            assert "transcription" in mgr.get_note_conflict_types(note_id)
            assert any(c.entity_type == "transcription" for c in mgr.get_note_conflicts(note_id))


# ---------------------------------------------------------------------------
# Synced settings
# ---------------------------------------------------------------------------


class TestSettingsSync:
    def test_setting_propagates(self, pair):
        a, b = pair
        a.set_setting("transcription.preferred_languages", '["he","en"]')
        exchange(a, b)
        assert b.get_setting("transcription.preferred_languages") == '["he","en"]'
        assert b.get_all_settings() == {"transcription.preferred_languages": '["he","en"]'}

    def test_setting_changed_on_both_keeps_one_and_flags(self, pair):
        a, b = pair
        a.set_setting("transcription.providers.assemblyai.api_key", "מפתח")
        exchange(a, b)
        a.set_setting("transcription.providers.assemblyai.api_key", "מפתח-א")
        b.set_setting("transcription.providers.assemblyai.api_key", "מפתח-ב")
        exchange(a, b)
        exchange(a, b)
        values = {a.get_setting("transcription.providers.assemblyai.api_key"),
                  b.get_setting("transcription.providers.assemblyai.api_key")}
        assert len(values) == 1 and values <= {"מפתח-א", "מפתח-ב"}
        assert a.get_unresolved_conflict_counts()[KIND_SCALAR] == 1
        c = ConflictManager(a).get_conflicts()[0]
        assert c.entity_type == "setting"


# ---------------------------------------------------------------------------
# Merge helpers (thin wrappers around Rust)
# ---------------------------------------------------------------------------


class TestMergeHelpers:
    def test_diff3_clean(self):
        r = diff3_merge("א\nב\nג\n", "א1\nב\nג\n", "א\nב\nג1\n")
        assert isinstance(r, MergeResult)
        assert r.has_conflicts is False
        assert r.merged_content == "א1\nב\nג1\n"

    def test_diff3_conflict_uses_symmetric_markers(self):
        r = diff3_merge("א\n", "ב\n", "ג\n")
        assert r.has_conflicts is True
        assert MARKER_A in r.merged_content and MARKER_B in r.merged_content

    def test_auto_merge(self):
        assert auto_merge_if_possible("א\nב\n", "א\nב\n") == "א\nב\n"
        assert auto_merge_if_possible("ב\n", "ג\n", "א\n") is None

    def test_diff_preview(self):
        assert "-ישן" in get_diff_preview("ישן\n", "חדש\n")
        assert "+חדש" in get_diff_preview("ישן\n", "חדש\n")

    def test_conflict_from_row_defaults(self):
        c = Conflict.from_row({
            "id": "x", "entity_type": "note", "entity_id": "n", "field": "content", "kind": KIND_TEXT,
            "version_a_id": "a", "version_b_id": "b", "merge_version_id": "m", "created_at": 1,
        })
        assert not c.is_resolved
        assert c.device_a_label == "unknown device"

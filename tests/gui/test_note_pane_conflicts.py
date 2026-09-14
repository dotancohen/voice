"""GUI tests for the conflict banner and the "Accept merge" button in NotePane."""

from __future__ import annotations

import pytest
from voicecore import apply_sync_changes

from core.conflicts import has_conflict_markers
from core.database import Database
from ui.note_pane import NotePane

PEER = "0000000000007000800000000000000b"


def make_conflict(db: Database) -> str:
    """A note edited here and, concurrently, on a peer; returns the note id."""
    peer = Database(":memory:")
    note_id = db.create_note("שורה משותפת")
    changes = db.get_changes_after_seq(0, None, 100000)["changes"]
    for c in changes:
        c.setdefault("device_id", "0000000000007000800000000000000a")
    apply_sync_changes(peer._rust_db, changes, "0000000000007000800000000000000a", "Desktop")
    db.update_note(note_id, "שורה משותפת מהמחשב")
    peer.update_note(note_id, "שורה משותפת מהטלפון")
    changes = peer.get_changes_after_seq(0, None, 100000)["changes"]
    for c in changes:
        c.setdefault("device_id", PEER)
    apply_sync_changes(db._rust_db, changes, PEER, "Phone")
    peer.close()
    return note_id


@pytest.mark.gui
class TestNotePaneConflicts:
    def test_banner_and_button_shown_for_conflicted_note(self, qapp, test_config, empty_db) -> None:
        note_id = make_conflict(empty_db)
        pane = NotePane(empty_db, audiofile_directory=None, config_dir=test_config.get_config_dir())
        pane.load_note(note_id)

        assert not pane.conflict_label.isHidden()
        assert "CONFLICT (content)" in pane.conflict_label.text()
        assert not pane.accept_conflict_button.isHidden()
        assert has_conflict_markers(pane.content_text.toPlainText())

    def test_accept_button_resolves_and_hides_banner(self, qapp, test_config, empty_db) -> None:
        note_id = make_conflict(empty_db)
        pane = NotePane(empty_db, audiofile_directory=None, config_dir=test_config.get_config_dir())
        pane.load_note(note_id)

        pane.accept_conflict_button.click()

        assert pane.conflict_label.isHidden()
        assert pane.accept_conflict_button.isHidden()
        assert empty_db.get_unresolved_conflict_counts()["total"] == 0
        # Accepting keeps the merged text as it is
        assert has_conflict_markers(empty_db.get_note(note_id)["content"])

    def test_saving_clean_text_resolves(self, qapp, test_config, empty_db) -> None:
        note_id = make_conflict(empty_db)
        pane = NotePane(empty_db, audiofile_directory=None, config_dir=test_config.get_config_dir())
        pane.load_note(note_id)
        pane.start_editing()
        pane.content_text.setPlainText("שורה משותפת מהמחשב ומהטלפון")
        pane.save_note()

        assert pane.conflict_label.isHidden()
        assert pane.accept_conflict_button.isHidden()
        assert empty_db.get_note(note_id)["content"] == "שורה משותפת מהמחשב ומהטלפון"
        assert empty_db.get_unresolved_conflict_counts()["total"] == 0

    def test_note_without_conflict_has_no_banner(self, qapp, test_config, empty_db) -> None:
        note_id = empty_db.create_note("פתק רגיל")
        pane = NotePane(empty_db, audiofile_directory=None, config_dir=test_config.get_config_dir())
        pane.load_note(note_id)
        assert pane.conflict_label.isHidden()
        assert pane.accept_conflict_button.isHidden()

    def test_clear_hides_banner(self, qapp, test_config, empty_db) -> None:
        note_id = make_conflict(empty_db)
        pane = NotePane(empty_db, audiofile_directory=None, config_dir=test_config.get_config_dir())
        pane.load_note(note_id)
        assert not pane.accept_conflict_button.isHidden()
        pane.clear()
        assert pane.conflict_label.isHidden()
        assert pane.accept_conflict_button.isHidden()


@pytest.mark.gui
class TestNotePaneHistoryAndResolve:
    def test_history_dialog_lists_versions_and_restores(self, qapp, test_config, empty_db) -> None:
        from ui.version_dialogs import HistoryDialog

        note_id = empty_db.create_note("גרסה ראשונה")
        empty_db.update_note(note_id, "גרסה שנייה")
        dialog = HistoryDialog(empty_db, note_id)
        labels = [dialog.version_list.item(i).text() for i in range(dialog.version_list.count())]
        assert len(labels) == 2
        assert "גרסה ראשונה" in labels[0]
        assert "current" in labels[1]

        dialog.version_list.setCurrentRow(0)
        assert dialog.restore_button.isEnabled()
        dialog._restore()
        assert dialog.restored
        assert empty_db.get_note(note_id)["content"] == "גרסה ראשונה"
        # The restore is a new version, nothing was lost
        assert len(empty_db.get_field_history("note", note_id, "content")) == 3

    def test_history_button_enabled_with_note(self, qapp, test_config, empty_db) -> None:
        note_id = empty_db.create_note("פתק")
        pane = NotePane(empty_db, audiofile_directory=None, config_dir=test_config.get_config_dir())
        assert not pane.history_button.isEnabled()
        pane.load_note(note_id)
        assert pane.history_button.isEnabled()
        pane.clear()
        assert not pane.history_button.isEnabled()

    def test_resolve_dialog_shows_both_sides_and_saves(self, qapp, test_config, empty_db) -> None:
        from core.conflicts import ConflictManager
        from ui.version_dialogs import ResolveConflictDialog

        note_id = make_conflict(empty_db)
        conflict = ConflictManager(empty_db).get_note_conflicts(note_id)[0]
        dialog = ResolveConflictDialog(empty_db, conflict)
        sides = {dialog.side_a.toPlainText(), dialog.side_b.toPlainText()}
        assert sides == {"שורה משותפת מהמחשב", "שורה משותפת מהטלפון"}
        assert dialog.base_view.toPlainText() == "שורה משותפת"
        assert has_conflict_markers(dialog.result_edit.toPlainText())

        dialog.result_edit.setPlainText("שורה משותפת מהמחשב ומהטלפון")
        dialog._save()
        assert dialog.resolved
        assert empty_db.get_note(note_id)["content"] == "שורה משותפת מהמחשב ומהטלפון"
        assert empty_db.get_unresolved_conflict_counts()["total"] == 0

    def test_resolve_button_shown_for_text_conflict(self, qapp, test_config, empty_db) -> None:
        note_id = make_conflict(empty_db)
        pane = NotePane(empty_db, audiofile_directory=None, config_dir=test_config.get_config_dir())
        pane.load_note(note_id)
        assert not pane.resolve_conflict_button.isHidden()
        pane.accept_conflict_button.click()
        assert pane.resolve_conflict_button.isHidden()

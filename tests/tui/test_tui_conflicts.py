"""TUI tests for the conflict banner and the "Accept merge" button."""

from __future__ import annotations

import pytest
from textual.widgets import Button, Label
from voicecore import apply_sync_changes

from core.conflicts import has_conflict_markers
from core.database import Database
from tui import NoteDetail, VoiceTUI

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


@pytest.mark.tui
class TestTuiConflicts:
    async def test_banner_and_button_shown(self, test_config, empty_db) -> None:
        note_id = make_conflict(empty_db)
        app = VoiceTUI(empty_db, test_config)
        async with app.run_test() as pilot:
            detail = app.query_one("#note-detail", NoteDetail)
            detail.load_note(note_id)
            await pilot.pause()

            warning = app.query_one("#note-conflict-warning", Label)
            assert warning.display is True
            assert "CONFLICT (content)" in str(warning.content)
            assert app.query_one("#accept-conflict-btn", Button).display is True

    async def test_accept_button_resolves(self, test_config, empty_db) -> None:
        note_id = make_conflict(empty_db)
        app = VoiceTUI(empty_db, test_config)
        async with app.run_test() as pilot:
            detail = app.query_one("#note-detail", NoteDetail)
            detail.load_note(note_id)
            await pilot.pause()

            detail.accept_conflicts()
            await pilot.pause()

            assert app.query_one("#note-conflict-warning", Label).display is False
            assert app.query_one("#accept-conflict-btn", Button).display is False
            assert empty_db.get_unresolved_conflict_counts()["total"] == 0
            assert has_conflict_markers(empty_db.get_note(note_id)["content"])

    async def test_accept_refused_while_editing(self, test_config, empty_db) -> None:
        note_id = make_conflict(empty_db)
        app = VoiceTUI(empty_db, test_config)
        async with app.run_test() as pilot:
            detail = app.query_one("#note-detail", NoteDetail)
            detail.load_note(note_id)
            detail.start_editing()
            await pilot.pause()

            detail.accept_conflicts()
            await pilot.pause()

            assert empty_db.get_unresolved_conflict_counts()["total"] == 1

    async def test_note_without_conflict_has_no_banner(self, test_config, empty_db) -> None:
        note_id = empty_db.create_note("פתק רגיל")
        app = VoiceTUI(empty_db, test_config)
        async with app.run_test() as pilot:
            detail = app.query_one("#note-detail", NoteDetail)
            detail.load_note(note_id)
            await pilot.pause()
            assert app.query_one("#note-conflict-warning", Label).display is False
            assert app.query_one("#accept-conflict-btn", Button).display is False


@pytest.mark.tui
class TestTuiHistoryAndResolve:
    async def test_history_screen_restores(self, test_config, empty_db) -> None:
        from tui import HistoryScreen

        note_id = empty_db.create_note("גרסה ראשונה")
        empty_db.update_note(note_id, "גרסה שנייה")
        app = VoiceTUI(empty_db, test_config)
        async with app.run_test() as pilot:
            screen = HistoryScreen(empty_db, note_id)
            app.push_screen(screen)
            await pilot.pause()
            assert len(screen.versions) == 2
            from textual.widgets import ListView
            screen.query_one("#history-list", ListView).index = 0
            await pilot.pause()
            assert screen.restore_selected()
            assert empty_db.get_note(note_id)["content"] == "גרסה ראשונה"

    async def test_resolve_screen_saves_result(self, test_config, empty_db) -> None:
        from core.conflicts import ConflictManager
        from tui import ResolveConflictScreen

        note_id = make_conflict(empty_db)
        conflict = ConflictManager(empty_db).get_note_conflicts(note_id)[0]
        app = VoiceTUI(empty_db, test_config)
        async with app.run_test() as pilot:
            screen = ResolveConflictScreen(empty_db, conflict)
            app.push_screen(screen)
            await pilot.pause()
            assert has_conflict_markers(screen.result_text())
            from textual.widgets import TextArea
            screen.query_one("#resolve-result", TextArea).text = "שורה משותפת מאוחדת"
            assert screen.save()
            assert empty_db.get_note(note_id)["content"] == "שורה משותפת מאוחדת"
            assert empty_db.get_unresolved_conflict_counts()["total"] == 0

    async def test_resolve_button_visible_only_for_text_conflict(self, test_config, empty_db) -> None:
        note_id = make_conflict(empty_db)
        app = VoiceTUI(empty_db, test_config)
        async with app.run_test() as pilot:
            detail = app.query_one("#note-detail", NoteDetail)
            detail.load_note(note_id)
            await pilot.pause()
            assert app.query_one("#resolve-conflict-btn", Button).display is True
            detail.accept_conflicts()
            await pilot.pause()
            assert app.query_one("#resolve-conflict-btn", Button).display is False

"""TUI tests for the trash bin screen.

Ctrl+T opens it; the notes in it can be recovered, and removing one for good
takes two presses so that a single keystroke can never destroy a note.
"""

from __future__ import annotations

import pytest
from textual.widgets import ListView

from src.core.config import Config
from src.core.database import Database
from src.tui import TrashScreen, VoiceTUI

pytestmark = pytest.mark.tui


class TestTrashScreen:
    async def test_ctrl_t_opens_the_trash(
        self, populated_db: Database, test_config: Config
    ) -> None:
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            await pilot.press("ctrl+t")
            await pilot.pause()
            assert isinstance(app.screen, TrashScreen)

    async def test_an_empty_trash_says_so(
        self, populated_db: Database, test_config: Config
    ) -> None:
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            await pilot.press("ctrl+t")
            await pilot.pause()
            screen = app.screen
            assert screen.notes == []
            assert "empty" in str(screen.query_one("#trash-title").render()).lower()

    async def test_a_deleted_note_is_listed_and_can_be_recovered(
        self, populated_db: Database, test_config: Config
    ) -> None:
        note_id = populated_db.create_note("פתק שנמחק ונמצא בפח")
        populated_db.delete_note(note_id)

        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            await pilot.press("ctrl+t")
            await pilot.pause()
            screen = app.screen
            assert [n["id"] for n in screen.notes] == [note_id]
            assert screen.query_one("#trash-list", ListView).index == 0

            screen.recover_selected()
            await pilot.pause()

            assert screen.notes == []
            assert populated_db.get_note(note_id) is not None
            assert screen.changed is True

    async def test_removing_for_good_takes_two_presses(
        self, populated_db: Database, test_config: Config
    ) -> None:
        """One keystroke must never destroy a note."""
        note_id = populated_db.create_note("להיעלם לתמיד")
        populated_db.delete_note(note_id)

        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            await pilot.press("ctrl+t")
            await pilot.pause()
            screen = app.screen

            screen.purge_selected()
            await pilot.pause()
            assert populated_db.get_note_raw(note_id) is not None, "the first press only asks"
            assert screen.confirm_purge_id == note_id

            screen.purge_selected()
            await pilot.pause()
            assert populated_db.get_note_raw(note_id) is None, "the second press does it"
            assert screen.notes == []

    async def test_moving_to_another_note_cancels_the_confirmation(
        self, populated_db: Database, test_config: Config
    ) -> None:
        """A press meant for one note must not destroy another."""
        first = populated_db.create_note("פתק ראשון")
        second = populated_db.create_note("פתק שני")
        populated_db.delete_note(first)
        populated_db.delete_note(second)

        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            await pilot.press("ctrl+t")
            await pilot.pause()
            screen = app.screen

            screen.purge_selected()
            await pilot.pause()
            assert screen.confirm_purge_id is not None

            listview = screen.query_one("#trash-list", ListView)
            listview.index = 1
            await pilot.pause()

            assert screen.confirm_purge_id is None
            assert populated_db.get_note_raw(first) is not None
            assert populated_db.get_note_raw(second) is not None

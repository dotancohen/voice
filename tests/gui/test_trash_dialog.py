"""Tests for the trash dialog: deleted notes, recovered or removed for good."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.database import Database
from ui.trash_dialog import TrashDialog, remove_audio_files


@pytest.mark.gui
class TestTrashDialog:
    """What the dialog lists and what its two buttons do."""

    def test_an_empty_trash_says_so(self, qapp, empty_db: Database) -> None:
        dialog = TrashDialog(empty_db)

        assert dialog.list_widget.count() == 0
        assert "empty" in dialog.summary_label.text().lower()
        assert not dialog.recover_button.isEnabled()
        assert not dialog.purge_button.isEnabled()

    def test_a_deleted_note_is_listed_with_its_text(
        self, qapp, empty_db: Database
    ) -> None:
        note_id = empty_db.create_note("פתק שנמחק ונמצא בפח")
        empty_db.delete_note(note_id)

        dialog = TrashDialog(empty_db)

        assert dialog.list_widget.count() == 1
        assert "פתק שנמחק ונמצא בפח" in dialog.list_widget.item(0).text()
        assert dialog.content_view.toPlainText() == "פתק שנמחק ונמצא בפח"
        assert dialog.recover_button.isEnabled()

    def test_recover_puts_the_note_back(self, qapp, empty_db: Database) -> None:
        note_id = empty_db.create_note("להחזיר אותי")
        empty_db.delete_note(note_id)
        dialog = TrashDialog(empty_db)

        dialog.recover_selected()

        assert dialog.list_widget.count() == 0
        assert empty_db.get_note(note_id) is not None
        assert dialog.changed is True

    def test_the_dialog_reports_whether_anything_changed(
        self, qapp, empty_db: Database
    ) -> None:
        """The caller reloads its list only when something happened."""
        empty_db.delete_note(empty_db.create_note("פתק"))
        dialog = TrashDialog(empty_db)

        assert dialog.changed is False

    def test_a_note_with_no_text_still_shows_a_row(
        self, qapp, empty_db: Database
    ) -> None:
        # A recording with no typed text is a common note; its row must not
        # be blank, or the user cannot tell what they are recovering.
        note_id = empty_db.create_note("")
        empty_db.delete_note(note_id)

        dialog = TrashDialog(empty_db)

        assert dialog.list_widget.count() == 1
        assert "(no text)" in dialog.list_widget.item(0).text()


@pytest.mark.gui
class TestTrashInTheMenu:
    """The dialog is only useful if the menu opens it."""

    def test_the_file_menu_offers_the_trash(
        self, qapp, test_config, empty_db: Database
    ) -> None:
        from ui.main_window import MainWindow

        window = MainWindow(test_config, empty_db)
        # The ampersand marks the keyboard mnemonic, so it is removed
        # before looking for the word.
        actions = [
            action.text().replace("&", "")
            for menu in window.menuBar().findChildren(type(window.menuBar().addMenu("x")))
            for action in menu.actions()
        ]

        assert any(text.startswith("Trash") for text in actions), actions


@pytest.mark.gui
class TestRemoveAudioFiles:
    """Deleting the files of recordings that were removed for good."""

    def test_the_recordings_files_are_deleted_by_their_stored_names(self, tmp_path: Path) -> None:
        audio_id = "0123456789abcdef0123456789abcdef"
        (tmp_path / "פגישה-89abcdef.ogg").write_bytes(b"audio")
        (tmp_path / "נשאר.ogg").write_bytes(b"audio")
        (tmp_path / f"{audio_id}.ogg").write_bytes(b"a file named by the id is not the recording's")

        removed = remove_audio_files([{"id": audio_id, "disk_name": "פגישה-89abcdef.ogg"}], tmp_path)

        assert removed == 1
        assert not (tmp_path / "פגישה-89abcdef.ogg").exists()
        assert (tmp_path / "נשאר.ogg").exists(), "another recording is untouched"
        assert (tmp_path / f"{audio_id}.ogg").exists(), "a file is never found by the id (FILE-15)"

    def test_nothing_to_delete_is_not_an_error(self, tmp_path: Path) -> None:
        assert remove_audio_files([], tmp_path) == 0
        assert remove_audio_files([{"id": "0123456789abcdef0123456789abcdef", "disk_name": "absent.ogg"}], tmp_path) == 0
        assert remove_audio_files([{"id": "0123456789abcdef0123456789abcdef", "disk_name": ""}], tmp_path) == 0
        assert remove_audio_files([{"id": "0123456789abcdef0123456789abcdef", "disk_name": "x.ogg"}], None) == 0

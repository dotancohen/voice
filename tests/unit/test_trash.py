"""The trash bin: deleted notes, recovered or removed for good.

Deleting a note has always been a soft delete, so a deleted note is not gone;
it is in the trash with its history and its recordings. These tests cover
what the user can do from there, and the one thing in the application that
really destroys something.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.database import Database


@pytest.mark.unit
class TestTrash:
    """Listing, recovering, and removing for good."""

    def test_a_deleted_note_is_in_the_trash_and_not_in_the_list(
        self, empty_db: Database
    ) -> None:
        note_id = empty_db.create_note("פתק שנמחק בטעות")
        assert empty_db.get_deleted_notes() == []

        empty_db.delete_note(note_id)

        assert empty_db.get_note(note_id) is None, "gone from the list"
        trash = empty_db.get_deleted_notes()
        assert [n["id"] for n in trash] == [note_id]
        assert trash[0]["content"] == "פתק שנמחק בטעות"
        assert trash[0]["deleted_at"] is not None

    def test_recovering_puts_the_note_back_with_its_text(
        self, empty_db: Database
    ) -> None:
        note_id = empty_db.create_note("שורה ראשונה\nשורה שנייה")
        empty_db.delete_note(note_id)

        assert empty_db.undelete_note(note_id) is True

        note = empty_db.get_note(note_id)
        assert note is not None
        assert note["content"] == "שורה ראשונה\nשורה שנייה"
        assert note["deleted_at"] is None
        assert empty_db.get_deleted_notes() == []

    def test_recovering_a_note_that_is_not_in_the_trash_says_so(
        self, empty_db: Database
    ) -> None:
        note_id = empty_db.create_note("פתק חי")
        assert empty_db.undelete_note(note_id) is False
        assert empty_db.undelete_note("00000000000040008000000000000099") is False

    def test_the_trash_is_newest_deletion_first(self, empty_db: Database) -> None:
        first = empty_db.create_note("נמחק ראשון")
        second = empty_db.create_note("נמחק שני")
        empty_db.delete_note(first)
        empty_db.delete_note(second)

        trash = empty_db.get_deleted_notes()

        assert [n["content"] for n in trash][0] == "נמחק שני"
        assert len(trash) == 2

    def test_removing_for_good_takes_the_note_and_its_recording(
        self, empty_db: Database
    ) -> None:
        note_id = empty_db.create_note("פתק עם הקלטה")
        audio_id = empty_db.create_audio_file("recording.ogg")
        empty_db.attach_to_note(note_id, audio_id, "audio_file")
        empty_db.delete_note(note_id)

        purged = empty_db.purge_note(note_id)
        # Each recording with the name its file has here (FILE-15)
        assert all(r["disk_name"] for r in purged), purged
        removed_audio = [r["id"] for r in purged]

        assert removed_audio == [audio_id], "the caller is told which files to delete"
        assert empty_db.get_note_raw(note_id) is None
        assert empty_db.get_deleted_notes() == []
        assert empty_db.get_audio_file(audio_id) is None

    def test_a_note_that_is_not_in_the_trash_cannot_be_removed_for_good(
        self, empty_db: Database
    ) -> None:
        """Deleting is one step and removing for good is another.

        A note that is still in the list has not been deleted, so there is
        nothing to empty out of the trash, and saying so is better than
        quietly destroying it.
        """
        note_id = empty_db.create_note("פתק חי")

        with pytest.raises(Exception):
            empty_db.purge_note(note_id)

        assert empty_db.get_note(note_id) is not None

    def test_a_recording_another_note_holds_is_kept(self, empty_db: Database) -> None:
        keeper = empty_db.create_note("הפתק שנשאר")
        doomed = empty_db.create_note("הפתק שנמחק")
        audio_id = empty_db.create_audio_file("shared.ogg")
        empty_db.attach_to_note(keeper, audio_id, "audio_file")
        empty_db.attach_to_note(doomed, audio_id, "audio_file")
        empty_db.delete_note(doomed)

        purged = empty_db.purge_note(doomed)
        # Each recording with the name its file has here (FILE-15)
        assert all(r["disk_name"] for r in purged), purged
        removed_audio = [r["id"] for r in purged]

        assert removed_audio == [], "nothing to delete from disk"
        assert empty_db.get_audio_file(audio_id) is not None
        assert len(empty_db.get_audio_files_for_note(keeper)) == 1

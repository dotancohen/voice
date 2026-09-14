"""Tests for note display cache rebuilding.

Tests that the di_cache_note_pane_display cache is rebuilt when:
- Note content is updated
- Tags are added/removed from notes
- Attachments are added/removed from notes
- Transcriptions are created/updated/deleted
- Audio file summary is updated
- Conflicts are resolved

The cache stores: tags (with full paths), conflicts, attachments (with audio files and transcriptions).

NOTE: These tests verify cache content changes rather than timestamp changes,
because SQLite datetime('now') has only second precision.
"""

from __future__ import annotations

import json

import pytest

from core.database import Database


def get_cache(db: Database, note_id: str) -> dict | None:
    """Get the parsed display cache for a note."""
    note = db.get_note(note_id)
    if note is None:
        return None
    cache_str = note.get("display_cache")
    if cache_str is None:
        return None
    return json.loads(cache_str)


@pytest.mark.unit
class TestCacheRebuildOnNoteUpdate:
    """Test cache is rebuilt when note content is updated."""

    def test_update_note_rebuilds_cache(self) -> None:
        """Updating note content should rebuild the cache.

        We verify by checking that cached_at exists after update,
        and that the cache reflects the current state.
        """
        db = Database(":memory:")

        # Create a note with a tag (so we can verify cache content)
        note_id = db.create_note("initial content")
        tag_id = db.create_tag("TestTag")
        db.add_tag_to_note(note_id, tag_id)

        # Get cache after tag add (which triggers rebuild)
        cache_after_tag = get_cache(db, note_id)
        assert cache_after_tag is not None
        assert len(cache_after_tag["tags"]) == 1

        # Update the note - this should rebuild cache
        db.update_note(note_id, "updated content")

        # Cache should still have the tag (proving it was rebuilt)
        new_cache = get_cache(db, note_id)
        assert new_cache is not None
        assert new_cache["cached_at"] is not None
        assert len(new_cache["tags"]) == 1


@pytest.mark.unit
class TestCacheRebuildOnTagChanges:
    """Test cache is rebuilt when tags are added/removed."""

    def test_add_tag_to_note_rebuilds_cache(self) -> None:
        """Adding a tag to a note should rebuild the cache."""
        db = Database(":memory:")

        # Create note and tag
        note_id = db.create_note("test note")
        tag_id = db.create_tag("TestTag")
        db.rebuild_note_cache(note_id)

        initial_cache = get_cache(db, note_id)
        assert initial_cache is not None
        assert len(initial_cache["tags"]) == 0

        # Add tag to note
        db.add_tag_to_note(note_id, tag_id)

        # Cache should now include the new tag (proving rebuild happened)
        new_cache = get_cache(db, note_id)
        assert new_cache is not None
        assert len(new_cache["tags"]) == 1, \
            "Cache should be rebuilt after add_tag_to_note() - tag count should be 1"
        assert new_cache["tags"][0]["name"] == "TestTag"

    def test_remove_tag_from_note_rebuilds_cache(self) -> None:
        """Removing a tag from a note should rebuild the cache."""
        db = Database(":memory:")

        # Create note, tag, and add tag to note
        note_id = db.create_note("test note")
        tag_id = db.create_tag("TestTag")
        db.add_tag_to_note(note_id, tag_id)

        # Verify cache has the tag
        initial_cache = get_cache(db, note_id)
        assert initial_cache is not None
        assert len(initial_cache["tags"]) == 1

        # Remove tag from note
        db.remove_tag_from_note(note_id, tag_id)

        # Cache should NOT include the removed tag (proving rebuild happened)
        new_cache = get_cache(db, note_id)
        assert new_cache is not None
        assert len(new_cache["tags"]) == 0, \
            "Cache should be rebuilt after remove_tag_from_note() - tag count should be 0"


@pytest.mark.unit
class TestCacheRebuildOnAttachmentChanges:
    """Test cache is rebuilt when attachments are added/removed."""

    def test_attach_to_note_rebuilds_cache(self) -> None:
        """Attaching an audio file to a note should rebuild the cache."""
        db = Database(":memory:")

        # Create note and audio file
        note_id = db.create_note("test note")
        audio_id = db.create_audio_file("test.mp3")
        db.rebuild_note_cache(note_id)

        initial_cache = get_cache(db, note_id)
        assert initial_cache is not None
        assert len(initial_cache["attachments"]) == 0

        # Attach audio file to note
        db.attach_to_note(note_id, audio_id, "audio_file")

        # Cache should include the attachment (proving rebuild happened)
        new_cache = get_cache(db, note_id)
        assert new_cache is not None
        assert len(new_cache["attachments"]) == 1, \
            "Cache should be rebuilt after attach_to_note() - attachment count should be 1"

    def test_detach_from_note_rebuilds_cache(self) -> None:
        """Detaching an audio file from a note should rebuild the cache."""
        db = Database(":memory:")

        # Create note, audio file, and attach
        note_id = db.create_note("test note")
        audio_id = db.create_audio_file("test.mp3")
        attachment_id = db.attach_to_note(note_id, audio_id, "audio_file")
        db.rebuild_note_cache(note_id)

        initial_cache = get_cache(db, note_id)
        assert initial_cache is not None
        assert len(initial_cache["attachments"]) == 1

        # Detach audio file from note
        db.detach_from_note(attachment_id)

        # Cache should NOT include the attachment (proving rebuild happened)
        new_cache = get_cache(db, note_id)
        assert new_cache is not None
        assert len(new_cache["attachments"]) == 0, \
            "Cache should be rebuilt after detach_from_note() - attachment count should be 0"


@pytest.mark.unit
class TestCacheRebuildOnTranscriptionChanges:
    """Test cache is rebuilt when transcriptions are created/updated/deleted."""

    def test_create_transcription_rebuilds_cache(self) -> None:
        """Creating a transcription should rebuild the note's cache."""
        db = Database(":memory:")

        # Create note, audio file, and attach
        note_id = db.create_note("test note")
        audio_id = db.create_audio_file("test.mp3")
        db.attach_to_note(note_id, audio_id, "audio_file")
        db.rebuild_note_cache(note_id)

        initial_cache = get_cache(db, note_id)
        assert initial_cache is not None
        attachment = initial_cache["attachments"][0]
        audio_file = attachment.get("audio_file", {})
        assert len(audio_file.get("transcriptions", [])) == 0

        # Create a transcription
        db.create_transcription(audio_id, "Hello world", "whisper")

        # Cache should include the transcription (proving rebuild happened)
        new_cache = get_cache(db, note_id)
        assert new_cache is not None
        attachment = new_cache["attachments"][0]
        audio_file = attachment.get("audio_file", {})
        assert len(audio_file.get("transcriptions", [])) == 1, \
            "Cache should be rebuilt after create_transcription() - transcription count should be 1"

    def test_update_transcription_rebuilds_cache(self) -> None:
        """Updating a transcription should rebuild the note's cache."""
        db = Database(":memory:")

        # Create note, audio file, attach, and transcription
        note_id = db.create_note("test note")
        audio_id = db.create_audio_file("test.mp3")
        db.attach_to_note(note_id, audio_id, "audio_file")
        transcription_id = db.create_transcription(audio_id, "Initial text", "whisper")
        db.rebuild_note_cache(note_id)

        initial_cache = get_cache(db, note_id)
        assert initial_cache is not None
        attachment = initial_cache["attachments"][0]
        transcription = attachment["audio_file"]["transcriptions"][0]
        assert transcription["content_preview"] == "Initial text"

        # Update the transcription
        db.update_transcription(transcription_id, "Updated text")

        # Cache should have updated content (proving rebuild happened)
        new_cache = get_cache(db, note_id)
        assert new_cache is not None
        attachment = new_cache["attachments"][0]
        transcription = attachment["audio_file"]["transcriptions"][0]
        assert transcription["content_preview"] == "Updated text", \
            "Cache should be rebuilt after update_transcription() - content should be updated"

    def test_delete_transcription_rebuilds_cache(self) -> None:
        """Deleting a transcription should rebuild the note's cache."""
        db = Database(":memory:")

        # Create note, audio file, attach, and transcription
        note_id = db.create_note("test note")
        audio_id = db.create_audio_file("test.mp3")
        db.attach_to_note(note_id, audio_id, "audio_file")
        transcription_id = db.create_transcription(audio_id, "Some text", "whisper")
        db.rebuild_note_cache(note_id)

        initial_cache = get_cache(db, note_id)
        assert initial_cache is not None
        attachment = initial_cache["attachments"][0]
        assert len(attachment["audio_file"]["transcriptions"]) == 1

        # Delete the transcription
        db.delete_transcription(transcription_id)

        # Cache should NOT include the transcription (proving rebuild happened)
        new_cache = get_cache(db, note_id)
        assert new_cache is not None
        attachment = new_cache["attachments"][0]
        assert len(attachment["audio_file"]["transcriptions"]) == 0, \
            "Cache should be rebuilt after delete_transcription() - transcription count should be 0"


@pytest.mark.unit
class TestCacheRebuildOnAudioFileChanges:
    """Test cache is rebuilt when audio file metadata changes."""

    def test_update_audio_file_summary_rebuilds_cache(self) -> None:
        """Updating an audio file's summary should rebuild the note's cache."""
        db = Database(":memory:")

        # Create note, audio file, and attach
        note_id = db.create_note("test note")
        audio_id = db.create_audio_file("test.mp3")
        db.attach_to_note(note_id, audio_id, "audio_file")
        db.rebuild_note_cache(note_id)

        initial_cache = get_cache(db, note_id)
        assert initial_cache is not None
        attachment = initial_cache["attachments"][0]
        assert attachment["audio_file"]["summary"] is None

        # Update audio file summary
        db.update_audio_file_summary(audio_id, "Meeting recording")

        # Cache should have the new summary (proving rebuild happened)
        new_cache = get_cache(db, note_id)
        assert new_cache is not None
        attachment = new_cache["attachments"][0]
        assert attachment["audio_file"]["summary"] == "Meeting recording", \
            "Cache should be rebuilt after update_audio_file_summary() - summary should be updated"


@pytest.mark.unit
class TestCacheRebuildOnConflictResolution:
    """The display cache lists a note's unresolved conflicts and is rebuilt
    when they appear (during sync) and when they are resolved."""

    DEV_A = "0000000000007000800000000000000a"
    DEV_B = "0000000000007000800000000000000b"

    @staticmethod
    def _push_all(src: Database, dst: Database, device_id: str) -> None:
        from voicecore import apply_sync_changes
        changes = src.get_changes_after_seq(0, None, 100000)["changes"]
        for c in changes:
            c.setdefault("device_id", device_id)
        apply_sync_changes(dst._rust_db, changes, device_id, "Device " + device_id[-1])

    def _conflicting_note(self) -> tuple:
        a = Database(":memory:")
        b = Database(":memory:")
        note_id = a.create_note("שורה ראשונה")
        self._push_all(a, b, self.DEV_A)
        a.update_note(note_id, "שורה ראשונה מהמחשב")
        b.update_note(note_id, "שורה ראשונה מהטלפון")
        self._push_all(b, a, self.DEV_B)
        return a, b, note_id

    def test_sync_conflict_appears_in_cache(self) -> None:
        a, _b, note_id = self._conflicting_note()
        cache = get_cache(a, note_id)
        assert cache is not None
        assert "content" in cache["conflicts"]

    def test_accept_conflict_rebuilds_cache(self) -> None:
        a, _b, note_id = self._conflicting_note()
        conflicts = a.get_entity_conflicts("note", note_id)
        assert len(conflicts) == 1
        assert a.accept_conflict(conflicts[0]["id"])

        new_cache = get_cache(a, note_id)
        assert new_cache is not None
        assert "content" not in new_cache["conflicts"], \
            "Cache should be rebuilt after accept_conflict() - conflict should be removed"

    def test_resolve_with_content_rebuilds_cache(self) -> None:
        a, _b, note_id = self._conflicting_note()
        conflicts = a.get_entity_conflicts("note", note_id)
        assert a.resolve_conflict_with_content(conflicts[0]["id"], "שורה ראשונה מהמחשב ומהטלפון")

        new_cache = get_cache(a, note_id)
        assert new_cache is not None
        assert "content" not in new_cache["conflicts"]
        assert a.get_note(note_id)["content"] == "שורה ראשונה מהמחשב ומהטלפון"

    def test_saving_note_rebuilds_cache(self) -> None:
        a, _b, note_id = self._conflicting_note()
        a.update_note(note_id, "שורה ראשונה מתוקנת")

        new_cache = get_cache(a, note_id)
        assert new_cache is not None
        assert new_cache["conflicts"] == []


@pytest.mark.unit
class TestCacheContentCorrectness:
    """Test that cached content is correct after operations."""

    def test_cache_tags_have_display_names(self) -> None:
        """Tags in cache should have display names (minimal path for disambiguation)."""
        db = Database(":memory:")

        # Create hierarchical tags
        parent_id = db.create_tag("Parent")
        child_id = db.create_tag("Child", parent_id=parent_id)

        # Create note and add child tag
        note_id = db.create_note("test note")
        db.add_tag_to_note(note_id, child_id)

        # Check cache has display_name (the key used for disambiguation)
        cache = get_cache(db, note_id)
        assert cache is not None
        assert len(cache["tags"]) == 1
        tag = cache["tags"][0]
        assert tag["name"] == "Child"
        # display_name shows minimal path needed (just "Child" if unambiguous)
        assert "display_name" in tag

    def test_cache_transcription_content_is_truncated(self) -> None:
        """Transcription content in cache should be truncated to 200 chars."""
        db = Database(":memory:")

        # Create note with audio and long transcription
        note_id = db.create_note("test note")
        audio_id = db.create_audio_file("test.mp3")
        db.attach_to_note(note_id, audio_id, "audio_file")

        long_content = "x" * 300  # Longer than 200 char limit
        db.create_transcription(audio_id, long_content, "whisper")
        db.rebuild_note_cache(note_id)

        # Check cache has truncated content
        cache = get_cache(db, note_id)
        assert cache is not None
        attachment = cache["attachments"][0]
        transcription = attachment["audio_file"]["transcriptions"][0]
        preview = transcription["content_preview"]

        # Should be truncated with ellipsis (200 chars + "…")
        assert len(preview) <= 201, f"Preview should be max 201 chars, got {len(preview)}"
        assert preview.startswith("x" * 50)  # Has beginning
        assert preview.endswith("…"), "Truncated preview should end with ellipsis"

    def test_cache_has_multiple_attachments(self) -> None:
        """Cache should include all attachments for a note."""
        db = Database(":memory:")

        # Create note with multiple audio files
        note_id = db.create_note("test note")
        audio_id_1 = db.create_audio_file("recording1.mp3")
        audio_id_2 = db.create_audio_file("recording2.wav")
        db.attach_to_note(note_id, audio_id_1, "audio_file")
        db.attach_to_note(note_id, audio_id_2, "audio_file")
        db.rebuild_note_cache(note_id)

        # Check cache has both attachments
        cache = get_cache(db, note_id)
        assert cache is not None
        assert len(cache["attachments"]) == 2

        filenames = {a["audio_file"]["filename"] for a in cache["attachments"]}
        assert filenames == {"recording1.mp3", "recording2.wav"}

    def test_cache_has_multiple_transcriptions_per_audio(self) -> None:
        """Cache should include all transcriptions for each audio file."""
        db = Database(":memory:")

        # Create note with audio and multiple transcriptions
        note_id = db.create_note("test note")
        audio_id = db.create_audio_file("test.mp3")
        db.attach_to_note(note_id, audio_id, "audio_file")
        db.create_transcription(audio_id, "Whisper result", "whisper")
        db.create_transcription(audio_id, "Google result", "google")
        db.rebuild_note_cache(note_id)

        # Check cache has both transcriptions
        cache = get_cache(db, note_id)
        assert cache is not None
        attachment = cache["attachments"][0]
        transcriptions = attachment["audio_file"]["transcriptions"]
        assert len(transcriptions) == 2

        services = {t["service"] for t in transcriptions}
        assert services == {"whisper", "google"}


@pytest.mark.unit
class TestCacheTimestampTypes:
    """Regression tests for timestamp type handling in cache.

    These tests verify that timestamps (which are stored as INTEGER Unix
    timestamps in the database) are correctly read and included in the cache.
    """

    def test_cache_audio_file_imported_at_is_integer(self) -> None:
        """Audio file imported_at should be an integer timestamp in cache.

        Regression test for bug where imported_at was read as String instead
        of i64, causing cache rebuild to fail silently.
        """
        db = Database(":memory:")

        # Create note with audio file (file_created_at as Unix timestamp)
        note_id = db.create_note("Audio: test_recording.mp3")
        audio_id = db.create_audio_file("test_recording.mp3", file_created_at=1700000000)
        db.attach_to_note(note_id, audio_id, "audio_file")
        db.rebuild_note_cache(note_id)

        cache = get_cache(db, note_id)
        assert cache is not None, "Cache should be populated after rebuild"

        attachments = cache.get("attachments", [])
        assert len(attachments) == 1

        audio_file = attachments[0].get("audio_file")
        assert audio_file is not None, "audio_file should be populated in cache"
        assert audio_file.get("id") == audio_id
        assert audio_file.get("filename") == "test_recording.mp3"

        # imported_at should be present and be an integer
        imported_at = audio_file.get("imported_at")
        assert imported_at is not None, "imported_at should be in cache"
        assert isinstance(imported_at, int), f"imported_at should be int, got {type(imported_at)}"

    def test_cache_audio_file_file_created_at_is_integer(self) -> None:
        """Audio file file_created_at should be an integer timestamp in cache."""
        db = Database(":memory:")

        note_id = db.create_note("Audio: test.mp3")
        audio_id = db.create_audio_file("test.mp3", file_created_at=1700000000)
        db.attach_to_note(note_id, audio_id, "audio_file")
        db.rebuild_note_cache(note_id)

        cache = get_cache(db, note_id)
        assert cache is not None

        audio_file = cache["attachments"][0].get("audio_file")
        file_created_at = audio_file.get("file_created_at")
        assert file_created_at is not None
        assert isinstance(file_created_at, int), f"file_created_at should be int, got {type(file_created_at)}"
        assert file_created_at == 1700000000

    def test_cache_transcription_created_at_is_integer(self) -> None:
        """Transcription created_at should be an integer timestamp in cache."""
        db = Database(":memory:")

        note_id = db.create_note("test note")
        audio_id = db.create_audio_file("test.mp3")
        db.attach_to_note(note_id, audio_id, "audio_file")
        db.create_transcription(audio_id, "Hello world", "whisper")
        db.rebuild_note_cache(note_id)

        cache = get_cache(db, note_id)
        assert cache is not None

        transcriptions = cache["attachments"][0]["audio_file"]["transcriptions"]
        assert len(transcriptions) == 1

        created_at = transcriptions[0].get("created_at")
        assert created_at is not None, "created_at should be in transcription cache"
        assert isinstance(created_at, int), f"created_at should be int, got {type(created_at)}"


@pytest.mark.unit
class TestCacheRebuildOnTagItselfChanging:
    """A Tag that is renamed, moved or deleted reaches every Note carrying it.

    Each Note's cache keeps a copy of the name of every Tag on it. Renaming a
    Tag therefore has to rebuild the cache of every Note that carries it, or
    those Notes go on showing the old name — to the user, the rename simply
    did not happen. This was the bug of 2026-09-10, and the same shape of
    mistake is easy to repeat with any denormalised copy.
    """

    def test_renaming_a_tag_reaches_the_notes_that_carry_it(self) -> None:
        db = Database(":memory:")
        note_id = db.create_note("פגישה עם הצוות")
        tag_id = db.create_tag("עבודה")
        db.add_tag_to_note(note_id, tag_id)

        assert get_cache(db, note_id)["tags"][0]["name"] == "עבודה"

        db.rename_tag(tag_id, "עבודה חדשה")

        assert get_cache(db, note_id)["tags"][0]["name"] == "עבודה חדשה", \
            "the Note's cache must show the new name at once"

    def test_renaming_a_tag_reaches_every_note_that_carries_it(self) -> None:
        db = Database(":memory:")
        tag_id = db.create_tag("עבודה")
        notes = [db.create_note(f"פגישה {i}") for i in range(5)]
        for note_id in notes:
            db.add_tag_to_note(note_id, tag_id)

        db.rename_tag(tag_id, "ארכיון")

        for note_id in notes:
            assert get_cache(db, note_id)["tags"][0]["name"] == "ארכיון"

    def test_renaming_a_tag_leaves_other_notes_alone(self) -> None:
        db = Database(":memory:")
        tagged = db.create_note("עם תגית")
        untagged = db.create_note("בלי תגית")
        tag_id = db.create_tag("עבודה")
        db.add_tag_to_note(tagged, tag_id)
        db.rebuild_note_cache(untagged)

        before = get_cache(db, untagged)
        db.rename_tag(tag_id, "ארכיון")

        assert get_cache(db, untagged) == before

    def test_moving_a_tag_reaches_the_notes_beneath_it(self) -> None:
        """A move changes the path of the whole subtree, not only the Tag."""
        db = Database(":memory:")
        parent = db.create_tag("עבודה")
        child = db.create_tag("נסיעות", parent)
        grandchild = db.create_tag("אתונה", child)
        note_id = db.create_note("הרצאה")
        db.add_tag_to_note(note_id, grandchild)

        cached_at = get_cache(db, note_id)["cached_at"]

        elsewhere = db.create_tag("פרויקטים")
        db.reparent_tag(child, elsewhere)

        # The cache was rebuilt: the Tag on this Note is two levels below the
        # one that moved, and its path changed with it.
        cache = get_cache(db, note_id)
        assert cache is not None
        assert len(cache["tags"]) == 1
        assert cache["tags"][0]["name"] == "אתונה"
        assert cache["cached_at"] >= cached_at

    def test_deleting_a_tag_reaches_the_notes_that_carried_it(self) -> None:
        db = Database(":memory:")
        note_id = db.create_note("פגישה")
        keep = db.create_tag("עבודה")
        drop = db.create_tag("זמני")
        db.add_tag_to_note(note_id, keep)
        db.add_tag_to_note(note_id, drop)
        assert len(get_cache(db, note_id)["tags"]) == 2

        db.delete_tag(drop)

        names = [t["name"] for t in get_cache(db, note_id)["tags"]]
        assert names == ["עבודה"], "a deleted Tag must leave the Note's cache at once"


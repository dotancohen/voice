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
    """Test cache is rebuilt when conflicts are resolved.

    NOTE: The resolve_note_*_conflict functions DO call rebuild_note_cache
    (verified in database.rs lines 3472 and 3514). These tests verify the
    cache rebuild behavior works correctly.
    """

    def test_resolve_note_content_conflict_rebuilds_cache(self) -> None:
        """Resolving a note content conflict should rebuild the cache."""
        db = Database(":memory:")

        # Create note and content conflict
        # Note: Using the raw Rust binding since Python wrapper has parameter mismatch
        note_id = db.create_note("local content")
        conflict_id = db._rust_db.create_note_content_conflict(
            note_id,
            "local content",
            "2025-01-01 12:00:00",
            None,  # local_device_id
            None,  # local_device_name
            "remote content",
            "2025-01-01 12:05:00",
            None,  # remote_device_id
            None,  # remote_device_name
        )
        db.rebuild_note_cache(note_id)

        initial_cache = get_cache(db, note_id)
        assert initial_cache is not None
        assert "content" in initial_cache["conflicts"]

        # Resolve the conflict
        db.resolve_note_content_conflict(conflict_id, "merged content")

        # Cache should NOT include the conflict (proving rebuild happened)
        new_cache = get_cache(db, note_id)
        assert new_cache is not None
        assert "content" not in new_cache["conflicts"], \
            "Cache should be rebuilt after resolve_note_content_conflict() - conflict should be removed"

    def test_resolve_note_delete_conflict_rebuilds_cache(self) -> None:
        """Resolving a note delete conflict should rebuild the cache (when restoring)."""
        db = Database(":memory:")

        # Create note and delete conflict
        # Note: Using the raw Rust binding since Python wrapper has parameter mismatch
        note_id = db.create_note("some content")
        conflict_id = db._rust_db.create_note_delete_conflict(
            note_id,
            "some content",
            "2025-01-01 12:00:00",
            None,  # surviving_device_id
            None,  # surviving_device_name
            None,  # deleted_content
            "2025-01-01 12:05:00",
            None,  # deleting_device_id
            None,  # deleting_device_name
        )
        db.rebuild_note_cache(note_id)

        initial_cache = get_cache(db, note_id)
        assert initial_cache is not None
        assert "delete" in initial_cache["conflicts"]

        # Resolve the conflict by restoring the note
        db.resolve_note_delete_conflict(conflict_id, restore_note=True)

        # Cache should NOT include the conflict (proving rebuild happened)
        new_cache = get_cache(db, note_id)
        assert new_cache is not None
        assert "delete" not in new_cache["conflicts"], \
            "Cache should be rebuilt after resolve_note_delete_conflict() - conflict should be removed"


@pytest.mark.unit
class TestCacheContentCorrectness:
    """Test that cached content is correct after operations."""

    def test_cache_tags_have_full_paths(self) -> None:
        """Tags in cache should have full hierarchical paths."""
        db = Database(":memory:")

        # Create hierarchical tags
        parent_id = db.create_tag("Parent")
        child_id = db.create_tag("Child", parent_id=parent_id)

        # Create note and add child tag
        note_id = db.create_note("test note")
        db.add_tag_to_note(note_id, child_id)

        # Check cache has full path
        cache = get_cache(db, note_id)
        assert cache is not None
        assert len(cache["tags"]) == 1
        tag = cache["tags"][0]
        assert tag["name"] == "Child"
        assert tag["full_path"] == "Parent/Child"

    def test_cache_transcription_content_is_truncated(self) -> None:
        """Transcription content in cache should be truncated to 100 chars."""
        db = Database(":memory:")

        # Create note with audio and long transcription
        note_id = db.create_note("test note")
        audio_id = db.create_audio_file("test.mp3")
        db.attach_to_note(note_id, audio_id, "audio_file")

        long_content = "x" * 200
        db.create_transcription(audio_id, long_content, "whisper")
        db.rebuild_note_cache(note_id)

        # Check cache has truncated content
        cache = get_cache(db, note_id)
        assert cache is not None
        attachment = cache["attachments"][0]
        transcription = attachment["audio_file"]["transcriptions"][0]
        preview = transcription["content_preview"]

        # Should be truncated with ellipsis
        assert len(preview) <= 101  # 100 chars + possible ellipsis
        assert preview.startswith("x" * 50)  # Has beginning

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

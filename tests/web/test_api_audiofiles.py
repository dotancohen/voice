"""Web API tests for audiofile endpoints.

Tests the REST API endpoints for audio files and attachments.
"""

from __future__ import annotations

import pytest
from flask.testing import FlaskClient

from tests.conftest import get_note_uuid_hex


class TestGetNoteAttachments:
    """Test GET /api/notes/<id>/attachments endpoint."""

    def test_returns_empty_list_for_note_without_attachments(
        self, client: FlaskClient, populated_db
    ) -> None:
        """Test that empty list is returned for note without attachments."""
        note_id = get_note_uuid_hex(1)
        response = client.get(f"/api/notes/{note_id}/attachments")

        assert response.status_code == 200
        data = response.get_json()
        assert "attachments" in data
        assert data["attachments"] == []

    def test_returns_attachments_for_note_with_audio(
        self, client: FlaskClient, populated_db
    ) -> None:
        """Test that attachments are returned for note with audio files."""
        note_id = get_note_uuid_hex(1)

        # Create audio file and attach it
        from src.web import db
        audio_id = db.create_audio_file("test_recording.mp3")
        db.attach_to_note(note_id, audio_id, "audio_file")

        response = client.get(f"/api/notes/{note_id}/attachments")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["attachments"]) == 1

        attachment = data["attachments"][0]
        assert attachment["attachment_type"] == "audio_file"
        assert attachment["attachment_id"] == audio_id
        assert "audio_file" in attachment
        assert attachment["audio_file"]["filename"] == "test_recording.mp3"

    def test_returns_404_for_nonexistent_note(self, client: FlaskClient, populated_db) -> None:
        """Test 404 for non-existent note."""
        fake_id = "00000000000070008000999999999999"
        response = client.get(f"/api/notes/{fake_id}/attachments")

        assert response.status_code == 404

    def test_returns_400_for_invalid_id(self, client: FlaskClient, populated_db) -> None:
        """Test 400 for invalid note ID format."""
        response = client.get("/api/notes/invalid-id/attachments")

        assert response.status_code == 400


class TestGetAudiofile:
    """Test GET /api/audiofiles/<id> endpoint."""

    def test_returns_audiofile_details(self, client: FlaskClient, populated_db) -> None:
        """Test retrieving audio file details."""
        from src.web import db
        audio_id = db.create_audio_file(
            "recording.mp3",
            file_created_at="2024-06-15 10:30:00"
        )

        response = client.get(f"/api/audiofiles/{audio_id}")

        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == audio_id
        assert data["filename"] == "recording.mp3"
        # Rust returns ISO format with T separator
        assert "2024-06-15" in data["file_created_at"]
        assert "10:30:00" in data["file_created_at"]

    def test_returns_404_for_nonexistent_audiofile(
        self, client: FlaskClient, populated_db
    ) -> None:
        """Test 404 for non-existent audio file."""
        fake_id = "00000000000070008000999999999999"
        response = client.get(f"/api/audiofiles/{fake_id}")

        assert response.status_code == 404

    def test_returns_400_for_invalid_id(self, client: FlaskClient, populated_db) -> None:
        """Test 400 for invalid audio file ID format."""
        response = client.get("/api/audiofiles/invalid-id")

        assert response.status_code == 400


class TestMultipleAttachments:
    """Test handling multiple attachments on a note."""

    def test_returns_all_attachments(self, client: FlaskClient, populated_db) -> None:
        """Test that all attachments are returned for a note."""
        note_id = get_note_uuid_hex(1)

        from src.web import db
        audio1_id = db.create_audio_file("recording1.mp3")
        audio2_id = db.create_audio_file("recording2.wav")

        db.attach_to_note(note_id, audio1_id, "audio_file")
        db.attach_to_note(note_id, audio2_id, "audio_file")

        response = client.get(f"/api/notes/{note_id}/attachments")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["attachments"]) == 2

        filenames = {a["audio_file"]["filename"] for a in data["attachments"]}
        assert filenames == {"recording1.mp3", "recording2.wav"}

    def test_excludes_detached_attachments(
        self, client: FlaskClient, populated_db
    ) -> None:
        """Test that detached attachments are excluded."""
        note_id = get_note_uuid_hex(1)

        from src.web import db
        audio1_id = db.create_audio_file("keep.mp3")
        audio2_id = db.create_audio_file("remove.mp3")

        db.attach_to_note(note_id, audio1_id, "audio_file")
        assoc2_id = db.attach_to_note(note_id, audio2_id, "audio_file")

        # Detach the second one
        db.detach_from_note(assoc2_id)

        response = client.get(f"/api/notes/{note_id}/attachments")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["attachments"]) == 1
        assert data["attachments"][0]["audio_file"]["filename"] == "keep.mp3"

"""Web API tests for notes endpoints.

Tests GET /api/notes and GET /api/notes/<id> endpoints.
"""

from __future__ import annotations

import json

import pytest
from flask.testing import FlaskClient

from tests.helpers import get_note_uuid_hex


@pytest.mark.web
class TestGetNotes:
    """Test GET /api/notes endpoint."""

    def test_get_all_notes(self, client: FlaskClient) -> None:
        """Test getting all notes."""
        response = client.get("/api/notes")

        assert response.status_code == 200
        assert response.content_type == "application/json"

        notes = json.loads(response.data)
        assert isinstance(notes, list)
        assert len(notes) == 9  # 9 notes in fixture

    def test_notes_have_required_fields(self, client: FlaskClient) -> None:
        """Test that notes have all required fields."""
        response = client.get("/api/notes")
        notes = json.loads(response.data)

        for note in notes:
            assert "id" in note
            assert "created_at" in note
            assert "content" in note
            assert isinstance(note["id"], str)  # UUID hex string
            assert isinstance(note["content"], str)

    def test_notes_include_tags(self, client: FlaskClient) -> None:
        """Test that notes include tag information."""
        response = client.get("/api/notes")
        notes = json.loads(response.data)

        # Find note 1 which has tags
        note_1_id = get_note_uuid_hex(1)
        note_1 = next(n for n in notes if n["id"] == note_1_id)
        assert "tag_names" in note_1
        assert "Work" in note_1["tag_names"]

    def test_notes_ordered_by_created_at(self, client: FlaskClient) -> None:
        """Test that notes are ordered by creation time."""
        response = client.get("/api/notes")
        notes = json.loads(response.data)

        # Notes should be in descending order (newest first)
        for i in range(len(notes) - 1):
            assert notes[i]["created_at"] >= notes[i + 1]["created_at"]


@pytest.mark.web
class TestGetNote:
    """Test GET /api/notes/<id> endpoint."""

    def test_get_note_by_id(self, client: FlaskClient) -> None:
        """Test getting specific note by ID."""
        note_id = get_note_uuid_hex(1)
        response = client.get(f"/api/notes/{note_id}")

        assert response.status_code == 200
        assert response.content_type == "application/json"

        note = json.loads(response.data)
        assert note["id"] == note_id
        assert "Meeting notes" in note["content"]

    def test_get_note_includes_tags(self, client: FlaskClient) -> None:
        """Test that single note includes tags."""
        note_id = get_note_uuid_hex(1)
        response = client.get(f"/api/notes/{note_id}")
        note = json.loads(response.data)

        assert "tag_names" in note
        assert "Work" in note["tag_names"]
        assert "Projects" in note["tag_names"]

    def test_get_note_with_hebrew_content(self, client: FlaskClient) -> None:
        """Test getting note with Hebrew content."""
        note_id = get_note_uuid_hex(6)
        response = client.get(f"/api/notes/{note_id}")
        note = json.loads(response.data)

        assert note["id"] == note_id
        assert "שלום עולם" in note["content"]

    def test_get_nonexistent_note(self, client: FlaskClient) -> None:
        """Test getting non-existent note returns 404."""
        # Use valid UUID format but nonexistent
        nonexistent_id = "00000000000070008000000000009999"
        response = client.get(f"/api/notes/{nonexistent_id}")

        assert response.status_code == 404
        error = json.loads(response.data)
        assert "error" in error
        assert "not found" in error["error"].lower()

    def test_get_note_invalid_id(self, client: FlaskClient) -> None:
        """Test getting note with invalid ID returns 400."""
        response = client.get("/api/notes/invalid")

        assert response.status_code == 400  # Invalid UUID format

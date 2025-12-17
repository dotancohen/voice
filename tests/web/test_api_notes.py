"""Web API tests for notes endpoints.

Tests GET /api/notes and GET /api/notes/<id> endpoints.
"""

from __future__ import annotations

import json

import pytest
from flask.testing import FlaskClient


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
        assert len(notes) == 8  # 8 notes in fixture

    def test_notes_have_required_fields(self, client: FlaskClient) -> None:
        """Test that notes have all required fields."""
        response = client.get("/api/notes")
        notes = json.loads(response.data)

        for note in notes:
            assert "id" in note
            assert "created_at" in note
            assert "content" in note
            assert isinstance(note["id"], int)
            assert isinstance(note["content"], str)

    def test_notes_include_tags(self, client: FlaskClient) -> None:
        """Test that notes include tag information."""
        response = client.get("/api/notes")
        notes = json.loads(response.data)

        # Find note 1 which has tags
        note_1 = next(n for n in notes if n["id"] == 1)
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
        response = client.get("/api/notes/1")

        assert response.status_code == 200
        assert response.content_type == "application/json"

        note = json.loads(response.data)
        assert note["id"] == 1
        assert "Meeting notes" in note["content"]

    def test_get_note_includes_tags(self, client: FlaskClient) -> None:
        """Test that single note includes tags."""
        response = client.get("/api/notes/1")
        note = json.loads(response.data)

        assert "tag_names" in note
        assert "Work" in note["tag_names"]
        assert "Projects" in note["tag_names"]

    def test_get_note_with_hebrew_content(self, client: FlaskClient) -> None:
        """Test getting note with Hebrew content."""
        response = client.get("/api/notes/6")
        note = json.loads(response.data)

        assert note["id"] == 6
        assert "שלום עולם" in note["content"]

    def test_get_nonexistent_note(self, client: FlaskClient) -> None:
        """Test getting non-existent note returns 404."""
        response = client.get("/api/notes/9999")

        assert response.status_code == 404
        error = json.loads(response.data)
        assert "error" in error
        assert "not found" in error["error"].lower()

    def test_get_note_invalid_id(self, client: FlaskClient) -> None:
        """Test getting note with invalid ID."""
        response = client.get("/api/notes/invalid")

        assert response.status_code == 404  # Flask routing returns 404 for non-int

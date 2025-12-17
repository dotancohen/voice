"""Web API tests for search endpoint.

Tests GET /api/search with various query parameters.
"""

from __future__ import annotations

import json
from urllib.parse import urlencode

import pytest
from flask.testing import FlaskClient


@pytest.mark.web
class TestSearchText:
    """Test search with text queries."""

    def test_search_by_text(self, client: FlaskClient) -> None:
        """Test searching by text."""
        response = client.get("/api/search?text=meeting")

        assert response.status_code == 200
        notes = json.loads(response.data)

        assert len(notes) == 1
        assert "Meeting notes" in notes[0]["content"]

    def test_search_case_insensitive(self, client: FlaskClient) -> None:
        """Test that text search is case-insensitive."""
        response = client.get("/api/search?text=DOCTOR")

        assert response.status_code == 200
        notes = json.loads(response.data)

        assert len(notes) == 1
        assert "Doctor appointment" in notes[0]["content"]

    def test_search_hebrew_text(self, client: FlaskClient) -> None:
        """Test searching Hebrew text."""
        response = client.get("/api/search?text=שלום")

        assert response.status_code == 200
        notes = json.loads(response.data)

        assert len(notes) == 1
        assert "שלום עולם" in notes[0]["content"]

    def test_search_no_results(self, client: FlaskClient) -> None:
        """Test search with no matching results."""
        response = client.get("/api/search?text=nonexistent")

        assert response.status_code == 200
        notes = json.loads(response.data)

        assert len(notes) == 0
        assert isinstance(notes, list)


@pytest.mark.web
class TestSearchTags:
    """Test search with tag filters."""

    def test_search_by_single_tag(self, client: FlaskClient) -> None:
        """Test searching by single tag."""
        response = client.get("/api/search?tag=Work")

        assert response.status_code == 200
        notes = json.loads(response.data)

        # Should find notes with Work tag
        assert len(notes) >= 2
        note_contents = [n["content"] for n in notes]
        assert any("Meeting notes" in content for content in note_contents)
        assert any("documentation" in content for content in note_contents)

    def test_search_by_hierarchical_tag(self, client: FlaskClient) -> None:
        """Test searching by hierarchical tag path."""
        response = client.get("/api/search?tag=Geography/Europe/France/Paris")

        assert response.status_code == 200
        notes = json.loads(response.data)

        assert len(notes) == 1
        assert "reunion" in notes[0]["content"].lower()

    def test_search_parent_includes_children(self, client: FlaskClient) -> None:
        """Test that parent tag search includes child tags."""
        response = client.get("/api/search?tag=Personal")

        assert response.status_code == 200
        notes = json.loads(response.data)

        # Should find 4 notes with Personal and its children
        assert len(notes) == 4

    def test_search_multiple_tags_and_logic(self, client: FlaskClient) -> None:
        """Test searching with multiple tags (AND logic)."""
        # Multiple tag parameters
        response = client.get("/api/search?tag=Work&tag=Work/Projects")

        assert response.status_code == 200
        notes = json.loads(response.data)

        # Should find notes with both Work AND Projects
        assert len(notes) == 2

    def test_search_nonexistent_tag(self, client: FlaskClient) -> None:
        """Test searching with non-existent tag."""
        response = client.get("/api/search?tag=NonExistentTag")

        assert response.status_code == 200
        notes = json.loads(response.data)

        # Should return empty results
        assert len(notes) == 0


@pytest.mark.web
class TestSearchCombined:
    """Test search with combined text and tags."""

    def test_search_text_and_tag(self, client: FlaskClient) -> None:
        """Test searching with both text and tag."""
        response = client.get("/api/search?text=meeting&tag=Work")

        assert response.status_code == 200
        notes = json.loads(response.data)

        assert len(notes) == 1
        assert "Meeting notes" in notes[0]["content"]

    def test_search_text_and_multiple_tags(self, client: FlaskClient) -> None:
        """Test searching with text and multiple tags."""
        response = client.get("/api/search?text=reunion&tag=Personal&tag=Geography")

        assert response.status_code == 200
        notes = json.loads(response.data)

        assert len(notes) == 1
        assert "reunion" in notes[0]["content"].lower()

    def test_search_empty_query(self, client: FlaskClient) -> None:
        """Test search with no query parameters."""
        response = client.get("/api/search")

        assert response.status_code == 200
        notes = json.loads(response.data)

        # Should return all notes
        assert len(notes) == 8


@pytest.mark.web
class TestSearchResponseFormat:
    """Test search response format."""

    def test_search_returns_json(self, client: FlaskClient) -> None:
        """Test that search returns JSON."""
        response = client.get("/api/search?tag=Work")

        assert response.status_code == 200
        assert response.content_type == "application/json"

    def test_search_notes_have_required_fields(self, client: FlaskClient) -> None:
        """Test that search results have required fields."""
        response = client.get("/api/search?tag=Work")
        notes = json.loads(response.data)

        for note in notes:
            assert "id" in note
            assert "created_at" in note
            assert "content" in note
            assert "tag_names" in note

    def test_search_response_is_list(self, client: FlaskClient) -> None:
        """Test that search always returns a list."""
        # Search with results
        response1 = client.get("/api/search?tag=Work")
        assert isinstance(json.loads(response1.data), list)

        # Search with no results
        response2 = client.get("/api/search?tag=NonExistent")
        assert isinstance(json.loads(response2.data), list)

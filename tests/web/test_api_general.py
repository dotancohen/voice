"""Web API tests for general functionality.

Tests health check, error handling, and CORS.
"""

from __future__ import annotations

import json

import pytest
from flask.testing import FlaskClient


@pytest.mark.web
class TestHealthCheck:
    """Test health check endpoint."""

    def test_health_check(self, client: FlaskClient) -> None:
        """Test /api/health endpoint."""
        response = client.get("/api/health")

        assert response.status_code == 200
        assert response.content_type == "application/json"

        data = json.loads(response.data)
        assert data["status"] == "ok"


@pytest.mark.web
class TestErrorHandling:
    """Test API error handling."""

    def test_nonexistent_endpoint_returns_404(self, client: FlaskClient) -> None:
        """Test that non-existent endpoints return 404."""
        response = client.get("/api/nonexistent")

        assert response.status_code == 404
        data = json.loads(response.data)
        assert "error" in data

    def test_invalid_route_returns_404(self, client: FlaskClient) -> None:
        """Test invalid route returns 404."""
        response = client.get("/invalid/path")

        assert response.status_code == 404


@pytest.mark.web
class TestCORS:
    """Test CORS headers."""

    def test_cors_headers_present(self, client: FlaskClient) -> None:
        """Test that CORS headers are present."""
        response = client.get("/api/notes")

        # Flask-CORS should add Access-Control-Allow-Origin header
        assert "Access-Control-Allow-Origin" in response.headers

    def test_options_request_supported(self, client: FlaskClient) -> None:
        """Test that OPTIONS requests are supported for CORS."""
        response = client.options("/api/notes")

        # Should return successful response for preflight request
        assert response.status_code in [200, 204]


@pytest.mark.web
class TestHTTPMethods:
    """Test HTTP method handling."""

    def test_get_method_allowed(self, client: FlaskClient) -> None:
        """Test that GET method is allowed."""
        response = client.get("/api/notes")
        assert response.status_code == 200

    def test_post_method_allowed(self, client: FlaskClient) -> None:
        """Test that POST method is allowed for creating notes."""
        response = client.post(
            "/api/notes",
            json={"content": "Test note"},
            content_type="application/json"
        )
        assert response.status_code == 201
        assert "id" in response.json

    def test_put_method_allowed(self, client: FlaskClient) -> None:
        """Test that PUT method is allowed for updating notes."""
        # First create a note
        create_resp = client.post(
            "/api/notes",
            json={"content": "Original content"},
            content_type="application/json"
        )
        note_id = create_resp.json["id"]

        # Then update it
        response = client.put(
            f"/api/notes/{note_id}",
            json={"content": "Updated content"},
            content_type="application/json"
        )
        assert response.status_code == 200
        assert response.json["content"] == "Updated content"

    def test_delete_method_not_allowed(self, client: FlaskClient) -> None:
        """Test that DELETE method returns 405 (read-only API)."""
        response = client.delete("/api/notes/1")
        assert response.status_code == 405


@pytest.mark.web
class TestJSONResponses:
    """Test JSON response formatting."""

    def test_all_responses_are_json(self, client: FlaskClient) -> None:
        """Test that all API responses are JSON."""
        endpoints = [
            "/api/notes",
            "/api/notes/1",
            "/api/tags",
            "/api/search",
            "/api/health"
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.content_type == "application/json"

    def test_error_responses_are_json(self, client: FlaskClient) -> None:
        """Test that error responses are also JSON."""
        response = client.get("/api/notes/9999")

        assert response.content_type == "application/json"
        data = json.loads(response.data)
        assert "error" in data

    def test_json_utf8_encoding(self, client: FlaskClient) -> None:
        """Test that JSON responses handle UTF-8 properly."""
        # Get note with Hebrew content
        response = client.get("/api/notes/6")
        note = json.loads(response.data)

        # Should properly decode Hebrew text
        assert "שלום עולם" in note["content"]

        # Search with Hebrew
        response2 = client.get("/api/search?text=שלום")
        notes = json.loads(response2.data)

        assert len(notes) > 0
        assert "שלום עולם" in notes[0]["content"]

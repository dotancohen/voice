"""Web API tests for tags endpoints.

Tests GET /api/tags endpoint.
"""

from __future__ import annotations

import json

import pytest
from flask.testing import FlaskClient

from tests.helpers import get_tag_uuid_hex


@pytest.mark.web
class TestGetTags:
    """Test GET /api/tags endpoint."""

    def test_get_all_tags(self, client: FlaskClient) -> None:
        """Test getting all tags."""
        response = client.get("/api/tags")

        assert response.status_code == 200
        assert response.content_type == "application/json"

        tags = json.loads(response.data)
        assert isinstance(tags, list)
        assert len(tags) == 23  # 19 tags in fixture + 4 system tags

    def test_tags_have_required_fields(self, client: FlaskClient) -> None:
        """Test that tags have all required fields."""
        response = client.get("/api/tags")
        tags = json.loads(response.data)

        for tag in tags:
            assert "id" in tag
            assert "name" in tag
            assert isinstance(tag["id"], str)  # UUID hex string
            assert isinstance(tag["name"], str)

    def test_tags_include_hierarchy_info(self, client: FlaskClient) -> None:
        """Test that tags include parent_id for hierarchy."""
        response = client.get("/api/tags")
        tags = json.loads(response.data)

        # Find Work tag (root, should have parent_id None)
        work_tag = next(t for t in tags if t["name"] == "Work")
        assert work_tag["parent_id"] is None

        # Find Projects tag (child of Work, should have parent_id matching Work's ID)
        projects_tag = next(t for t in tags if t["name"] == "Projects")
        assert projects_tag["parent_id"] == get_tag_uuid_hex("Work")

    def test_tags_include_all_hierarchy_levels(self, client: FlaskClient) -> None:
        """Test that tags include deep hierarchy."""
        response = client.get("/api/tags")
        tags = json.loads(response.data)

        # Check Geography -> Europe -> France -> Paris hierarchy exists
        geography = next(t for t in tags if t["name"] == "Geography")
        europe = next(t for t in tags if t["name"] == "Europe")
        france = next(t for t in tags if t["name"] == "France")
        # There are two Paris tags - find the one under France
        paris_list = [t for t in tags if t["name"] == "Paris"]
        paris = next(p for p in paris_list if p["parent_id"] == france["id"])

        assert geography["parent_id"] is None
        assert europe["parent_id"] == geography["id"]
        assert france["parent_id"] == europe["id"]
        assert paris["parent_id"] == france["id"]

    def test_tags_response_is_json_serializable(self, client: FlaskClient) -> None:
        """Test that tags response is properly JSON serializable."""
        response = client.get("/api/tags")
        tags = json.loads(response.data)

        # Should be able to serialize back to JSON without errors
        json_str = json.dumps(tags)
        assert isinstance(json_str, str)
        assert len(json_str) > 0

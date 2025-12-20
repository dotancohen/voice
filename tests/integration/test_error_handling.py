"""Error handling integration tests.

Tests how the system handles errors across interface layers.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from core.config import Config
from core.database import Database
from core.validation import ValidationError


@pytest.mark.integration
class TestCLIErrorHandling:
    """Test CLI error handling."""

    def test_show_nonexistent_note(
        self,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
    ) -> None:
        """CLI handles nonexistent note gracefully."""
        # Use valid UUID format but nonexistent
        nonexistent_id = "00000000000070008000000000009999"
        returncode, stdout, stderr = cli_runner("show-note", nonexistent_id)
        assert returncode == 1
        assert "not found" in stderr.lower() or "not found" in stdout.lower()

    def test_search_nonexistent_tag(
        self,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
    ) -> None:
        """CLI handles nonexistent tag search gracefully."""
        returncode, stdout, stderr = cli_runner("--format", "json", "search", "--tag", "NonexistentTag")
        assert returncode == 0  # Returns empty results, not error
        notes = json.loads(stdout)
        assert notes == []
        assert "not found" in stderr.lower()

    def test_invalid_note_id_type(
        self,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
    ) -> None:
        """CLI handles invalid note ID type."""
        returncode, stdout, stderr = cli_runner("show-note", "abc")
        assert returncode != 0  # validation error
        assert "invalid" in stderr.lower() or "error" in stderr.lower()

    def test_missing_required_argument(
        self,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
    ) -> None:
        """CLI handles missing required argument."""
        returncode, stdout, stderr = cli_runner("show-note")
        assert returncode != 0
        assert "required" in stderr.lower() or "argument" in stderr.lower()

    def test_empty_search_criteria(
        self,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
    ) -> None:
        """CLI handles search with no criteria (returns all notes)."""
        returncode, stdout, stderr = cli_runner("--format", "json", "search")
        assert returncode == 0
        notes = json.loads(stdout)
        assert len(notes) == 9  # All notes returned


@pytest.mark.integration
class TestWebAPIErrorHandling:
    """Test Web API error handling."""

    def test_get_nonexistent_note(
        self,
        test_config_dir: Path,
        populated_db: Database,
        web_client,
    ) -> None:
        """API returns 404 for nonexistent note."""
        # Use valid UUID format but nonexistent
        nonexistent_id = "00000000000070008000000000009999"
        response = web_client.get(f"/api/notes/{nonexistent_id}")
        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data

    def test_invalid_note_id_format(
        self,
        test_config_dir: Path,
        populated_db: Database,
        web_client,
    ) -> None:
        """API handles invalid note ID format."""
        response = web_client.get("/api/notes/abc")
        assert response.status_code == 400  # Invalid UUID format

    def test_nonexistent_endpoint(
        self,
        test_config_dir: Path,
        populated_db: Database,
        web_client,
    ) -> None:
        """API returns 404 for nonexistent endpoint."""
        response = web_client.get("/api/nonexistent")
        assert response.status_code == 404

    def test_search_nonexistent_tag(
        self,
        test_config_dir: Path,
        populated_db: Database,
        web_client,
    ) -> None:
        """API returns empty results for nonexistent tag."""
        response = web_client.get("/api/search?tag=NonexistentTag")
        assert response.status_code == 200
        notes = response.get_json()
        assert notes == []

    def test_health_check_always_works(
        self,
        test_config_dir: Path,
        populated_db: Database,
        web_client,
    ) -> None:
        """Health check endpoint always returns OK."""
        response = web_client.get("/api/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"


@pytest.mark.integration
class TestValidationErrorHandling:
    """Test validation error handling across interfaces."""

    def test_database_validates_note_id(
        self,
        populated_db: Database,
    ) -> None:
        """Database raises ValidationError for invalid note ID."""
        # Wrong type (integer)
        with pytest.raises(ValidationError) as exc:
            populated_db.get_note(0)  # type: ignore
        assert exc.value.field == "note_id"

        # Wrong length (short bytes)
        with pytest.raises(ValidationError) as exc:
            populated_db.get_note(b"short")
        assert exc.value.field == "note_id"

    def test_database_validates_tag_id(
        self,
        populated_db: Database,
    ) -> None:
        """Database raises ValidationError for invalid tag ID."""
        with pytest.raises(ValidationError) as exc:
            populated_db.get_tag(0)  # type: ignore
        assert exc.value.field == "tag_id"

    def test_database_validates_search_query_length(
        self,
        populated_db: Database,
    ) -> None:
        """Database validates search query length."""
        # Very long query should raise validation error
        long_query = "x" * 1000
        with pytest.raises(ValidationError) as exc:
            populated_db.search_notes(text_query=long_query)
        assert "search_query" in exc.value.field


@pytest.mark.integration
class TestEdgeCaseHandling:
    """Test handling of edge cases."""

    def test_empty_database_operations(
        self,
        empty_db: Database,
    ) -> None:
        """Operations work correctly on empty database."""
        # Get all notes - should be empty
        notes = empty_db.get_all_notes()
        assert notes == []

        # Get all tags - should be empty
        tags = empty_db.get_all_tags()
        assert tags == []

        # Search should return empty
        results = empty_db.search_notes(text_query="anything")
        assert results == []

    def test_special_characters_in_search(
        self,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
        web_client,
    ) -> None:
        """Search handles special characters gracefully."""
        # CLI with special characters
        returncode, stdout, stderr = cli_runner(
            "--format", "json", "search", "--text", "test%20with%special"
        )
        assert returncode == 0
        notes = json.loads(stdout)
        assert notes == []  # No match, but no error

        # Web API with special characters
        response = web_client.get("/api/search?text=test%20with%special")
        assert response.status_code == 200

    def test_unicode_handling(
        self,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
        web_client,
    ) -> None:
        """All interfaces handle Unicode correctly."""
        # CLI search for Hebrew text
        returncode, stdout, stderr = cli_runner("--format", "json", "search", "--text", "שלום")
        assert returncode == 0
        notes = json.loads(stdout)
        assert len(notes) == 1
        assert "שלום" in notes[0]["content"]

        # Web API search for Hebrew text
        response = web_client.get("/api/search?text=שלום")
        assert response.status_code == 200
        notes = response.get_json()
        assert len(notes) == 1
        assert "שלום" in notes[0]["content"]

    def test_very_long_tag_path(
        self,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
    ) -> None:
        """CLI handles very long tag paths."""
        long_path = "/".join(["level"] * 60)  # Exceeds max depth
        returncode, stdout, stderr = cli_runner("--format", "json", "search", "--tag", long_path)
        # Should fail validation or return empty results
        # Either is acceptable error handling
        if returncode == 0:
            notes = json.loads(stdout)
            assert notes == []  # No match
        else:
            assert "error" in stderr.lower() or "invalid" in stderr.lower()

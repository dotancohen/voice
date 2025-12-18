"""Cross-interface consistency tests.

Verifies that the same operations produce consistent results across
GUI, CLI, and Web API interfaces.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import Config
from core.database import Database
from core.search import execute_search
from ui.notes_list_pane import NotesListPane


@pytest.mark.integration
class TestSearchConsistency:
    """Verify search results are consistent across all interfaces."""

    def test_text_search_same_results(
        self,
        qapp,
        test_config: Config,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
        web_client,
    ) -> None:
        """Text search returns same results across all interfaces."""
        search_query = "Doctor"

        # Core search module (ground truth)
        core_result = execute_search(populated_db, search_query)
        core_note_ids = sorted([n["id"] for n in core_result.notes])

        # GUI search
        pane = NotesListPane(test_config, populated_db)
        pane.search_field.setPlainText(search_query)
        pane.perform_search()
        gui_note_ids = sorted(
            [
                pane.list_widget.item(i).data(0x0100)  # UserRole
                for i in range(pane.list_widget.count())
            ]
        )

        # CLI search
        returncode, stdout, stderr = cli_runner("--format", "json", "search", "--text", search_query)
        assert returncode == 0, f"CLI failed: {stderr}"
        cli_notes = json.loads(stdout)
        cli_note_ids = sorted([n["id"] for n in cli_notes])

        # Web API search
        response = web_client.get(f"/api/search?text={search_query}")
        assert response.status_code == 200
        web_notes = response.get_json()
        web_note_ids = sorted([n["id"] for n in web_notes])

        # All interfaces should return same results
        assert core_note_ids == gui_note_ids, "GUI results differ from core"
        assert core_note_ids == cli_note_ids, "CLI results differ from core"
        assert core_note_ids == web_note_ids, "Web API results differ from core"

    def test_tag_search_same_results(
        self,
        qapp,
        test_config: Config,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
        web_client,
    ) -> None:
        """Tag search returns same results across all interfaces."""
        # Core search module
        core_result = execute_search(populated_db, "tag:Work")
        core_note_ids = sorted([n["id"] for n in core_result.notes])

        # GUI search
        pane = NotesListPane(test_config, populated_db)
        pane.search_field.setPlainText("tag:Work")
        pane.perform_search()
        gui_note_ids = sorted(
            [
                pane.list_widget.item(i).data(0x0100)
                for i in range(pane.list_widget.count())
            ]
        )

        # CLI search
        returncode, stdout, stderr = cli_runner("--format", "json", "search", "--tag", "Work")
        assert returncode == 0, f"CLI failed: {stderr}"
        cli_notes = json.loads(stdout)
        cli_note_ids = sorted([n["id"] for n in cli_notes])

        # Web API search
        response = web_client.get("/api/search?tag=Work")
        assert response.status_code == 200
        web_notes = response.get_json()
        web_note_ids = sorted([n["id"] for n in web_notes])

        # All should match
        assert core_note_ids == gui_note_ids, "GUI results differ from core"
        assert core_note_ids == cli_note_ids, "CLI results differ from core"
        assert core_note_ids == web_note_ids, "Web API results differ from core"

    def test_combined_search_same_results(
        self,
        qapp,
        test_config: Config,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
        web_client,
    ) -> None:
        """Combined text and tag search returns same results."""
        # Core search
        core_result = execute_search(populated_db, "reunion tag:Personal")
        core_note_ids = sorted([n["id"] for n in core_result.notes])

        # GUI search
        pane = NotesListPane(test_config, populated_db)
        pane.search_field.setPlainText("reunion tag:Personal")
        pane.perform_search()
        gui_note_ids = sorted(
            [
                pane.list_widget.item(i).data(0x0100)
                for i in range(pane.list_widget.count())
            ]
        )

        # CLI search
        returncode, stdout, stderr = cli_runner(
            "--format", "json", "search", "--text", "reunion", "--tag", "Personal"
        )
        assert returncode == 0, f"CLI failed: {stderr}"
        cli_notes = json.loads(stdout)
        cli_note_ids = sorted([n["id"] for n in cli_notes])

        # Web API search
        response = web_client.get("/api/search?text=reunion&tag=Personal")
        assert response.status_code == 200
        web_notes = response.get_json()
        web_note_ids = sorted([n["id"] for n in web_notes])

        # All should match
        assert core_note_ids == gui_note_ids
        assert core_note_ids == cli_note_ids
        assert core_note_ids == web_note_ids

    def test_ambiguous_tag_search_same_results(
        self,
        qapp,
        test_config: Config,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
        web_client,
    ) -> None:
        """Ambiguous tag search returns same results (OR logic)."""
        # Core search - Paris is ambiguous (France and Texas)
        core_result = execute_search(populated_db, "tag:Paris")
        core_note_ids = sorted([n["id"] for n in core_result.notes])
        assert len(core_note_ids) == 2, "Should find 2 notes for ambiguous Paris"

        # GUI search
        pane = NotesListPane(test_config, populated_db)
        pane.search_field.setPlainText("tag:Paris")
        pane.perform_search()
        gui_note_ids = sorted(
            [
                pane.list_widget.item(i).data(0x0100)
                for i in range(pane.list_widget.count())
            ]
        )

        # CLI search
        returncode, stdout, stderr = cli_runner("--format", "json", "search", "--tag", "Paris")
        assert returncode == 0
        cli_notes = json.loads(stdout)
        cli_note_ids = sorted([n["id"] for n in cli_notes])

        # Web API search
        response = web_client.get("/api/search?tag=Paris")
        assert response.status_code == 200
        web_notes = response.get_json()
        web_note_ids = sorted([n["id"] for n in web_notes])

        # All should return both Paris notes
        assert core_note_ids == gui_note_ids
        assert core_note_ids == cli_note_ids
        assert core_note_ids == web_note_ids


@pytest.mark.integration
class TestDataConsistency:
    """Verify data retrieval is consistent across interfaces."""

    def test_all_notes_same_count(
        self,
        qapp,
        test_config: Config,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
        web_client,
    ) -> None:
        """All interfaces return same number of notes."""
        # Database direct
        db_notes = populated_db.get_all_notes()
        db_count = len(db_notes)

        # GUI
        pane = NotesListPane(test_config, populated_db)
        gui_count = pane.list_widget.count()

        # CLI
        returncode, stdout, stderr = cli_runner("--format", "json", "list-notes")
        assert returncode == 0
        cli_notes = json.loads(stdout)
        cli_count = len(cli_notes)

        # Web API
        response = web_client.get("/api/notes")
        assert response.status_code == 200
        web_notes = response.get_json()
        web_count = len(web_notes)

        # All should match
        assert db_count == gui_count == cli_count == web_count

    def test_all_tags_same_count(
        self,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
        web_client,
    ) -> None:
        """All interfaces return same number of tags."""
        # Database direct
        db_tags = populated_db.get_all_tags()
        db_count = len(db_tags)

        # CLI
        returncode, stdout, stderr = cli_runner("--format", "json", "list-tags")
        assert returncode == 0
        cli_tags = json.loads(stdout)
        cli_count = len(cli_tags)

        # Web API
        response = web_client.get("/api/tags")
        assert response.status_code == 200
        web_tags = response.get_json()
        web_count = len(web_tags)

        # All should match
        assert db_count == cli_count == web_count

    def test_note_content_identical(
        self,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
        web_client,
    ) -> None:
        """Note content is identical across interfaces."""
        note_id = 6  # Hebrew text note

        # Database direct
        db_note = populated_db.get_note(note_id)
        assert db_note is not None
        db_content = db_note["content"]

        # CLI
        returncode, stdout, stderr = cli_runner("--format", "json", "show-note", str(note_id))
        assert returncode == 0
        cli_note = json.loads(stdout)
        cli_content = cli_note["content"]

        # Web API
        response = web_client.get(f"/api/notes/{note_id}")
        assert response.status_code == 200
        web_note = response.get_json()
        web_content = web_note["content"]

        # Content should be identical (including Hebrew)
        assert db_content == cli_content == web_content
        assert "שלום עולם" in db_content


@pytest.mark.integration
class TestHierarchicalSearchConsistency:
    """Verify hierarchical tag searches are consistent."""

    def test_parent_tag_includes_children_all_interfaces(
        self,
        qapp,
        test_config: Config,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
        web_client,
    ) -> None:
        """Searching parent tag includes children across all interfaces."""
        # Core - Personal includes Family, Health
        core_result = execute_search(populated_db, "tag:Personal")
        core_count = len(core_result.notes)
        assert core_count == 4, "Personal should find 4 notes"

        # GUI
        pane = NotesListPane(test_config, populated_db)
        pane.search_field.setPlainText("tag:Personal")
        pane.perform_search()
        gui_count = pane.list_widget.count()

        # CLI
        returncode, stdout, _ = cli_runner("--format", "json", "search", "--tag", "Personal")
        assert returncode == 0
        cli_count = len(json.loads(stdout))

        # Web API
        response = web_client.get("/api/search?tag=Personal")
        web_count = len(response.get_json())

        # All should include children
        assert core_count == gui_count == cli_count == web_count

    def test_full_path_disambiguates_all_interfaces(
        self,
        qapp,
        test_config: Config,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
        web_client,
    ) -> None:
        """Full path correctly disambiguates across all interfaces."""
        # Core - France Paris only
        core_result = execute_search(populated_db, "tag:Geography/Europe/France/Paris")
        assert len(core_result.notes) == 1

        # GUI
        pane = NotesListPane(test_config, populated_db)
        pane.search_field.setPlainText("tag:Geography/Europe/France/Paris")
        pane.perform_search()
        gui_count = pane.list_widget.count()

        # CLI
        returncode, stdout, _ = cli_runner(
            "--format", "json", "search", "--tag", "Geography/Europe/France/Paris"
        )
        assert returncode == 0
        cli_count = len(json.loads(stdout))

        # Web API
        response = web_client.get("/api/search?tag=Geography/Europe/France/Paris")
        web_count = len(response.get_json())

        # All should find exactly 1 note
        assert gui_count == cli_count == web_count == 1

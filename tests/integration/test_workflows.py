"""End-to-end workflow tests.

Tests multi-step user scenarios that span multiple components.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import Config
from core.database import Database
from ui.main_window import MainWindow
from ui.notes_list_pane import NotesListPane
from ui.tags_pane import TagsPane
from ui.note_pane import NotePane
from tests.helpers import get_note_uuid_hex, get_tag_uuid_hex


@pytest.mark.integration
class TestGUIWorkflows:
    """Test complete GUI workflows."""

    def test_search_then_select_note_workflow(
        self,
        qapp,
        test_config: Config,
        populated_db: Database,
    ) -> None:
        """Search for notes, then select one to view details."""
        # Create panes
        notes_pane = NotesListPane(test_config, populated_db)
        note_pane = NotePane(populated_db)

        # Connect signal
        selected_note_id = None

        def on_note_selected(note_id: str) -> None:
            nonlocal selected_note_id
            selected_note_id = note_id
            note_pane.load_note(note_id)

        notes_pane.note_selected.connect(on_note_selected)

        # Step 1: Search for "Doctor"
        notes_pane.search_field.setPlainText("Doctor")
        notes_pane.perform_search()
        assert notes_pane.list_widget.count() == 1

        # Step 2: Click on the result
        item = notes_pane.list_widget.item(0)
        notes_pane.list_widget.itemClicked.emit(item)

        # Step 3: Verify note details are displayed (UUID hex string)
        assert selected_note_id == get_note_uuid_hex(3)
        assert "Doctor appointment" in note_pane.content_text.toPlainText()

    def test_tag_click_filters_notes_workflow(
        self,
        qapp,
        test_config: Config,
        populated_db: Database,
    ) -> None:
        """Click on tag in sidebar to filter notes."""
        # Create panes
        tags_pane = TagsPane(populated_db)
        notes_pane = NotesListPane(test_config, populated_db)

        # Connect signal
        tags_pane.tag_selected.connect(notes_pane.filter_by_tag)

        # Initial state - all notes visible
        initial_count = notes_pane.list_widget.count()
        assert initial_count == 9

        # Step 1: Click on Work tag (UUID hex string)
        tags_pane.tag_selected.emit(get_tag_uuid_hex("Work"))

        # Step 2: Verify notes are filtered
        assert notes_pane.list_widget.count() == 2
        assert "tag:Work" in notes_pane.search_field.toPlainText()

    def test_clear_search_shows_all_notes_workflow(
        self,
        qapp,
        test_config: Config,
        populated_db: Database,
    ) -> None:
        """Searching, then clearing search shows all notes again."""
        notes_pane = NotesListPane(test_config, populated_db)

        # Initial state
        initial_count = notes_pane.list_widget.count()
        assert initial_count == 9

        # Step 1: Search to filter
        notes_pane.search_field.setPlainText("tag:Work")
        notes_pane.perform_search()
        assert notes_pane.list_widget.count() == 2

        # Step 2: Clear search
        notes_pane.clear_search()

        # Step 3: All notes visible again
        assert notes_pane.list_widget.count() == 9

    def test_multiple_tag_filters_workflow(
        self,
        qapp,
        test_config: Config,
        populated_db: Database,
    ) -> None:
        """Apply multiple tag filters progressively."""
        tags_pane = TagsPane(populated_db)
        notes_pane = NotesListPane(test_config, populated_db)
        tags_pane.tag_selected.connect(notes_pane.filter_by_tag)

        # Step 1: Filter by Personal (UUID hex string)
        tags_pane.tag_selected.emit(get_tag_uuid_hex("Personal"))
        assert notes_pane.list_widget.count() == 4

        # Step 2: Add Geography filter (AND logic) - UUID hex string
        tags_pane.tag_selected.emit(get_tag_uuid_hex("Geography"))
        # Note 4 and 5 have both Personal and Geography
        assert notes_pane.list_widget.count() == 2


@pytest.mark.integration
class TestCLIWorkflows:
    """Test complete CLI workflows."""

    def test_list_then_show_note_workflow(
        self,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
    ) -> None:
        """List notes, then show details of a specific note."""
        # Step 1: List all notes
        returncode, stdout, stderr = cli_runner("--format", "json", "list-notes")
        assert returncode == 0
        notes = json.loads(stdout)
        assert len(notes) == 9

        # Step 2: Get ID of first note
        first_note_id = notes[0]["id"]

        # Step 3: Show note details
        returncode, stdout, stderr = cli_runner("--format", "json", "show-note", str(first_note_id))
        assert returncode == 0
        note = json.loads(stdout)
        assert note["id"] == first_note_id
        assert "content" in note

    def test_search_with_multiple_formats_workflow(
        self,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
    ) -> None:
        """Search and output in different formats."""
        # Step 1: Search in text format
        returncode, stdout, _ = cli_runner("search", "--text", "Doctor")
        assert returncode == 0
        assert "Doctor" in stdout
        assert "Found 1 note" in stdout

        # Step 2: Same search in JSON format
        returncode, stdout, _ = cli_runner("--format", "json", "search", "--text", "Doctor")
        assert returncode == 0
        notes = json.loads(stdout)
        assert len(notes) == 1

        # Step 3: Same search in CSV format
        returncode, stdout, _ = cli_runner("--format", "csv", "search", "--text", "Doctor")
        assert returncode == 0
        assert "id,created_at,content,tags" in stdout
        assert "Doctor" in stdout

    def test_tag_hierarchy_exploration_workflow(
        self,
        test_config_dir: Path,
        populated_db: Database,
        cli_runner,
    ) -> None:
        """Explore tag hierarchy and search by specific path."""
        # Step 1: List all tags to see hierarchy
        returncode, stdout, _ = cli_runner("list-tags")
        assert returncode == 0
        assert "Geography" in stdout
        assert "Europe" in stdout
        assert "Paris" in stdout

        # Step 2: Search by ambiguous tag (Paris)
        returncode, stdout, stderr = cli_runner("--format", "json", "search", "--tag", "Paris")
        assert returncode == 0
        notes = json.loads(stdout)
        assert len(notes) == 2  # Both Paris locations
        assert "ambiguous" in stderr.lower()

        # Step 3: Search by specific path
        returncode, stdout, _ = cli_runner(
            "--format", "json", "search", "--tag", "Geography/Europe/France/Paris"
        )
        assert returncode == 0
        notes = json.loads(stdout)
        assert len(notes) == 1  # Only France Paris


@pytest.mark.integration
class TestWebAPIWorkflows:
    """Test complete Web API workflows."""

    def test_browse_then_search_workflow(
        self,
        test_config_dir: Path,
        populated_db: Database,
        web_client,
    ) -> None:
        """Browse all notes, then search for specific ones."""
        # Step 1: Get all notes
        response = web_client.get("/api/notes")
        assert response.status_code == 200
        all_notes = response.get_json()
        assert len(all_notes) == 9

        # Step 2: Search for specific text
        response = web_client.get("/api/search?text=Doctor")
        assert response.status_code == 200
        search_results = response.get_json()
        assert len(search_results) == 1

        # Step 3: Get details of found note
        note_id = search_results[0]["id"]
        response = web_client.get(f"/api/notes/{note_id}")
        assert response.status_code == 200
        note = response.get_json()
        assert note["id"] == note_id

    def test_tag_based_navigation_workflow(
        self,
        test_config_dir: Path,
        populated_db: Database,
        web_client,
    ) -> None:
        """Navigate using tags."""
        # Step 1: Get all tags
        response = web_client.get("/api/tags")
        assert response.status_code == 200
        tags = response.get_json()
        assert len(tags) == 21

        # Step 2: Find Work tag and search by it
        work_tags = [t for t in tags if t["name"] == "Work"]
        assert len(work_tags) == 1

        response = web_client.get("/api/search?tag=Work")
        assert response.status_code == 200
        work_notes = response.get_json()
        assert len(work_notes) == 2

        # Step 3: Narrow down with child tag
        response = web_client.get("/api/search?tag=Work&tag=Work/Meetings")
        assert response.status_code == 200
        meeting_notes = response.get_json()
        assert len(meeting_notes) == 1

    def test_combined_filters_workflow(
        self,
        test_config_dir: Path,
        populated_db: Database,
        web_client,
    ) -> None:
        """Apply multiple filters progressively."""
        # Step 1: Start with text search
        response = web_client.get("/api/search?text=reunion")
        assert response.status_code == 200
        assert len(response.get_json()) == 1

        # Step 2: Add tag filter
        response = web_client.get("/api/search?text=reunion&tag=Personal")
        assert response.status_code == 200
        assert len(response.get_json()) == 1

        # Step 3: Add another tag filter
        response = web_client.get("/api/search?text=reunion&tag=Personal&tag=Geography")
        assert response.status_code == 200
        assert len(response.get_json()) == 1

        # Step 4: Filter that excludes - should be empty
        response = web_client.get("/api/search?text=reunion&tag=Work")
        assert response.status_code == 200
        assert len(response.get_json()) == 0

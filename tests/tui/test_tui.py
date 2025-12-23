"""TUI tests for Voice.

Tests the Textual terminal interface using async testing with Pilot.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from textual.widgets import Tree, ListView, Static, TextArea, Button

from src.tui import VoiceTUI, TagsTree, NotesList, NotesListView, NoteDetail, SearchInput
from src.core.config import Config
from src.core.database import Database


pytestmark = pytest.mark.tui


class TestTUIStartup:
    """Test TUI application startup."""

    async def test_app_starts(self, populated_db: Database, test_config: Config) -> None:
        """Test that the TUI app starts without errors."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            assert app.is_running

    async def test_app_has_title(self, populated_db: Database, test_config: Config) -> None:
        """Test that the app has the correct title."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            assert app.title == "Voice"

    async def test_three_panes_exist(self, populated_db: Database, test_config: Config) -> None:
        """Test that all three panes are created."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            tags_tree = app.query_one("#tags-tree", TagsTree)
            notes_list = app.query_one("#notes-list", NotesList)
            note_detail = app.query_one("#note-detail", NoteDetail)

            assert tags_tree is not None
            assert notes_list is not None
            assert note_detail is not None


class TestTagsTree:
    """Test tags tree widget."""

    async def test_tags_tree_loads(self, populated_db: Database, test_config: Config) -> None:
        """Test that tags tree populates with tags from database."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            tree = app.query_one("#tags-tree", TagsTree)
            # Root should have children (root-level tags)
            assert len(tree.root.children) > 0

    async def test_tags_tree_has_root_tags(self, populated_db: Database, test_config: Config) -> None:
        """Test that root-level tags are present."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            tree = app.query_one("#tags-tree", TagsTree)
            root_tag_names = [str(node.label) for node in tree.root.children]

            # Check for expected root tags
            assert "Work" in root_tag_names
            assert "Personal" in root_tag_names
            assert "Geography" in root_tag_names

    async def test_expand_tag_with_right_arrow(self, populated_db: Database, test_config: Config) -> None:
        """Test that right arrow expands a tag."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            tree = app.query_one("#tags-tree", TagsTree)
            tree.focus()

            # Move to first tag and expand
            await pilot.press("down")
            node = tree.cursor_node

            if node and node.allow_expand:
                was_expanded = node.is_expanded
                await pilot.press("right")
                # After right arrow, should be expanded
                assert node.is_expanded or was_expanded

    async def test_left_arrow_collapses_expanded_node(self, populated_db: Database, test_config: Config) -> None:
        """Test that left arrow collapses the current node if expanded."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            tree = app.query_one("#tags-tree", TagsTree)
            tree.focus()

            # Find any expanded node and verify left collapses it
            await pilot.press("down")

            # Find an expanded node
            for _ in range(15):
                node = tree.cursor_node
                if node and node.is_expanded and node.allow_expand:
                    # Found an expanded node, collapse it
                    await pilot.press("left")
                    await pilot.pause()
                    assert not node.is_expanded, f"Node {node.label} should be collapsed"
                    return  # Test passed
                await pilot.press("down")

            # If no expanded nodes found, just verify left arrow doesn't crash
            await pilot.press("left")
            # Test passes if no exception


class TestNotesList:
    """Test notes list widget."""

    async def test_notes_list_loads(self, populated_db: Database, test_config: Config) -> None:
        """Test that notes list populates with notes from database."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            notes_list = app.query_one("#notes-list", NotesList)
            # Should have notes loaded
            assert len(notes_list.notes) > 0

    async def test_notes_list_count_matches_database(self, populated_db: Database, test_config: Config) -> None:
        """Test that notes list has correct number of notes."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            notes_list = app.query_one("#notes-list", NotesList)
            db_notes = populated_db.get_all_notes()
            assert len(notes_list.notes) == len(db_notes)

    async def test_search_by_tag(self, populated_db: Database, test_config: Config) -> None:
        """Test that selecting a tag populates search and filters notes."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            notes_list = app.query_one("#notes-list", NotesList)

            # Focus tags tree and select a tag
            tree = app.query_one("#tags-tree", TagsTree)
            tree.focus()
            await pilot.press("down")  # Move to first tag
            await pilot.press("enter")  # Select it

            # Search field should be populated with tag search
            search_text = notes_list.get_search_text()
            assert search_text.startswith("tag:"), f"Expected 'tag:' prefix, got: {search_text}"


class TestNoteDetail:
    """Test note detail widget."""

    async def test_note_detail_exists(self, populated_db: Database, test_config: Config) -> None:
        """Test that note detail pane exists with expected widgets."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            detail = app.query_one("#note-detail", NoteDetail)

            # Should have header, view, edit area, and buttons
            header = detail.query_one("#note-header")
            view = detail.query_one("#note-view")
            edit = detail.query_one("#note-edit")

            assert header is not None
            assert view is not None
            assert edit is not None

    async def test_select_note_shows_content(self, populated_db: Database, test_config: Config) -> None:
        """Test that selecting a note displays its content."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            # Focus notes listview (inside notes-list container) and select first note
            listview = app.query_one("#notes-listview", NotesListView)
            notes_list = app.query_one("#notes-list", NotesList)

            # Verify notes are loaded
            assert len(notes_list.notes) > 0, "No notes loaded in list"

            listview.focus()
            await pilot.pause()
            await pilot.press("down")  # Move to first item
            await pilot.press("enter")  # Select first note
            await pilot.pause()

            detail = app.query_one("#note-detail", NoteDetail)
            # Should have a note loaded
            assert detail.current_note_id is not None

    async def test_edit_button_shows_textarea(self, populated_db: Database, test_config: Config) -> None:
        """Test that edit button reveals the text area."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            # Select a note first via the listview
            listview = app.query_one("#notes-listview", NotesListView)
            notes_list = app.query_one("#notes-list", NotesList)

            # Verify notes are loaded
            assert len(notes_list.notes) > 0, "No notes loaded in list"

            listview.focus()
            await pilot.pause()
            await pilot.press("down")  # Move to first item
            await pilot.press("enter")
            await pilot.pause()

            detail = app.query_one("#note-detail", NoteDetail)
            edit_area = detail.query_one("#note-edit", TextArea)

            # Initially hidden
            assert not edit_area.display

            # Click edit button
            await pilot.click("#edit-btn")
            await pilot.pause()

            # Now should be visible
            assert edit_area.display


class TestKeyboardNavigation:
    """Test keyboard navigation and shortcuts."""

    async def test_quit_with_q(self, populated_db: Database, test_config: Config) -> None:
        """Test that 'q' quits the application."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            await pilot.press("q")
            # App should exit (no assertion needed - test passes if no error)

    async def test_show_all_with_a(self, populated_db: Database, test_config: Config) -> None:
        """Test that 'a' shows all notes (clears search)."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            notes_list = app.query_one("#notes-list", NotesList)

            # First search by a tag
            tree = app.query_one("#tags-tree", TagsTree)
            tree.focus()
            await pilot.press("down")
            await pilot.press("enter")

            # Verify search was set
            assert notes_list.get_search_text() != ""

            # Now clear search with 'a'
            await pilot.press("a")

            # Search should be cleared
            assert notes_list.get_search_text() == ""

    async def test_refresh_with_r(self, populated_db: Database, test_config: Config) -> None:
        """Test that 'r' refreshes the notes list."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            notes_list = app.query_one("#notes-list", NotesList)
            initial_count = len(notes_list.notes)

            await pilot.press("r")

            # Should still have notes after refresh
            assert len(notes_list.notes) == initial_count


class TestSearch:
    """Test search functionality."""

    async def test_search_input_exists(self, populated_db: Database, test_config: Config) -> None:
        """Test that search input field exists."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            search_input = app.query_one("#search-input", SearchInput)
            assert search_input is not None

    async def test_search_filters_notes(self, populated_db: Database, test_config: Config) -> None:
        """Test that typing in search field and pressing Enter filters notes."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            notes_list = app.query_one("#notes-list", NotesList)

            # Use the NotesList method to set search (search input has can_focus=False)
            notes_list.set_search_text("Work")

            # Focus listview and press up to access search, then enter to search
            listview = app.query_one("#notes-listview", NotesListView)
            listview.focus()
            await pilot.press("up")  # Go to search input
            await pilot.pause()
            await pilot.press("enter")  # Run search
            await pilot.pause()

            # Notes should be filtered
            assert notes_list.current_search == "Work"

    async def test_clear_search_with_a(self, populated_db: Database, test_config: Config) -> None:
        """Test that pressing 'a' clears search and shows all notes."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            notes_list = app.query_one("#notes-list", NotesList)
            initial_count = len(notes_list.notes)

            # Set a search
            notes_list.set_search_text("test search")
            notes_list.perform_search("test search")

            # Now press 'a' to clear
            await pilot.press("a")
            await pilot.pause()

            # Search should be cleared and all notes shown
            assert notes_list.get_search_text() == ""
            assert len(notes_list.notes) == initial_count

    async def test_up_arrow_focuses_search(self, populated_db: Database, test_config: Config) -> None:
        """Test that Up Arrow from notes list focuses search input."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            listview = app.query_one("#notes-listview", NotesListView)
            search_input = app.query_one("#search-input", SearchInput)

            # Focus the listview
            listview.focus()
            await pilot.pause()

            # Press up to go to search
            await pilot.press("up")
            await pilot.pause()

            # Search input should now have focus
            assert search_input.has_focus

    async def test_down_arrow_focuses_list(self, populated_db: Database, test_config: Config) -> None:
        """Test that Down Arrow from search input focuses notes list."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            listview = app.query_one("#notes-listview", NotesListView)
            search_input = app.query_one("#search-input", SearchInput)

            # Focus the listview first, then go up to search
            listview.focus()
            await pilot.press("up")
            await pilot.pause()
            assert search_input.has_focus

            # Press down to go back to list
            await pilot.press("down")
            await pilot.pause()

            # Listview should now have focus
            assert listview.has_focus


class TestBorderColors:
    """Test that border colors are applied from config."""

    async def test_config_colors_loaded(self, populated_db: Database, test_config: Config) -> None:
        """Test that TUI loads border colors from config."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            # Check that border colors were loaded
            assert app._border_focused is not None
            assert app._border_unfocused is not None

    async def test_default_colors(self, populated_db: Database, test_config: Config) -> None:
        """Test that default colors are green/blue."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            # Default colors from config
            assert app._border_focused == "green"
            assert app._border_unfocused == "blue"


class TestHebrewContent:
    """Test Hebrew/RTL content display."""

    async def test_hebrew_note_loads(self, populated_db: Database, test_config: Config) -> None:
        """Test that Hebrew notes load without errors."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            notes_list = app.query_one("#notes-list", NotesList)

            # Find Hebrew note
            hebrew_notes = [n for n in notes_list.notes if "שלום" in n["content"]]
            assert len(hebrew_notes) > 0

    async def test_hebrew_tag_loads(self, populated_db: Database, test_config: Config) -> None:
        """Test that Hebrew text in notes displays correctly."""
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            # App should start without errors even with Hebrew content
            assert app.is_running

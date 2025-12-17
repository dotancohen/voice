"""Integration tests for NotesListPane.

Tests the notes list pane UI component including:
- Note display
- Search functionality
- Tag filtering
- Signal emission
"""

from __future__ import annotations

import pytest
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtCore import Qt

from core.config import Config
from core.database import Database
from ui.notes_list_pane import NotesListPane


@pytest.mark.integration
class TestNotesListPaneInit:
    """Test NotesListPane initialization."""

    def test_creates_notes_list_pane(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that NotesListPane can be created."""
        pane = NotesListPane(test_config, populated_db)
        assert pane is not None
        assert pane.list_widget is not None
        assert pane.search_field is not None
        assert pane.search_button is not None
        assert pane.clear_button is not None

    def test_loads_notes_on_init(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that notes are loaded on initialization."""
        pane = NotesListPane(test_config, populated_db)
        assert pane.list_widget.count() == 6  # 6 notes in fixture


@pytest.mark.integration
class TestNoteDisplay:
    """Test note display formatting."""

    def test_displays_all_notes(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that all notes are displayed."""
        pane = NotesListPane(test_config, populated_db)
        assert pane.list_widget.count() == 6

    def test_note_format_two_lines(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that notes are displayed in two-line format."""
        pane = NotesListPane(test_config, populated_db)

        # Get first note
        item = pane.list_widget.item(0)
        text = item.text()

        # Should have newline separating timestamp and content
        assert "\n" in text
        lines = text.split("\n")
        assert len(lines) == 2

        # First line should be timestamp (YYYY-MM-DD HH:MM:SS)
        assert "-" in lines[0]  # Date separator
        assert ":" in lines[0]  # Time separator

    def test_long_content_truncated(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that long content is truncated with ellipsis."""
        # Add a note with very long content
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        long_content = "A" * 200  # Much longer than 100 char limit

        with populated_db.conn:
            cursor = populated_db.conn.cursor()
            cursor.execute(
                "INSERT INTO notes (created_at, content) VALUES (?, ?)",
                (now, long_content)
            )

        pane = NotesListPane(test_config, populated_db)

        # Find the note with long content
        found_truncated = False
        for i in range(pane.list_widget.count()):
            item = pane.list_widget.item(i)
            text = item.text()
            if "AAAA" in text:  # Part of our long content
                assert text.endswith("...")
                # Content line should be truncated
                lines = text.split("\n")
                assert len(lines[1]) <= 103  # 100 chars + "..."
                found_truncated = True
                break

        assert found_truncated

    def test_hebrew_text_displays(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that Hebrew text is displayed correctly."""
        pane = NotesListPane(test_config, populated_db)

        # Find Hebrew note (Note 6)
        found_hebrew = False
        for i in range(pane.list_widget.count()):
            item = pane.list_widget.item(i)
            text = item.text()
            if "שלום" in text:
                found_hebrew = True
                break

        assert found_hebrew


@pytest.mark.integration
class TestNoteSelection:
    """Test note selection functionality."""

    def test_clicking_note_emits_signal(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that clicking a note emits note_selected signal."""
        pane = NotesListPane(test_config, populated_db)
        spy = QSignalSpy(pane.note_selected)

        # Click first note
        item = pane.list_widget.item(0)
        pane.on_note_clicked(item)

        # Signal should be emitted
        assert spy.count() == 1
        # Should emit a note ID
        args = spy.at(0)
        assert len(args) == 1
        assert isinstance(args[0], int)

    def test_emits_correct_note_id(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that correct note ID is emitted."""
        pane = NotesListPane(test_config, populated_db)
        spy = QSignalSpy(pane.note_selected)

        # Find note with known content
        for i in range(pane.list_widget.count()):
            item = pane.list_widget.item(i)
            if "Meeting notes" in item.text():
                pane.on_note_clicked(item)
                break

        # Should emit note ID 1
        assert spy.count() == 1
        args = spy.at(0)
        assert args[0] == 1


@pytest.mark.integration
class TestSearchField:
    """Test search field functionality."""

    def test_search_field_placeholder(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that search field has appropriate placeholder."""
        pane = NotesListPane(test_config, populated_db)
        placeholder = pane.search_field.placeholderText()
        assert "tag:" in placeholder.lower()

    def test_search_button_triggers_search(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that clicking search button triggers search."""
        pane = NotesListPane(test_config, populated_db)

        # Enter search text
        pane.search_field.setText("meeting")

        # Click search button
        pane.search_button.click()

        # Should filter to 1 note
        assert pane.list_widget.count() == 1
        item = pane.list_widget.item(0)
        assert "Meeting notes" in item.text()

    def test_return_key_triggers_search(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that pressing Return in search field triggers search."""
        pane = NotesListPane(test_config, populated_db)

        # Enter search text
        pane.search_field.setText("reunion")

        # Simulate Return key
        QTest.keyClick(pane.search_field, Qt.Key.Key_Return)

        # Should filter to 1 note
        assert pane.list_widget.count() == 1

    def test_clear_button_clears_search(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that Clear button clears search field."""
        pane = NotesListPane(test_config, populated_db)

        # Enter search and execute
        pane.search_field.setText("meeting")
        pane.search_button.click()
        assert pane.list_widget.count() == 1

        # Click clear
        pane.clear_button.click()

        # Search field should be empty and all notes shown
        assert pane.search_field.text() == ""
        assert pane.list_widget.count() == 6


@pytest.mark.integration
class TestFreeTextSearch:
    """Test free-text search functionality."""

    def test_searches_note_content(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test free-text search in note content."""
        pane = NotesListPane(test_config, populated_db)

        pane.search_field.setText("doctor")
        pane.perform_search()

        assert pane.list_widget.count() == 1
        item = pane.list_widget.item(0)
        assert "Doctor appointment" in item.text()

    def test_case_insensitive_search(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that search is case-insensitive."""
        pane = NotesListPane(test_config, populated_db)

        # Try different cases
        test_cases = ["MEETING", "meeting", "MeEtInG"]
        for query in test_cases:
            pane.search_field.setText(query)
            pane.perform_search()
            assert pane.list_widget.count() == 1

    def test_hebrew_text_search(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test search with Hebrew text."""
        pane = NotesListPane(test_config, populated_db)

        pane.search_field.setText("שלום")
        pane.perform_search()

        assert pane.list_widget.count() == 1
        item = pane.list_widget.item(0)
        assert "שלום עולם" in item.text()


@pytest.mark.integration
class TestTagFiltering:
    """Test tag filtering from sidebar."""

    def test_filter_by_tag_single_match(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test filtering by tag with single name match."""
        pane = NotesListPane(test_config, populated_db)

        # Filter by Work tag (ID 1)
        pane.filter_by_tag(1)

        # Should add to search field and perform search
        assert "tag:Work" in pane.search_field.text()
        # Work has 2 notes directly tagged
        assert pane.list_widget.count() >= 2

    def test_filter_includes_child_tags(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that filtering by parent includes child tags."""
        pane = NotesListPane(test_config, populated_db)

        # Filter by Personal (ID 5)
        # Should include notes with Family, Health (children)
        pane.filter_by_tag(5)

        # Should find 4 notes (3, 4, 5, 6)
        assert pane.list_widget.count() == 4

    def test_appends_to_existing_search(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that clicking tag appends to existing search."""
        pane = NotesListPane(test_config, populated_db)

        # Start with text search
        pane.search_field.setText("reunion")

        # Click tag
        pane.filter_by_tag(5)  # Personal

        # Should have both
        search_text = pane.search_field.text()
        assert "reunion" in search_text
        assert "tag:" in search_text


@pytest.mark.integration
class TestColorManagement:
    """Test search field color management."""

    def test_default_text_color_white(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that default text color is white."""
        from ui.notes_list_pane import DEFAULT_TEXT_COLOR
        assert DEFAULT_TEXT_COLOR == "#FFFFFF"

    def test_editing_restores_white_color(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that editing search field restores white color."""
        pane = NotesListPane(test_config, populated_db)

        # Simulate yellow highlighting
        from PySide6.QtGui import QColor
        palette = pane.search_field.palette()
        palette.setColor(pane.search_field.foregroundRole(), QColor("#FFFF00"))
        pane.search_field.setPalette(palette)

        # Edit field (triggers textChanged)
        pane.search_field.setText("test")

        # Color should be restored to white
        current_color = pane.search_field.palette().color(
            pane.search_field.foregroundRole()
        )
        assert current_color.name().upper() == "#FFFFFF"

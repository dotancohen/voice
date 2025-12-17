"""Notes list pane displaying notes with two-line format.

This module provides the center pane showing a list of notes with search functionality.
Each note displays created_at on the first line and truncated content on the second line.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.config import Config
from core.database import Database

logger = logging.getLogger(__name__)

# Constants
CONTENT_TRUNCATE_LENGTH = 100
DEFAULT_TEXT_COLOR = "#FFFFFF"  # White


class NotesListPane(QWidget):
    """Pane displaying list of notes with two-line format and search.

    Each note shows:
    - Line 1: created_at timestamp (YYYY-MM-DD HH:MM:SS)
    - Line 2: content (truncated to 100 characters with "...")

    Search supports:
    - Free-text search in note content
    - tag:tagname syntax for tag filtering (case-insensitive)
    - Hierarchical paths like tag:Europe/France/Paris

    Signals:
        note_selected: Emitted when a note is clicked (note_id: int)

    Attributes:
        config: Configuration manager
        db: Database connection
        search_field: QLineEdit for search input
        search_button: QPushButton to trigger search
        list_widget: QListWidget for displaying notes
        warning_color: Hex color for highlighting ambiguous tags
    """

    note_selected = Signal(int)  # Emits note_id

    def __init__(
        self, config: Config, db: Database, parent: Optional[QWidget] = None
    ) -> None:
        """Initialize the notes list pane.

        Args:
            config: Configuration manager
            db: Database connection
            parent: Parent widget (default None)
        """
        super().__init__(parent)
        self.config = config
        self.db = db
        self.warning_color = self.config.get_warning_color()

        self.setup_ui()
        self.load_notes()

        logger.info("Notes list pane initialized")

    def setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create search toolbar
        toolbar = QHBoxLayout()

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search notes... (use tag:tagname for tags)")
        self.search_field.returnPressed.connect(self.perform_search)
        self.search_field.textChanged.connect(self.on_search_field_edited)

        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_search)

        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.perform_search)

        toolbar.addWidget(self.search_field)
        toolbar.addWidget(self.clear_button)
        toolbar.addWidget(self.search_button)

        layout.addLayout(toolbar)

        # Create list widget
        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(self.on_note_clicked)

        layout.addWidget(self.list_widget)

    def load_notes(self, notes: Optional[List[Dict[str, Any]]] = None) -> None:
        """Load notes into the list widget.

        Args:
            notes: List of note dictionaries. If None, loads all notes from database.
        """
        self.list_widget.clear()

        if notes is None:
            notes = self.db.get_all_notes()

        for note in notes:
            item = self.create_note_item(note)
            self.list_widget.addItem(item)

        logger.info(f"Loaded {len(notes)} notes into list")

    def create_note_item(self, note: Dict[str, Any]) -> QListWidgetItem:
        """Create a list item for a note with two-line format.

        Args:
            note: Note dictionary from database

        Returns:
            QListWidgetItem configured with note data.
        """
        # Format created_at timestamp
        created_at = note.get("created_at", "Unknown")

        # Truncate and clean content
        content = note.get("content", "")
        # Replace newlines and carriage returns with spaces
        content = content.replace("\n", " ").replace("\r", "")
        # Truncate if too long
        if len(content) > CONTENT_TRUNCATE_LENGTH:
            content = content[:CONTENT_TRUNCATE_LENGTH] + "..."

        # Create two-line text
        display_text = f"{created_at}\n{content}"

        # Create item
        item = QListWidgetItem(display_text)
        item.setData(Qt.ItemDataRole.UserRole, note["id"])  # Store note_id

        return item

    def on_note_clicked(self, item: QListWidgetItem) -> None:
        """Handle note click event.

        Args:
            item: Clicked list widget item
        """
        note_id = item.data(Qt.ItemDataRole.UserRole)
        logger.info(f"Note selected: ID {note_id}")
        self.note_selected.emit(note_id)

    def filter_by_tag(self, tag_id: int) -> None:
        """Handle tag selection from sidebar.

        Finds tag name and full path, then adds to search field.
        If multiple tags share the name, adds all paths with yellow highlighting.
        If single tag, appends to search and runs search immediately.

        Args:
            tag_id: Tag ID from sidebar selection
        """
        # Get the clicked tag's information
        tag = self.db.get_tag(tag_id)
        if not tag:
            logger.warning(f"Tag ID {tag_id} not found")
            return

        tag_name = tag["name"]
        logger.info(f"Sidebar tag clicked: {tag_name} (ID: {tag_id})")

        # Find ALL tags with this name (case-insensitive)
        matching_tags = self.db.get_tags_by_name(tag_name)

        if len(matching_tags) == 0:
            logger.warning(f"No tags found matching '{tag_name}'")
            return
        elif len(matching_tags) == 1:
            # Single match: append to search and run immediately
            tag_path = self._get_tag_full_path(matching_tags[0]["id"])
            tag_search = f"tag:{tag_path}"

            # Check if already in search field
            current_text = self.search_field.text()
            if tag_search.lower() not in current_text.lower():
                # Append to search field
                new_text = f"{current_text} {tag_search}".strip()
                self.search_field.setText(new_text)

            # Run search immediately
            self.perform_search()
        else:
            # Multiple matches: add all paths with yellow highlighting, don't run search
            logger.info(f"Found {len(matching_tags)} tags named '{tag_name}'")

            current_text = self.search_field.text()
            new_tags: List[str] = []

            for tag_match in matching_tags:
                tag_path = self._get_tag_full_path(tag_match["id"])
                tag_search = f"tag:{tag_path}"

                # Check if already in search field (case-insensitive)
                if tag_search.lower() not in current_text.lower():
                    new_tags.append(tag_search)

            if new_tags:
                # Append new tags
                all_new_tags = " ".join(new_tags)
                new_text = f"{current_text} {all_new_tags}".strip()
                self.search_field.setText(new_text)

                # Highlight the newly added tags in yellow
                self._highlight_new_tags(new_tags)

                # Focus the search field
                self.search_field.setFocus()

    def _get_tag_full_path(self, tag_id: int) -> str:
        """Get the full hierarchical path for a tag.

        Args:
            tag_id: Tag ID to get path for

        Returns:
            Full path like "Europe/France/Paris" or just "Work" for root tags.
        """
        path_parts: List[str] = []
        current_id: Optional[int] = tag_id

        while current_id is not None:
            tag = self.db.get_tag(current_id)
            if not tag:
                break
            path_parts.insert(0, tag["name"])
            current_id = tag.get("parent_id")

        return "/".join(path_parts)

    def _highlight_new_tags(self, new_tags: List[str]) -> None:
        """Highlight newly added tags in the search field with warning color.

        Args:
            new_tags: List of tag search strings that were just added
        """
        # Set text color for the search field
        palette = self.search_field.palette()
        palette.setColor(self.search_field.foregroundRole(), QColor(self.warning_color))
        self.search_field.setPalette(palette)

    def on_search_field_edited(self) -> None:
        """Handle search field text changes - restore default color on edit."""
        # Restore default text color
        palette = self.search_field.palette()
        palette.setColor(self.search_field.foregroundRole(), QColor(DEFAULT_TEXT_COLOR))
        self.search_field.setPalette(palette)

    def clear_search(self) -> None:
        """Clear the search field and show all notes."""
        self.search_field.clear()
        self.load_notes()
        logger.info("Search cleared, showing all notes")

    def perform_search(self) -> None:
        """Perform search based on search field content.

        Parses tag: keywords and free text, then searches database.
        """
        search_text = self.search_field.text().strip()
        logger.info(f"Performing search: '{search_text}'")

        # Parse search input
        tag_names, free_text = self._parse_search_input(search_text)

        # Collect tag ID groups (each tag term with its descendants is one group)
        tag_id_groups: List[List[int]] = []

        for tag_name in tag_names:
            # Get tag by path (handles hierarchical paths like Europe/France/Paris)
            tag = self.db.get_tag_by_path(tag_name)
            if tag:
                # Get this tag and all descendants as a group
                descendants = self.db.get_tag_descendants(tag["id"])
                tag_id_groups.append(descendants)
                logger.info(
                    f"Tag '{tag_name}' matched {len(descendants)} tags (including descendants)"
                )
            else:
                logger.warning(f"Tag path '{tag_name}' not found")

        # Perform search
        if free_text or tag_id_groups:
            notes = self.db.search_notes(
                text_query=free_text if free_text else None,
                tag_id_groups=tag_id_groups if tag_id_groups else None
            )
        else:
            # No search criteria, show all notes
            notes = self.db.get_all_notes()

        logger.info(f"Search returned {len(notes)} notes")

        # Update display
        self.load_notes(notes)

    def _parse_search_input(self, search_input: str) -> tuple[List[str], str]:
        """Parse search input to extract tag: keywords and free text.

        Args:
            search_input: Raw search input from search field

        Returns:
            Tuple of (tag_names, free_text) where tag_names may include paths.
        """
        if not search_input:
            return ([], "")

        words = search_input.split()
        tag_names: List[str] = []
        text_words: List[str] = []

        for word in words:
            if word.lower().startswith("tag:"):
                # Extract tag name/path (everything after "tag:")
                tag_name = word[4:]  # Remove "tag:" prefix
                if tag_name:
                    tag_names.append(tag_name)
            else:
                text_words.append(word)

        free_text = " ".join(text_words).strip()

        return (tag_names, free_text)

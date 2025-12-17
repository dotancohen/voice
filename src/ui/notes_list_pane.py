"""Notes list pane displaying notes with two-line format.

This module provides the center pane showing a list of notes with search functionality.
Each note displays created_at on the first line and truncated content on the second line.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QTextCharFormat, QTextCursor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.config import Config
from core.database import Database

logger = logging.getLogger(__name__)

# Constants
CONTENT_TRUNCATE_LENGTH = 100
DEFAULT_TEXT_COLOR = "#FFFFFF"  # White


class SearchTextEdit(QTextEdit):
    """Custom QTextEdit that triggers search on Enter key."""

    returnPressed = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle key press events."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Trigger search on Enter, don't insert newline
            if event.modifiers() == Qt.KeyboardModifier.NoModifier:
                self.returnPressed.emit()
                event.accept()
                return
        super().keyPressEvent(event)


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
        self._updating_search_field = False  # Flag to prevent recursive updates

        self.setup_ui()
        self.load_notes()

        logger.info("Notes list pane initialized")

    def setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create search toolbar
        toolbar = QHBoxLayout()

        self.search_field = SearchTextEdit()
        self.search_field.setPlaceholderText("Search notes... (use tag:tagname for tags)")
        self.search_field.setAcceptRichText(False)  # Use plain text to prevent formatting inheritance
        # Configure as single-line input
        self.search_field.setMaximumHeight(35)
        self.search_field.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.search_field.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.search_field.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        # Enable undo/redo functionality
        self.search_field.setUndoRedoEnabled(True)
        self.search_field.textChanged.connect(self.on_search_field_edited)
        self.search_field.returnPressed.connect(self.perform_search)

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

        Adds the clicked tag to search field.
        If ambiguous (multiple tags with same name): adds full path with yellow highlighting.
        If not ambiguous (single tag): uses just the tag name and runs search immediately.

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

        # Check if this tag name is ambiguous (appears more than once)
        matching_tags = self.db.get_tags_by_name(tag_name)
        is_ambiguous = len(matching_tags) > 1

        if is_ambiguous:
            # Tag name is ambiguous: use full path for THIS specific tag
            tag_path = self._get_tag_full_path(tag_id)
            tag_search = f"tag:{tag_path}"
            logger.info(f"Tag name '{tag_name}' is ambiguous, using full path: {tag_path}")

            # Check if already in search field
            current_text = self.search_field.toPlainText()
            if tag_search.lower() not in current_text.lower():
                # Append to search field
                new_text = f"{current_text} {tag_search}".strip()
                self.search_field.setPlainText(new_text)

            # Run search immediately (highlighting will happen in on_search_field_edited)
            self.perform_search()
        else:
            # Tag name is not ambiguous: use just the tag name
            tag_search = f"tag:{tag_name}"

            # Check if already in search field
            current_text = self.search_field.toPlainText()
            if tag_search.lower() not in current_text.lower():
                # Append to search field
                new_text = f"{current_text} {tag_search}".strip()
                self.search_field.setPlainText(new_text)

            # Run search immediately
            self.perform_search()

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

    def on_search_field_edited(self) -> None:
        """Handle search field text changes and highlight ambiguous tags."""
        # Prevent recursive updates
        if self._updating_search_field:
            return

        self._updating_search_field = True
        try:
            # Get plain text to avoid recursive updates
            text = self.search_field.toPlainText()

            # Parse to find tag terms
            tag_names, _ = self._parse_search_input(text)

            # Check which tags are ambiguous
            ambiguous_tag_terms: List[str] = []
            for tag_name in tag_names:
                matching_tags = self.db.get_all_tags_by_path(tag_name)
                if len(matching_tags) > 1:
                    ambiguous_tag_terms.append(f"tag:{tag_name}")

            # Save cursor position before making changes
            cursor_position = self.search_field.textCursor().position()

            # Block signals to prevent recursive updates
            self.search_field.blockSignals(True)

            # Apply highlighting if there are ambiguous tags
            if ambiguous_tag_terms:
                self._apply_highlighting(text, ambiguous_tag_terms, cursor_position)
            else:
                # No ambiguous tags - ensure all text is white
                self._clear_all_formatting(text, cursor_position)

            self.search_field.blockSignals(False)
        finally:
            self._updating_search_field = False

    def _clear_all_formatting(self, text: str, cursor_position: int) -> None:
        """Clear all formatting and set text to white.

        Args:
            text: The text to set
            cursor_position: Position to restore cursor to
        """
        # Set the text
        self.search_field.setPlainText(text)

        # Create white color format for all text
        white_format = QTextCharFormat()
        white_format.setForeground(QColor("#FFFFFF"))

        # Apply white color to entire document
        cursor = self.search_field.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.setCharFormat(white_format)

        # Restore cursor position
        cursor.clearSelection()
        cursor.setPosition(min(cursor_position, len(text)))
        self.search_field.setTextCursor(cursor)

    def _apply_highlighting(self, text: str, ambiguous_terms: List[str], cursor_position: int) -> None:
        """Apply yellow highlighting to ambiguous tag terms in the search field.

        Args:
            text: The full search text
            ambiguous_terms: List of ambiguous tag terms (e.g., ["tag:bar"])
            cursor_position: Position to restore cursor to
        """
        # Set the plain text first
        self.search_field.setPlainText(text)

        # Create text formats
        white_format = QTextCharFormat()
        white_format.setForeground(QColor("#FFFFFF"))

        yellow_format = QTextCharFormat()
        yellow_format.setForeground(QColor(self.warning_color))

        # Get cursor for formatting
        cursor = self.search_field.textCursor()

        # First, set all text to white
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.setCharFormat(white_format)

        # Find and highlight ambiguous terms
        text_lower = text.lower()
        for term in ambiguous_terms:
            term_lower = term.lower()
            pos = 0
            while True:
                # Find next occurrence of this term (case-insensitive)
                idx = text_lower.find(term_lower, pos)
                if idx == -1:
                    break

                # Select the match and apply yellow format
                cursor.setPosition(idx)
                cursor.setPosition(idx + len(term), QTextCursor.MoveMode.KeepAnchor)
                cursor.setCharFormat(yellow_format)

                pos = idx + len(term)

        # Restore cursor position
        cursor.clearSelection()
        cursor.setPosition(min(cursor_position, len(text)))
        self.search_field.setTextCursor(cursor)

    def clear_search(self) -> None:
        """Clear the search field and show all notes."""
        self.search_field.clear()
        self.load_notes()
        logger.info("Search cleared, showing all notes")

    def perform_search(self) -> None:
        """Perform search based on search field content.

        Parses tag: keywords and free text, then searches database.
        Ambiguous tags (matching multiple tags) use OR logic within the group.
        """
        search_text = self.search_field.toPlainText().strip()
        logger.info(f"Performing search: '{search_text}'")

        # Parse search input
        tag_names, free_text = self._parse_search_input(search_text)

        # Collect tag ID groups (each tag term with its descendants is one group)
        # For ambiguous tags, all matching tags' descendants go into ONE group (OR logic)
        tag_id_groups: List[List[int]] = []
        any_tag_not_found = False

        for tag_name in tag_names:
            # Get ALL tags matching this path (handles hierarchical paths and ambiguous names)
            matching_tags = self.db.get_all_tags_by_path(tag_name)

            if matching_tags:
                # Collect all descendants from all matching tags into ONE group (OR logic)
                all_descendants: List[int] = []
                for tag in matching_tags:
                    descendants = self.db.get_tag_descendants(tag["id"])
                    all_descendants.extend(descendants)

                # Remove duplicates
                all_descendants = list(set(all_descendants))
                tag_id_groups.append(all_descendants)

                # Check if ambiguous (multiple matches)
                if len(matching_tags) > 1:
                    logger.info(
                        f"Tag '{tag_name}' is ambiguous - matched {len(matching_tags)} tags, "
                        f"total {len(all_descendants)} tag IDs with descendants (OR logic)"
                    )
                else:
                    logger.info(
                        f"Tag '{tag_name}' matched {len(all_descendants)} tags (including descendants)"
                    )
            else:
                logger.warning(f"Tag path '{tag_name}' not found")
                any_tag_not_found = True

        # Note: Highlighting of ambiguous tags is now handled in on_search_field_edited()

        # If any requested tag was not found, return empty results
        if any_tag_not_found:
            notes = []
        # Perform search
        elif free_text or tag_id_groups:
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

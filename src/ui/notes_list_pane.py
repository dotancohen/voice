"""Notes list pane displaying notes with two-line format.

This module provides the center pane showing a list of notes.
Each note displays created_at on the first line and truncated content on the second line.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from core.database import Database

logger = logging.getLogger(__name__)

# Constants
CONTENT_TRUNCATE_LENGTH = 100


class NotesListPane(QWidget):
    """Pane displaying list of notes with two-line format.

    Each note shows:
    - Line 1: created_at timestamp (YYYY-MM-DD HH:MM:SS)
    - Line 2: content (truncated to 100 characters with "...")

    Signals:
        note_selected: Emitted when a note is clicked (note_id: int)

    Attributes:
        db: Database connection
        list_widget: QListWidget for displaying notes
        current_filter_tag_id: Currently selected tag ID for filtering (None = show all)
    """

    note_selected = Signal(int)  # Emits note_id

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        """Initialize the notes list pane.

        Args:
            db: Database connection
            parent: Parent widget (default None)
        """
        super().__init__(parent)
        self.db = db
        self.current_filter_tag_id: Optional[int] = None

        self.setup_ui()
        self.load_notes()

        logger.info("Notes list pane initialized")

    def setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

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
        """Filter notes by tag ID (including descendant tags).

        Args:
            tag_id: Tag ID to filter by
        """
        self.current_filter_tag_id = tag_id
        logger.info(f"Filtering notes by tag ID: {tag_id}")

        # Get tag descendants (includes the tag itself)
        tag_ids = self.db.get_tag_descendants(tag_id)

        # Get filtered notes
        notes = self.db.filter_notes(tag_ids)

        # Update display
        self.load_notes(notes)

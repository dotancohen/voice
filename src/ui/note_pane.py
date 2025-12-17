"""Note detail pane displaying full note information.

This module provides the right pane showing detailed note information
including timestamps, tags, and full content.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget

from core.database import Database

logger = logging.getLogger(__name__)


class NotePane(QWidget):
    """Pane displaying detailed note information.

    Shows complete note details in read-only mode:
    - Created timestamp
    - Modified timestamp (or "Never modified")
    - Associated tags (comma-separated)
    - Full content (read-only)

    Attributes:
        db: Database connection
        created_label: Label for creation timestamp
        modified_label: Label for modification timestamp
        tags_label: Label for associated tags
        content_text: Text edit for note content (read-only)
    """

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        """Initialize the note pane.

        Args:
            db: Database connection
            parent: Parent widget (default None)
        """
        super().__init__(parent)
        self.db = db

        self.setup_ui()

        logger.info("Note pane initialized")

    def setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)

        # Created timestamp
        self.created_label = QLabel("Created: ")
        layout.addWidget(self.created_label)

        # Modified timestamp
        self.modified_label = QLabel("Modified: Never modified")
        layout.addWidget(self.modified_label)

        # Tags
        self.tags_label = QLabel("Tags: ")
        layout.addWidget(self.tags_label)

        # Content (read-only)
        self.content_text = QTextEdit()
        self.content_text.setReadOnly(True)
        layout.addWidget(self.content_text)

    def load_note(self, note_id: int) -> None:
        """Load and display note details.

        Args:
            note_id: ID of the note to display
        """
        note = self.db.get_note(note_id)

        if note is None:
            logger.warning(f"Note {note_id} not found")
            self.clear()
            return

        # Update created timestamp
        created_at = note.get("created_at", "Unknown")
        self.created_label.setText(f"Created: {created_at}")

        # Update modified timestamp
        modified_at = note.get("modified_at")
        if modified_at:
            self.modified_label.setText(f"Modified: {modified_at}")
        else:
            self.modified_label.setText("Modified: Never modified")

        # Update tags
        tag_names = note.get("tag_names", "")
        if tag_names:
            self.tags_label.setText(f"Tags: {tag_names}")
        else:
            self.tags_label.setText("Tags: None")

        # Update content
        content = note.get("content", "")
        self.content_text.setPlainText(content)

        logger.info(f"Loaded note {note_id}")

    def clear(self) -> None:
        """Clear all fields."""
        self.created_label.setText("Created: ")
        self.modified_label.setText("Modified: Never modified")
        self.tags_label.setText("Tags: ")
        self.content_text.clear()

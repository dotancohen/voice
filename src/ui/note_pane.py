"""Note detail pane displaying full note information.

This module provides the right pane showing detailed note information
including timestamps, tags, and full content with editing capability.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.database import Database

logger = logging.getLogger(__name__)

# Button focus style - makes focused buttons visually distinct
BUTTON_STYLE = """
    QPushButton {
        padding: 5px 15px;
    }
    QPushButton:focus {
        border: 2px solid #3daee9;
        background-color: #3daee9;
        color: white;
    }
"""


class NotePane(QWidget):
    """Pane displaying detailed note information with editing capability.

    Shows complete note details:
    - Created timestamp
    - Modified timestamp (or "Never modified")
    - Associated tags (comma-separated)
    - Full content (editable)

    Signals:
        note_saved: Emitted when a note is saved (note_id: int)

    Attributes:
        db: Database connection
        current_note_id: ID of currently displayed note
        created_label: Label for creation timestamp
        modified_label: Label for modification timestamp
        tags_label: Label for associated tags
        content_text: Text edit for note content
        edit_button: Button to enable editing
        save_button: Button to save changes
        cancel_button: Button to cancel editing
    """

    note_saved = Signal(int)  # Emits note_id when saved

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        """Initialize the note pane.

        Args:
            db: Database connection
            parent: Parent widget (default None)
        """
        super().__init__(parent)
        self.db = db
        self.current_note_id: Optional[int] = None
        self.editing = False

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

        # Content (initially read-only)
        self.content_text = QTextEdit()
        self.content_text.setReadOnly(True)
        self.content_text.setTabChangesFocus(True)  # Tab moves to next widget
        layout.addWidget(self.content_text)

        # Button toolbar
        button_layout = QHBoxLayout()

        self.edit_button = QPushButton("Edit")
        self.edit_button.setStyleSheet(BUTTON_STYLE)
        self.edit_button.clicked.connect(self.start_editing)
        button_layout.addWidget(self.edit_button)

        self.save_button = QPushButton("Save")
        self.save_button.setStyleSheet(BUTTON_STYLE)
        self.save_button.clicked.connect(self.save_note)
        self.save_button.hide()
        button_layout.addWidget(self.save_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet(BUTTON_STYLE)
        self.cancel_button.clicked.connect(self.cancel_editing)
        self.cancel_button.hide()
        button_layout.addWidget(self.cancel_button)

        button_layout.addStretch()
        layout.addLayout(button_layout)

    def load_note(self, note_id: int) -> None:
        """Load and display note details.

        Args:
            note_id: ID of the note to display
        """
        # Exit editing mode if switching notes
        if self.editing:
            self._set_view_mode()

        note = self.db.get_note(note_id)

        if note is None:
            logger.warning(f"Note {note_id} not found")
            self.clear()
            return

        self.current_note_id = note_id

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
        self.current_note_id = None
        self.created_label.setText("Created: ")
        self.modified_label.setText("Modified: Never modified")
        self.tags_label.setText("Tags: ")
        self.content_text.clear()
        self._set_view_mode()

    def start_editing(self) -> None:
        """Switch to edit mode."""
        if self.current_note_id is None:
            return

        self.editing = True
        self.content_text.setReadOnly(False)
        self.content_text.setFocus()

        # Update button visibility
        self.edit_button.hide()
        self.save_button.show()
        self.cancel_button.show()

        logger.info(f"Started editing note {self.current_note_id}")

    def save_note(self) -> None:
        """Save the current note and return to view mode."""
        if self.current_note_id is None:
            return

        content = self.content_text.toPlainText()
        self.db.update_note(self.current_note_id, content)
        logger.info(f"Saved note {self.current_note_id}")

        # Reload the note to update modified timestamp
        self.load_note(self.current_note_id)

        # Emit signal so main window can refresh notes list
        self.note_saved.emit(self.current_note_id)

    def cancel_editing(self) -> None:
        """Cancel editing and restore original content."""
        if self.current_note_id is not None:
            # Reload original content
            self.load_note(self.current_note_id)
        else:
            self._set_view_mode()

    def _set_view_mode(self) -> None:
        """Switch to view mode (read-only)."""
        self.editing = False
        self.content_text.setReadOnly(True)

        # Update button visibility
        self.edit_button.show()
        self.save_button.hide()
        self.cancel_button.hide()

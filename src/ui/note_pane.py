"""Note detail pane displaying full note information.

This module provides the right pane showing detailed note information
including timestamps, tags, and full content with editing capability.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.database import Database
from src.core.note_editor import NoteEditorMixin
from src.ui.styles import BUTTON_STYLE

logger = logging.getLogger(__name__)


class NotePane(QWidget, NoteEditorMixin):
    """Pane displaying detailed note information with editing capability.

    Shows complete note details:
    - Created timestamp
    - Modified timestamp (or "Never modified")
    - Associated tags (comma-separated)
    - Full content (editable)

    Inherits from NoteEditorMixin to share editing state logic with TUI.

    Signals:
        note_saved: Emitted when a note is saved (note_id: str)

    Attributes:
        db: Database connection
        current_note_id: ID of currently displayed note (hex string)
        current_note_content: Content of current note
        editing: Whether currently in edit mode
        created_label: Label for creation timestamp
        modified_label: Label for modification timestamp
        tags_label: Label for associated tags
        content_text: Text edit for note content
        edit_button: Button to enable editing
        save_button: Button to save changes
        cancel_button: Button to cancel editing
    """

    note_saved = Signal(str)  # Emits note_id when saved

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        """Initialize the note pane.

        Args:
            db: Database connection
            parent: Parent widget (default None)
        """
        super().__init__(parent)
        self.db = db
        self.init_editor_state()  # Initialize mixin state

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

        # Content (initially read-only) - BEFORE attachments per requirements
        self.content_text = QTextEdit()
        self.content_text.setReadOnly(True)
        self.content_text.setTabChangesFocus(True)  # Tab moves to next widget
        layout.addWidget(self.content_text)

        # Attachments - BELOW content per requirements
        self.attachments_label = QLabel("Attachments:")
        layout.addWidget(self.attachments_label)

        self.attachments_list = QListWidget()
        self.attachments_list.setMaximumHeight(100)  # Compact display
        layout.addWidget(self.attachments_list)

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

    def load_note(self, note_id: str) -> None:
        """Load and display note details.

        Args:
            note_id: ID of the note to display (hex string)
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

        # Update attachments - display BELOW content
        self.attachments_list.clear()
        try:
            audio_files = self.db.get_audio_files_for_note(note_id)
            if audio_files:
                self.attachments_label.setText(f"Attachments ({len(audio_files)}):")
                for af in audio_files:
                    # Display: id (8 chars) | filename | imported_at | file_created_at
                    id_short = af.get("id", "")[:8]
                    filename = af.get("filename", "unknown")
                    imported_at = af.get("imported_at", "unknown")
                    file_created_at = af.get("file_created_at", "unknown")

                    item_text = f"{id_short}... | {filename} | Imported: {imported_at} | Created: {file_created_at}"
                    item = QListWidgetItem(item_text)
                    self.attachments_list.addItem(item)
            else:
                self.attachments_label.setText("Attachments: None")
        except Exception as e:
            logger.warning(f"Error loading attachments for note {note_id}: {e}")
            self.attachments_label.setText("Attachments: None")

        # Use mixin to handle content and state
        content = note.get("content", "")
        self.load_note_content(note_id, content)

        logger.info(f"Loaded note {note_id}")

    def clear(self) -> None:
        """Clear all fields."""
        self.created_label.setText("Created: ")
        self.modified_label.setText("Modified: Never modified")
        self.tags_label.setText("Tags: ")
        self.attachments_label.setText("Attachments:")
        self.attachments_list.clear()
        self.clear_editor()  # Handles content and state via mixin

    # ===== NoteEditorMixin abstract method implementations =====

    def _ui_set_content_editable(self, editable: bool) -> None:
        """Set whether the content area is editable."""
        self.content_text.setReadOnly(not editable)

    def _ui_set_content_text(self, text: str) -> None:
        """Set the content area text."""
        self.content_text.setPlainText(text)

    def _ui_get_content_text(self) -> str:
        """Get the current content area text."""
        return self.content_text.toPlainText()

    def _ui_focus_content(self) -> None:
        """Set focus to the content area."""
        self.content_text.setFocus()

    def _ui_show_edit_buttons(self) -> None:
        """Show Save/Cancel buttons, hide Edit button."""
        self.edit_button.hide()
        self.save_button.show()
        self.cancel_button.show()

    def _ui_show_view_buttons(self) -> None:
        """Show Edit button, hide Save/Cancel buttons."""
        self.edit_button.show()
        self.save_button.hide()
        self.cancel_button.hide()

    def _ui_on_note_saved(self) -> None:
        """Called after a note is saved. Refresh UI and emit signal."""
        # Reload the note to update modified timestamp
        self.load_note(self.current_note_id)
        # Emit signal so main window can refresh notes list
        self.note_saved.emit(self.current_note_id)

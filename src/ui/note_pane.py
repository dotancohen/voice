"""Note detail pane displaying full note information.

This module provides the right pane showing detailed note information
including timestamps, tags, and full content with editing capability.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
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
from src.core.models import UUID_SHORT_LEN
from src.core.note_editor import NoteEditorMixin
from src.ui.audio_player_widget import AudioPlayerWidget
from src.ui.transcription_widget import TranscriptionsContainer
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
        note_id_label: Label for note ID (selectable)
        created_label: Label for creation timestamp
        modified_label: Label for modification timestamp
        tags_label: Label for associated tags
        content_text: Text edit for note content
        edit_button: Button to enable editing
        save_button: Button to save changes
        cancel_button: Button to cancel editing
    """

    note_saved = Signal(str)  # Emits note_id when saved
    transcribe_requested = Signal(str)  # Emits audio_file_id when transcription requested

    def __init__(
        self,
        db: Database,
        audiofile_directory: Optional[Path | str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize the note pane.

        Args:
            db: Database connection
            audiofile_directory: Path to audiofile directory for playback
            parent: Parent widget (default None)
        """
        super().__init__(parent)
        self.db = db
        self.audiofile_directory = Path(audiofile_directory) if audiofile_directory else None
        self.init_editor_state()  # Initialize mixin state

        self.setup_ui()

        logger.info("Note pane initialized")

    def setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)

        # Note ID (selectable for debugging)
        self.note_id_label = QLabel("Note ID: ")
        self.note_id_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.note_id_label)

        # Created timestamp
        self.created_label = QLabel("Created: ")
        self.created_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.created_label)

        # Modified timestamp
        self.modified_label = QLabel("Modified: Never modified")
        self.modified_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.modified_label)

        # Tags
        self.tags_label = QLabel("Tags: ")
        self.tags_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.tags_label)

        # Content (initially read-only) - BEFORE attachments per requirements
        self.content_text = QTextEdit()
        self.content_text.setReadOnly(True)
        self.content_text.setTabChangesFocus(True)  # Tab moves to next widget
        layout.addWidget(self.content_text)

        # Attachments label
        self.attachments_label = QLabel("Attachments:")
        layout.addWidget(self.attachments_label)

        # Transcriptions container (above waveform)
        self.transcriptions_container = TranscriptionsContainer()
        self.transcriptions_container.transcribe_requested.connect(
            self._on_transcribe_requested
        )
        self.transcriptions_container.transcription_saved.connect(
            self._on_transcription_saved
        )
        self.transcriptions_container.hide()  # Hidden until audio files are loaded
        layout.addWidget(self.transcriptions_container)

        # Audio player widget (replaces simple list when audio files present)
        self.audio_player = AudioPlayerWidget()
        self.audio_player.hide()  # Hidden until audio files are loaded
        layout.addWidget(self.audio_player)

        # Simple attachments list (fallback for non-audio)
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

        # Update Note ID
        self.note_id_label.setText(f"Note ID: {note_id}")

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
        self.audio_player.hide()
        self.attachments_list.hide()
        self.transcriptions_container.hide()
        self._current_audio_files = []

        try:
            audio_files = self.db.get_audio_files_for_note(note_id)
            self._current_audio_files = audio_files
            if audio_files:
                self.attachments_label.setText(f"Audio Files ({len(audio_files)}):")

                # Get transcription counts for each audio file
                transcription_counts = {}
                for af in audio_files:
                    audio_id = af.get("id", "")
                    transcriptions = self.db.get_transcriptions_for_audio_file(audio_id)
                    transcription_counts[audio_id] = len(transcriptions)

                    # Show transcriptions for the first audio file by default
                    if af == audio_files[0]:
                        self.transcriptions_container.set_audio_file(
                            audio_id, transcriptions
                        )
                        if transcriptions or self.audiofile_directory:
                            self.transcriptions_container.show()

                # Use audio player widget if audiofile directory is configured
                if self.audiofile_directory:
                    self.audio_player.set_audio_files(
                        audio_files,
                        get_file_path=self._get_audio_file_path,
                        transcription_counts=transcription_counts,
                    )
                    self.audio_player.show()
                else:
                    # Fallback to simple list
                    for af in audio_files:
                        id_short = af.get("id", "")[:UUID_SHORT_LEN]
                        filename = af.get("filename", "unknown")
                        imported_at = af.get("imported_at", "unknown")
                        file_created_at = af.get("file_created_at", "unknown")
                        t_count = transcription_counts.get(af.get("id", ""), 0)

                        item_text = f"{id_short}... | {filename} | T: {t_count} | Imported: {imported_at}"
                        item = QListWidgetItem(item_text)
                        self.attachments_list.addItem(item)
                    self.attachments_list.show()
            else:
                self.attachments_label.setText("Attachments: None")
        except Exception as e:
            logger.warning(f"Error loading attachments for note {note_id}: {e}")
            self.attachments_label.setText("Attachments: None")

        # Use mixin to handle content and state
        content = note.get("content", "")
        self.load_note_content(note_id, content)

        logger.info(f"Loaded note {note_id}")

    def _get_audio_file_path(self, audio_id: str) -> Optional[str]:
        """Get the file path for an audio file.

        Args:
            audio_id: UUID of the audio file.

        Returns:
            Path to the audio file, or None if not found.
        """
        if not self.audiofile_directory:
            return None

        # Get the audio file record to find the extension
        audio_file = self.db.get_audio_file(audio_id)
        if not audio_file:
            return None

        filename = audio_file.get("filename", "")
        if "." not in filename:
            return None

        ext = filename.rsplit(".", 1)[-1].lower()
        path = self.audiofile_directory / f"{audio_id}.{ext}"
        return str(path) if path.exists() else None

    def clear(self) -> None:
        """Clear all fields."""
        self.note_id_label.setText("Note ID: ")
        self.created_label.setText("Created: ")
        self.modified_label.setText("Modified: Never modified")
        self.tags_label.setText("Tags: ")
        self.attachments_label.setText("Attachments:")
        self.attachments_list.clear()
        self.audio_player.hide()
        self.transcriptions_container.hide()
        self.transcriptions_container.set_audio_file(None, [])
        self._current_audio_files = []
        self.clear_editor()  # Handles content and state via mixin

    def _on_transcribe_requested(self, audio_file_id: str) -> None:
        """Handle transcribe request from transcriptions container.

        Args:
            audio_file_id: Audio file UUID hex string
        """
        self.transcribe_requested.emit(audio_file_id)

    def _on_transcription_saved(
        self, transcription_id: str, content: str, state: str
    ) -> None:
        """Handle transcription saved from transcriptions container.

        Args:
            transcription_id: Transcription UUID hex string
            content: Updated transcription content
            state: Updated transcription state
        """
        try:
            success = self.db.update_transcription(
                transcription_id, content, state=state
            )
            if success:
                logger.info(f"Saved transcription {transcription_id}")
            else:
                logger.warning(f"Failed to save transcription {transcription_id}")
        except Exception as e:
            logger.error(f"Error saving transcription {transcription_id}: {e}")

    def refresh_transcriptions(self, audio_file_id: str) -> None:
        """Refresh transcriptions for an audio file after transcription completes.

        Args:
            audio_file_id: Audio file UUID hex string
        """
        # Reload transcriptions
        transcriptions = self.db.get_transcriptions_for_audio_file(audio_file_id)
        self.transcriptions_container.set_audio_file(audio_file_id, transcriptions)

        # Update count in audio player
        self.audio_player.update_transcription_count(audio_file_id, len(transcriptions))

    def update_transcription(self, transcription_id: str) -> None:
        """Update a specific transcription display.

        Args:
            transcription_id: Transcription UUID hex string
        """
        transcription = self.db.get_transcription(transcription_id)
        if transcription:
            self.transcriptions_container.update_transcription(transcription)

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

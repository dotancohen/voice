"""Transcription display widgets for PySide6 GUI.

This module provides widgets for displaying and editing transcription results
with foldable text boxes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# Default state for new transcriptions
DEFAULT_TRANSCRIPTION_STATE = "original !verified !verbatim !cleaned !polished"


class TranscriptionTextBox(QFrame):
    """Foldable text box for displaying and editing a single transcription.

    Features:
    - Fold/unfold button
    - Header with service name and status
    - Editable content area
    - State field editor
    - Save/Cancel buttons when editing
    """

    transcription_saved = Signal(str, str, str)  # transcription_id, content, state

    def __init__(
        self,
        transcription: Dict[str, Any],
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize transcription text box.

        Args:
            transcription: Transcription dict from database
            parent: Parent widget
        """
        super().__init__(parent)
        self._transcription = transcription
        self._is_folded = True
        self._is_editing = False
        self._original_content = ""
        self._original_state = ""

        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Header row
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        # Fold button
        self._fold_button = QPushButton(">")
        self._fold_button.setFixedWidth(24)
        self._fold_button.setFlat(True)
        self._fold_button.clicked.connect(self._toggle_fold)
        header_layout.addWidget(self._fold_button)

        # Service name
        service = self._transcription.get("service", "Unknown")
        service_label = QLabel(service)
        service_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(service_label)

        # Status/datetime
        status = self._get_status()
        self._status_label = QLabel(status)
        self._status_label.setStyleSheet("color: gray;")
        header_layout.addWidget(self._status_label)

        header_layout.addStretch()
        layout.addWidget(header)

        # Content preview (always visible when folded)
        content = self._transcription.get("content", "")
        preview = content[:100].replace("\n", " ")
        if len(content) > 100:
            preview += "..."

        self._preview_label = QLabel(preview)
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet("color: #cccccc;")
        layout.addWidget(self._preview_label)

        # Full content (hidden when folded)
        self._content_edit = QTextEdit()
        self._content_edit.setPlainText(content)
        self._content_edit.setMinimumHeight(100)
        self._content_edit.setMaximumHeight(300)
        self._content_edit.setVisible(False)
        self._content_edit.textChanged.connect(self._on_content_changed)
        layout.addWidget(self._content_edit)

        # State field row (hidden when folded)
        state_row = QWidget()
        state_layout = QHBoxLayout(state_row)
        state_layout.setContentsMargins(0, 0, 0, 0)

        state_label = QLabel("State:")
        state_label.setStyleSheet("color: gray;")
        state_layout.addWidget(state_label)

        state = self._transcription.get("state", DEFAULT_TRANSCRIPTION_STATE)
        self._state_edit = QLineEdit(state)
        self._state_edit.textChanged.connect(self._on_state_changed)
        state_layout.addWidget(self._state_edit)

        self._state_row = state_row
        self._state_row.setVisible(False)
        layout.addWidget(state_row)

        # Button row (hidden until editing)
        button_row = QWidget()
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addStretch()

        self._save_button = QPushButton("Save")
        self._save_button.clicked.connect(self._save_changes)
        self._save_button.setEnabled(False)
        button_layout.addWidget(self._save_button)

        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.clicked.connect(self._cancel_changes)
        button_layout.addWidget(self._cancel_button)

        self._button_row = button_row
        self._button_row.setVisible(False)
        layout.addWidget(button_row)

    def _get_status(self) -> str:
        """Get status string for display."""
        content = self._transcription.get("content", "")

        if content.startswith("Pending..."):
            return "Pending"
        elif content.startswith("Error:"):
            return "Error"
        else:
            # Get datetime from created_at
            created = self._transcription.get("created_at", "")
            return created

    def _toggle_fold(self) -> None:
        """Toggle fold state."""
        self._is_folded = not self._is_folded

        if self._is_folded:
            # If we have unsaved changes, cancel them
            if self._is_editing:
                self._cancel_changes()

            self._fold_button.setText(">")
            self._preview_label.setVisible(True)
            self._content_edit.setVisible(False)
            self._state_row.setVisible(False)
            self._button_row.setVisible(False)
        else:
            self._fold_button.setText("v")
            self._preview_label.setVisible(False)
            self._content_edit.setVisible(True)
            self._state_row.setVisible(True)
            self._button_row.setVisible(True)

            # Store original values when unfolding
            self._original_content = self._content_edit.toPlainText()
            self._original_state = self._state_edit.text()

    def _on_content_changed(self) -> None:
        """Handle content text changes."""
        self._check_for_changes()

    def _on_state_changed(self) -> None:
        """Handle state text changes."""
        self._check_for_changes()

    def _check_for_changes(self) -> None:
        """Check if there are unsaved changes and update button state."""
        current_content = self._content_edit.toPlainText()
        current_state = self._state_edit.text()

        has_changes = (
            current_content != self._original_content or
            current_state != self._original_state
        )

        self._is_editing = has_changes
        self._save_button.setEnabled(has_changes)

    def _save_changes(self) -> None:
        """Save changes and emit signal."""
        transcription_id = self._transcription.get("id", "")
        content = self._content_edit.toPlainText()
        state = self._state_edit.text()

        # Update internal state
        self._transcription["content"] = content
        self._transcription["state"] = state
        self._original_content = content
        self._original_state = state
        self._is_editing = False
        self._save_button.setEnabled(False)

        # Update preview
        preview = content[:100].replace("\n", " ")
        if len(content) > 100:
            preview += "..."
        self._preview_label.setText(preview)

        # Emit signal for parent to handle database update
        self.transcription_saved.emit(transcription_id, content, state)

    def _cancel_changes(self) -> None:
        """Cancel changes and restore original values."""
        self._content_edit.blockSignals(True)
        self._state_edit.blockSignals(True)

        self._content_edit.setPlainText(self._original_content)
        self._state_edit.setText(self._original_state)

        self._content_edit.blockSignals(False)
        self._state_edit.blockSignals(False)

        self._is_editing = False
        self._save_button.setEnabled(False)

    def update_transcription(self, transcription: Dict[str, Any]) -> None:
        """Update the displayed transcription.

        Args:
            transcription: Updated transcription dict
        """
        self._transcription = transcription
        content = transcription.get("content", "")
        state = transcription.get("state", DEFAULT_TRANSCRIPTION_STATE)

        # Update preview
        preview = content[:100].replace("\n", " ")
        if len(content) > 100:
            preview += "..."
        self._preview_label.setText(preview)

        # Update full content and state (only if not currently editing)
        if not self._is_editing:
            self._content_edit.blockSignals(True)
            self._state_edit.blockSignals(True)

            self._content_edit.setPlainText(content)
            self._state_edit.setText(state)
            self._original_content = content
            self._original_state = state

            self._content_edit.blockSignals(False)
            self._state_edit.blockSignals(False)

        # Update status
        self._status_label.setText(self._get_status())

    def is_pending(self) -> bool:
        """Check if this transcription is pending."""
        content = self._transcription.get("content", "")
        return content.startswith("Pending...")

    def get_id(self) -> str:
        """Get the transcription ID."""
        return self._transcription.get("id", "")


class TranscriptionsContainer(QWidget):
    """Container widget for multiple transcription text boxes.

    Features:
    - Scrollable container
    - Displays all transcriptions for an audio file
    - Shows transcription count in header
    """

    transcribe_requested = Signal(str)  # audio_file_id
    transcription_saved = Signal(str, str, str)  # transcription_id, content, state

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize transcriptions container."""
        super().__init__(parent)
        self._audio_file_id: Optional[str] = None
        self._text_boxes: Dict[str, TranscriptionTextBox] = {}

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(4)

        # Header
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        self._header_label = QLabel("Transcriptions")
        self._header_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(self._header_label)

        self._count_label = QLabel("(0)")
        self._count_label.setStyleSheet("color: gray;")
        header_layout.addWidget(self._count_label)

        header_layout.addStretch()

        self._transcribe_button = QPushButton("Transcribe")
        self._transcribe_button.clicked.connect(self._on_transcribe)
        self._transcribe_button.setEnabled(False)
        header_layout.addWidget(self._transcribe_button)

        main_layout.addWidget(header)

        # Scroll area for transcriptions
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(100)
        scroll.setMaximumHeight(300)

        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(4)
        self._content_layout.addStretch()

        scroll.setWidget(self._content_widget)
        main_layout.addWidget(scroll)

    def set_audio_file(
        self,
        audio_file_id: Optional[str],
        transcriptions: List[Dict[str, Any]],
    ) -> None:
        """Set the audio file and its transcriptions.

        Args:
            audio_file_id: Audio file UUID hex string, or None to clear
            transcriptions: List of transcription dicts
        """
        self._audio_file_id = audio_file_id
        self._transcribe_button.setEnabled(audio_file_id is not None)

        # Clear existing boxes
        for box in self._text_boxes.values():
            box.deleteLater()
        self._text_boxes.clear()

        # Remove stretch
        while self._content_layout.count() > 0:
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Add transcription boxes
        for t in transcriptions:
            box = TranscriptionTextBox(t)
            box.transcription_saved.connect(self._on_transcription_saved)
            self._text_boxes[t["id"]] = box
            self._content_layout.addWidget(box)

        # Add stretch at end
        self._content_layout.addStretch()

        # Update count
        self._count_label.setText(f"({len(transcriptions)})")

    def _on_transcription_saved(
        self, transcription_id: str, content: str, state: str
    ) -> None:
        """Handle transcription saved signal from child box."""
        self.transcription_saved.emit(transcription_id, content, state)

    def update_transcription(self, transcription: Dict[str, Any]) -> None:
        """Update a specific transcription.

        Args:
            transcription: Updated transcription dict
        """
        tid = transcription.get("id", "")
        if tid in self._text_boxes:
            self._text_boxes[tid].update_transcription(transcription)

    def add_transcription(self, transcription: Dict[str, Any]) -> None:
        """Add a new transcription.

        Args:
            transcription: Transcription dict
        """
        tid = transcription.get("id", "")
        if tid in self._text_boxes:
            return  # Already exists

        # Remove stretch
        if self._content_layout.count() > 0:
            item = self._content_layout.takeAt(self._content_layout.count() - 1)

        box = TranscriptionTextBox(transcription)
        box.transcription_saved.connect(self._on_transcription_saved)
        self._text_boxes[tid] = box
        self._content_layout.addWidget(box)
        self._content_layout.addStretch()

        # Update count
        count = len(self._text_boxes)
        self._count_label.setText(f"({count})")

    def _on_transcribe(self) -> None:
        """Handle transcribe button click."""
        if self._audio_file_id:
            self.transcribe_requested.emit(self._audio_file_id)

    def get_pending_ids(self) -> List[str]:
        """Get IDs of pending transcriptions.

        Returns:
            List of transcription IDs that are pending
        """
        return [
            box.get_id()
            for box in self._text_boxes.values()
            if box.is_pending()
        ]

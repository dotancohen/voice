"""Note detail pane displaying full note information.

This module provides the right pane showing detailed note information
including timestamps, tags, and full content with editing capability.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

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

from src.core.conflicts import ConflictManager
from src.core.database import Database
from src.core.models import UUID_SHORT_LEN
from src.core.note_editor import NoteEditorMixin
from src.core.timestamp_utils import format_timestamp
from src.ui.audio_player_widget import AudioPlayerWidget
from src.ui.tag_management_dialog import TagManagementDialog
from src.ui.transcription_widget import TranscriptionsContainer
from src.ui.styles import BUTTON_STYLE

logger = logging.getLogger(__name__)


class NotePane(QWidget, NoteEditorMixin):
    """Pane displaying detailed note information with editing capability.

    Shows complete note details:
    - Created timestamp
    - Modified timestamp (or "Never modified")
    - Tags button (opens tag management dialog) with tag names display
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
        tags_button: Button to open tag management dialog
        tags_display: Label showing current tag names
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

        # Tags - button that opens tag management dialog, with tag names display
        tags_layout = QHBoxLayout()
        self.tags_button = QPushButton("Tags")
        self.tags_button.setStyleSheet(BUTTON_STYLE)
        self.tags_button.clicked.connect(self._open_tag_management)
        self.tags_button.setEnabled(False)  # Disabled until a note is loaded
        tags_layout.addWidget(self.tags_button)

        self.tags_display = QLabel("")
        self.tags_display.setTextInteractionFlags(Qt.TextSelectableByMouse)
        tags_layout.addWidget(self.tags_display)
        tags_layout.addStretch()
        layout.addLayout(tags_layout)

        # Conflict warning (hidden by default)
        self.conflict_label = QLabel()
        self.conflict_label.setStyleSheet("color: red; font-weight: bold;")
        self.conflict_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.conflict_label.hide()
        layout.addWidget(self.conflict_label)

        # Content (initially read-only) - BEFORE attachments per requirements
        self.content_text = QTextEdit()
        self.content_text.setReadOnly(True)
        self.content_text.setTabChangesFocus(True)  # Tab moves to next widget
        layout.addWidget(self.content_text)

        # Attachments label
        self.attachments_label = QLabel("Attachments:")
        layout.addWidget(self.attachments_label)

        # Transcriptions container (above waveform)
        self.transcriptions_container = TranscriptionsContainer(
            content_loader=self._load_transcription_content
        )
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

        Uses the display cache for faster loading when available.
        If cache is not populated, rebuilds it and reloads.

        Args:
            note_id: ID of the note to display (hex string)
        """
        import json

        note = self.db.get_note(note_id)

        if note is None:
            logger.warning(f"Note {note_id} not found")
            self.clear()
            return

        # Update Note ID
        self.note_id_label.setText(f"Note ID: {note_id}")

        # Update created timestamp (Unix timestamp)
        created_at = note.get("created_at")
        created_str = format_timestamp(created_at) if created_at else "Unknown"
        self.created_label.setText(f"Created: {created_str}")

        # Update modified timestamp (Unix timestamp)
        modified_at = note.get("modified_at")
        if modified_at:
            self.modified_label.setText(f"Modified: {format_timestamp(modified_at)}")
        else:
            self.modified_label.setText("Modified: Never modified")

        # Use display cache from get_note (included in query)
        cache_str = note.get("display_cache")
        cache = None
        if cache_str:
            try:
                cache = json.loads(cache_str)
            except json.JSONDecodeError:
                pass

        if cache is None:
            # Cache not populated - show empty strings, rebuild cache, then reload
            logger.info(f"Cache not populated for note {note_id}, rebuilding...")
            self.tags_display.setText("")
            self.conflict_label.hide()
            self.attachments_label.setText("Attachments:")
            self.attachments_list.clear()
            self.audio_player.hide()
            self.transcriptions_container.hide()
            self._current_audio_files = []

            # Rebuild cache and re-fetch note to get updated cache
            try:
                self.db.rebuild_note_cache(note_id)
                note = self.db.get_note(note_id)
                if note and note.get("display_cache"):
                    cache = json.loads(note["display_cache"])
            except Exception as e:
                logger.warning(f"Failed to rebuild cache for note {note_id}: {e}")

        # Load from cache if available, otherwise fall back to direct queries
        if cache:
            self._load_from_cache(note_id, note, cache)
        else:
            self._load_without_cache(note_id, note)

        # Use mixin to handle content and state
        content = note.get("content", "")
        self.load_note_content(note_id, content)

        logger.info(f"Loaded note {note_id}")

    def _load_from_cache(self, note_id: str, note: dict, cache: dict) -> None:
        """Load note display data from cache.

        Args:
            note_id: Note UUID hex string
            note: Note dict from database
            cache: Display cache dict
        """
        # Update tags display from cache (uses display_name which handles ambiguity)
        tags = cache.get("tags", [])
        if tags:
            # Use display_name which shows minimal path for ambiguous tags
            tag_display_names = [t.get("display_name", t.get("name", "")) for t in tags]
            self.tags_display.setText(", ".join(tag_display_names))
        else:
            self.tags_display.setText("None")
        self.tags_button.setEnabled(True)

        # Conflicts from cache
        conflicts = cache.get("conflicts", [])
        if conflicts:
            types_str = ", ".join(conflicts)
            self.conflict_label.setText(f"WARNING: This note has unresolved {types_str} conflict(s)")
            self.conflict_label.show()
        else:
            self.conflict_label.hide()

        # Attachments from cache
        self.attachments_list.clear()
        self.audio_player.hide()
        self.attachments_list.hide()
        self.transcriptions_container.hide()
        self._current_audio_files = []

        attachments = cache.get("attachments", [])
        audio_attachments = [a for a in attachments if a.get("type") == "audio_file"]

        if audio_attachments:
            self.attachments_label.setText(f"Audio Files ({len(audio_attachments)}):")

            # Build audio_files list, transcription counts, and waveforms from cache
            audio_files = []
            transcription_counts = {}
            cached_waveforms = {}
            first_transcriptions = []

            for attachment in audio_attachments:
                af_data = attachment.get("audio_file", {})
                audio_id = af_data.get("id", "")
                transcriptions_data = af_data.get("transcriptions", [])

                # Build audio file dict matching database format
                audio_file = {
                    "id": audio_id,
                    "filename": af_data.get("filename", ""),
                    "imported_at": af_data.get("imported_at", ""),
                    "file_created_at": af_data.get("file_created_at"),
                    "summary": af_data.get("summary"),
                }
                audio_files.append(audio_file)
                transcription_counts[audio_id] = len(transcriptions_data)

                # Extract cached waveform
                waveform = af_data.get("waveform")
                if waveform and audio_id:
                    cached_waveforms[audio_id] = waveform

                # Use transcriptions from first audio file (cache has content_preview)
                if not first_transcriptions and transcriptions_data:
                    first_transcriptions = transcriptions_data

            self._current_audio_files = audio_files

            # Build a lookup for audio file paths from cached filenames
            self._cached_audio_filenames = {
                af.get("id", ""): af.get("filename", "") for af in audio_files
            }

            # Show transcriptions for first audio file
            if audio_files:
                first_audio_id = audio_files[0].get("id", "")
                if first_transcriptions or self.audiofile_directory:
                    self.transcriptions_container.set_audio_file(
                        first_audio_id, first_transcriptions
                    )
                    self.transcriptions_container.show()

            # Use audio player widget if audiofile directory is configured
            if self.audiofile_directory:
                self.audio_player.set_audio_files(
                    audio_files,
                    get_file_path=self._get_audio_file_path_cached,
                    transcription_counts=transcription_counts,
                    cached_waveforms=cached_waveforms,
                    on_waveform_extracted=self._on_waveform_extracted,
                )
                self.audio_player.show()
            else:
                # Fallback to simple list
                for af in audio_files:
                    id_short = af.get("id", "")[:UUID_SHORT_LEN]
                    filename = af.get("filename", "unknown")
                    imported_at = af.get("imported_at", "unknown")
                    t_count = transcription_counts.get(af.get("id", ""), 0)

                    item_text = f"{id_short}... | {filename} | T: {t_count} | Imported: {imported_at}"
                    item = QListWidgetItem(item_text)
                    self.attachments_list.addItem(item)
                self.attachments_list.show()
        else:
            self.attachments_label.setText("Attachments: None")

    def _load_transcription_content(self, transcription_id: str) -> Optional[str]:
        """Load full transcription content from database.

        Used for lazy loading when user unfolds a transcription.

        Args:
            transcription_id: Transcription UUID hex string

        Returns:
            Full transcription content, or None if not found
        """
        return self.db.get_transcription_content(transcription_id)

    def _on_waveform_extracted(self, audio_id: str, waveform: List[int]) -> None:
        """Callback when a waveform is extracted from an audio file.

        Updates the note's display cache with the waveform data.

        Args:
            audio_id: Audio file UUID hex string
            waveform: Waveform data as list of 0-255 values
        """
        if not self.current_note_id:
            return
        try:
            self.db.update_cache_waveform(self.current_note_id, audio_id, waveform)
            logger.debug(f"Updated cache waveform for audio {audio_id[:8]}")
        except Exception as e:
            logger.warning(f"Failed to update cache waveform: {e}")

    def _load_without_cache(self, note_id: str, note: dict) -> None:
        """Load note display data without cache (fallback).

        Args:
            note_id: Note UUID hex string
            note: Note dict from database
        """
        # Update tags display (fallback uses simple tag_names, not ambiguity-aware display)
        # Cache path uses display_name which handles ambiguous tag names properly
        tag_names = note.get("tag_names", "")
        if tag_names:
            self.tags_display.setText(tag_names)
        else:
            self.tags_display.setText("None")
        self.tags_button.setEnabled(True)

        # Check for conflicts
        try:
            conflict_mgr = ConflictManager(self.db)
            conflict_types = conflict_mgr.get_note_conflict_types(note_id)
            if conflict_types:
                types_str = ", ".join(conflict_types)
                self.conflict_label.setText(f"WARNING: This note has unresolved {types_str} conflict(s)")
                self.conflict_label.show()
            else:
                self.conflict_label.hide()
        except Exception as e:
            logger.warning(f"Error checking conflicts for note {note_id}: {e}")
            self.conflict_label.hide()

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
                        imported_at = format_timestamp(af.get("imported_at")) or "unknown"
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

    def _get_audio_file_path_cached(self, audio_id: str) -> Optional[str]:
        """Get the file path for an audio file using cached filename.

        This avoids a database query by using the filename from the display cache.

        Args:
            audio_id: UUID of the audio file.

        Returns:
            Path to the audio file, or None if not found.
        """
        if not self.audiofile_directory:
            return None

        # Use cached filename if available
        filename = getattr(self, '_cached_audio_filenames', {}).get(audio_id, "")
        if not filename or "." not in filename:
            # Fallback to database query
            return self._get_audio_file_path(audio_id)

        ext = filename.rsplit(".", 1)[-1].lower()
        path = self.audiofile_directory / f"{audio_id}.{ext}"
        return str(path) if path.exists() else None

    def clear(self) -> None:
        """Clear all fields."""
        self.note_id_label.setText("Note ID: ")
        self.created_label.setText("Created: ")
        self.modified_label.setText("Modified: Never modified")
        self.tags_display.setText("")
        self.tags_button.setEnabled(False)
        self.conflict_label.hide()
        self.attachments_label.setText("Attachments:")
        self.attachments_list.clear()
        self.audio_player.hide()
        self.transcriptions_container.hide()
        self.transcriptions_container.set_audio_file(None, [])
        self._current_audio_files = []
        self.clear_editor()  # Handles content and state via mixin

    def _open_tag_management(self) -> None:
        """Open the tag management dialog."""
        if not self.current_note_id:
            return

        dialog = TagManagementDialog(self.db, self.current_note_id, self)
        dialog.tags_changed.connect(self._on_tags_changed)
        dialog.exec()

    def _on_tags_changed(self, note_id: str) -> None:
        """Handle tags changed from the tag management dialog.

        Args:
            note_id: Note UUID hex string
        """
        # Reload the note to update tag display
        if note_id == self.current_note_id:
            self.load_note(note_id)
            # Emit note_saved to refresh the notes list (tags may affect display)
            self.note_saved.emit(note_id)

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

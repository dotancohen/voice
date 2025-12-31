"""Main application window with 3-pane layout.

This module defines the main window containing three resizable panes:
Tags (left), Notes List (center), and Note Detail (right).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src import __version__
from src.core.config import Config
from src.core.database import Database
from src.core.transcription_service import TranscriptionService
from src.ui.note_pane import NotePane
from src.ui.notes_list_pane import NotesListPane
from src.ui.tags_pane import TagsPane
from src.ui.transcription_dialog import TranscriptionDialog

try:
    from voice_transcription import get_provider_schemas
    TRANSCRIPTION_AVAILABLE = True
except ImportError:
    TRANSCRIPTION_AVAILABLE = False

try:
    from voicecore import sync_all_peers
    SYNC_AVAILABLE = True
except ImportError:
    SYNC_AVAILABLE = False

logger = logging.getLogger(__name__)

# Constants
DEFAULT_SPLITTER_SIZES = [200, 600, 400]  # Tags, Notes List, Note Detail


class MainWindow(QMainWindow):
    """Main application window with three-pane layout.

    The window contains a horizontal splitter with three panes:
    - Left: TagsPane (hierarchical tag tree)
    - Center: NotesListPane (list of notes with two-line display)
    - Right: NotePane (detailed note view)

    Attributes:
        config: Configuration manager
        db: Database connection
        splitter: QSplitter containing the three panes
        tags_pane: Left pane for tag selection
        notes_list_pane: Center pane for notes list
        note_pane: Right pane for note detail
    """

    def __init__(
        self, config: Config, db: Database, theme: str = "dark", parent: Optional[QWidget] = None
    ) -> None:
        """Initialize the main window.

        Args:
            config: Configuration manager
            db: Database connection
            theme: UI theme ("dark" or "light")
            parent: Parent widget (default None)
        """
        super().__init__(parent)
        self.config = config
        self.db = db
        self.theme = theme

        # User-facing message log: list of (timestamp, level, title, message)
        self._message_log: List[Tuple[str, str, str, str]] = []

        # Initialize transcription service if available
        self._transcription_service: Optional[TranscriptionService] = None
        audiofile_dir = self.config.get("audiofile_directory")
        if audiofile_dir and TRANSCRIPTION_AVAILABLE:
            from pathlib import Path
            self._transcription_service = TranscriptionService(self.db, Path(audiofile_dir))

        self.setup_ui()
        self.connect_signals()

        logger.info("Main window initialized")

    def setup_ui(self) -> None:
        """Set up the user interface with three-pane layout."""
        self.setWindowTitle("Voice")
        self.showMaximized()

        # Create menu bar
        self.setup_menu_bar()

        # Create horizontal splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.splitter)

        # Create the three panes
        self.tags_pane = TagsPane(self.db)
        self.notes_list_pane = NotesListPane(self.config, self.db, theme=self.theme)
        audiofile_directory = self.config.get("audiofile_directory")
        self.note_pane = NotePane(self.db, audiofile_directory=audiofile_directory)

        # Add panes to splitter
        self.splitter.addWidget(self.tags_pane)
        self.splitter.addWidget(self.notes_list_pane)
        self.splitter.addWidget(self.note_pane)

        # Set initial sizes
        self.splitter.setSizes(DEFAULT_SPLITTER_SIZES)

        logger.info("UI layout created with 3 panes")

    def setup_menu_bar(self) -> None:
        """Set up the menu bar with File menu."""
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("&File")

        # New Note action
        self.new_note_action = QAction("&New Note", self)
        self.new_note_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_note_action.setStatusTip("Create a new note")
        self.new_note_action.triggered.connect(self.create_new_note)
        file_menu.addAction(self.new_note_action)

        file_menu.addSeparator()

        # Sync Now action
        self.sync_now_action = QAction("Sync Now", self)
        self.sync_now_action.setShortcut("Ctrl+Shift+S")
        self.sync_now_action.triggered.connect(self.sync_now)
        file_menu.addAction(self.sync_now_action)

        # Track unsynced state
        self._has_unsynced_changes = False

        # Set up timer to check for unsynced changes periodically
        self._sync_check_timer = QTimer(self)
        self._sync_check_timer.timeout.connect(self._check_unsynced_changes)
        self._sync_check_timer.start(5000)  # Check every 5 seconds

        # Initial check
        self._check_unsynced_changes()

        file_menu.addSeparator()

        # Quit action
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.setStatusTip("Exit the application")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Help menu
        help_menu = menu_bar.addMenu("&Help")

        # Message Log action
        message_log_action = QAction("&Message Log", self)
        message_log_action.triggered.connect(self.show_message_log)
        help_menu.addAction(message_log_action)

        # Application Log action
        app_log_action = QAction("Application &Log", self)
        app_log_action.triggered.connect(self.show_application_log)
        help_menu.addAction(app_log_action)

        help_menu.addSeparator()

        # About action
        about_action = QAction("&About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        logger.info("Menu bar created")

    def connect_signals(self) -> None:
        """Connect signals between panes for communication."""
        # When a tag is selected, filter notes list
        self.tags_pane.tag_selected.connect(self.notes_list_pane.filter_by_tag)

        # When a note is selected, show note detail
        self.notes_list_pane.note_selected.connect(self.note_pane.load_note)

        # When a note is saved, refresh the notes list
        self.note_pane.note_saved.connect(self.on_note_saved)

        # When transcription is requested, show dialog
        self.note_pane.transcribe_requested.connect(self._on_transcribe_requested)

        logger.info("Inter-pane signals connected")

    def on_note_saved(self, note_id: int) -> None:
        """Handle note saved event - refresh notes list and mark unsynced.

        Args:
            note_id: ID of the saved note
        """
        self.notes_list_pane.load_notes()
        self.notes_list_pane.select_note_by_id(note_id)

        # Immediately mark as having unsynced changes
        if not self._has_unsynced_changes:
            self._has_unsynced_changes = True
            self._update_sync_action_style()

        logger.info(f"Refreshed notes list after saving note {note_id}")

    def create_new_note(self) -> None:
        """Create a new note and display it for editing."""
        note_id = self.db.create_note()
        logger.info(f"Created new note {note_id}")

        # Refresh the notes list and select the new note
        self.notes_list_pane.load_notes()
        self.notes_list_pane.select_note_by_id(note_id)

        # Load the note in the detail pane and start editing
        self.note_pane.load_note(note_id)
        self.note_pane.start_editing()

        # Mark as having unsynced changes
        if not self._has_unsynced_changes:
            self._has_unsynced_changes = True
            self._update_sync_action_style()

    def _check_unsynced_changes(self) -> None:
        """Check if there are unsynced changes and update menu styling."""
        try:
            # Get peers to check if sync is configured
            peers = self.config.get_peers()
            if not peers:
                self._has_unsynced_changes = False
                self._update_sync_action_style()
                return

            # Check each peer for unsynced changes
            has_changes = False
            for peer in peers:
                peer_id = peer.get("peer_id")
                if peer_id:
                    last_sync = self.db.get_peer_last_sync(peer_id)
                    changes = self.db.get_changes_since(last_sync, limit=1)
                    if changes.get("changes"):
                        has_changes = True
                        break

            if has_changes != self._has_unsynced_changes:
                self._has_unsynced_changes = has_changes
                self._update_sync_action_style()
                logger.debug(f"Unsynced changes: {has_changes}")

        except Exception as e:
            logger.warning(f"Error checking unsynced changes: {e}")

    def _update_sync_action_style(self) -> None:
        """Update the Sync Now menu item text based on unsynced state."""
        if self._has_unsynced_changes:
            self.sync_now_action.setText("Sync Now *")
        else:
            self.sync_now_action.setText("Sync Now")

    def sync_now(self) -> None:
        """Perform sync with all configured peers."""
        if not SYNC_AVAILABLE:
            self._show_warning("Sync Unavailable", "Sync functionality is not available.")
            return

        peers = self.config.get_peers()
        if not peers:
            self._show_info(
                "No Peers",
                "No sync peers are configured.\n\n"
                "Use the CLI to add peers:\n"
                "  voice sync add-peer <peer_id> <name> <url>",
            )
            return

        try:
            config_dir = str(self.config.get_config_dir())
            results: Dict[str, object] = sync_all_peers(config_dir)

            if not results:
                self._show_info("Sync Complete", "No peers to sync with.")
                return

            # Build result summary
            all_success = True
            summary_lines = []
            for peer_id, result in results.items():
                peer = self.config.get_peer(peer_id)
                peer_name = peer.get("peer_name", peer_id) if peer else peer_id

                if result.success:
                    summary_lines.append(
                        f"{peer_name}: OK (pulled {result.pulled}, pushed {result.pushed})"
                    )
                else:
                    all_success = False
                    errors = ", ".join(result.errors) if result.errors else "Unknown error"
                    summary_lines.append(f"{peer_name}: FAILED - {errors}")

            # Refresh notes list after sync
            self.notes_list_pane.load_notes()
            self.tags_pane.load_tags()

            # Re-check unsynced changes
            self._check_unsynced_changes()

            # Show result
            summary = "\n".join(summary_lines)
            if all_success:
                self._show_info("Sync Complete", summary)
            else:
                self._show_warning("Sync Completed with Errors", summary)

            logger.info(f"Sync completed: {summary_lines}")

        except Exception as e:
            logger.error(f"Sync failed: {e}")
            self._show_error("Sync Failed", f"An error occurred during sync:\n\n{e}")

    # ===== User-facing message methods =====

    def _log_message(self, level: str, title: str, message: str) -> None:
        """Add a message to the user-facing log.

        Args:
            level: Message level (info, warning, error)
            title: Message title
            message: Message content
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._message_log.append((timestamp, level, title, message))
        # Keep only last 100 messages
        if len(self._message_log) > 100:
            self._message_log = self._message_log[-100:]

    def _show_info(self, title: str, message: str) -> None:
        """Show an information message and log it.

        Args:
            title: Message title
            message: Message content
        """
        self._log_message("info", title, message)
        QMessageBox.information(self, title, message)

    def _show_warning(self, title: str, message: str) -> None:
        """Show a warning message and log it.

        Args:
            title: Message title
            message: Message content
        """
        self._log_message("warning", title, message)
        QMessageBox.warning(self, title, message)

    def _show_error(self, title: str, message: str) -> None:
        """Show an error message and log it.

        Args:
            title: Message title
            message: Message content
        """
        self._log_message("error", title, message)
        QMessageBox.critical(self, title, message)

    # ===== Help menu handlers =====

    def show_message_log(self) -> None:
        """Show the user-facing message log dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Message Log")
        dialog.resize(600, 400)

        layout = QVBoxLayout(dialog)

        if not self._message_log:
            label = QLabel("No messages yet.")
            layout.addWidget(label)
        else:
            text_edit = QPlainTextEdit()
            text_edit.setReadOnly(True)

            lines = []
            for timestamp, level, title, message in self._message_log:
                level_upper = level.upper()
                lines.append(f"[{timestamp}] [{level_upper}] {title}")
                # Indent message lines
                for line in message.split("\n"):
                    lines.append(f"    {line}")
                lines.append("")

            text_edit.setPlainText("\n".join(lines))
            layout.addWidget(text_edit)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        dialog.exec()

    def show_application_log(self) -> None:
        """Show the application log dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Application Log")
        dialog.resize(800, 500)

        layout = QVBoxLayout(dialog)

        text_edit = QPlainTextEdit()
        text_edit.setReadOnly(True)

        # Try to get log file path from config
        log_file = self.config.get_config_dir() / "voice.log"
        if log_file.exists():
            try:
                # Read last 1000 lines
                with open(log_file, "r") as f:
                    lines = f.readlines()
                    text_edit.setPlainText("".join(lines[-1000:]))
                    # Scroll to bottom
                    text_edit.verticalScrollBar().setValue(
                        text_edit.verticalScrollBar().maximum()
                    )
            except Exception as e:
                text_edit.setPlainText(f"Error reading log file: {e}")
        else:
            text_edit.setPlainText(f"Log file not found: {log_file}")

        layout.addWidget(text_edit)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        dialog.exec()

    def show_about(self) -> None:
        """Show the About dialog."""
        about_text = f"""<h2>Voice</h2>
<p>Version {__version__}</p>

<p>A note-taking application with audio transcription support
and peer-to-peer synchronization.</p>

<h3>Credits</h3>
<p>
<b>Developer:</b> Dotan Cohen<br>
<b>Built with:</b> Python, PySide6, Rust, SQLite
</p>

<p><small>Copyright 2024-2025 Dotan Cohen. All rights reserved.</small></p>
"""
        QMessageBox.about(self, "About Voice", about_text)

    # ===== Transcription handlers =====

    def _on_transcribe_requested(self, audio_file_id: str) -> None:
        """Handle transcription request from note pane.

        Args:
            audio_file_id: Audio file UUID hex string
        """
        if not TRANSCRIPTION_AVAILABLE:
            self._show_warning(
                "Transcription Unavailable",
                "VoiceTranscription is not installed.\n\n"
                "Install it with:\n"
                "  pip install voice-transcription",
            )
            return

        if not self._transcription_service:
            self._show_warning(
                "Transcription Unavailable",
                "Audiofile directory is not configured.\n\n"
                "Set audiofile_directory in your config.",
            )
            return

        # Get audio file info
        audio_file = self.db.get_audio_file(audio_file_id)
        if not audio_file:
            self._show_error("Error", f"Audio file not found: {audio_file_id}")
            return

        # Get provider schemas
        schemas = get_provider_schemas()
        if not schemas:
            self._show_warning(
                "No Providers",
                "No transcription providers are available.",
            )
            return

        # Show transcription dialog
        dialog = TranscriptionDialog(
            audio_filename=audio_file.get("filename", "Unknown"),
            provider_schemas=schemas,
            parent=self,
        )

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # Get selected provider configs
        configs = dialog.get_provider_configs()
        if not configs:
            return

        # Start transcription for each selected provider
        for provider_config in configs:
            try:
                transcription_id = self._transcription_service.transcribe_async(
                    audio_file_id=audio_file_id,
                    provider_config=provider_config,
                    on_complete=self._on_transcription_complete,
                    on_error=self._on_transcription_error,
                )

                # Refresh transcriptions display to show pending
                self.note_pane.refresh_transcriptions(audio_file_id)

                logger.info(
                    f"Started transcription {transcription_id} for {audio_file_id}"
                )

            except Exception as e:
                logger.error(f"Failed to start transcription: {e}")
                self._show_error("Transcription Error", f"Failed to start transcription:\n\n{e}")

    def _on_transcription_complete(
        self, transcription_id: str, result: Dict[str, any]
    ) -> None:
        """Handle transcription completion.

        Args:
            transcription_id: Transcription UUID hex string
            result: Transcription result dict
        """
        logger.info(f"Transcription {transcription_id} completed")

        # Update the display (called from background thread, so use Qt's thread-safe method)
        # For simplicity, refresh the entire transcription display
        transcription = self.db.get_transcription(transcription_id)
        if transcription:
            audio_file_id = transcription.get("audio_file_id")
            if audio_file_id:
                # Use QTimer.singleShot to ensure we're on the main thread
                QTimer.singleShot(0, lambda: self.note_pane.refresh_transcriptions(audio_file_id))

    def _on_transcription_error(self, transcription_id: str, error_message: str) -> None:
        """Handle transcription error.

        Args:
            transcription_id: Transcription UUID hex string
            error_message: Error message
        """
        logger.error(f"Transcription {transcription_id} failed: {error_message}")

        # Update the display
        transcription = self.db.get_transcription(transcription_id)
        if transcription:
            audio_file_id = transcription.get("audio_file_id")
            if audio_file_id:
                QTimer.singleShot(0, lambda: self.note_pane.refresh_transcriptions(audio_file_id))

        # Show error to user
        QTimer.singleShot(0, lambda: self._log_message("error", "Transcription Failed", error_message))

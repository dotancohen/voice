"""Main application window with 3-pane layout.

This module defines the main window containing three resizable panes:
Tags (left), Notes List (center), and Note Detail (right).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
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
from src.ui.tag_hierarchy_dialog import TagHierarchyDialog
from src.ui.trash_dialog import TrashDialog
from src.ui.tags_pane import TagsPane
from src.ui.transcription_dialog import TranscriptionDialog

try:
    from voice_transcription import get_provider_schemas
    TRANSCRIPTION_AVAILABLE = True
except ImportError:
    TRANSCRIPTION_AVAILABLE = False


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

        # Track currently selected note for delete action
        self._current_note_id: Optional[str] = None

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
        self.note_pane = NotePane(
            self.db,
            audiofile_directory=audiofile_directory,
            config_dir=self.config.get_config_dir(),
        )

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
        self.new_note_action.setStatusTip("Create a new Note")
        self.new_note_action.triggered.connect(self.create_new_note)
        file_menu.addAction(self.new_note_action)

        file_menu.addSeparator()

        # Sync: the dialogue with the one button, the peers and the line
        self.sync_action = QAction("&Sync…", self)
        self.sync_action.setShortcut("Ctrl+Shift+S")
        self.sync_action.setStatusTip("Exchange with the other devices of the account, show a code, check a connection")
        self.sync_action.triggered.connect(self.open_sync_dialog)
        file_menu.addAction(self.sync_action)

        # The bucket: the wizard, and a new key for it
        wizard_action = QAction("Set up the &bucket…", self)
        wizard_action.setStatusTip("Make the key, make and harden the bucket, test it, save it for every device")
        wizard_action.triggered.connect(self.open_storage_wizard)
        file_menu.addAction(wizard_action)
        replace_key_action = QAction("Replace the bucket's &key…", self)
        replace_key_action.triggered.connect(self.open_replace_key)
        file_menu.addAction(replace_key_action)

        # Listen for peers: the listener runs only while this is checked
        self.listen_action = QAction("&Listen for peers", self)
        self.listen_action.setCheckable(True)
        self.listen_action.setStatusTip("Let other devices of the account reach this computer to sync")
        self.listen_action.toggled.connect(self._toggle_listener)
        file_menu.addAction(self.listen_action)
        self._listener_thread = None

        file_menu.addSeparator()

        # Manage Tags action
        manage_tags_action = QAction("Manage &Tags...", self)
        manage_tags_action.triggered.connect(self._open_manage_tags)
        file_menu.addAction(manage_tags_action)

        # Trash: deleted notes, recovered or removed for good
        trash_action = QAction("T&rash...", self)
        trash_action.setStatusTip("Deleted notes: recover them, or remove them for good")
        trash_action.triggered.connect(self._open_trash)
        file_menu.addAction(trash_action)

        # Calculate what was never calculated: lengths, dates, display caches
        fill_action = QAction("Calculate &missing data...", self)
        fill_action.setStatusTip(
            "Work out Recording lengths and creation dates that were never recorded, "
            "and rebuild missing display caches"
        )
        fill_action.triggered.connect(self._calculate_missing_data)
        file_menu.addAction(fill_action)

        # What is waiting to be transcribed here, and what the finished work cost
        queue_action = QAction("&Transcription queue...", self)
        queue_action.setStatusTip(
            "What is waiting to be transcribed on this computer, what is being "
            "worked on, and what the finished ones cost"
        )
        queue_action.triggered.connect(self._show_transcription_queue)
        file_menu.addAction(queue_action)

        file_menu.addSeparator()

        # Quit action
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.setStatusTip("Exit the application")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Note menu
        note_menu = menu_bar.addMenu("&Note")

        # Delete Note action
        self.delete_note_action = QAction("&Delete Note", self)
        self.delete_note_action.setShortcut(QKeySequence.StandardKey.Delete)
        self.delete_note_action.setStatusTip("Delete the selected note")
        self.delete_note_action.triggered.connect(self.delete_current_note)
        self.delete_note_action.setEnabled(False)  # Disabled until a note is selected
        note_menu.addAction(self.delete_note_action)

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

        # When a tag is shift-clicked, add it to the current note
        self.tags_pane.tag_add_requested.connect(self._on_tag_add_requested)

        # When a note is selected, show note detail and enable Delete action
        self.notes_list_pane.note_selected.connect(self.note_pane.load_note)
        self.notes_list_pane.note_selected.connect(self._on_note_selected)

        # When a note is saved, refresh the notes list
        self.note_pane.note_saved.connect(self.on_note_saved)

        # When transcription is requested, show dialog
        self.note_pane.transcribe_requested.connect(self._on_transcribe_requested)

        logger.info("Inter-pane signals connected")

    def _on_note_selected(self, note_id: str) -> None:
        """Handle note selection - enable Delete action.

        Args:
            note_id: ID of the selected note (hex string)
        """
        self._current_note_id = note_id
        self.delete_note_action.setEnabled(True)

    def _on_tag_add_requested(self, tag_id: str) -> None:
        """Handle tag add request (shift-click) - add tag to current note.

        Args:
            tag_id: ID of the tag to add (hex string)
        """
        if not self._current_note_id:
            logger.warning("Cannot add tag: no note selected")
            return

        # Add tag to note
        result = self.db.add_tag_to_note(self._current_note_id, tag_id)
        if result:
            logger.info(f"Added tag {tag_id} to note {self._current_note_id}")
            # Refresh the note pane to show updated tags
            self.note_pane.load_note(self._current_note_id)
        else:
            logger.warning(f"Failed to add tag {tag_id} to note {self._current_note_id}")

    def on_note_saved(self, note_id: int) -> None:
        """Handle note saved event - refresh notes list and mark unsynced.

        Args:
            note_id: ID of the saved note
        """
        self.notes_list_pane.load_notes()
        self.notes_list_pane.select_note_by_id(note_id)


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


    def delete_current_note(self) -> None:
        """Delete the currently selected note after confirmation."""
        if not self._current_note_id:
            return

        # Get note content for confirmation message
        note = self.db.get_note(self._current_note_id)
        if not note:
            return

        # Show preview in confirmation
        content_preview = note.get("content", "")[:100]
        if len(note.get("content", "")) > 100:
            content_preview += "..."

        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            "Delete Note",
            f"Are you sure you want to delete this Note?\n\n{content_preview}\n\n"
            "It goes to the trash, where it can be recovered (File \u2192 Trash).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Perform soft delete
        try:
            success = self.db.delete_note(self._current_note_id)
            if success:
                logger.info(f"Deleted note {self._current_note_id}")

                # Clear the note pane
                self.note_pane.clear()

                # Disable delete action
                self.delete_note_action.setEnabled(False)
                self._current_note_id = None

                # Refresh notes list
                self.notes_list_pane.load_notes()

            else:
                self._show_error("Delete Failed", "Failed to delete the note.")
        except Exception as e:
            logger.error(f"Failed to delete note: {e}")
            self._show_error("Delete Failed", f"An error occurred:\n\n{e}")

    def _open_manage_tags(self) -> None:
        """Open the tag hierarchy management dialog."""
        dialog = TagHierarchyDialog(self.db, parent=self)
        dialog.tags_modified.connect(self._on_tags_modified)
        dialog.exec()

    def _on_tags_modified(self) -> None:
        """Handle tags being modified in the hierarchy dialog."""
        # Refresh the tags pane
        self.tags_pane.load_tags()

        # Refresh the note pane if a note is selected (to update tag display)
        if self._current_note_id:
            self.note_pane.load_note(self._current_note_id)


        logger.info("Tags modified - refreshed UI")

    def open_storage_wizard(self) -> None:
        from src.ui.storage_wizard import StorageWizard

        StorageWizard(self.db, self.config, listen_action=self.listen_action, parent=self).exec()

    def open_replace_key(self) -> None:
        from src.ui.storage_wizard import ReplaceKeyWizard

        ReplaceKeyWizard(self.db, parent=self).exec()

    def open_sync_dialog(self) -> None:
        """The sync dialogue: the peers, the one button, the code, the check."""
        from src.ui.sync_dialog import SyncDialog

        def after_operation() -> None:
            self.notes_list_pane.load_notes()
            self.tags_pane.load_tags()
            if self._current_note_id:
                self.note_pane.load_note(self._current_note_id)

        dialog = SyncDialog(self.db, self.config, listen_action=self.listen_action, after_operation=after_operation, parent=self)
        dialog.exec()

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

    def _show_transcription_queue(self) -> None:
        """Open the transcription queue: what is waiting here and what it cost."""
        from src.ui.transcription_queue_dialog import TranscriptionQueueDialog

        dialog = TranscriptionQueueDialog(self.db, self.config, self)
        dialog.exec()
        if dialog.changed:
            self._start_queue_worker()

    def _start_queue_worker(self) -> None:
        """Work through the transcription queue in the background, one at a time.

        One recording at a time is the point of the queue: the local model wants
        every core, so two at once are slower than two in turn. The thread ends
        when the queue is empty, and a new one is started when something is added.
        """
        from src.core import transcription_queue as queue_module

        if self._transcription_service is None:
            # No audio directory, or VoiceTranscription is not installed: the
            # recordings stay in the queue until one of those is put right.
            logger.warning("Nothing can be transcribed here: no transcription service")
            return
        if getattr(self, "_queue_thread", None) is not None and self._queue_thread.is_alive():
            return

        import threading

        def work() -> None:
            try:
                queue_module.drain(
                    self.db, self.config, self._transcription_service,
                    on_complete=self._on_transcription_complete,
                    on_error=self._on_transcription_error,
                )
            except Exception as e:
                logger.error(f"The transcription queue stopped: {e}")

        self._queue_thread = threading.Thread(target=work, daemon=True)
        self._queue_thread.start()

    def _calculate_missing_data(self) -> None:
        """Calculate what was never calculated, after showing what is missing.

        Reading the audio files takes a moment each, so the survey comes first
        and the user decides; see `core.missing_data`.
        """
        from src.core import missing_data

        survey = missing_data.survey(self.db, self.config)
        if not survey.anything_missing:
            QMessageBox.information(self, "Missing data", "Nothing is missing.")
            return

        question = QMessageBox(self)
        question.setWindowTitle("Calculate missing data")
        question.setIcon(QMessageBox.Icon.Question)
        question.setText("What is missing:")
        question.setInformativeText(survey.summary())
        if survey.total_calculable:
            question.setStandardButtons(
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
            )
            question.button(QMessageBox.StandardButton.Ok).setText(
                f"Calculate {survey.total_calculable}"
            )
        else:
            question.setStandardButtons(QMessageBox.StandardButton.Close)
        if question.exec() != QMessageBox.StandardButton.Ok:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            report = missing_data.calculate_missing_data(self.db, self.config)
        finally:
            QApplication.restoreOverrideCursor()

        QMessageBox.information(
            self,
            "Calculated",
            report.summary() or "Nothing could be calculated.",
        )
        if report.total_calculated:
            self.notes_list_pane.load_notes()
            if self._current_note_id:
                self.note_pane.load_note(self._current_note_id)

    def _open_trash(self) -> None:
        """Open the trash bin, and reload the list if anything came back."""
        audiofile_directory = self.config.get_audiofile_directory()
        dialog = TrashDialog(
            self.db,
            Path(audiofile_directory) if audiofile_directory else None,
            self,
        )
        dialog.exec()
        if dialog.changed:
            self.notes_list_pane.load_notes()

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
                # The end of the file only. Reading all of it to show the last
                # thousand lines means holding the whole log in memory, which
                # is fine until the day it is not.
                TAIL_BYTES = 1024 * 1024
                with open(log_file, "rb") as f:
                    if log_file.stat().st_size > TAIL_BYTES:
                        f.seek(-TAIL_BYTES, 2)
                        f.readline()  # drop the half line the seek landed in
                    tail = f.read().decode("utf-8", errors="replace")
                    lines = tail.splitlines(keepends=True)
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

    def _toggle_listener(self, checked: bool) -> None:
        """Start or stop the listener; it runs on a thread of its own."""
        import threading
        from voicecore import start_sync_server, stop_sync_server

        if checked:
            config_dir = str(self.config.get_config_dir())
            port = self.config.get_sync_server_port()

            def serve() -> None:
                try:
                    start_sync_server(config_dir=config_dir, port=port)
                except Exception as e:  # noqa: BLE001 - reported on the status bar
                    logger.error(f"The listener stopped: {e}")

            self._listener_thread = threading.Thread(target=serve, daemon=True, name="voice-listener")
            self._listener_thread.start()
            self._announce_listener(port)
            self.statusBar().showMessage(f"Listening for peers on port {port}", 5000)
        else:
            stop_sync_server()
            self._stop_announcing()
            self.statusBar().showMessage("No longer listening for peers", 5000)

    def _announce_listener(self, port: int) -> None:
        """Announce this listener on the local network (Stage 7) while it runs."""
        from voicecore import certificate_fingerprint
        from src.core.discovery import Announcer

        try:
            fingerprint = certificate_fingerprint(str(self.config.get_config_dir()))
        except Exception:  # noqa: BLE001
            fingerprint = ""
        self._announcer = Announcer(self.db.account_id(), self.config.get_device_id_hex(), self.config.get_device_name(), port, fingerprint)
        try:
            self._announcer.start()
        except Exception as e:  # noqa: BLE001 - listening does not depend on it
            logger.info(f"Not announced on the network: {e}")
            self._announcer = None

    def _stop_announcing(self) -> None:
        announcer = getattr(self, "_announcer", None)
        if announcer is not None:
            announcer.stop()
            self._announcer = None

    def _this_device_lines(self) -> str:
        """The account, the device and the address a peer would type, for About."""
        from voicecore import certificate_fingerprint, listen_urls

        config_dir = str(self.config.get_config_dir())
        port = self.config.get_sync_server_port()
        urls = listen_urls(port)
        try:
            fingerprint = certificate_fingerprint(config_dir)
        except Exception:  # noqa: BLE001
            fingerprint = "(not made yet)"
        return (
            f"<b>Account:</b> {self.db.account_id()}<br>"
            f"<b>Device:</b> {self.config.get_device_id_hex()} ({self.config.get_device_name()})<br>"
            f"<b>Address:</b> {', '.join(urls) or 'unknown'}<br>"
            f"<b>Certificate:</b> {fingerprint}"
        )

    def show_about(self) -> None:
        """Show the About dialog."""
        about_text = f"""<h2>Voice</h2>
<p>Version {__version__}</p>

<h3>This device</h3>
<p>{self._this_device_lines()}</p>

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

        # Into the queue, not straight into a thread: the local model wants
        # every core, so two transcriptions at once are slower than two in turn,
        # and the queue is what every interface can see and reorder (File →
        # Transcription queue).
        from src.core import transcription_queue as queue_module

        for provider_config in configs:
            problem = queue_module.enqueue(
                self.db, self.config, audio_file_id, provider_config
            )
            if problem:
                self._show_error("Transcription queue", problem)
                continue
            logger.info(f"Queued {audio_file_id} for {provider_config.get('provider_id')}")

        self._start_queue_worker()
        # Shows the "Pending..." row the queue will fill in
        self.note_pane.refresh_transcriptions(audio_file_id)

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

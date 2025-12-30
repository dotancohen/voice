"""Main application window with 3-pane layout.

This module defines the main window containing three resizable panes:
Tags (left), Notes List (center), and Note Detail (right).
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QSplitter,
    QWidget,
)

from src.core.config import Config
from src.core.database import Database
from src.ui.note_pane import NotePane
from src.ui.notes_list_pane import NotesListPane
from src.ui.tags_pane import TagsPane

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

        logger.info("Menu bar created")

    def connect_signals(self) -> None:
        """Connect signals between panes for communication."""
        # When a tag is selected, filter notes list
        self.tags_pane.tag_selected.connect(self.notes_list_pane.filter_by_tag)

        # When a note is selected, show note detail
        self.notes_list_pane.note_selected.connect(self.note_pane.load_note)

        # When a note is saved, refresh the notes list
        self.note_pane.note_saved.connect(self.on_note_saved)

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
            QMessageBox.warning(
                self,
                "Sync Unavailable",
                "Sync functionality is not available.",
            )
            return

        peers = self.config.get_peers()
        if not peers:
            QMessageBox.information(
                self,
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
                QMessageBox.information(
                    self,
                    "Sync Complete",
                    "No peers to sync with.",
                )
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
            if all_success:
                QMessageBox.information(
                    self,
                    "Sync Complete",
                    "\n".join(summary_lines),
                )
            else:
                QMessageBox.warning(
                    self,
                    "Sync Completed with Errors",
                    "\n".join(summary_lines),
                )

            logger.info(f"Sync completed: {summary_lines}")

        except Exception as e:
            logger.error(f"Sync failed: {e}")
            QMessageBox.critical(
                self,
                "Sync Failed",
                f"An error occurred during sync:\n\n{e}",
            )

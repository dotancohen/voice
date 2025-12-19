"""Main application window with 3-pane layout.

This module defines the main window containing three resizable panes:
Tags (left), Notes List (center), and Note Detail (right).
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QMenuBar, QSplitter, QWidget

from src.core.config import Config
from src.core.database import Database
from src.ui.note_pane import NotePane
from src.ui.notes_list_pane import NotesListPane
from src.ui.tags_pane import TagsPane

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
        self.setWindowTitle("Voice Rewrite")
        self.showMaximized()

        # Create menu bar
        self.setup_menu_bar()

        # Create horizontal splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.splitter)

        # Create the three panes
        self.tags_pane = TagsPane(self.db)
        self.notes_list_pane = NotesListPane(self.config, self.db, theme=self.theme)
        self.note_pane = NotePane(self.db)

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
        """Handle note saved event - refresh notes list.

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

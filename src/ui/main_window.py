"""Main application window with 3-pane layout.

This module defines the main window containing three resizable panes:
Tags (left), Notes List (center), and Note Detail (right).
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QSplitter, QWidget

from core.config import Config
from core.database import Database
from ui.note_pane import NotePane
from ui.notes_list_pane import NotesListPane
from ui.tags_pane import TagsPane

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
        self, config: Config, db: Database, parent: Optional[QWidget] = None
    ) -> None:
        """Initialize the main window.

        Args:
            config: Configuration manager
            db: Database connection
            parent: Parent widget (default None)
        """
        super().__init__(parent)
        self.config = config
        self.db = db

        self.setup_ui()
        self.connect_signals()

        logger.info("Main window initialized")

    def setup_ui(self) -> None:
        """Set up the user interface with three-pane layout."""
        self.setWindowTitle("Voice Rewrite")
        self.showMaximized()

        # Create horizontal splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.splitter)

        # Create the three panes
        self.tags_pane = TagsPane(self.db)
        self.notes_list_pane = NotesListPane(self.config, self.db)
        self.note_pane = NotePane(self.db)

        # Add panes to splitter
        self.splitter.addWidget(self.tags_pane)
        self.splitter.addWidget(self.notes_list_pane)
        self.splitter.addWidget(self.note_pane)

        # Set initial sizes
        self.splitter.setSizes(DEFAULT_SPLITTER_SIZES)

        logger.info("UI layout created with 3 panes")

    def connect_signals(self) -> None:
        """Connect signals between panes for communication."""
        # When a tag is selected, filter notes list
        self.tags_pane.tag_selected.connect(self.notes_list_pane.filter_by_tag)

        # When a note is selected, show note detail
        self.notes_list_pane.note_selected.connect(self.note_pane.load_note)

        logger.info("Inter-pane signals connected")

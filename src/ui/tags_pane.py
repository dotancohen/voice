"""Tags pane displaying hierarchical tag tree.

This module provides the left pane showing tags in a tree structure.
Users can click tags to filter notes by that tag and its descendants.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication, QTreeView, QVBoxLayout, QWidget

from src.core.database import Database

logger = logging.getLogger(__name__)


class TagsTreeView(QTreeView):
    """Custom tree view that emits activated signal on Space key.

    Signals:
        shift_clicked: Emitted when a tag is shift-clicked (index)
    """

    shift_clicked = Signal(object)  # Emits QModelIndex

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle key press - emit activated on Space."""
        if event.key() == Qt.Key.Key_Space:
            index = self.currentIndex()
            if index.isValid():
                self.activated.emit(index)
                event.accept()
                return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse press - detect shift-click."""
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            index = self.indexAt(event.pos())
            if index.isValid():
                self.shift_clicked.emit(index)
                event.accept()
                return
        super().mousePressEvent(event)


class TagsPane(QWidget):
    """Pane displaying hierarchical tag tree.

    Shows all tags in a tree structure. Clicking a tag emits a signal
    to filter notes by that tag (including descendant tags).
    Shift-clicking a tag emits a signal to add it to the current note.

    Signals:
        tag_selected: Emitted when a tag is clicked (tag_id: str)
        tag_add_requested: Emitted when a tag is shift-clicked (tag_id: str)

    Attributes:
        db: Database connection
        tree_view: QTreeView for displaying tags
        model: Tree model for tags
    """

    tag_selected = Signal(str)  # Emits tag_id (UUID hex string)
    tag_add_requested = Signal(str)  # Emits tag_id when shift-clicked

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        """Initialize the tags pane.

        Args:
            db: Database connection
            parent: Parent widget (default None)
        """
        super().__init__(parent)
        self.db = db

        self.setup_ui()
        self.load_tags()

        logger.info("Tags pane initialized")

    def setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create tree view
        self.tree_view = TagsTreeView()
        self.tree_view.setHeaderHidden(True)  # Hide column header
        self.tree_view.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)  # Read-only
        self.tree_view.clicked.connect(self.on_tag_clicked)
        self.tree_view.activated.connect(self.on_tag_clicked)  # Enter/Space keys
        self.tree_view.shift_clicked.connect(self.on_tag_shift_clicked)  # Shift+click

        # Create model
        self.model = QStandardItemModel()
        self.tree_view.setModel(self.model)

        layout.addWidget(self.tree_view)

    def load_tags(self) -> None:
        """Load tags from database and build tree structure."""
        self.model.clear()

        tags = self.db.get_all_tags()
        if not tags:
            logger.info("No tags found in database")
            return

        # Build a map of tag_id -> tag_data for quick lookup
        tag_map: Dict[int, Dict[str, Any]] = {tag["id"]: tag for tag in tags}

        # Build a map of tag_id -> QStandardItem
        item_map: Dict[int, QStandardItem] = {}

        # First pass: create items for all tags
        for tag in tags:
            item = QStandardItem(tag["name"])
            item.setData(tag["id"], role=Qt.ItemDataRole.UserRole)  # Store tag_id
            item_map[tag["id"]] = item

        # Second pass: build hierarchy
        root_items: List[QStandardItem] = []
        for tag in tags:
            item = item_map[tag["id"]]
            parent_id = tag.get("parent_id")

            if parent_id is None:
                # Root level tag
                root_items.append(item)
            elif parent_id in item_map:
                # Add as child to parent
                parent_item = item_map[parent_id]
                parent_item.appendRow(item)
            else:
                # Parent not found, treat as root
                logger.warning(f"Tag {tag['id']} has invalid parent_id {parent_id}")
                root_items.append(item)

        # Add root items to model
        for item in root_items:
            self.model.appendRow(item)

        # Expand all tags by default
        self.tree_view.expandAll()

        logger.info(f"Loaded {len(tags)} tags into tree")

    def on_tag_clicked(self, index: Any) -> None:
        """Handle tag click event.

        Args:
            index: QModelIndex of the clicked item
        """
        item = self.model.itemFromIndex(index)
        if item:
            tag_id = item.data(Qt.ItemDataRole.UserRole)
            logger.info(f"Tag selected: {item.text()} (ID: {tag_id})")
            self.tag_selected.emit(tag_id)

    def on_tag_shift_clicked(self, index: Any) -> None:
        """Handle tag shift-click event (add tag to current note).

        Args:
            index: QModelIndex of the clicked item
        """
        item = self.model.itemFromIndex(index)
        if item:
            tag_id = item.data(Qt.ItemDataRole.UserRole)
            logger.info(f"Tag add requested: {item.text()} (ID: {tag_id})")
            self.tag_add_requested.emit(tag_id)

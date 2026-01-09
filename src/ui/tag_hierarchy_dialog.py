"""Tag hierarchy management dialog.

This module provides a dialog for managing the tag hierarchy, allowing users to:
- View all tags in a tree structure
- Add new tags (with optional parent)
- Rename existing tags
- Reparent tags (move to different parent)
- Delete tags
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.database import Database
from src.ui.styles import BUTTON_STYLE

logger = logging.getLogger(__name__)


class TagHierarchyDialog(QDialog):
    """Dialog for managing the tag hierarchy.

    Signals:
        tags_modified: Emitted when tags are added, renamed, or reorganized
    """

    tags_modified = Signal()

    def __init__(
        self,
        db: Database,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.all_tags: List[dict] = []
        self.tag_items: Dict[str, QTreeWidgetItem] = {}  # tag_id -> tree item

        self.setWindowTitle("Manage Tags")
        self.setMinimumSize(500, 600)
        self.setup_ui()
        self.load_tags()

    def setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)

        # Instructions
        instructions = QLabel(
            "Manage your tag hierarchy. Select a tag to rename, reparent, or delete it.\n"
            "Drag and drop tags to reparent them."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        # Filter field
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter:"))
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Type to filter tags...")
        self.filter_input.textChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.filter_input)
        layout.addLayout(filter_layout)

        # Tree widget for tag hierarchy
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Tag Name", "Notes"])
        self.tree.setColumnWidth(0, 300)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemDropped = self._on_item_dropped  # Custom signal handling
        layout.addWidget(self.tree)

        # Override dropEvent to handle reparenting
        original_drop_event = self.tree.dropEvent

        def custom_drop_event(event):
            # Get the item being dropped and target
            source_item = self.tree.currentItem()
            if source_item:
                source_tag_id = source_item.data(0, Qt.ItemDataRole.UserRole)
                target_item = self.tree.itemAt(event.position().toPoint())
                if target_item:
                    target_tag_id = target_item.data(0, Qt.ItemDataRole.UserRole)
                else:
                    target_tag_id = None  # Drop to root

                # Perform the reparenting in database
                self._reparent_tag(source_tag_id, target_tag_id)

            # Prevent default behavior - we'll reload manually
            event.ignore()

        self.tree.dropEvent = custom_drop_event

        # Action buttons
        button_layout = QHBoxLayout()

        self.add_btn = QPushButton("Add Tag")
        self.add_btn.setStyleSheet(BUTTON_STYLE)
        self.add_btn.clicked.connect(self._add_tag)
        button_layout.addWidget(self.add_btn)

        self.add_child_btn = QPushButton("Add Child")
        self.add_child_btn.setStyleSheet(BUTTON_STYLE)
        self.add_child_btn.clicked.connect(self._add_child_tag)
        self.add_child_btn.setEnabled(False)
        button_layout.addWidget(self.add_child_btn)

        self.rename_btn = QPushButton("Rename")
        self.rename_btn.setStyleSheet(BUTTON_STYLE)
        self.rename_btn.clicked.connect(self._rename_tag)
        self.rename_btn.setEnabled(False)
        button_layout.addWidget(self.rename_btn)

        self.reparent_btn = QPushButton("Move To...")
        self.reparent_btn.setStyleSheet(BUTTON_STYLE)
        self.reparent_btn.clicked.connect(self._show_reparent_dialog)
        self.reparent_btn.setEnabled(False)
        button_layout.addWidget(self.reparent_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setStyleSheet(BUTTON_STYLE)
        self.delete_btn.clicked.connect(self._delete_tag)
        self.delete_btn.setEnabled(False)
        button_layout.addWidget(self.delete_btn)

        layout.addLayout(button_layout)

        # Close button
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(BUTTON_STYLE)
        close_btn.clicked.connect(self.accept)
        close_layout.addWidget(close_btn)
        layout.addLayout(close_layout)

    def load_tags(self) -> None:
        """Load all tags and display them in the tree."""
        try:
            self.all_tags = self.db.get_all_tags()
            self._rebuild_tree()
        except Exception as e:
            logger.error(f"Error loading tags: {e}", exc_info=True)

    def _rebuild_tree(self, filter_text: str = "") -> None:
        """Rebuild the tree widget from tags data.

        Args:
            filter_text: Optional filter text to show only matching tags
        """
        self.tree.clear()
        self.tag_items.clear()

        # Build lookup structures
        tags_by_id = {t["id"]: t for t in self.all_tags}
        tags_by_parent: Dict[Optional[str], List[dict]] = {}

        for tag in self.all_tags:
            parent_id = tag.get("parent_id")
            if parent_id not in tags_by_parent:
                tags_by_parent[parent_id] = []
            tags_by_parent[parent_id].append(tag)

        # Get note counts for each tag
        note_counts = self._get_note_counts()

        # Build full paths for filtering
        tag_paths = self._build_tag_paths()

        if filter_text:
            # Show flat list of matching tags with full paths
            filter_lower = filter_text.lower()
            for tag in self.all_tags:
                full_path = tag_paths.get(tag["id"], tag["name"])
                if filter_lower in full_path.lower():
                    item = QTreeWidgetItem([full_path, str(note_counts.get(tag["id"], 0))])
                    item.setData(0, Qt.ItemDataRole.UserRole, tag["id"])
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                    self.tree.addTopLevelItem(item)
                    self.tag_items[tag["id"]] = item
        else:
            # Show hierarchical view
            self._add_tags_recursive(None, None, tags_by_parent, note_counts)

        self.tree.expandAll()

    def _add_tags_recursive(
        self,
        parent_id: Optional[str],
        parent_item: Optional[QTreeWidgetItem],
        tags_by_parent: Dict[Optional[str], List[dict]],
        note_counts: Dict[str, int],
    ) -> None:
        """Recursively add tags to the tree.

        Args:
            parent_id: Parent tag ID (None for root)
            parent_item: Parent tree item (None for root)
            tags_by_parent: Mapping of parent_id to child tags
            note_counts: Mapping of tag_id to note count
        """
        children = tags_by_parent.get(parent_id, [])

        for tag in sorted(children, key=lambda t: t["name"].lower()):
            tag_id = tag["id"]
            count = note_counts.get(tag_id, 0)

            item = QTreeWidgetItem([tag["name"], str(count)])
            item.setData(0, Qt.ItemDataRole.UserRole, tag_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)

            if parent_item:
                parent_item.addChild(item)
            else:
                self.tree.addTopLevelItem(item)

            self.tag_items[tag_id] = item

            # Add children recursively
            self._add_tags_recursive(tag_id, item, tags_by_parent, note_counts)

    def _build_tag_paths(self) -> Dict[str, str]:
        """Build full paths for all tags.

        Returns:
            Mapping of tag_id to full path (e.g., "Parent > Child > Grandchild")
        """
        tag_by_id = {t["id"]: t for t in self.all_tags}
        paths: Dict[str, str] = {}

        def get_path(tag_id: str) -> str:
            if tag_id in paths:
                return paths[tag_id]

            tag = tag_by_id.get(tag_id)
            if not tag:
                return ""

            parent_id = tag.get("parent_id")
            if parent_id and parent_id in tag_by_id:
                parent_path = get_path(parent_id)
                path = f"{parent_path} > {tag['name']}" if parent_path else tag["name"]
            else:
                path = tag["name"]

            paths[tag_id] = path
            return path

        for tag in self.all_tags:
            get_path(tag["id"])

        return paths

    def _get_note_counts(self) -> Dict[str, int]:
        """Get note count for each tag.

        Returns:
            Mapping of tag_id to number of notes with that tag
        """
        counts: Dict[str, int] = {}
        try:
            for tag in self.all_tags:
                # Get notes for this tag using filter_notes
                notes = self.db.filter_notes([tag["id"]])
                counts[tag["id"]] = len(notes) if notes else 0
        except Exception as e:
            logger.warning(f"Error getting note counts: {e}")
        return counts

    def _on_filter_changed(self, text: str) -> None:
        """Handle filter text change."""
        self._rebuild_tree(text)

    def _on_selection_changed(self) -> None:
        """Handle tree selection change - enable/disable buttons."""
        items = self.tree.selectedItems()
        has_selection = len(items) > 0
        self.add_child_btn.setEnabled(has_selection)
        self.rename_btn.setEnabled(has_selection)
        self.reparent_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)

    def _get_selected_tag_id(self) -> Optional[str]:
        """Get the currently selected tag ID."""
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, Qt.ItemDataRole.UserRole)

    def _add_tag(self) -> None:
        """Add a new root-level tag."""
        name, ok = QInputDialog.getText(
            self,
            "Add Tag",
            "Enter tag name:",
            QLineEdit.EchoMode.Normal,
            "",
        )

        if ok and name.strip():
            try:
                tag_id = self.db.create_tag(name.strip())
                logger.info(f"Created tag {tag_id}: {name}")
                self.load_tags()
                self.tags_modified.emit()
            except Exception as e:
                logger.error(f"Failed to create tag: {e}")
                QMessageBox.warning(self, "Error", f"Failed to create tag:\n{e}")

    def _add_child_tag(self) -> None:
        """Add a child tag under the selected tag."""
        parent_id = self._get_selected_tag_id()
        if not parent_id:
            return

        # Get parent name for display
        parent_name = ""
        for tag in self.all_tags:
            if tag["id"] == parent_id:
                parent_name = tag["name"]
                break

        name, ok = QInputDialog.getText(
            self,
            "Add Child Tag",
            f"Enter child tag name (under '{parent_name}'):",
            QLineEdit.EchoMode.Normal,
            "",
        )

        if ok and name.strip():
            try:
                tag_id = self.db.create_tag(name.strip(), parent_id=parent_id)
                logger.info(f"Created child tag {tag_id}: {name} (parent: {parent_id})")
                self.load_tags()
                self.tags_modified.emit()
            except Exception as e:
                logger.error(f"Failed to create child tag: {e}")
                QMessageBox.warning(self, "Error", f"Failed to create tag:\n{e}")

    def _rename_tag(self) -> None:
        """Rename the selected tag."""
        tag_id = self._get_selected_tag_id()
        if not tag_id:
            return

        # Get current name
        current_name = ""
        for tag in self.all_tags:
            if tag["id"] == tag_id:
                current_name = tag["name"]
                break

        new_name, ok = QInputDialog.getText(
            self,
            "Rename Tag",
            "Enter new name:",
            QLineEdit.EchoMode.Normal,
            current_name,
        )

        if ok and new_name.strip() and new_name.strip() != current_name:
            try:
                self.db.rename_tag(tag_id, new_name.strip())
                logger.info(f"Renamed tag {tag_id}: {current_name} -> {new_name}")
                self.load_tags()
                self.tags_modified.emit()
            except Exception as e:
                logger.error(f"Failed to rename tag: {e}")
                QMessageBox.warning(self, "Error", f"Failed to rename tag:\n{e}")

    def _show_reparent_dialog(self) -> None:
        """Show dialog to select new parent for the selected tag."""
        tag_id = self._get_selected_tag_id()
        if not tag_id:
            return

        # Get current tag info
        current_tag = None
        for tag in self.all_tags:
            if tag["id"] == tag_id:
                current_tag = tag
                break

        if not current_tag:
            return

        # Build list of possible parents (excluding self and descendants)
        descendants = self._get_descendants(tag_id)
        descendants.add(tag_id)

        # Create selection dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Move Tag To...")
        dialog.setMinimumSize(400, 500)

        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel(f"Select new parent for '{current_tag['name']}':"))

        # Tree for parent selection
        parent_tree = QTreeWidget()
        parent_tree.setHeaderLabels(["Tag"])

        # Add "No Parent (Root)" option
        root_item = QTreeWidgetItem(["(No Parent - Move to Root)"])
        root_item.setData(0, Qt.ItemDataRole.UserRole, None)
        parent_tree.addTopLevelItem(root_item)

        # Build parent tree excluding descendants
        tags_by_parent: Dict[Optional[str], List[dict]] = {}
        for tag in self.all_tags:
            if tag["id"] in descendants:
                continue  # Skip self and descendants
            parent_id = tag.get("parent_id")
            if parent_id not in tags_by_parent:
                tags_by_parent[parent_id] = []
            tags_by_parent[parent_id].append(tag)

        def add_items(parent_id: Optional[str], parent_item: Optional[QTreeWidgetItem]) -> None:
            children = tags_by_parent.get(parent_id, [])
            for tag in sorted(children, key=lambda t: t["name"].lower()):
                item = QTreeWidgetItem([tag["name"]])
                item.setData(0, Qt.ItemDataRole.UserRole, tag["id"])
                if parent_item:
                    parent_item.addChild(item)
                else:
                    parent_tree.addTopLevelItem(item)
                add_items(tag["id"], item)

        add_items(None, None)
        parent_tree.expandAll()
        layout.addWidget(parent_tree)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(BUTTON_STYLE)
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        move_btn = QPushButton("Move")
        move_btn.setStyleSheet(BUTTON_STYLE)
        move_btn.setEnabled(False)

        def on_selection_changed():
            move_btn.setEnabled(len(parent_tree.selectedItems()) > 0)

        parent_tree.itemSelectionChanged.connect(on_selection_changed)

        def do_move():
            items = parent_tree.selectedItems()
            if items:
                new_parent_id = items[0].data(0, Qt.ItemDataRole.UserRole)
                dialog.accept()
                self._reparent_tag(tag_id, new_parent_id)

        move_btn.clicked.connect(do_move)
        parent_tree.itemDoubleClicked.connect(lambda: do_move())
        btn_layout.addWidget(move_btn)

        layout.addLayout(btn_layout)
        dialog.exec()

    def _get_descendants(self, tag_id: str) -> set:
        """Get all descendant tag IDs.

        Args:
            tag_id: Parent tag ID

        Returns:
            Set of descendant tag IDs
        """
        descendants = set()
        tags_by_parent: Dict[Optional[str], List[dict]] = {}

        for tag in self.all_tags:
            parent_id = tag.get("parent_id")
            if parent_id not in tags_by_parent:
                tags_by_parent[parent_id] = []
            tags_by_parent[parent_id].append(tag)

        def collect(parent_id: str) -> None:
            for child in tags_by_parent.get(parent_id, []):
                descendants.add(child["id"])
                collect(child["id"])

        collect(tag_id)
        return descendants

    def _reparent_tag(self, tag_id: str, new_parent_id: Optional[str]) -> None:
        """Move a tag to a new parent.

        Args:
            tag_id: Tag to move
            new_parent_id: New parent ID (None for root)
        """
        try:
            # Get current tag info for logging
            current_name = ""
            for tag in self.all_tags:
                if tag["id"] == tag_id:
                    current_name = tag["name"]
                    break

            new_parent_name = "(root)"
            if new_parent_id:
                for tag in self.all_tags:
                    if tag["id"] == new_parent_id:
                        new_parent_name = tag["name"]
                        break

            self.db.reparent_tag(tag_id, new_parent_id)
            logger.info(f"Moved tag {tag_id} ({current_name}) to parent: {new_parent_name}")
            self.load_tags()
            self.tags_modified.emit()
        except Exception as e:
            logger.error(f"Failed to reparent tag: {e}")
            QMessageBox.warning(self, "Error", f"Failed to move tag:\n{e}")

    def _delete_tag(self) -> None:
        """Delete the selected tag after confirmation."""
        tag_id = self._get_selected_tag_id()
        if not tag_id:
            return

        # Get tag info
        tag_name = ""
        for tag in self.all_tags:
            if tag["id"] == tag_id:
                tag_name = tag["name"]
                break

        # Check for children
        children = [t for t in self.all_tags if t.get("parent_id") == tag_id]
        if children:
            child_names = ", ".join(c["name"] for c in children[:5])
            if len(children) > 5:
                child_names += f", ... and {len(children) - 5} more"
            QMessageBox.warning(
                self,
                "Cannot Delete",
                f"Cannot delete '{tag_name}' because it has child tags:\n\n{child_names}\n\n"
                f"Please move or delete the child tags first.",
            )
            return

        # Check for notes using this tag
        notes = self.db.filter_notes([tag_id])
        note_count = len(notes) if notes else 0

        message = f"Delete tag '{tag_name}'?"
        if note_count > 0:
            message += f"\n\nThis tag is used by {note_count} note(s). The tag will be removed from those notes."

        reply = QMessageBox.question(
            self,
            "Delete Tag",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self.db.delete_tag(tag_id)
            logger.info(f"Deleted tag {tag_id}: {tag_name}")
            self.load_tags()
            self.tags_modified.emit()
        except Exception as e:
            logger.error(f"Failed to delete tag: {e}")
            QMessageBox.warning(self, "Error", f"Failed to delete tag:\n{e}")

    def _on_item_dropped(self) -> None:
        """Handle item being dropped (for drag-and-drop reparenting)."""
        # This is handled in the custom dropEvent override
        pass

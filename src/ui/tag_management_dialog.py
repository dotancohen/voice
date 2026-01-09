"""Tag management dialog for adding/removing tags from notes.

This module provides a dialog for managing tags on a note, similar to
VoiceAndroid's TagManagementScreen. Features:
- Hierarchical display of tags with indentation
- Collapse/expand for parent tags
- Filter field that filters on each keypress
- Full path shown when filtering
- Checkboxes to add/remove tags from the note
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.core.database import Database
from src.ui.styles import BUTTON_STYLE

logger = logging.getLogger(__name__)


class TagTreeItem(QWidget):
    """A single tag item with checkbox and optional expand/collapse."""

    toggled = Signal(str, bool)  # tag_id, is_checked
    collapse_toggled = Signal(str)  # tag_id

    def __init__(
        self,
        tag_id: str,
        tag_name: str,
        full_path: str,
        depth: int,
        has_children: bool,
        is_selected: bool,
        is_collapsed: bool,
        is_filtering: bool,
        filter_text: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.tag_id = tag_id
        self.tag_name = tag_name
        self.full_path = full_path
        self.depth = depth
        self.has_children = has_children
        self.is_collapsed = is_collapsed

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        if is_filtering:
            # When filtering, show checkbox then full path
            self.checkbox = QCheckBox()
            self.checkbox.setChecked(is_selected)
            self.checkbox.stateChanged.connect(self._on_checkbox_changed)
            layout.addWidget(self.checkbox)

            # Show full path with filter text highlighted
            label_text = self._highlight_text(full_path, filter_text)
            self.label = QLabel(label_text)
            self.label.setTextFormat(Qt.RichText)
            layout.addWidget(self.label)
        else:
            # When not filtering, show hierarchical layout with indentation
            if depth > 0:
                indent = QWidget()
                indent.setFixedWidth(depth * 24)
                layout.addWidget(indent)

            # Expand/collapse button for tags with children
            if has_children:
                self.collapse_btn = QPushButton(">" if is_collapsed else "v")
                self.collapse_btn.setFixedWidth(24)
                self.collapse_btn.setFlat(True)
                self.collapse_btn.clicked.connect(self._on_collapse_clicked)
                layout.addWidget(self.collapse_btn)
            else:
                spacer = QWidget()
                spacer.setFixedWidth(24)
                layout.addWidget(spacer)

            self.checkbox = QCheckBox()
            self.checkbox.setChecked(is_selected)
            self.checkbox.stateChanged.connect(self._on_checkbox_changed)
            layout.addWidget(self.checkbox)

            self.label = QLabel(tag_name)
            layout.addWidget(self.label)

        layout.addStretch()

    def _highlight_text(self, text: str, highlight: str) -> str:
        """Return HTML with highlighted substring."""
        if not highlight:
            return text

        lower_text = text.lower()
        lower_highlight = highlight.lower()
        result = []
        current_index = 0

        while current_index < len(text):
            match_index = lower_text.find(lower_highlight, current_index)
            if match_index == -1:
                result.append(text[current_index:])
                break

            if match_index > current_index:
                result.append(text[current_index:match_index])

            match_end = match_index + len(highlight)
            result.append(f"<b style='background-color: #ffff00;'>{text[match_index:match_end]}</b>")
            current_index = match_end

        return "".join(result)

    def _on_checkbox_changed(self, state: int) -> None:
        is_checked = state == Qt.Checked.value
        logger.info(f"Checkbox changed for {self.tag_id}: state={state}, is_checked={is_checked}")
        self.toggled.emit(self.tag_id, is_checked)

    def _on_collapse_clicked(self) -> None:
        self.collapse_toggled.emit(self.tag_id)


class TagManagementDialog(QDialog):
    """Dialog for managing tags on a note.

    Signals:
        tags_changed: Emitted when tags are added/removed (note_id: str)
    """

    tags_changed = Signal(str)

    def __init__(
        self,
        db: Database,
        note_id: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.note_id = note_id
        self.filter_text = ""
        self.collapsed_tag_ids: Set[str] = set()
        self.note_tag_ids: Set[str] = set()  # Current state in dialog
        self.original_tag_ids: Set[str] = set()  # Original state from database
        self.all_tags: List[dict] = []

        self.setWindowTitle("Manage Tags")
        self.setMinimumSize(400, 500)
        self.setup_ui()
        self.load_tags()

    def setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)

        # Filter field
        filter_layout = QHBoxLayout()
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter tags...")
        self.filter_input.textChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.filter_input)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setStyleSheet(BUTTON_STYLE)
        self.clear_btn.clicked.connect(self._clear_filter)
        filter_layout.addWidget(self.clear_btn)

        layout.addLayout(filter_layout)

        # Status label
        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        # Scrollable tags area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.tags_container = QWidget()
        self.tags_layout = QVBoxLayout(self.tags_container)
        self.tags_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(self.tags_container)

        layout.addWidget(scroll)

        # Save and Cancel buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(BUTTON_STYLE)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setStyleSheet(BUTTON_STYLE)
        save_btn.clicked.connect(self._save_and_close)
        button_layout.addWidget(save_btn)

        layout.addLayout(button_layout)

    def load_tags(self) -> None:
        """Load all tags and the note's current tags."""
        try:
            # Get all tags
            self.all_tags = self.db.get_all_tags()
            logger.info(f"Loaded {len(self.all_tags)} tags")

            # Get note's current tags
            note = self.db.get_note(self.note_id)
            if note:
                note_tags = self.db.get_note_tags(self.note_id)
                self.note_tag_ids = {t["id"] for t in note_tags}
                self.original_tag_ids = self.note_tag_ids.copy()
                logger.info(f"Note {self.note_id} has tags: {self.note_tag_ids}")
            else:
                self.note_tag_ids = set()
                self.original_tag_ids = set()
                logger.warning(f"Note {self.note_id} not found")

            self._refresh_tags_display()

        except Exception as e:
            logger.error(f"Error loading tags: {e}", exc_info=True)
            self.status_label.setText(f"Error: {e}")

    def _refresh_tags_display(self) -> None:
        """Refresh the tags display based on current filter and state."""
        # Clear existing items
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Build tag hierarchy
        tags_by_parent: Dict[Optional[str], List[dict]] = {}
        tag_children: Dict[str, bool] = {}

        for tag in self.all_tags:
            parent_id = tag.get("parent_id")
            if parent_id not in tags_by_parent:
                tags_by_parent[parent_id] = []
            tags_by_parent[parent_id].append(tag)

        # Mark tags that have children
        for tag in self.all_tags:
            tag_id = tag["id"]
            tag_children[tag_id] = tag_id in tags_by_parent

        # Build full paths for all tags
        tag_paths = self._build_tag_paths()

        is_filtering = bool(self.filter_text)

        if is_filtering:
            # Show flat list of matching tags with full paths
            matching_tags = []
            filter_lower = self.filter_text.lower()

            for tag in self.all_tags:
                full_path = tag_paths.get(tag["id"], tag["name"])
                if filter_lower in full_path.lower():
                    matching_tags.append({
                        "tag": tag,
                        "path": full_path,
                    })

            if not matching_tags:
                self.status_label.setText(f'No tags match "{self.filter_text}"')
            else:
                self.status_label.setText(f"{len(matching_tags)} tag(s) found")

            for item in matching_tags:
                tag = item["tag"]
                tag_item = TagTreeItem(
                    tag_id=tag["id"],
                    tag_name=tag["name"],
                    full_path=item["path"],
                    depth=0,
                    has_children=False,
                    is_selected=tag["id"] in self.note_tag_ids,
                    is_collapsed=False,
                    is_filtering=True,
                    filter_text=self.filter_text,
                )
                tag_item.toggled.connect(self._on_tag_toggled)
                self.tags_layout.addWidget(tag_item)
        else:
            # Show hierarchical view
            self.status_label.setText(f"{len(self.all_tags)} tag(s)")
            self._add_tags_recursive(None, 0, tags_by_parent, tag_children, tag_paths)

    def _build_tag_paths(self) -> Dict[str, str]:
        """Build full paths for all tags."""
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

    def _add_tags_recursive(
        self,
        parent_id: Optional[str],
        depth: int,
        tags_by_parent: Dict[Optional[str], List[dict]],
        tag_children: Dict[str, bool],
        tag_paths: Dict[str, str],
    ) -> None:
        """Recursively add tags to the display."""
        children = tags_by_parent.get(parent_id, [])

        for tag in sorted(children, key=lambda t: t["name"].lower()):
            tag_id = tag["id"]
            has_children = tag_children.get(tag_id, False)
            is_collapsed = tag_id in self.collapsed_tag_ids

            tag_item = TagTreeItem(
                tag_id=tag_id,
                tag_name=tag["name"],
                full_path=tag_paths.get(tag_id, tag["name"]),
                depth=depth,
                has_children=has_children,
                is_selected=tag_id in self.note_tag_ids,
                is_collapsed=is_collapsed,
                is_filtering=False,
                filter_text="",
            )
            tag_item.toggled.connect(self._on_tag_toggled)
            tag_item.collapse_toggled.connect(self._on_collapse_toggled)
            self.tags_layout.addWidget(tag_item)

            # Add children if not collapsed
            if has_children and not is_collapsed:
                self._add_tags_recursive(
                    tag_id, depth + 1, tags_by_parent, tag_children, tag_paths
                )

    def _on_filter_changed(self, text: str) -> None:
        """Handle filter text change."""
        self.filter_text = text
        self._refresh_tags_display()

    def _clear_filter(self) -> None:
        """Clear the filter."""
        self.filter_input.clear()

    def _on_tag_toggled(self, tag_id: str, is_checked: bool) -> None:
        """Handle tag checkbox toggle (updates local state only)."""
        logger.info(f"Tag toggled: {tag_id}, checked: {is_checked}")
        if is_checked:
            self.note_tag_ids.add(tag_id)
        else:
            self.note_tag_ids.discard(tag_id)
        logger.info(f"  Current note_tag_ids: {self.note_tag_ids}")

    def _save_and_close(self) -> None:
        """Save tag changes to the database and close the dialog."""
        try:
            # Find tags to add and remove
            tags_to_add = self.note_tag_ids - self.original_tag_ids
            tags_to_remove = self.original_tag_ids - self.note_tag_ids

            logger.info(f"Saving tags for note {self.note_id}")
            logger.info(f"  Original tags: {self.original_tag_ids}")
            logger.info(f"  Current tags: {self.note_tag_ids}")
            logger.info(f"  Tags to add: {tags_to_add}")
            logger.info(f"  Tags to remove: {tags_to_remove}")

            # Apply changes
            for tag_id in tags_to_add:
                result = self.db.add_tag_to_note(self.note_id, tag_id)
                logger.info(f"Added tag {tag_id} to note {self.note_id}, result: {result}")

            for tag_id in tags_to_remove:
                result = self.db.remove_tag_from_note(self.note_id, tag_id)
                logger.info(f"Removed tag {tag_id} from note {self.note_id}, result: {result}")

            # Verify changes were saved
            note_tags_after = self.db.get_note_tags(self.note_id)
            saved_tag_ids = {t["id"] for t in note_tags_after}
            logger.info(f"  Tags after save: {saved_tag_ids}")

            if saved_tag_ids != self.note_tag_ids:
                logger.error(f"Tag save verification FAILED!")
                logger.error(f"  Expected: {self.note_tag_ids}")
                logger.error(f"  Got: {saved_tag_ids}")
            else:
                logger.info(f"Tag save verification OK")

            # Emit signal if any changes were made
            if tags_to_add or tags_to_remove:
                self.tags_changed.emit(self.note_id)

            self.accept()

        except Exception as e:
            logger.error(f"Error saving tags: {e}", exc_info=True)

    def _on_collapse_toggled(self, tag_id: str) -> None:
        """Handle collapse/expand toggle."""
        if tag_id in self.collapsed_tag_ids:
            self.collapsed_tag_ids.discard(tag_id)
        else:
            self.collapsed_tag_ids.add(tag_id)
        self._refresh_tags_display()

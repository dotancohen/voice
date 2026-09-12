"""Dialogs for a note's version history and for resolving conflicts side by side.

Both are thin views over voicecore's version graph:

- :class:`HistoryDialog` lists every version of a note's content (oldest
  first) and lets the user restore one. A restore is an ordinary edit, so
  nothing is lost and the change syncs like any other.
- :class:`ResolveConflictDialog` shows the two sides of a conflict (and the
  base) next to an editable result. The user can start from either side or
  from the merged text, edit, and save. Saving writes the field once, which
  resolves the conflict everywhere.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.core.conflicts import Conflict, ConflictManager, FieldVersion, has_conflict_markers
from src.core.database import Database
from src.core.models import UUID_SHORT_LEN
from src.core.timestamp_utils import format_timestamp
from src.ui.styles import BUTTON_STYLE

logger = logging.getLogger(__name__)


def version_label(v: FieldVersion, current: Optional[str]) -> str:
    """One line describing a version for lists."""
    kind = "merge" if v.merge_parent_id else ("original" if v.parent_id is None else "edit")
    if v.conflict_kind:
        kind += f" ({v.conflict_kind} conflict)"
    first_line = (v.content or "").split("\n", 1)[0]
    if len(first_line) > 50:
        first_line = first_line[:47] + "…"
    marker = "  ← current" if current is not None and (v.content or "") == current else ""
    return f"{format_timestamp(v.created_at, v.created_at_offset)}  {v.device_label}  {kind}  {first_line}{marker}"


class HistoryDialog(QDialog):
    """Version history of a note's content with restore."""

    def __init__(self, db: Database, note_id: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.note_id = note_id
        self.restored = False
        self.setWindowTitle(f"History of note {note_id[:UUID_SHORT_LEN]}")
        self.resize(900, 600)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Every version of this note, oldest first. Select one to read it; Restore makes it the current text."))

        splitter = QSplitter(Qt.Horizontal)
        self.version_list = QListWidget()
        self.version_list.currentRowChanged.connect(self._show_selected)
        splitter.addWidget(self.version_list)
        self.content_view = QPlainTextEdit()
        self.content_view.setReadOnly(True)
        splitter.addWidget(self.content_view)
        splitter.setSizes([450, 450])
        layout.addWidget(splitter, stretch=1)

        buttons = QHBoxLayout()
        self.restore_button = QPushButton("Restore this version")
        self.restore_button.setStyleSheet(BUTTON_STYLE)
        self.restore_button.clicked.connect(self._restore)
        self.restore_button.setEnabled(False)
        buttons.addWidget(self.restore_button)
        buttons.addStretch()
        close = QPushButton("Close")
        close.setStyleSheet(BUTTON_STYLE)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self.versions: List[FieldVersion] = []
        self._load()

    def _load(self) -> None:
        self.versions = ConflictManager(self.db).get_field_history("note", self.note_id, "content")
        raw = self.db.get_note_raw(self.note_id) or {}
        current = raw.get("content")
        self.version_list.clear()
        for v in self.versions:
            item = QListWidgetItem(version_label(v, current))
            item.setData(Qt.UserRole, v.id)
            self.version_list.addItem(item)
        if self.versions:
            self.version_list.setCurrentRow(len(self.versions) - 1)

    def selected_version(self) -> Optional[FieldVersion]:
        row = self.version_list.currentRow()
        if 0 <= row < len(self.versions):
            return self.versions[row]
        return None

    def _show_selected(self, row: int) -> None:
        v = self.selected_version()
        self.content_view.setPlainText(v.content or "" if v else "")
        raw = self.db.get_note_raw(self.note_id) or {}
        self.restore_button.setEnabled(v is not None and (v.content or "") != raw.get("content"))

    def _restore(self) -> None:
        v = self.selected_version()
        if v is None:
            return
        try:
            self.db.update_note(self.note_id, v.content or "")
        except Exception as e:
            logger.error(f"Failed to restore version {v.id}: {e}")
            QMessageBox.warning(self, "Restore", f"Could not restore: {e}")
            return
        self.restored = True
        logger.info(f"Restored note {self.note_id} to version {v.id}")
        self._load()


class ResolveConflictDialog(QDialog):
    """Side-by-side resolution of one text conflict."""

    def __init__(self, db: Database, conflict: Conflict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.conflict = conflict
        self.resolved = False
        mgr = ConflictManager(db)
        self.versions = mgr.get_conflict_versions(conflict)
        self.setWindowTitle(f"Resolve conflict: {conflict.describe()}")
        self.resize(1100, 650)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"{conflict.describe()}. Pick a starting point, edit the result on the right, then Save. "
            "Saving resolves the conflict on every device."
        ))

        panes = QSplitter(Qt.Horizontal)
        self.side_a = self._pane(panes, f"{conflict.device_a_label} (version A)", self.versions.version_a)
        self.side_b = self._pane(panes, f"{conflict.device_b_label} (version B)", self.versions.version_b)
        result_box = QWidget()
        result_layout = QVBoxLayout(result_box)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.addWidget(QLabel("Result (editable)"))
        self.result_edit = QPlainTextEdit()
        result_layout.addWidget(self.result_edit)
        panes.addWidget(result_box)
        layout.addWidget(panes, stretch=1)

        base_text = self.versions.base.content if self.versions.base else ""
        self.base_view = QPlainTextEdit()
        self.base_view.setReadOnly(True)
        self.base_view.setPlainText(base_text or "")
        self.base_view.setMaximumHeight(120)
        layout.addWidget(QLabel("Common ancestor (before both edits)"))
        layout.addWidget(self.base_view)

        starts = QHBoxLayout()
        for label, text in (
            ("Start from A", self.versions.version_a.content if self.versions.version_a else ""),
            ("Start from B", self.versions.version_b.content if self.versions.version_b else ""),
            ("Start from merged text", self.versions.merge.content if self.versions.merge else ""),
        ):
            b = QPushButton(label)
            b.setStyleSheet(BUTTON_STYLE)
            b.clicked.connect(lambda _=False, t=text: self.result_edit.setPlainText(t or ""))
            starts.addWidget(b)
        starts.addStretch()
        layout.addLayout(starts)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.result_edit.setPlainText((self.versions.merge.content if self.versions.merge else "") or "")

    @staticmethod
    def _pane(parent: QSplitter, title: str, version: Optional[FieldVersion]) -> QPlainTextEdit:
        box = QWidget()
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        when = f" · {format_timestamp(version.created_at, version.created_at_offset)}" if version else ""
        box_layout.addWidget(QLabel(title + when))
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText((version.content if version else "") or "")
        box_layout.addWidget(view)
        parent.addWidget(box)
        return view

    def _save(self) -> None:
        text = self.result_edit.toPlainText()
        if has_conflict_markers(text):
            answer = QMessageBox.question(
                self,
                "Conflict markers remain",
                "The result still contains conflict markers. Save it anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            ok = ConflictManager(self.db).resolve_with_content(self.conflict.id, text)
        except Exception as e:
            logger.error(f"Failed to resolve conflict {self.conflict.id}: {e}")
            QMessageBox.warning(self, "Resolve", f"Could not resolve: {e}")
            return
        if not ok:
            QMessageBox.information(self, "Resolve", "This conflict was already resolved.")
        self.resolved = True
        self.accept()

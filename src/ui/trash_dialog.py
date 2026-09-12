"""The trash bin: notes that were deleted, and what can still be done with them.

Deleting a note in Voice has always been a soft delete, so nothing has ever
really been lost. This dialog is where the user sees that: every deleted note
is listed with the text it had, and goes back to the list with one button or
out of the database for good with the other.

"For good" means for good, on every device: the removal is written down and
travels with the next sync, and the note cannot come back from a device that
had not heard about it yet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

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

from src.core.database import Database
from src.core.timestamp_utils import format_timestamp

UUID_SHORT_LEN = 12


class TrashDialog(QDialog):
    """Shows deleted notes; recovers them or removes them for good."""

    def __init__(
        self,
        db: Database,
        audiofile_directory: Optional[Path] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.audiofile_directory = audiofile_directory
        self.notes: List[Dict[str, Any]] = []
        # True when something was recovered or removed, so the caller reloads
        self.changed = False

        self.setWindowTitle("Trash")
        self.resize(800, 500)

        layout = QVBoxLayout(self)

        self.summary_label = QLabel("")
        layout.addWidget(self.summary_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._show_selected)
        splitter.addWidget(self.list_widget)

        self.content_view = QPlainTextEdit()
        self.content_view.setReadOnly(True)
        splitter.addWidget(self.content_view)
        splitter.setSizes([320, 480])
        layout.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        self.recover_button = QPushButton("Recover")
        self.recover_button.clicked.connect(self.recover_selected)
        buttons.addWidget(self.recover_button)

        self.purge_button = QPushButton("Delete for good")
        self.purge_button.clicked.connect(self.purge_selected)
        buttons.addWidget(self.purge_button)

        buttons.addStretch(1)
        layout.addLayout(buttons)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.accept)
        layout.addWidget(button_box)

        self.reload()

    def reload(self) -> None:
        """Read the trash again and show what is in it."""
        self.notes = self.db.get_deleted_notes()
        self.list_widget.clear()
        for note in self.notes:
            lines = [line.strip() for line in (note.get("content") or "").split("\n") if line.strip()]
            first_line = lines[0][:70] if lines else "(no text)"
            deleted = format_timestamp(note.get("deleted_at"), note.get("deleted_at_offset"))
            item = QListWidgetItem(f"{deleted}   {first_line}")
            item.setData(Qt.ItemDataRole.UserRole, note["id"])
            self.list_widget.addItem(item)

        if self.notes:
            self.summary_label.setText(
                f"{len(self.notes)} note(s) in the trash. "
                "Recover puts one back in the list; Delete for good removes it from every device."
            )
            self.list_widget.setCurrentRow(0)
        else:
            self.summary_label.setText("The trash is empty.")
            self.content_view.setPlainText("")
        self._update_buttons()

    def _update_buttons(self) -> None:
        has_selection = self.selected_note() is not None
        self.recover_button.setEnabled(has_selection)
        self.purge_button.setEnabled(has_selection)

    def selected_note(self) -> Optional[Dict[str, Any]]:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self.notes):
            return self.notes[row]
        return None

    def _show_selected(self, row: int) -> None:
        if 0 <= row < len(self.notes):
            self.content_view.setPlainText(self.notes[row].get("content") or "(no text)")
        else:
            self.content_view.setPlainText("")
        self._update_buttons()

    def recover_selected(self) -> None:
        note = self.selected_note()
        if note is None:
            return
        if self.db.undelete_note(note["id"]):
            self.changed = True
            self.reload()

    def purge_selected(self) -> None:
        """Remove the selected note for good, after asking plainly."""
        note = self.selected_note()
        if note is None:
            return
        lines = [line.strip() for line in (note.get("content") or "").split("\n") if line.strip()]
        first_line = lines[0][:70] if lines else "(no text)"

        confirm = QMessageBox(self)
        confirm.setWindowTitle("Delete for good")
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setText(f"Remove this note for good?\n\n{first_line}")
        confirm.setInformativeText(
            "The note, its history and the recordings that belong only to it are removed "
            "from this device and from every device it syncs with. This cannot be undone."
        )
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes
        )
        confirm.setDefaultButton(QMessageBox.StandardButton.Cancel)
        confirm.button(QMessageBox.StandardButton.Yes).setText("Delete for good")
        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return

        audio_ids = self.db.purge_note(note["id"])
        removed = remove_audio_files(audio_ids, self.audiofile_directory)
        self.changed = True
        self.reload()
        if removed:
            self.summary_label.setText(
                f"{self.summary_label.text()}  ({removed} recording file(s) deleted)"
            )


def remove_audio_files(audio_ids: List[str], directory: Optional[Path]) -> int:
    """Delete the files of recordings that were purged; return how many went.

    The database says which recordings were removed; where their files live
    is the application's business, not the core's.
    """
    if not audio_ids or directory is None:
        return 0
    removed = 0
    for audio_id in audio_ids:
        for path in Path(directory).glob(f"{audio_id}.*"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed

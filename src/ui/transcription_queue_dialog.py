"""What is waiting to be transcribed on this computer, and what it cost.

Three groups, read downwards as time runs forwards: what is **waiting**, what is
being **worked on**, and what is **done**. Newest first within each group, as in
the notes list, so the order the waiting Recordings will really be reached in is
printed on the row itself.

The numbers on a finished Recording — how much text came out, how long the
Recording was, the clock time, the processor time, the peak memory — are what
this screen exists for. They are what says whether a larger model is worth its
wait, and they are what the estimate for every waiting Recording is calculated
from. See ``core/transcription_queue.py``.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.core import transcription_queue as queue_module

logger = logging.getLogger(__name__)


class TranscriptionQueueDialog(QDialog):
    """The transcription queue, with what the finished work cost."""

    def __init__(self, db: Any, config: Any, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.config = config
        self.rows: List[Any] = []
        self.changed = False

        self.setWindowTitle("Transcription queue")
        self.resize(1000, 640)

        layout = QVBoxLayout(self)

        self.heading = QLabel()
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)

        self.table = QTableWidget(0, 8, self)
        self.table.setHorizontalHeaderLabels([
            "", "Note", "Recording", "Length", "Text", "Clock", "Processor", "Memory",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        self.next_button = QPushButton("Transcribe this one &next")
        self.next_button.clicked.connect(self._do_next)
        buttons.addWidget(self.next_button)

        self.remove_button = QPushButton("Take out of the &queue")
        self.remove_button.clicked.connect(self._remove)
        buttons.addWidget(self.remove_button)

        self.reload_button = QPushButton("&Reload")
        self.reload_button.clicked.connect(self.reload)
        buttons.addWidget(self.reload_button)

        buttons.addStretch()
        close_button = QPushButton("&Close")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.reload()

    # ----------------------------------------------------------------- loading

    def reload(self) -> None:
        """Read the queue and the finished work again."""
        view = queue_module.view(self.db, self.config)
        self.rows = list(view.waiting) + list(view.processing) + list(view.completed)

        if view.rate:
            self.heading.setText(
                f"This computer transcribes at about {view.rate:.1f} seconds of work per "
                f"second of Recording. Waiting first, then what is being worked on, then "
                f"what is done; newest first in each."
            )
        else:
            self.heading.setText(
                "Nothing has finished on this computer yet, so there is nothing to estimate "
                "the waiting from. Waiting first, then what is being worked on, then what is done."
            )

        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            for column, text in enumerate(self._cells(row)):
                item = QTableWidgetItem(text)
                # Top-aligned: a note's line is the long column, and the
                # numbers beside it belong level with its first line.
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                self.table.setItem(index, column, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        if self.rows:
            self.table.selectRow(0)
        self._update_buttons()

    def _cells(self, row: Any) -> List[str]:
        """One row of the table."""
        state = {
            "waiting": "waiting",
            "processing": "working",
            "done": "done",
            "failed": "failed",
        }.get(row.state, row.state)
        if row.state == "waiting":
            place = "next" if row.position == 1 else f"{row.position}th"
            wait = queue_module.in_words(row.wait_seconds)
            state = f"waiting, {place}"
            text_column = f"done in {wait}" if wait else "no estimate yet"
        elif row.state == "processing":
            text_column = row.outcome or "working"
        elif row.state == "failed":
            text_column = row.outcome or "did not finish"
        else:
            text_column = f"{row.characters} characters" if row.characters is not None else "-"

        work = row.work
        return [
            state,
            row.note_line or "(no note)",
            row.filename,
            self._length(row.audio_seconds),
            text_column,
            self._seconds(work.clock_seconds) if work else "-",
            self._seconds(work.cpu_seconds) if work else "-",
            self._bytes(work.peak_memory_bytes) if work else "-",
        ]

    @staticmethod
    def _length(seconds: Optional[float]) -> str:
        if not seconds:
            return "-"
        seconds = int(seconds)
        if seconds >= 3600:
            return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
        return f"{seconds // 60}:{seconds % 60:02d}"

    @staticmethod
    def _seconds(value: Optional[float]) -> str:
        if not value:
            return "-"
        if value >= 3600:
            return f"{value / 3600:.1f} h"
        if value >= 60:
            return f"{int(value // 60)} min {int(value % 60)} s"
        return f"{value:.1f} s"

    @staticmethod
    def _bytes(value: Optional[int]) -> str:
        if not value:
            return "-"
        if value >= 1_000_000_000:
            return f"{value / 1e9:.2f} GB"
        if value >= 1_000_000:
            return f"{value / 1e6:.0f} MB"
        return f"{value / 1e3:.0f} kB"

    # ----------------------------------------------------------------- actions

    def _selected(self) -> Optional[Any]:
        index = self.table.currentRow()
        if 0 <= index < len(self.rows):
            return self.rows[index]
        return None

    def _update_buttons(self) -> None:
        row = self._selected()
        waiting = row is not None and row.state == "waiting"
        self.next_button.setEnabled(waiting)
        self.remove_button.setEnabled(waiting)

    def _do_next(self) -> None:
        row = self._selected()
        if row is None or row.state != "waiting":
            return
        if queue_module.Queue(self.config.config_dir).do_next(row.audio_file_id):
            self.changed = True
            self.reload()
        else:
            QMessageBox.information(
                self, "Transcription queue", "That Recording is already next."
            )

    def _remove(self) -> None:
        row = self._selected()
        if row is None or row.state != "waiting":
            return
        if queue_module.Queue(self.config.config_dir).remove(row.audio_file_id):
            self.changed = True
            self.reload()

"""Test all syncing paths (Stage 8): the connection check against every other
device of the account and against the bucket, as one table. The checks run on
a thread of its own with a spinner meanwhile; that thread opens its own
connections and touches no object of the window's."""

from __future__ import annotations

import threading
import weakref
from typing import Any, Dict, List, Tuple

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core import storage_setup


class _Relay(QObject):
    done = Signal(object)


def _test_paths(config_dir: str, devices: List[Tuple[str, str]], relay: _Relay) -> None:
    """The worker thread: plain values in, the rows (or the exception) out. It
    holds no window and no configuration, so nothing of theirs is freed here."""
    try:
        result: Any = storage_setup.check_all_paths(config_dir, devices)
    except Exception as e:  # noqa: BLE001 - said in the window
        result = e
    relay.done.emit(result)


class SyncPathsDialog(QDialog):
    """One row per check: passed or failed, the device or the bucket, what was checked, what was found."""

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Test all syncing paths")
        self.resize(760, 420)
        self.config = config
        self.busy = False
        self._relay = _Relay()
        # Weakly: a relay the worker thread holds last keeps no window alive
        dialog = weakref.ref(self)
        self._relay.done.connect(lambda result: dialog() and dialog()._done(result))
        box = QVBoxLayout(self)
        self.busy_row = QWidget()
        busy_layout = QHBoxLayout(self.busy_row)
        busy_layout.setContentsMargins(0, 0, 0, 0)
        spinner = QProgressBar()
        spinner.setRange(0, 0)
        spinner.setTextVisible(False)
        spinner.setMaximumWidth(120)
        busy_layout.addWidget(spinner)
        self.busy_label = QLabel("Testing each device and the bucket…")
        busy_layout.addWidget(self.busy_label, 1)
        box.addWidget(self.busy_row)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        box.addWidget(self.summary)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "Path", "Check", "Found"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        box.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.again_button = QPushButton("Test again")
        self.again_button.clicked.connect(self.start)
        buttons.addWidget(self.again_button)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        box.addLayout(buttons)
        self.start()

    def start(self) -> None:
        if self.busy:
            return
        # Read on the window's thread; the worker gets plain values only
        devices = storage_setup.devices_of(self.config)
        config_dir = str(self.config.get_config_dir())
        self.busy = True
        self.busy_row.setVisible(True)
        self.again_button.setEnabled(False)
        self.summary.setText("")

        threading.Thread(target=_test_paths, args=(config_dir, devices, self._relay), daemon=True).start()

    def _done(self, result: Any) -> None:
        self.busy = False
        self.busy_row.setVisible(False)
        self.again_button.setEnabled(True)
        if isinstance(result, Exception):
            self.summary.setText(f"The tests could not run: {result}")
            self.table.setRowCount(0)
            return
        rows: List[Dict[str, Any]] = result
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            path, _, check = row["name"].partition(": ")
            detail = row["detail"] + (f" ({row['code']})" if row.get("code") else "")
            for column, text in enumerate(["✓" if row["passed"] else "✗", path, check, detail]):
                self.table.setItem(index, column, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        failed = sum(1 for r in rows if not r["passed"])
        if not rows:
            self.summary.setText("No device and no bucket to test yet.")
        elif failed:
            self.summary.setText(f"{failed} of {len(rows)} checks failed.")
        else:
            self.summary.setText(f"All {len(rows)} checks passed.")

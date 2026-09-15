"""The sync dialogue (Stage 5, Stage 10, Stage 12).

One place for everything between this device and the others: the line that
says what is on this device only, the devices with when each was last reached,
one button that names the last device, the code to show, the connection check,
the listener switch, and this device's own address at the bottom.
"""

from __future__ import annotations

import html

import logging
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
)

from src.core.config import Config
from src.core.database import Database
from src.core.timestamp_utils import format_timestamp

logger = logging.getLogger(__name__)

UUID_SHORT_LEN = 8

# The five operations of the terms table, as the menu names them
OPERATIONS = [
    ("exchange", "Exchange", "sync, then send and fetch recordings"),
    ("deliver", "Deliver", "sync, then send recordings"),
    ("sync", "Sync", "notes only"),
    ("send", "Send", "recordings the device lacks, no sync"),
    ("fetch", "Fetch", "recordings this device lacks, no sync"),
]

# Which button fixes a refusal, by its code (Stage 5): the sentence, then
# the button
FIX_FOR_CODE = {
    "DEVICE_UNKNOWN": "show_code",
    "KEY_WRONG": "show_code",
    "KEY_MISSING": "show_code",
    "DEVICE_REVOKED": "show_code",
    "ACCOUNT_MISMATCH": "show_code",
    "ACCOUNT_UNKNOWN": "check",
    "CERTIFICATE_MISMATCH": "check",
    "TLS_REQUIRED": "check",
}


def not_duplicated_sentence(counts: Dict[str, int]) -> str:
    """The one line of Stage 10: what exists on this device only."""
    notes, recordings = counts["notes"], counts["recordings"]
    if notes == 0 and recordings == 0:
        return "Everything is duplicated off this device."
    note_part = f"{notes} note{'s' if notes != 1 else ''}"
    recording_part = f"{recordings} recording{'s' if recordings != 1 else ''}"
    return f"{note_part} and {recording_part} are not duplicated off this device."


def result_sentence(operation: str, device_name: str, result: Any) -> str:
    """One sentence for a result (Stage 5), followed by the request id."""
    verb = dict((k, v) for k, v, _ in OPERATIONS)[operation]
    parts = []
    if operation in ("sync", "deliver", "exchange"):
        parts.append(f"received {result.pulled} changes and sent {result.pushed}")
    if getattr(result, "sent", 0):
        parts.append(f"sent {result.sent} recordings")
    if getattr(result, "fetched", 0):
        parts.append(f"fetched {result.fetched} recordings")
    if getattr(result, "bytes_moved", 0):
        parts.append(f"{result.bytes_moved / (1024 * 1024):.1f} MB moved")
    what = ", ".join(parts) if parts else "nothing to move"
    request = f" Request {result.request_id}." if getattr(result, "request_id", "") else ""
    if result.success:
        return f"{verb} with {device_name}: {what}.{request}"
    errors = "; ".join(result.errors) if result.errors else "it did not say why"
    return f"{verb} with {device_name} failed: {errors}.{request}"


def refusal_code(errors: List[str]) -> str:
    """The refusal code in an error sentence, if any."""
    for sentence in errors:
        for code in FIX_FOR_CODE:
            if code in sentence:
                return code
    return ""


class OperationWorker(QThread):
    """One operation on a thread of its own, so the window stays alive and
    Cancel works; progress arrives as sentences (Stage 4)."""

    progressed = Signal(str)
    done = Signal(object)

    def __init__(self, client, method_name: str, device_id: str, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.method_name = method_name
        self.device_id = device_id

    def run(self) -> None:
        self.client.set_progress(lambda stage, done, total, bytes_moved, sentence: self.progressed.emit(sentence))
        try:
            result = getattr(self.client, self.method_name)(self.device_id)
        except Exception as e:  # noqa: BLE001 - handed to the window
            result = e
        finally:
            self.client.set_progress(None)
        self.done.emit(result)


# The idle-stop choices: hours of silence after which the listener stops
IDLE_STOP_CHOICES = [(0, "keep listening"), (1, "stop after 1 hour of silence"), (4, "stop after 4 hours of silence"), (8, "stop after 8 hours of silence")]


class SyncDialog(QDialog):
    """Everything between this device and the others, in one window."""

    def __init__(
        self,
        db: Database,
        config: Config,
        listen_action: Optional[QAction] = None,
        after_operation: Optional[Callable[[], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.config = config
        self.listen_action = listen_action
        self.after_operation = after_operation
        self.setWindowTitle("Sync")
        self.resize(720, 560)

        layout = QVBoxLayout(self)

        # Which device this window is on, before anything else: its name heads the
        # window, and every other device is listed under a heading of its own
        self.this_device_heading = QLabel()
        self.this_device_heading.setObjectName("this_device_heading")
        self.this_device_heading.setAccessibleName("This device")
        layout.addWidget(self.this_device_heading)

        # Stage 8: the checklist, each row its state and the one button that completes it
        self.checklist_box = QVBoxLayout()
        self.checklist_rows: List[Any] = []
        layout.addLayout(self.checklist_box)

        # Stage 10: the line, here and nowhere else
        self.proof_label = QLabel()
        self.proof_label.setObjectName("proof_label")
        self.proof_label.setAccessibleName("What is on this device only")
        layout.addWidget(self.proof_label)

        # The other devices of the account
        self.devices_heading = QLabel("Other devices of this account")
        self.devices_heading.setObjectName("devices_heading")
        layout.addWidget(self.devices_heading)
        self.devices_table = QTableWidget(0, 4)
        self.devices_table.setHorizontalHeaderLabels(["Other device", "Address", "Last reached", "Last operation"])
        self.devices_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.devices_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.devices_table.horizontalHeader().setStretchLastSection(True)
        self.devices_table.setAccessibleName("Other devices of this account")
        layout.addWidget(self.devices_table)

        # One visible button, naming the last device; the arrow chooses another
        # device or another operation
        actions = QHBoxLayout()
        self.operation_button = QToolButton()
        self.operation_button.setObjectName("operation_button")
        self.operation_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.operation_button.clicked.connect(self._run_default)
        self.operation_menu = QMenu(self)
        self.submenus: List[QMenu] = []
        self.operation_button.setMenu(self.operation_menu)
        actions.addWidget(self.operation_button)

        self.check_button = QPushButton("Check connection")
        self.check_button.setAccessibleDescription("Reachability, certificate, account, key, clock and free space, each with its code")
        self.check_button.clicked.connect(self._check_connection)
        actions.addWidget(self.check_button)

        self.show_code_button = QPushButton("Show my code")
        self.show_code_button.setAccessibleDescription("A code another device reads to join this account")
        self.show_code_button.clicked.connect(self._show_code)
        actions.addWidget(self.show_code_button)
        self.test_all_button = QPushButton("Test all syncing paths…")
        self.test_all_button.setAccessibleDescription("The connection check against every other device of the account and the bucket, as one table")
        self.test_all_button.clicked.connect(self._test_everything)
        actions.addWidget(self.test_all_button)
        self.wizard_button = QPushButton("Set up the bucket…")
        self.wizard_button.setAccessibleDescription("The bucket wizard: make the key, make and harden the bucket, test it")
        self.wizard_button.clicked.connect(self._open_wizard)
        actions.addWidget(self.wizard_button)
        actions.addStretch()
        layout.addLayout(actions)

        # Encryption of recordings in the bucket (Stage 15): off until the key was exported
        encryption = QHBoxLayout()
        self.encrypt_box = QCheckBox("Encrypt recordings in the bucket")
        self.encrypt_box.setAccessibleDescription("New uploads are encrypted with the account's recording key; export the key first")
        self.encrypt_box.toggled.connect(self._set_encryption)
        encryption.addWidget(self.encrypt_box)
        self.export_key_button = QPushButton("Export the recording key…")
        self.export_key_button.setAccessibleDescription("Show the key as text and a QR code; keep it on paper")
        self.export_key_button.clicked.connect(self._export_recording_key)
        encryption.addWidget(self.export_key_button)
        self.import_key_button = QPushButton("Import…")
        self.import_key_button.setAccessibleDescription("Keep a recording key from an export")
        self.import_key_button.clicked.connect(self._import_recording_key)
        encryption.addWidget(self.import_key_button)
        self.reupload_button = QPushButton("Re-upload existing recordings encrypted")
        self.reupload_button.clicked.connect(self._reupload_encrypted)
        encryption.addWidget(self.reupload_button)
        encryption.addStretch()
        layout.addLayout(encryption)
        self._refresh_encryption()

        device_actions = QHBoxLayout()
        self.rename_button = QPushButton("Rename…")
        self.rename_button.clicked.connect(self._rename_device)
        device_actions.addWidget(self.rename_button)
        self.forget_button = QPushButton("Forget")
        self.forget_button.setAccessibleDescription("Remove the selected device from this device's list; its card does not bring it back")
        self.forget_button.clicked.connect(self._forget_device)
        device_actions.addWidget(self.forget_button)
        self.add_button = QPushButton("Add by address…")
        self.add_button.clicked.connect(self._add_device)
        device_actions.addWidget(self.add_button)
        self.find_button = QPushButton("Find on this network")
        self.find_button.setAccessibleDescription("Devices of this account announcing on the local network; a found one can be added as a device")
        self.find_button.clicked.connect(self._find_on_network)
        device_actions.addWidget(self.find_button)
        device_actions.addStretch()
        layout.addLayout(device_actions)

        # The result: one sentence, and the button that fixes a refusal
        self.result_label = QLabel()
        self.result_label.setObjectName("result_label")
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.result_label.setAccessibleName("Result of the last operation")
        layout.addWidget(self.result_label)
        self.fix_button = QPushButton()
        self.fix_button.hide()
        self._fix: Optional[Callable[[], None]] = None
        self.fix_button.clicked.connect(lambda: self._fix() if self._fix else None)
        layout.addWidget(self.fix_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setAccessibleDescription("Stop the operation under way; a transfer continues from where it stopped next time")
        self.cancel_button.hide()
        self.cancel_button.clicked.connect(self._cancel)
        layout.addWidget(self.cancel_button)
        self._worker: Optional[OperationWorker] = None
        self._client = None

        # Stage 6: the listener, the same switch as the File menu's, and
        # the hours of silence after which it stops itself
        listen_row = QHBoxLayout()
        self.listen_checkbox = QCheckBox("Listen for devices")
        self.listen_checkbox.setAccessibleDescription("Let other devices of the account reach this computer")
        if listen_action is not None:
            self.listen_checkbox.setChecked(listen_action.isChecked())
            self.listen_checkbox.toggled.connect(listen_action.setChecked)
            listen_action.toggled.connect(self.listen_checkbox.setChecked)
        else:
            self.listen_checkbox.setEnabled(False)
        listen_row.addWidget(self.listen_checkbox)
        self.idle_stop = QComboBox()
        self.idle_stop.setAccessibleName("When the listener stops itself")
        for hours, label in IDLE_STOP_CHOICES:
            self.idle_stop.addItem(label, hours)
        current = self.config.listener_idle_stop_hours()
        self.idle_stop.setCurrentIndex(next((i for i, (h, _) in enumerate(IDLE_STOP_CHOICES) if h == current), 0))
        self.idle_stop.currentIndexChanged.connect(lambda i: self.config.set_listener_idle_stop_hours(int(self.idle_stop.itemData(i))))
        listen_row.addWidget(self.idle_stop)
        listen_row.addStretch()
        layout.addLayout(listen_row)

        # This device, in plain sight
        self.device_label = QLabel()
        self.device_label.setObjectName("device_label")
        self.device_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.device_label.setWordWrap(True)
        layout.addWidget(self.device_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.refresh()

    # ----- state

    def refresh(self) -> None:
        """Read everything again: the checklist, the line, the devices, the button, this device."""
        self._refresh_checklist()
        try:
            counts = self.db.not_duplicated(self.config.get_audiofile_directory())
            self.proof_label.setText(not_duplicated_sentence(counts))
        except Exception as e:  # noqa: BLE001 - the dialogue still opens
            self.proof_label.setText(f"Could not count what is on this device only: {e}")

        self.devices = self.config.get_devices()
        summaries = {p["device_id"]: p for p in self.db.device_summaries()}
        self.devices_table.setRowCount(len(self.devices))
        for row, device in enumerate(self.devices):
            summary = summaries.get(device["device_id"], {})
            reached = summary.get("last_reached_at")
            self.devices_table.setItem(row, 0, QTableWidgetItem(f"{device['device_name']} ({device['device_id'][:UUID_SHORT_LEN]})"))
            self.devices_table.setItem(row, 1, QTableWidgetItem(device.get("device_url") or "no address yet"))
            self.devices_table.setItem(row, 2, QTableWidgetItem(format_timestamp(reached) if reached else "never"))
            self.devices_table.setItem(row, 3, QTableWidgetItem(summary.get("last_operation") or ""))
        self.devices_table.resizeColumnsToContents()

        self._build_operation_menu()
        self.device_label.setText(self._this_device_text())
        this_name = self.config.get_this_device_name()
        self.this_device_heading.setText(f"<b>This device:</b> {html.escape(this_name)}")
        self.setWindowTitle(f"Sync — {this_name}")

    def _refresh_checklist(self) -> None:
        from src.core.storage_setup import checklist

        for widget in self.checklist_rows:
            widget.setParent(None)
            widget.deleteLater()
        self.checklist_rows = []
        listening = self.listen_action.isChecked() if self.listen_action is not None else False
        try:
            rows = checklist(self.config, self.db, listening)
        except Exception as e:  # noqa: BLE001
            rows = [{"name": "Checklist", "done": False, "detail": str(e), "action": "", "action_label": ""}]
        self.checklist = rows
        for entry in rows:
            line = QHBoxLayout()
            holder = QLabel(f"{'✓' if entry['done'] else '✗'} {entry['name']}: {entry['detail']}")
            holder.setAccessibleName(f"{entry['name']}, {'done' if entry['done'] else 'not done'}: {entry['detail']}")
            line.addWidget(holder)
            if entry["action"]:
                button = QPushButton(entry["action_label"])
                button.clicked.connect(lambda _checked=False, a=entry["action"]: self._checklist_action(a))
                line.addWidget(button)
            line.addStretch()
            from PySide6.QtWidgets import QWidget

            row_widget = QWidget()
            row_widget.setLayout(line)
            self.checklist_box.addWidget(row_widget)
            self.checklist_rows.append(row_widget)

    def _checklist_action(self, action: str) -> None:
        if action == "show_code":
            self._show_code()
        elif action == "storage_wizard":
            self._open_wizard()
        elif action == "listen" and self.listen_action is not None:
            self.listen_action.setChecked(True)
            self.refresh()
        elif action == "exchange":
            self._run_default()

    def _open_wizard(self) -> None:
        from src.ui.storage_wizard import StorageWizard

        # Already in the Sync window: the last page does not offer to open it
        StorageWizard(self.db, self.config, offer_sync=False, parent=self).exec()
        self.refresh()

    def _test_everything(self) -> None:
        """Test all syncing paths: every other device and the bucket."""
        from src.ui.sync_paths_dialog import SyncPathsDialog

        SyncPathsDialog(self.config, parent=self).exec()

    def _last_device(self) -> Optional[Dict[str, Any]]:
        """The device the visible button names: the last used, else the only one."""
        last = self.config.last_device_id()
        for device in self.devices:
            if device["device_id"] == last:
                return device
        return self.devices[0] if len(self.devices) == 1 else None

    def _selected_device(self) -> Optional[Dict[str, Any]]:
        rows = self.devices_table.selectionModel().selectedRows() if self.devices_table.selectionModel() else []
        if rows:
            return self.devices[rows[0].row()]
        return self._last_device()

    def _build_operation_menu(self) -> None:
        # A fresh menu each time: clearing one deletes its submenus under us
        old_menu = self.operation_menu
        self.operation_menu = QMenu(self)
        self.submenus = []
        self.operation_button.setMenu(self.operation_menu)
        old_menu.deleteLater()
        device = self._last_device()
        if device is None:
            self.operation_button.setText("Exchange…" if self.devices else "No device yet: show my code, or read another device's")
            self.operation_button.setEnabled(bool(self.devices))
        else:
            self.operation_button.setText(f"Exchange with {device['device_name']}")
            self.operation_button.setEnabled(True)
        self.operation_button.setAccessibleName(self.operation_button.text())
        for other in self.devices:
            submenu = self.operation_menu.addMenu(other["device_name"])
            self.submenus.append(submenu)
            for operation, label, detail in OPERATIONS:
                action = submenu.addAction(f"{label} — {detail}")
                action.triggered.connect(lambda _checked=False, o=operation, p=other: self._run(o, p))

    def _this_device_text(self) -> str:
        from voicecore import certificate_fingerprint, listen_addresses

        from src.core.addresses_text import address_words

        port = self.config.get_sync_server_port()
        addresses = listen_addresses(port)
        try:
            fingerprint = certificate_fingerprint(str(self.config.get_config_dir()))
        except Exception:  # noqa: BLE001
            fingerprint = "(made when the listener first runs)"
        return (
            f"<b>This device:</b> {self.config.get_this_device_name()} ({self.config.get_this_device_id_hex()})<br>"
            f"<b>Address:</b> {address_words(addresses)} (port {port})<br>"
            f"<b>Certificate:</b> {fingerprint}"
        )

    # ----- operations

    def _run_default(self) -> None:
        device = self._last_device()
        if device is None:
            if self.devices:
                self.operation_button.showMenu()
            return
        self._run("exchange", device)

    def _run(self, operation: str, device: Dict[str, Any]) -> None:
        """The operation on a worker thread, with progress and Cancel (Stage 4)."""
        from voicecore import SyncClient

        if self._worker is not None and self._worker.isRunning():
            self.result_label.setText("An operation is under way; cancel it first.")
            return
        self.result_label.setText(f"{dict((k, v) for k, v, _ in OPERATIONS)[operation]} with {device['device_name']}…")
        self.fix_button.hide()
        self.cancel_button.show()
        self.operation_button.setEnabled(False)
        self._client = SyncClient(str(self.config.get_config_dir()))
        method_name = {"sync": "sync_with_device", "deliver": "deliver", "exchange": "exchange", "send": "send_to_device", "fetch": "fetch_from_device"}[operation]
        self._worker = OperationWorker(self._client, method_name, device["device_id"], parent=self)
        self._worker.progressed.connect(self.result_label.setText)
        self._worker.done.connect(lambda result, o=operation, p=device: self._finished(o, p, result))
        self._worker.start()

    def _cancel(self) -> None:
        if self._client is not None:
            self._client.cancel()
            self.result_label.setText("Cancelling at the next page, file or chunk…")

    def _finished(self, operation: str, device: Dict[str, Any], result: Any) -> None:
        self.cancel_button.hide()
        self.operation_button.setEnabled(True)
        if isinstance(result, Exception):
            self.result_label.setText(f"{operation} with {device['device_name']} could not run: {result}")
            return
        # The remembered address was silent: the network is asked once, on this thread
        from src.core.discovery import looks_unreachable, find_device_url

        if not result.success and looks_unreachable(list(result.errors)):
            try:
                found = find_device_url(self.db.account_id(), device["device_id"], 3.0)
            except Exception:  # noqa: BLE001
                found = None
            if found is not None and found.urls and found.urls[0].rstrip("/") != (device.get("device_url") or "").rstrip("/"):
                self.config.add_device(device["device_id"], device["device_name"], found.urls[0], found.certificate_fingerprint or None, True)
                self.result_label.setText(f"{device['device_name']} answered from {found.urls[0]}; trying there…")
                self._run(operation, {**device, "device_url": found.urls[0]})
                return
        self.result_label.setText(result_sentence(operation, device["device_name"], result))
        code = refusal_code(list(result.errors))
        if code:
            self._offer_fix(code)
        for warning in getattr(result, "warnings", []) or []:
            self.result_label.setText(self.result_label.text() + f"\n{warning}")
        if self.after_operation is not None:
            self.after_operation()
        self.refresh()

    def _offer_fix(self, code: str) -> None:
        """After a refusal, the button that fixes it (Stage 5)."""
        fix = FIX_FOR_CODE.get(code)
        if fix == "show_code":
            self.fix_button.setText("Show my code")
            self._fix = self._show_code
        elif fix == "check":
            self.fix_button.setText("Check connection")
            self._fix = self._check_connection
        else:
            return
        self.fix_button.show()

    def _check_connection(self) -> None:
        from voicecore import SyncClient

        device = self._selected_device()
        if device is None:
            self.result_label.setText("Choose a device to check.")
            return
        rows = SyncClient(str(self.config.get_config_dir())).check(device["device_id"])
        lines = []
        for row in rows:
            mark = "✓" if row["passed"] else "✗"
            code = f" ({row['code']})" if row["code"] else ""
            lines.append(f"{mark} {row['name']}: {row['detail']}{code}")
        self.result_label.setText("\n".join(lines))

    # ----- encryption (Stage 15)

    def _refresh_encryption(self) -> None:
        """The switch follows the synced setting and stays off until the key was exported here."""
        from voicecore import encryption_state

        try:
            state = encryption_state(str(self.config.get_config_dir()))
        except Exception as e:  # noqa: BLE001
            logger.info(f"Encryption state not read: {e}")
            state = {"has_key": False, "exported": False, "on": False}
        self.encrypt_box.blockSignals(True)
        self.encrypt_box.setChecked(bool(state["on"]))
        self.encrypt_box.setEnabled(bool(state["has_key"] and state["exported"]) or bool(state["on"]))
        self.encrypt_box.blockSignals(False)
        self.encrypt_box.setToolTip("" if state["exported"] else "Export the recording key first")
        self.reupload_button.setEnabled(bool(state["on"] and state["has_key"]))

    def _set_encryption(self, on: bool) -> None:
        from voicecore import set_encryption_on

        try:
            set_encryption_on(on, str(self.config.get_config_dir()))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Not changed", str(e))
        self._refresh_encryption()

    def _export_recording_key(self) -> None:
        """The key as text and a QR code (ENC-1); showing it is the export the switch waits for."""
        from voicecore import recording_key_export

        text = recording_key_export(str(self.config.get_config_dir()))
        dialog = QDialog(self)
        dialog.setWindowTitle("Recording key")
        box = QVBoxLayout(dialog)
        try:
            import io

            import segno

            buffer = io.BytesIO()
            segno.make(text, error="m").save(buffer, kind="png", scale=6)
            pixmap = QPixmap()
            pixmap.loadFromData(buffer.getvalue())
            image = QLabel()
            image.setPixmap(pixmap)
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.addWidget(image)
        except ImportError:
            box.addWidget(QLabel("(install segno to draw the QR code; the text below is the same key)"))
        text_label = QLabel(text)
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(text_label)
        box.addWidget(QLabel("Recording key. Keep this on paper. Without it these recordings cannot be played."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy = buttons.addButton("Copy", QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        dialog.exec()
        self._refresh_encryption()

    def _import_recording_key(self) -> None:
        from voicecore import recording_key_import

        text, ok = QInputDialog.getText(self, "Import the recording key", "The 43 characters from an export:")
        if not ok or not text.strip():
            return
        try:
            recording_key_import(text, str(self.config.get_config_dir()))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Not imported", str(e))
        self._refresh_encryption()

    def _reupload_encrypted(self) -> None:
        """The plain objects' recordings up again encrypted (ENC-3), one at a time, resumable."""
        from voicecore import reupload_encrypted

        try:
            result = reupload_encrypted(str(self.config.get_config_dir()))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Not re-uploaded", str(e))
            return
        self.result_label.setText(f"Re-uploaded encrypted: {result.uploaded}; not on this device: {result.skipped}; failed: {result.failed}" + ("; " + "; ".join(result.errors) if result.errors else ""))

    def _show_code(self) -> None:
        """The code another device reads to join this account (PAIR-1)."""
        from voicecore import listen_addresses, pairing_offer, pairing_withdraw

        from src.core.addresses_text import address_words

        addresses = listen_addresses(self.config.get_sync_server_port())
        urls = addresses["urls"]
        if not urls:
            QMessageBox.warning(self, "No address", addresses["sentence"])
            return
        if self.listen_action is not None and not self.listen_action.isChecked():
            self.listen_action.setChecked(True)
            started_for_code = True
        else:
            started_for_code = False
        text = pairing_offer(urls, str(self.config.get_config_dir()))

        dialog = QDialog(self)
        dialog.setWindowTitle("My code")
        box = QVBoxLayout(dialog)
        try:
            import io

            import segno

            buffer = io.BytesIO()
            segno.make(text, error="m").save(buffer, kind="png", scale=6)
            pixmap = QPixmap()
            pixmap.loadFromData(buffer.getvalue())
            image = QLabel()
            image.setPixmap(pixmap)
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.addWidget(image)
        except ImportError:
            box.addWidget(QLabel("(install segno to draw the QR code; the text below is the same code)"))
        text_label = QLabel(text)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(text_label)
        address_label = QLabel(f"This device's address: {address_words(addresses)}")
        address_label.setWordWrap(True)
        box.addWidget(address_label)
        box.addWidget(QLabel("Treat this like a password: it is valid for ten minutes and for one device."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        dialog.exec()

        pairing_withdraw(str(self.config.get_config_dir()))
        if started_for_code and self.listen_action is not None:
            self.listen_action.setChecked(False)
        self.refresh()

    # ----- the devices

    def _find_on_network(self) -> None:
        """The devices of this account announcing nearby (Stage 7); one can be added."""
        from src.core.discovery import browse

        self.result_label.setText("Listening on the network for three seconds…")
        try:
            found = browse(self.db.account_id(), 3.0)
        except Exception as e:  # noqa: BLE001
            self.result_label.setText(f"Could not browse the network: {e}")
            return
        known = {p["device_id"] for p in self.devices}
        if not found:
            self.result_label.setText("No device of this account is announcing on this network.")
            return
        lines = []
        for entry in found:
            if entry.device_id in known:
                lines.append(f"{entry.name} ({entry.device_id[:UUID_SHORT_LEN]}) at {', '.join(entry.urls)}: already a device")
                continue
            answer = QMessageBox.question(self, "Found on the network", f"{entry.name} ({entry.device_id[:UUID_SHORT_LEN]}) at {', '.join(entry.urls)} is of this account. Add it as a device?")
            if answer == QMessageBox.StandardButton.Yes and entry.urls:
                self.config.add_device(entry.device_id, entry.name or entry.device_id[:UUID_SHORT_LEN], entry.urls[0], entry.certificate_fingerprint or None, True)
                lines.append(f"{entry.name}: added")
            else:
                lines.append(f"{entry.name}: not added")
        self.result_label.setText("\n".join(lines))
        self.refresh()

    def _rename_device(self) -> None:
        device = self._selected_device()
        if device is None:
            return
        name, ok = QInputDialog.getText(self, "Rename device", "The name shown on this device:", text=device["device_name"])
        if ok and name.strip():
            self.config.rename_device(device["device_id"], name.strip())
            self.refresh()

    def _forget_device(self) -> None:
        device = self._selected_device()
        if device is None:
            return
        answer = QMessageBox.question(
            self,
            "Forget device",
            f"Forget {device['device_name']} on this device? Its card will not bring it back; adding it again or pairing again undoes this.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.config.forget_device(device["device_id"])
            self.refresh()

    def _add_device(self) -> None:
        """A device typed by hand (Stage 7, the third way)."""
        device_id, ok = QInputDialog.getText(self, "Add device", "The other device's id (32 hex characters, shown in its About or sync screen):")
        if not ok or not device_id.strip():
            return
        url, ok = QInputDialog.getText(self, "Add device", "Where it listens (https://address:port):")
        if not ok or not url.strip():
            return
        name, ok = QInputDialog.getText(self, "Add device", "A name for it:", text=device_id.strip()[:UUID_SHORT_LEN])
        if not ok:
            return
        try:
            self.config.add_device(device_id.strip(), name.strip() or device_id.strip()[:UUID_SHORT_LEN], url.strip(), None, True)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Not added", str(e))
            return
        self.refresh()

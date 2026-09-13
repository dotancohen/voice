"""The sync dialogue (Stage 5, Stage 10, Stage 12).

One place for everything between this device and the others: the line that
says what is on this device only, the peers with when each was last reached,
one button that names the last peer, the code to show, the connection check,
the listener switch, and this device's own address at the bottom.
"""

from __future__ import annotations

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
    ("send", "Send", "recordings the peer lacks, no sync"),
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


def result_sentence(operation: str, peer_name: str, result: Any) -> str:
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
        return f"{verb} with {peer_name}: {what}.{request}"
    errors = "; ".join(result.errors) if result.errors else "it did not say why"
    return f"{verb} with {peer_name} failed: {errors}.{request}"


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

    def __init__(self, client, method_name: str, peer_id: str, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.method_name = method_name
        self.peer_id = peer_id

    def run(self) -> None:
        self.client.set_progress(lambda stage, done, total, bytes_moved, sentence: self.progressed.emit(sentence))
        try:
            result = getattr(self.client, self.method_name)(self.peer_id)
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

        # Stage 8: the checklist, each row its state and the one button that completes it
        self.checklist_box = QVBoxLayout()
        self.checklist_rows: List[Any] = []
        layout.addLayout(self.checklist_box)

        # Stage 10: the line, here and nowhere else
        self.proof_label = QLabel()
        self.proof_label.setObjectName("proof_label")
        self.proof_label.setAccessibleName("What is on this device only")
        layout.addWidget(self.proof_label)

        # The peers
        self.peers_table = QTableWidget(0, 4)
        self.peers_table.setHorizontalHeaderLabels(["Peer", "Address", "Last reached", "Last operation"])
        self.peers_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.peers_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.peers_table.horizontalHeader().setStretchLastSection(True)
        self.peers_table.setAccessibleName("Peers of this account")
        layout.addWidget(self.peers_table)

        # One visible button, naming the last peer; the arrow chooses another
        # peer or another operation
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
        self.test_all_button = QPushButton("Test everything")
        self.test_all_button.setAccessibleDescription("The connection check against every peer and the bucket, as one table")
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

        peer_actions = QHBoxLayout()
        self.rename_button = QPushButton("Rename…")
        self.rename_button.clicked.connect(self._rename_peer)
        peer_actions.addWidget(self.rename_button)
        self.forget_button = QPushButton("Forget")
        self.forget_button.setAccessibleDescription("Remove the selected peer from this device's list; its card does not bring it back")
        self.forget_button.clicked.connect(self._forget_peer)
        peer_actions.addWidget(self.forget_button)
        self.add_button = QPushButton("Add by address…")
        self.add_button.clicked.connect(self._add_peer)
        peer_actions.addWidget(self.add_button)
        self.find_button = QPushButton("Find on this network")
        self.find_button.setAccessibleDescription("Devices of this account announcing on the local network; a found one can be added as a peer")
        self.find_button.clicked.connect(self._find_on_network)
        peer_actions.addWidget(self.find_button)
        peer_actions.addStretch()
        layout.addLayout(peer_actions)

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
        self.listen_checkbox = QCheckBox("Listen for peers")
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
        """Read everything again: the checklist, the line, the peers, the button, this device."""
        self._refresh_checklist()
        try:
            counts = self.db.not_duplicated(self.config.get_audiofile_directory())
            self.proof_label.setText(not_duplicated_sentence(counts))
        except Exception as e:  # noqa: BLE001 - the dialogue still opens
            self.proof_label.setText(f"Could not count what is on this device only: {e}")

        self.peers = self.config.get_peers()
        summaries = {p["peer_id"]: p for p in self.db.peer_summaries()}
        self.peers_table.setRowCount(len(self.peers))
        for row, peer in enumerate(self.peers):
            summary = summaries.get(peer["peer_id"], {})
            reached = summary.get("last_reached_at")
            self.peers_table.setItem(row, 0, QTableWidgetItem(f"{peer['peer_name']} ({peer['peer_id'][:UUID_SHORT_LEN]})"))
            self.peers_table.setItem(row, 1, QTableWidgetItem(peer.get("peer_url") or "no address yet"))
            self.peers_table.setItem(row, 2, QTableWidgetItem(format_timestamp(reached) if reached else "never"))
            self.peers_table.setItem(row, 3, QTableWidgetItem(summary.get("last_operation") or ""))
        self.peers_table.resizeColumnsToContents()

        self._build_operation_menu()
        self.device_label.setText(self._this_device_text())

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

        StorageWizard(self.db, self.config, listen_action=self.listen_action, parent=self).exec()
        self.refresh()

    def _test_everything(self) -> None:
        """Every peer and the bucket, as one table (Stage 8 step 11)."""
        from src.core.storage_setup import check_everything

        self.result_label.setText("Checking every peer and the bucket…")
        try:
            rows = check_everything(str(self.config.get_config_dir()), self.config, self.db)
        except Exception as e:  # noqa: BLE001
            self.result_label.setText(f"The checks could not run: {e}")
            return
        self.result_label.setText("\n".join(f"{'✓' if r['passed'] else '✗'} {r['name']}: {r['detail']}{' (' + r['code'] + ')' if r.get('code') else ''}" for r in rows) or "Nothing to check yet.")

    def _last_peer(self) -> Optional[Dict[str, Any]]:
        """The peer the visible button names: the last used, else the only one."""
        last = self.config.last_peer_id()
        for peer in self.peers:
            if peer["peer_id"] == last:
                return peer
        return self.peers[0] if len(self.peers) == 1 else None

    def _selected_peer(self) -> Optional[Dict[str, Any]]:
        rows = self.peers_table.selectionModel().selectedRows() if self.peers_table.selectionModel() else []
        if rows:
            return self.peers[rows[0].row()]
        return self._last_peer()

    def _build_operation_menu(self) -> None:
        # A fresh menu each time: clearing one deletes its submenus under us
        old_menu = self.operation_menu
        self.operation_menu = QMenu(self)
        self.submenus = []
        self.operation_button.setMenu(self.operation_menu)
        old_menu.deleteLater()
        peer = self._last_peer()
        if peer is None:
            self.operation_button.setText("Exchange…" if self.peers else "No peer yet: show my code, or read another device's")
            self.operation_button.setEnabled(bool(self.peers))
        else:
            self.operation_button.setText(f"Exchange with {peer['peer_name']}")
            self.operation_button.setEnabled(True)
        self.operation_button.setAccessibleName(self.operation_button.text())
        for other in self.peers:
            submenu = self.operation_menu.addMenu(other["peer_name"])
            self.submenus.append(submenu)
            for operation, label, detail in OPERATIONS:
                action = submenu.addAction(f"{label} — {detail}")
                action.triggered.connect(lambda _checked=False, o=operation, p=other: self._run(o, p))

    def _this_device_text(self) -> str:
        from voicecore import certificate_fingerprint, listen_urls

        port = self.config.get_sync_server_port()
        urls = listen_urls(port)
        try:
            fingerprint = certificate_fingerprint(str(self.config.get_config_dir()))
        except Exception:  # noqa: BLE001
            fingerprint = "(made when the listener first runs)"
        return (
            f"<b>This device:</b> {self.config.get_device_name()} ({self.config.get_device_id_hex()})<br>"
            f"<b>Address:</b> {', '.join(urls) or 'unknown (not on a network?)'}, port {port}<br>"
            f"<b>Certificate:</b> {fingerprint}"
        )

    # ----- operations

    def _run_default(self) -> None:
        peer = self._last_peer()
        if peer is None:
            if self.peers:
                self.operation_button.showMenu()
            return
        self._run("exchange", peer)

    def _run(self, operation: str, peer: Dict[str, Any]) -> None:
        """The operation on a worker thread, with progress and Cancel (Stage 4)."""
        from voicecore import SyncClient

        if self._worker is not None and self._worker.isRunning():
            self.result_label.setText("An operation is under way; cancel it first.")
            return
        self.result_label.setText(f"{dict((k, v) for k, v, _ in OPERATIONS)[operation]} with {peer['peer_name']}…")
        self.fix_button.hide()
        self.cancel_button.show()
        self.operation_button.setEnabled(False)
        self._client = SyncClient(str(self.config.get_config_dir()))
        method_name = {"sync": "sync_with_peer", "deliver": "deliver", "exchange": "exchange", "send": "send_to_peer", "fetch": "fetch_from_peer"}[operation]
        self._worker = OperationWorker(self._client, method_name, peer["peer_id"], parent=self)
        self._worker.progressed.connect(self.result_label.setText)
        self._worker.done.connect(lambda result, o=operation, p=peer: self._finished(o, p, result))
        self._worker.start()

    def _cancel(self) -> None:
        if self._client is not None:
            self._client.cancel()
            self.result_label.setText("Cancelling at the next page, file or chunk…")

    def _finished(self, operation: str, peer: Dict[str, Any], result: Any) -> None:
        self.cancel_button.hide()
        self.operation_button.setEnabled(True)
        if isinstance(result, Exception):
            self.result_label.setText(f"{operation} with {peer['peer_name']} could not run: {result}")
            return
        # The remembered address was silent: the network is asked once, on this thread
        from src.core.discovery import looks_unreachable, find_peer_url

        if not result.success and looks_unreachable(list(result.errors)):
            try:
                found = find_peer_url(self.db.account_id(), peer["peer_id"], 3.0)
            except Exception:  # noqa: BLE001
                found = None
            if found is not None and found.urls and found.urls[0].rstrip("/") != (peer.get("peer_url") or "").rstrip("/"):
                self.config.add_peer(peer["peer_id"], peer["peer_name"], found.urls[0], found.certificate_fingerprint or None, True)
                self.result_label.setText(f"{peer['peer_name']} answered from {found.urls[0]}; trying there…")
                self._run(operation, {**peer, "peer_url": found.urls[0]})
                return
        self.result_label.setText(result_sentence(operation, peer["peer_name"], result))
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

        peer = self._selected_peer()
        if peer is None:
            self.result_label.setText("Choose a peer to check.")
            return
        rows = SyncClient(str(self.config.get_config_dir())).check(peer["peer_id"])
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
        from voicecore import listen_urls, pairing_offer, pairing_withdraw

        urls = listen_urls(self.config.get_sync_server_port())
        if not urls:
            QMessageBox.warning(self, "No address", "This machine's address is not known; is it on a network?")
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
        box.addWidget(QLabel("Treat this like a password: it is valid for ten minutes and for one device."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        dialog.exec()

        pairing_withdraw(str(self.config.get_config_dir()))
        if started_for_code and self.listen_action is not None:
            self.listen_action.setChecked(False)
        self.refresh()

    # ----- the peers

    def _find_on_network(self) -> None:
        """The devices of this account announcing nearby (Stage 7); one can be added."""
        from src.core.discovery import browse

        self.result_label.setText("Listening on the network for three seconds…")
        try:
            found = browse(self.db.account_id(), 3.0)
        except Exception as e:  # noqa: BLE001
            self.result_label.setText(f"Could not browse the network: {e}")
            return
        known = {p["peer_id"] for p in self.peers}
        if not found:
            self.result_label.setText("No device of this account is announcing on this network.")
            return
        lines = []
        for entry in found:
            if entry.device_id in known:
                lines.append(f"{entry.name} ({entry.device_id[:UUID_SHORT_LEN]}) at {', '.join(entry.urls)}: already a peer")
                continue
            answer = QMessageBox.question(self, "Found on the network", f"{entry.name} ({entry.device_id[:UUID_SHORT_LEN]}) at {', '.join(entry.urls)} is of this account. Add it as a peer?")
            if answer == QMessageBox.StandardButton.Yes and entry.urls:
                self.config.add_peer(entry.device_id, entry.name or entry.device_id[:UUID_SHORT_LEN], entry.urls[0], entry.certificate_fingerprint or None, True)
                lines.append(f"{entry.name}: added")
            else:
                lines.append(f"{entry.name}: not added")
        self.result_label.setText("\n".join(lines))
        self.refresh()

    def _rename_peer(self) -> None:
        peer = self._selected_peer()
        if peer is None:
            return
        name, ok = QInputDialog.getText(self, "Rename peer", "The name shown on this device:", text=peer["peer_name"])
        if ok and name.strip():
            self.config.rename_peer(peer["peer_id"], name.strip())
            self.refresh()

    def _forget_peer(self) -> None:
        peer = self._selected_peer()
        if peer is None:
            return
        answer = QMessageBox.question(
            self,
            "Forget peer",
            f"Forget {peer['peer_name']} on this device? Its card will not bring it back; adding it again or pairing again undoes this.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.config.forget_peer(peer["peer_id"])
            self.refresh()

    def _add_peer(self) -> None:
        """A peer typed by hand (Stage 7, the third way)."""
        peer_id, ok = QInputDialog.getText(self, "Add peer", "The other device's id (32 hex characters, shown in its About or sync screen):")
        if not ok or not peer_id.strip():
            return
        url, ok = QInputDialog.getText(self, "Add peer", "Where it listens (https://address:port):")
        if not ok or not url.strip():
            return
        name, ok = QInputDialog.getText(self, "Add peer", "A name for it:", text=peer_id.strip()[:UUID_SHORT_LEN])
        if not ok:
            return
        try:
            self.config.add_peer(peer_id.strip(), name.strip() or peer_id.strip()[:UUID_SHORT_LEN], url.strip(), None, True)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Not added", str(e))
            return
        self.refresh()

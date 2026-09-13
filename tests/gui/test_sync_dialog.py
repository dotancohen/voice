"""GUI tests for the sync dialogue (Stage 5, Stage 10): the line, the peers
and the one button naming the last peer."""

from __future__ import annotations

import pytest

from core.config import Config
from core.database import Database
from ui.sync_dialog import SyncDialog, not_duplicated_sentence, refusal_code, result_sentence

DESK = "0199aaaaaaaa7000800000000000000a"
PHONE = "0199aaaaaaaa7000800000000000000b"


class _Result:
    def __init__(self, success=True, pulled=0, pushed=0, sent=0, fetched=0, bytes_moved=0, errors=None, request_id="abcdef0123456789"):
        self.success, self.pulled, self.pushed, self.sent, self.fetched, self.bytes_moved = success, pulled, pushed, sent, fetched, bytes_moved
        self.errors = errors or []
        self.request_id = request_id
        self.warnings = []


@pytest.mark.gui
class TestSyncDialog:
    def test_the_line_and_the_peers_and_the_button_name_the_last_peer(self, qapp, test_config: Config, empty_db: Database) -> None:
        dialog = SyncDialog(empty_db, test_config)
        assert dialog.proof_label.text() == "Everything is duplicated off this device."
        assert dialog.peers_table.rowCount() == 0
        assert not dialog.operation_button.isEnabled()
        assert "No peer yet" in dialog.operation_button.text()

        empty_db.create_note("רק כאן")
        test_config.add_peer(DESK, "Desk", "https://desk:8384", None, True)
        test_config.add_peer(PHONE, "Phone", "", None, True)
        dialog.refresh()
        assert dialog.proof_label.text() == "1 note and 0 recordings are not duplicated off this device."
        assert dialog.peers_table.rowCount() == 2
        assert dialog.peers_table.item(1, 1).text() == "no address yet"
        assert dialog.peers_table.item(0, 2).text() == "never"
        # Two peers and none used yet: the button asks
        assert dialog.operation_button.text() == "Exchange…"
        assert dialog.operation_button.isEnabled()

        test_config.set_last_peer(DESK)
        dialog.refresh()
        assert dialog.operation_button.text() == "Exchange with Desk"
        # Every peer offers the five operations
        submenus = dialog.submenus
        assert [m.title() for m in submenus] == ["Desk", "Phone"]
        assert len(submenus[0].actions()) == 5
        assert submenus[0].actions()[0].text().startswith("Exchange")

    def test_forgetting_and_renaming_change_the_list(self, qapp, test_config: Config, empty_db: Database, monkeypatch) -> None:
        test_config.add_peer(DESK, "Desk", "https://desk:8384", None, True)
        dialog = SyncDialog(empty_db, test_config)
        dialog.peers_table.selectRow(0)
        monkeypatch.setattr("ui.sync_dialog.QInputDialog.getText", lambda *a, **k: ("Study", True))
        dialog._rename_peer()
        assert test_config.get_peer(DESK)["peer_name"] == "Study"
        assert dialog.peers_table.item(0, 0).text().startswith("Study")

        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr("ui.sync_dialog.QMessageBox.question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        dialog.peers_table.selectRow(0)
        dialog._forget_peer()
        assert test_config.get_peers() == []
        assert test_config.is_forgotten(DESK)
        assert dialog.peers_table.rowCount() == 0

    def test_this_device_is_in_plain_sight(self, qapp, test_config: Config, empty_db: Database) -> None:
        dialog = SyncDialog(empty_db, test_config)
        text = dialog.device_label.text()
        assert test_config.get_device_id_hex() in text
        assert f"port {test_config.get_sync_server_port()}" in text
        assert "Certificate" in text


class TestSentences:
    def test_the_line(self) -> None:
        assert not_duplicated_sentence({"notes": 0, "recordings": 0}) == "Everything is duplicated off this device."
        assert not_duplicated_sentence({"notes": 1, "recordings": 2}) == "1 note and 2 recordings are not duplicated off this device."

    def test_a_result_is_one_sentence_ending_with_the_request(self) -> None:
        sentence = result_sentence("exchange", "Desk", _Result(pulled=12, pushed=3, sent=2, bytes_moved=410 * 1024 * 1024))
        assert sentence == "Exchange with Desk: received 12 changes and sent 3, sent 2 recordings, 410.0 MB moved. Request abcdef0123456789."
        assert result_sentence("send", "Desk", _Result()) == "Send with Desk: nothing to move. Request abcdef0123456789."
        failed = result_sentence("sync", "Desk", _Result(success=False, errors=["This device is not known there (DEVICE_UNKNOWN)"]))
        assert failed.startswith("Sync with Desk failed: This device is not known there (DEVICE_UNKNOWN).")

    def test_the_code_in_a_refusal_names_the_fixing_button(self) -> None:
        assert refusal_code(["Refused (DEVICE_UNKNOWN)"]) == "DEVICE_UNKNOWN"
        assert refusal_code(["The network is down"]) == ""

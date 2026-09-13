"""The bucket wizard (Stage 8, Stage 14): complete for a person who has never
seen the Amazon console. One screen at a time; every failure in words; the
values kept for the session if the window is closed part way; the secret
written nowhere until the final save.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from src.core import storage_setup
from src.core.storage_setup import SetupState

logger = logging.getLogger(__name__)

# The state survives a closed window for the session (Stage 8 step 10)
_SESSION_STATE: Optional[SetupState] = None


def session_state() -> SetupState:
    global _SESSION_STATE
    if _SESSION_STATE is None:
        _SESSION_STATE = SetupState()
    return _SESSION_STATE


def forget_session_state() -> None:
    global _SESSION_STATE
    _SESSION_STATE = None


class _Page(QWizardPage):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.setTitle(title)
        if subtitle:
            self.setSubTitle(subtitle)
        self.box = QVBoxLayout(self)

    def note(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.box.addWidget(label)
        return label


class ConsolePage(_Page):
    """Step 1: where to click, and the policy text with a copy button."""

    def __init__(self, state: SetupState) -> None:
        super().__init__("Make the key", "In the Amazon console, one step at a time. Nothing here costs money.")
        self.state = state
        for n, step in enumerate(storage_setup.CONSOLE_STEPS, 1):
            self.note(f"{n}. {step}")
        self.note("The policy text to paste in step 3. It lets the key make and use buckets named voice-… and nothing else; it cannot delete a recording.")
        self.policy = QPlainTextEdit(storage_setup.policy_text())
        self.policy.setReadOnly(True)
        self.policy.setMaximumHeight(160)
        self.box.addWidget(self.policy)
        copy = QPushButton("Copy the policy text")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.policy.toPlainText()))
        self.box.addWidget(copy)


class KeyPage(_Page):
    """Step 2: paste the key; whitespace and labels are trimmed."""

    def __init__(self, state: SetupState) -> None:
        super().__init__("Paste the key", "The two values from the console. Spaces and a pasted label are removed for you.")
        self.state = state
        self.key_id = QLineEdit(state.access_key_id)
        self.key_id.setPlaceholderText("Access key ID, 20 characters starting with AKIA")
        self.key_id.setAccessibleName("Access key ID")
        self.box.addWidget(self.key_id)
        self.secret = QLineEdit(state.secret_access_key)
        self.secret.setPlaceholderText("Secret access key, 40 characters")
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret.setAccessibleName("Secret access key")
        self.box.addWidget(self.secret)
        self.endpoint = QLineEdit(state.endpoint)
        self.endpoint.setPlaceholderText("Leave empty for Amazon; an https address for DigitalOcean, Backblaze or MinIO")
        self.endpoint.setAccessibleName("Endpoint, for a service other than Amazon")
        self.box.addWidget(self.endpoint)
        self.problem = self.note("")

    def validatePage(self) -> bool:  # noqa: N802 - Qt's name
        self.state.endpoint = self.endpoint.text().strip()
        if self.state.endpoint and not (self.state.endpoint.startswith("https://") or self.state.endpoint.startswith("http://127.0.0.1") or self.state.endpoint.startswith("http://localhost")):
            self.problem.setText("An endpoint is an https address.")
            return False
        problem = storage_setup.take_key(self.state, self.key_id.text(), self.secret.text())
        self.problem.setText(problem or "")
        return problem is None


class RegionPage(_Page):
    """Step 3: a region, the nearest by round-trip time proposed."""

    def __init__(self, state: SetupState) -> None:
        super().__init__("Choose a region", "Where the recordings are kept. The nearest one answers fastest; any works.")
        self.state = state
        self.regions = QComboBox()
        self.regions.setEditable(True)
        self.regions.addItems(storage_setup.regions())
        self.regions.setAccessibleName("Region")
        self.box.addWidget(self.regions)
        self.hint = self.note("")

    def initializePage(self) -> None:  # noqa: N802
        if self.state.region:
            self.regions.setCurrentText(self.state.region)
            return
        if self.state.endpoint:
            self.regions.setCurrentText("us-east-1")
            self.hint.setText("With another service, the region is what its console shows; us-east-1 is accepted by most.")
            return
        nearest = storage_setup.nearest_region()
        if nearest:
            self.regions.setCurrentText(nearest)
            self.hint.setText(f"{nearest} answered fastest from here.")
        else:
            self.hint.setText("No region answered; is this machine on the network?")

    def validatePage(self) -> bool:  # noqa: N802
        self.state.region = self.regions.currentText().strip()
        return bool(self.state.region)


class BucketPage(_Page):
    """Steps 4, 5, 8 and the hardening: make it, prove it, set its rules."""

    def __init__(self, state: SetupState) -> None:
        super().__init__("Make the bucket", "A private bucket with a generated name; change the name if you like.")
        self.state = state
        self.name = QLineEdit(state.bucket or storage_setup.suggest_bucket_name())
        self.name.setAccessibleName("Bucket name")
        self.box.addWidget(self.name)
        self.prefix = QLineEdit(state.prefix)
        self.prefix.setPlaceholderText("A folder inside the bucket, optional")
        self.prefix.setAccessibleName("Prefix")
        self.box.addWidget(self.prefix)
        self.run_button = QPushButton("Make the bucket and test it")
        self.run_button.clicked.connect(self.run)
        self.box.addWidget(self.run_button)
        self.report = self.note("")
        self.done = False

    def run(self) -> None:
        self.state.bucket = self.name.text().strip()
        self.state.prefix = self.prefix.text().strip()
        lines: List[str] = []
        problem = storage_setup.create_bucket(self.state)
        if problem:
            self.report.setText(f"Not made: {problem}")
            self.done = False
            self.completeChanged.emit()
            return
        lines.append(f"✓ Bucket {self.state.bucket} is there and private.")
        for row in storage_setup.harden(self.state):
            lines.append(f"{'✓' if row['passed'] else '✗'} {row['name']}: {row['detail']}")
        problem = storage_setup.set_lifecycle(self.state)
        lines.append("✓ Lifecycle: recordings move to the cheaper class after 30 days; purged ones are deleted a day after; abandoned uploads after two." if not problem else f"✗ Lifecycle: {problem}")
        problem = storage_setup.round_trip(self.state)
        lines.append("✓ A small object was written, read back and compared." if not problem else f"✗ Round trip: {problem}")
        self.done = problem is None
        self.report.setText("\n".join(lines))
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # noqa: N802
        return self.done


class SavePage(_Page):
    """Steps 6 and 9: save through the synced configuration; offer the listener."""

    def __init__(self, state: SetupState, db, listen_action=None) -> None:
        super().__init__("Save", storage_setup.WHAT_THE_BUCKET_HOLDS)
        self.state = state
        self.db = db
        self.listen_action = listen_action
        self.note("The bucket's key is saved as part of the account and reaches every device of the account at its next sync. The phone can upload only after that first sync.")
        self.listen = QCheckBox("Listen for peers now, so the phone can sync and receive the key")
        self.listen.setChecked(True)
        self.listen.setEnabled(listen_action is not None)
        self.box.addWidget(self.listen)
        self.saved = self.note("")

    def validatePage(self) -> bool:  # noqa: N802
        storage_setup.save(self.state, self.db)
        if self.listen.isChecked() and self.listen_action is not None and not self.listen_action.isChecked():
            self.listen_action.setChecked(True)
        return True


class TestEverythingPage(_Page):
    """Step 11: the connection check against every peer and the bucket."""

    def __init__(self, state: SetupState, config_dir: str, config, db) -> None:
        super().__init__("Test everything", "Every peer and the bucket, as one table.")
        self.config_dir, self.config, self.db = config_dir, config, db
        self.table = self.note("")
        self.run_button = QPushButton("Run the checks")
        self.run_button.clicked.connect(self.run)
        self.box.addWidget(self.run_button)

    def run(self) -> None:
        rows = storage_setup.check_everything(self.config_dir, self.config, self.db)
        self.table.setText("\n".join(f"{'✓' if r['passed'] else '✗'} {r['name']}: {r['detail']}{' (' + r['code'] + ')' if r.get('code') else ''}" for r in rows) or "Nothing to check yet.")


class StorageWizard(QWizard):
    """The bucket, from nothing to tested, one screen at a time."""

    def __init__(self, db, config, listen_action=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set up the bucket")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(720, 620)
        self.state = session_state()
        self.addPage(ConsolePage(self.state))
        self.addPage(KeyPage(self.state))
        self.addPage(RegionPage(self.state))
        self.addPage(BucketPage(self.state))
        self.addPage(SavePage(self.state, db, listen_action))
        self.addPage(TestEverythingPage(self.state, str(config.get_config_dir()), config, db))
        self.finished.connect(self._finished)

    def _finished(self, result: int) -> None:
        if self.state.saved:
            forget_session_state()


class ReplaceKeyWizard(QWizard):
    """Stage 14: a new key, tested exactly as the first one, then saved for every device."""

    def __init__(self, db, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Replace the bucket's key")
        self.db = db
        page = _Page("Replace the key", "Make a new key in the console (Users → voice → Security credentials → Create access key), paste it here, then deactivate the old one on the same page.")
        self.key_id = QLineEdit()
        self.key_id.setPlaceholderText("New access key ID")
        page.box.addWidget(self.key_id)
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret.setPlaceholderText("New secret access key")
        page.box.addWidget(self.secret)
        self.problem = page.note("")
        page.validatePage = self._validate  # type: ignore[assignment]
        self.addPage(page)

    def _validate(self) -> bool:
        problem = storage_setup.replace_key(self.db, self.key_id.text(), self.secret.text())
        self.problem.setText(problem or "Saved. Every device gets the new key at its next sync; deactivate the old key in the console.")
        return problem is None

"""The bucket wizard (Stage 8, Stage 14): complete for a person who has never
seen the Amazon console. One step on each page; every text to type into the
console has a copy button beside it; every failure is said in words; the
values are kept for the session if the window is closed part way; the secret
is written nowhere until the final save.

A page whose Next asks the storage service (the key, the region, the bucket)
does that on a thread of its own, with a spinner and "Waiting for a response
from Amazon…" meanwhile, and moves on when the answer is good. The thread
touches no database: the database is used on the window's own thread only.
"""

from __future__ import annotations

import logging
import threading
import weakref
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
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


def copy_icon() -> QIcon:
    """Two overlapping sheets, drawn in the application's own text colour.

    Not the system icon theme's "edit-copy": that icon is drawn for the system's
    light or dark look, not for Voice's, and on Voice's dark theme it was dark
    ink on a dark window. The palette is the theme's (`ui.theme.apply_theme`)."""
    palette = QApplication.palette()
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(palette.windowText().color(), 2.4))
    painter.setBrush(palette.window().color())
    painter.drawRoundedRect(11, 3, 17, 20, 2, 2)
    painter.drawRoundedRect(4, 10, 17, 20, 2, 2)
    painter.end()
    return QIcon(pixmap)


def copy_button(label: str, value_of: Callable[[], str]) -> QToolButton:
    """A button that puts a text on the clipboard and says "Copied" beside itself;
    `value_of` gives the text at the moment of the click."""
    button = QToolButton()
    button.setIcon(copy_icon())
    button.setAutoRaise(True)
    button.setToolTip(f"Copy {label}")
    button.setAccessibleName(f"Copy {label}")

    def copy() -> None:
        QApplication.clipboard().setText(value_of())
        QToolTip.showText(button.mapToGlobal(QPoint(0, button.height())), "Copied", button)

    button.clicked.connect(copy)
    return button


def secret_field(placeholder: str, accessible: str, text: str = "") -> QLineEdit:
    """A password box with an eye button inside it that shows and hides what was typed."""
    field = QLineEdit(text)
    field.setPlaceholderText(placeholder)
    field.setAccessibleName(accessible)
    field.setEchoMode(QLineEdit.EchoMode.Password)
    icon = QIcon.fromTheme("view-reveal-symbolic")
    if icon.isNull():
        icon = QIcon.fromTheme("visibility")
    reveal = QAction(icon, "Show the secret", field)
    reveal.setToolTip("Show the secret")

    def toggle() -> None:
        hidden = field.echoMode() == QLineEdit.EchoMode.Password
        field.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        reveal.setToolTip("Hide the secret" if hidden else "Show the secret")
        reveal.setText("Hide the secret" if hidden else "Show the secret")

    reveal.triggered.connect(toggle)
    field.addAction(reveal, QLineEdit.ActionPosition.TrailingPosition)
    field.reveal_action = reveal  # type: ignore[attr-defined] - reached by the tests
    return field


class _Relay(QObject):
    """Carries a worker thread's result to the window's thread."""

    done = Signal(object)


def _run_job(job: Callable[[], Optional[str]], relay: _Relay) -> None:
    """The worker thread: run a job made of plain values and send its answer.
    The thread holds no window, no database and no configuration, so nothing
    of theirs is ever freed on this thread."""
    try:
        problem = job()
    except Exception as e:  # noqa: BLE001 - said on the page
        logger.warning(f"The wizard's request failed: {e}")
        problem = str(e)
    relay.done.emit(problem)


def deliver_weakly(relay: _Relay, receiver: Callable[[object], None]) -> None:
    """Connect a relay to a bound method through a weak reference to its object,
    so the relay (which a worker thread may hold last) keeps no window alive."""
    owner = weakref.ref(receiver.__self__)  # type: ignore[attr-defined]
    name = receiver.__name__

    def deliver(result: object) -> None:
        target = owner()
        if target is not None:
            getattr(target, name)(result)

    relay.done.connect(deliver)


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

    def console_line(self, words: str, value: Optional[str]) -> None:
        """One line of a console page: the value to type, if any, in bold with
        its copy button right beside it."""
        if value is None:
            self.note(words)
            return
        before, _, after = words.partition("{}")
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        if before.strip():
            layout.addWidget(QLabel(before.rstrip()))
        shown = QLabel(f"<b>{value}</b>")
        shown.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(shown)
        layout.addWidget(copy_button(value, lambda: value))
        if after.strip():
            layout.addWidget(QLabel(after.strip()))
        layout.addStretch(1)
        self.box.addWidget(row)


class _WorkingPage(_Page):
    """A page whose Next asks the storage service first. The work runs on a
    thread of its own while a spinner and a sentence show; a good answer moves
    the wizard on, a problem is said on the page and the page stays."""

    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__(title, subtitle)
        self.busy = False
        self.ready = False
        self._relay = _Relay()
        deliver_weakly(self._relay, self._work_done)
        self.busy_row = QWidget()
        busy_layout = QHBoxLayout(self.busy_row)
        busy_layout.setContentsMargins(0, 0, 0, 0)
        self.spinner = QProgressBar()
        self.spinner.setRange(0, 0)
        self.spinner.setTextVisible(False)
        self.spinner.setMaximumWidth(120)
        self.busy_label = QLabel("")
        busy_layout.addWidget(self.spinner)
        busy_layout.addWidget(self.busy_label, 1)
        self.busy_row.setVisible(False)
        self.problem = QLabel("")
        self.problem.setWordWrap(True)
        self.problem.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def add_status_rows(self) -> None:
        """Put the spinner and the problem line at the bottom of the page."""
        self.box.addStretch(1)
        self.box.addWidget(self.busy_row)
        self.box.addWidget(self.problem)

    # What a page defines
    def endpoint(self) -> str:
        return ""

    def prepare(self) -> Optional[bool]:
        """On the window's thread, before any work: False stops with the problem
        already said, None moves on without asking the service, True asks it."""
        return True

    def job(self) -> Callable[[], Optional[str]]:
        """The request to the service, as a function of plain values only (never
        the page, the database or the configuration): it runs on the worker
        thread and returns a problem sentence, or None."""
        return lambda: None

    def complete_when_idle(self) -> bool:
        return True

    # The mechanism
    def isComplete(self) -> bool:  # noqa: N802 - Qt's name
        return not self.busy and self.complete_when_idle()

    def validatePage(self) -> bool:  # noqa: N802
        if self.ready:
            self.ready = False
            return True
        if self.busy:
            return False
        self.problem.setText("")
        go = self.prepare()
        if go is None:
            return True
        if not go:
            return False
        self.busy = True
        self.busy_label.setText(storage_setup.waiting_sentence(self.endpoint()))
        self.busy_row.setVisible(True)
        self._enable_back(False)
        self.completeChanged.emit()
        threading.Thread(target=_run_job, args=(self.job(), self._relay), daemon=True).start()
        return False

    def _work_done(self, problem: Optional[str]) -> None:
        self.busy = False
        self.busy_row.setVisible(False)
        self._enable_back(True)
        self.completeChanged.emit()
        if problem:
            self.problem.setText(problem)
            return
        self.ready = True
        wizard = self.wizard()
        if wizard is None:
            return
        if wizard.nextId() != -1:
            wizard.next()
        elif wizard.currentPage() is self and wizard.validateCurrentPage():
            # The last page: its Next is Finish
            wizard.accept()

    def _enable_back(self, on: bool) -> None:
        wizard = self.wizard()
        if wizard is not None and wizard.button(QWizard.WizardButton.BackButton) is not None:
            wizard.button(QWizard.WizardButton.BackButton).setEnabled(on)


class KeyBoxes:
    """The two boxes of a key on a page, each checked for its form as it is
    typed, with a line under each saying what is wrong or that it is right."""

    def __init__(self, page: QWizardPage, box: QVBoxLayout, state: SetupState, endpoint_of: Callable[[], str]) -> None:
        # Weak, and `endpoint_of` must not hold the page either: a cycle through
        # a page that holds the database is freed by the collector on whatever
        # thread runs it, and the database may only be closed on its own
        self.page = weakref.ref(page)
        self.endpoint_of = endpoint_of
        self.key_id = QLineEdit(state.access_key_id)
        self.key_id.setPlaceholderText("Access key: 20 capital letters and digits, starting with AKIA")
        self.key_id.setAccessibleName("Access key ID")
        box.addWidget(self.key_id)
        self.key_verdict = QLabel("")
        self.key_verdict.setWordWrap(True)
        box.addWidget(self.key_verdict)
        self.secret = secret_field("Secret access key: 40 characters", "Secret access key", state.secret_access_key)
        box.addWidget(self.secret)
        self.secret_verdict = QLabel("")
        self.secret_verdict.setWordWrap(True)
        box.addWidget(self.secret_verdict)
        self.key_id.textChanged.connect(self.recheck)
        self.secret.textChanged.connect(self.recheck)

    def recheck(self, *_args) -> None:
        endpoint = self.endpoint_of()
        for field, verdict, check, right in (
            (self.key_id, self.key_verdict, storage_setup.key_id_problem, "The access key has the right form."),
            (self.secret, self.secret_verdict, storage_setup.secret_problem, "The secret access key has the right form."),
        ):
            if not field.text():
                verdict.setText("")
                continue
            problem = check(field.text(), endpoint)
            verdict.setText(f"✗ {problem}" if problem else f"✓ {right}")
        page = self.page()
        if page is not None:
            page.completeChanged.emit()

    def complete(self) -> bool:
        endpoint = self.endpoint_of()
        return (
            storage_setup.key_id_problem(self.key_id.text(), endpoint) is None
            and storage_setup.secret_problem(self.secret.text(), endpoint) is None
        )


class ConsoleStepPage(_Page):
    """One step in the Amazon console: short lines, a copy button beside every
    value to type, and on the policy step the policy text with its own button."""

    def __init__(self, number: int, title: str, lines: List[storage_setup.ConsoleLine], with_policy: bool = False) -> None:
        super().__init__(f"{number}. {title}", "In the Amazon console. Nothing here costs money.")
        for words, value in lines:
            self.console_line(words, value)
        self.policy: Optional[QPlainTextEdit] = None
        if with_policy:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(QLabel("The policy text:"))
            policy_text = storage_setup.policy_text()
            self.copy_policy = copy_button("the policy text", lambda: policy_text)
            layout.addWidget(self.copy_policy)
            layout.addStretch(1)
            self.box.addWidget(row)
            self.policy = QPlainTextEdit(policy_text)
            self.policy.setReadOnly(True)
            self.policy.setAccessibleName("Policy text")
            self.box.addWidget(self.policy, 1)
            self.note("It lets the key make and use buckets named voice-… and nothing else: write, read, tag and delete an object in them, never delete a bucket.")
        self.box.addStretch(1)


class KeyPage(_WorkingPage):
    """Step 5: the key the console shows, checked as it is typed; Next asks the
    service which region accepts it."""

    def __init__(self, number: int, title: str, lines: List[storage_setup.ConsoleLine], state: SetupState) -> None:
        super().__init__(f"{number}. {title}")
        self.state = state
        for words, value in lines:
            self.console_line(words, value)
        self.other = QCheckBox("A service other than Amazon (DigitalOcean, Backblaze, Hetzner, MinIO)")
        self.endpoint_box = QLineEdit(state.endpoint)
        self.endpoint_box.setPlaceholderText("The service's https address")
        self.endpoint_box.setAccessibleName("Endpoint, for a service other than Amazon")
        self.keys = KeyBoxes(self, self.box, state, self.endpoint_text)
        self.box.addWidget(self.other)
        self.box.addWidget(self.endpoint_box)
        self.other.setChecked(bool(state.endpoint))
        self.endpoint_box.setVisible(bool(state.endpoint))
        self.other.toggled.connect(self._other)
        self.endpoint_box.textChanged.connect(self.keys.recheck)
        self.add_status_rows()
        self.keys.recheck()

    def endpoint_text(self) -> str:
        return self.endpoint_box.text().strip() if self.other.isChecked() else ""

    def endpoint(self) -> str:
        return self.state.endpoint

    def _other(self, on: bool) -> None:
        self.endpoint_box.setVisible(on)
        self.keys.recheck()

    def complete_when_idle(self) -> bool:
        return self.keys.complete()

    def prepare(self) -> Optional[bool]:
        self.state.endpoint = self.endpoint_text()
        if self.state.endpoint and not (self.state.endpoint.startswith("https://") or self.state.endpoint.startswith("http://127.0.0.1") or self.state.endpoint.startswith("http://localhost")):
            self.problem.setText("An endpoint is an https address.")
            return False
        problem = storage_setup.take_key(self.state, self.keys.key_id.text(), self.keys.secret.text())
        if problem:
            self.problem.setText(problem)
            return False
        # Another service's regions are what its console shows; nothing to measure
        return None if self.state.endpoint else True

    def job(self) -> Callable[[], Optional[str]]:
        state = self.state

        def find_region() -> Optional[str]:
            nearest = storage_setup.nearest_region(state)
            state.nearest = nearest or ""
            if not nearest:
                return "No region accepted the key. Is this computer on the network? A key made a moment ago can take a minute to work."
            return None

        return find_region


class RegionPage(_WorkingPage):
    """Step 6: the region, the nearest one that accepts the key proposed; Next
    finds a bucket name no other bucket has."""

    def __init__(self, number: int, state: SetupState) -> None:
        super().__init__(f"{number}. Choose the region", "Where the recordings are kept. The nearest one answers fastest; any that accepts the key works.")
        self.state = state
        self.regions = QComboBox()
        self.regions.setEditable(True)
        self.regions.addItems(storage_setup.regions())
        self.regions.setAccessibleName("Region")
        self.box.addWidget(self.regions)
        self.hint = self.note("")
        self.refusal = self.note("")
        self.regions.currentTextChanged.connect(self._chosen)
        self.add_status_rows()

    def endpoint(self) -> str:
        return self.state.endpoint

    def initializePage(self) -> None:  # noqa: N802
        if self.state.region:
            self.regions.setCurrentText(self.state.region)
        elif self.state.endpoint:
            self.regions.setCurrentText("us-east-1")
            self.hint.setText(f"With {storage_setup.provider_name(self.state.endpoint)}, the region is the one its console shows; us-east-1 is accepted by most.")
        elif self.state.nearest:
            self.regions.setCurrentText(self.state.nearest)
            self.hint.setText(f"{self.state.nearest} is the nearest region that accepts this key.")
        self._chosen(self.regions.currentText())

    def _chosen(self, region: str) -> None:
        # Explained only when the user picks such a region
        if region.strip() in self.state.regions_refused:
            self.refusal.setText(f"{region.strip()} does not accept this key: the region is not switched on for the Amazon account.")
        else:
            self.refusal.setText("")
        self.completeChanged.emit()

    def complete_when_idle(self) -> bool:
        region = self.regions.currentText().strip()
        return bool(region) and region not in self.state.regions_refused

    def prepare(self) -> Optional[bool]:
        self.state.region = self.regions.currentText().strip()
        return None if self.state.bucket else True

    def job(self) -> Callable[[], Optional[str]]:
        state = self.state
        return lambda: storage_setup.choose_free_bucket(state)


def make_bucket(state: SetupState) -> Optional[str]:
    """Make the bucket private, harden it, set its rules and prove it with a
    round trip; the lines of what was found go into `state.report`. Returns a
    problem sentence, or None."""
    lines: List[str] = []
    problem = storage_setup.create_bucket(state)
    if problem:
        return f"Not made: {problem}"
    if state.renamed_from:
        lines.append(f"Another account already has a bucket named {state.renamed_from}, so this bucket is named {state.bucket}.")
    lines.append(f"✓ Bucket {state.bucket} is there and private.")
    for row in storage_setup.harden(state):
        lines.append(f"{'✓' if row['passed'] else '✗'} {row['name']}: {row['detail']}")
    problem = storage_setup.set_lifecycle(state)
    lines.append("✓ Lifecycle: recordings move to the cheaper class after 30 days; purged ones are deleted a day after; abandoned uploads after two." if not problem else f"✗ Lifecycle: {problem}")
    problem = storage_setup.round_trip(state)
    if problem:
        return "\n".join(lines + [f"✗ The test of the bucket failed: {problem}"])
    lines.append("✓ A small object was written, read back and compared.")
    state.report = lines
    return None


class BucketPage(_WorkingPage):
    """Step 7: Next makes the bucket private, hardens it, sets its rules and
    proves it with a round trip. The name is a free generated one; a name and a
    folder of the user's own are offered under "Custom bucket name and folder"."""

    def __init__(self, number: int, state: SetupState) -> None:
        super().__init__(f"{number}. Make the bucket", "Next makes a private bucket and tests it.")
        self.state = state
        self.name_line = self.note("")
        self.custom = QCheckBox("Custom bucket name and folder")
        self.box.addWidget(self.custom)
        self.name = QLineEdit(state.bucket)
        self.name.setAccessibleName("Bucket name")
        self.name.setPlaceholderText("A bucket name starting with voice-")
        self.prefix = QLineEdit(state.prefix)
        self.prefix.setPlaceholderText("A folder inside the bucket, optional")
        self.prefix.setAccessibleName("Folder inside the bucket")
        self.box.addWidget(self.name)
        self.box.addWidget(self.prefix)
        self.custom.setChecked(state.bucket_chosen)
        self.custom.toggled.connect(self._custom)
        self.add_status_rows()
        self._custom(state.bucket_chosen)

    def endpoint(self) -> str:
        return self.state.endpoint

    def initializePage(self) -> None:  # noqa: N802
        self.name_line.setText(f"Bucket name: <b>{self.state.bucket}</b>")
        if not self.custom.isChecked():
            self.name.setText(self.state.bucket)

    def _custom(self, on: bool) -> None:
        self.name.setVisible(on)
        self.prefix.setVisible(on)
        self.name_line.setVisible(not on)
        self.completeChanged.emit()

    def complete_when_idle(self) -> bool:
        return bool(self.name.text().strip()) if self.custom.isChecked() else bool(self.state.bucket)

    def prepare(self) -> Optional[bool]:
        if self.custom.isChecked():
            typed = self.name.text().strip()
            problem = storage_setup.bucket_name_problem(typed)
            if problem:
                self.problem.setText(problem)
                return False
            if typed != self.state.bucket:
                self.state.bucket_chosen = True
            self.state.bucket = typed
            self.state.prefix = self.prefix.text().strip()
        return True

    def job(self) -> Callable[[], Optional[str]]:
        return lambda state=self.state: make_bucket(state)


class ReadyPage(_Page):
    """Step 8: what making the bucket found; Next saves it for every device."""

    def __init__(self, number: int, state: SetupState, db) -> None:
        super().__init__(f"{number}. The bucket is ready", "Next saves it for every device of the account.")
        self.state = state
        self.db = db
        self.lines = self.note("")
        self.box.addStretch(1)

    def initializePage(self) -> None:  # noqa: N802
        self.lines.setText("\n".join(self.state.report))

    def validatePage(self) -> bool:  # noqa: N802
        storage_setup.save(self.state, self.db)
        return True


class SyncPage(_Page):
    """The last page: what the bucket does not hold, and sync between devices."""

    def __init__(self, state: SetupState, offer_sync: bool) -> None:
        super().__init__("Sync between devices")
        self.state = state
        self.sentence = self.note("")
        self.set_up_sync = QCheckBox("Set up sync now")
        self.set_up_sync.setChecked(True)
        self.set_up_sync.setVisible(offer_sync)
        self.box.addWidget(self.set_up_sync)
        self.box.addStretch(1)
        self.offer_sync = offer_sync

    def initializePage(self) -> None:  # noqa: N802
        question = " Set up sync now?" if self.offer_sync else ""
        self.sentence.setText(storage_setup.stores_files_sentence(self.state.endpoint) + question)


class StorageWizard(QWizard):
    """The bucket, from nothing to tested and saved, one step on each page."""

    def __init__(self, db, config, offer_sync: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set up the bucket")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(760, 600)
        self.state = session_state()
        user_name, policy_name = storage_setup.console_names()
        self.user_name, self.policy_name = user_name, policy_name
        pages = storage_setup.console_pages(user_name, policy_name)
        for number, (title, lines) in enumerate(pages[:-1], 1):
            self.addPage(ConsoleStepPage(number, title, lines, with_policy=number == storage_setup.POLICY_STEP))
        key_number = len(pages)
        self.key_page = KeyPage(key_number, pages[-1][0], pages[-1][1], self.state)
        self.addPage(self.key_page)
        self.region_page = RegionPage(key_number + 1, self.state)
        self.addPage(self.region_page)
        self.bucket_page = BucketPage(key_number + 2, self.state)
        self.addPage(self.bucket_page)
        self.ready_page = ReadyPage(key_number + 3, self.state, db)
        self.addPage(self.ready_page)
        self.sync_page = SyncPage(self.state, offer_sync)
        self.addPage(self.sync_page)
        self.finished.connect(self._finished)

    def set_up_sync_now(self) -> bool:
        """Whether the user asked, on the last page, to set up sync now."""
        return self.sync_page.offer_sync and self.sync_page.set_up_sync.isChecked()

    def _finished(self, result: int) -> None:
        if self.state.saved:
            forget_session_state()


class ReplaceKeyPage(_WorkingPage):
    """Stage 14: the new key's boxes, checked as they are typed; Next tests the
    key on the bucket exactly as the first run did, then saves it."""

    def __init__(self, db) -> None:
        super().__init__(
            "Replace the key",
            "In the Amazon console: IAM Users → the bucket's user (voice-NNNN) → Security credentials → Create access key. "
            "Enter the new key here; after it is saved, deactivate the old key on the same console page.",
        )
        self.db = db
        saved = storage_setup.saved_state(db)
        endpoint = saved.endpoint if saved else ""
        self.keys = KeyBoxes(self, self.box, SetupState(endpoint=endpoint), lambda: endpoint)
        self.saved_line = self.note("")
        self.add_status_rows()
        self._trial: Optional[SetupState] = None

    def endpoint(self) -> str:
        return self._trial.endpoint if self._trial else ""

    def complete_when_idle(self) -> bool:
        return self.keys.complete()

    def prepare(self) -> Optional[bool]:
        # The database is read here, on the window's thread; the test runs without it
        trial = storage_setup.saved_state(self.db)
        if trial is None:
            self.problem.setText("No bucket is configured yet; run the wizard first.")
            return False
        problem = storage_setup.take_key(trial, self.keys.key_id.text(), self.keys.secret.text())
        if problem:
            self.problem.setText(problem)
            return False
        self._trial = trial
        return True

    def job(self) -> Callable[[], Optional[str]]:
        trial = self._trial
        return lambda: storage_setup.round_trip(trial) if trial else "Nothing to test"

    def validatePage(self) -> bool:  # noqa: N802
        moving_on = super().validatePage()
        if moving_on and self._trial is not None:
            storage_setup.save(self._trial, self.db)
            self.saved_line.setText("Saved. Every device gets the new key at its next sync; deactivate the old key in the console.")
        return moving_on


class ReplaceKeyWizard(QWizard):
    """Stage 14: a new key, tested exactly as the first one, then saved for every device."""

    def __init__(self, db, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Replace the bucket's key")
        self.db = db
        self.page_ = ReplaceKeyPage(db)
        self.addPage(self.page_)

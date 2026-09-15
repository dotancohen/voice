"""GUI tests for the bucket wizard (Stage 8, Stage 14) and for Test all syncing
paths: one step on each page, a copy button beside every value to type, the key
checked as it is typed, Next asking the service in the background with a
spinner and a sentence naming the service, the nearest region said alone and a
refused region explained only when chosen, the bucket's name and folder offered
as boxes only under "Custom bucket name and folder", and the last page's
sentence about what the service stores."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QToolButton, QWidget

from core import storage_setup
from core.database import Database
from core.storage_setup import SetupState
from tests.fake_s3 import TEST_KEY_ID as KEY_ID
from tests.fake_s3 import TEST_SECRET as SECRET
from tests.fake_s3 import FakeS3
from ui import storage_wizard
from ui.storage_wizard import BucketPage, KeyPage, ReadyPage, RegionPage, ReplaceKeyWizard, StorageWizard, SyncPage
from ui.sync_paths_dialog import SyncPathsDialog


@pytest.fixture
def s3():
    fake = FakeS3(KEY_ID, SECRET).start()
    yield fake
    fake.stop()


def new_wizard(test_config, db) -> StorageWizard:
    storage_wizard.forget_session_state()
    return StorageWizard(db, test_config)


def key_page(state: SetupState) -> KeyPage:
    title, lines = storage_setup.console_pages("voice-1234", "Voice-Recordings-1234")[-1]
    return KeyPage(5, title, lines, state)


def texts_of(widget: QWidget) -> list:
    found = []
    for child in widget.findChildren(QWidget):
        text = getattr(child, "text", None)
        if callable(text):
            found.append(text())
    return found


@pytest.mark.gui
class TestTheConsolePages:
    def test_each_step_is_a_page_and_every_value_has_a_copy_button_beside_it(self, qapp, test_config, empty_db: Database) -> None:
        wizard = new_wizard(test_config, empty_db)
        titles = [wizard.page(page_id).title() for page_id in wizard.pageIds()]
        assert titles == [
            "1. Open the Amazon console", "2. Make the policy", "3. Make the user", "4. Make the access key",
            "5. Enter the key", "6. Choose the region", "7. Make the bucket", "8. The bucket is ready", "Sync between devices",
        ]
        copied = set()
        for page_id in wizard.pageIds()[:4]:
            for button in wizard.page(page_id).findChildren(QToolButton):
                button.click()
                copied.add(QApplication.clipboard().text())
        assert copied == {storage_setup.CONSOLE_URL, wizard.user_name, wizard.policy_name, storage_setup.policy_text()}
        assert wizard.user_name.startswith("voice-") and wizard.policy_name.endswith(wizard.user_name[-4:])

    def test_no_page_says_peer_or_carries_a_make_or_test_button(self, qapp, test_config, empty_db: Database) -> None:
        wizard = new_wizard(test_config, empty_db)
        words = []
        for page_id in wizard.pageIds():
            page = wizard.page(page_id)
            words += [page.title(), page.subTitle()] + texts_of(page)
            assert not page.findChildren(QPushButton), f"Next is the only button on {page.title()}"
        joined = " ".join(words).lower()
        # The owner: "Don't use the word peer - use the word Device"
        assert "peer" not in joined
        assert "every device and the bucket" not in joined and "yours to make" not in joined


@pytest.mark.gui
class TestTheKeyPage:
    def test_the_key_is_checked_as_it_is_typed_and_next_waits_for_both(self, qapp) -> None:
        page = key_page(SetupState())
        assert not page.isComplete()
        page.keys.key_id.setText("akiaiosfodnn7example")
        assert page.keys.key_verdict.text().startswith("✗") and "small letters" in page.keys.key_verdict.text()
        page.keys.key_id.setText(KEY_ID[:-1])
        assert "19 characters" in page.keys.key_verdict.text()
        page.keys.key_id.setText(f"  {KEY_ID} ")
        assert page.keys.key_verdict.text() == "✓ The access key has the right form."
        assert not page.isComplete(), "the secret is still empty"
        page.keys.secret.setText(SECRET + "!")
        assert page.keys.secret_verdict.text().startswith("✗")
        page.keys.secret.setText(SECRET)
        assert page.keys.secret_verdict.text() == "✓ The secret access key has the right form."
        assert page.isComplete()

    def test_the_secret_is_hidden_until_the_eye_is_pressed(self, qapp) -> None:
        page = key_page(SetupState())
        secret: QLineEdit = page.keys.secret
        assert secret.echoMode() == QLineEdit.EchoMode.Password
        secret.reveal_action.trigger()
        assert secret.echoMode() == QLineEdit.EchoMode.Normal
        secret.reveal_action.trigger()
        assert secret.echoMode() == QLineEdit.EchoMode.Password

    def test_another_service_s_key_is_not_held_to_amazon_s_form_and_needs_no_waiting(self, qapp) -> None:
        state = SetupState()
        page = key_page(state)
        page.keys.key_id.setText("DO00ה-key")
        page.keys.secret.setText("short")
        assert not page.isComplete()
        page.other.setChecked(True)
        assert page.endpoint_box.isVisibleTo(page)
        page.endpoint_box.setText("https://fra1.digitaloceanspaces.com")
        assert page.isComplete()
        assert page.validatePage(), "another service's regions are not measured: Next moves on at once"
        assert state.endpoint == "https://fra1.digitaloceanspaces.com" and state.secret_access_key == "short"


@pytest.mark.gui
class TestTheRegionPage:
    def test_only_the_nearest_region_is_said_and_a_refused_one_is_explained_when_chosen(self, qapp) -> None:
        state = SetupState(access_key_id=KEY_ID, secret_access_key=SECRET, nearest="eu-west-2", regions_refused=["il-central-1"])
        page = RegionPage(6, state)
        page.initializePage()
        assert page.hint.text() == "eu-west-2 is the nearest region that accepts this key."
        assert page.refusal.text() == ""
        assert page.isComplete()
        page.regions.setCurrentText("il-central-1")
        assert page.refusal.text() == "il-central-1 does not accept this key: the region is not switched on for the Amazon account."
        assert not page.isComplete(), "a region that refuses the key is not a choice"
        page.regions.setCurrentText("eu-west-2")
        assert page.refusal.text() == "" and page.isComplete()

    def test_next_waits_for_the_service_with_a_spinner_and_finds_a_free_bucket_name(self, qapp, qtbot, s3: FakeS3) -> None:
        state = SetupState(endpoint=s3.endpoint, access_key_id=KEY_ID, secret_access_key=SECRET)
        page = RegionPage(6, state)
        page.initializePage()
        assert page.regions.currentText() == "us-east-1"
        assert not page.validatePage(), "Next waits for the answer"
        assert page.busy and page.busy_row.isVisibleTo(page) and not page.isComplete()
        assert page.busy_label.text() == "Waiting for a response from 127.0.0.1…"
        qtbot.waitUntil(lambda: not page.busy, timeout=15000)
        assert page.ready, page.problem.text()
        assert not page.busy_row.isVisibleTo(page)
        assert state.bucket.startswith("voice-") and state.region == "us-east-1"
        assert page.validatePage(), "the answer is in: Next moves on"


@pytest.mark.gui
class TestTheBucketPage:
    def test_the_name_is_said_and_boxes_appear_only_for_a_custom_name_and_folder(self, qapp) -> None:
        page = BucketPage(7, SetupState(bucket="voice-92890c"))
        page.initializePage()
        assert page.name_line.text() == "Bucket name: <b>voice-92890c</b>" and page.name_line.isVisibleTo(page)
        assert not page.name.isVisibleTo(page) and not page.prefix.isVisibleTo(page)
        assert page.custom.text() == "Custom bucket name and folder"
        page.custom.setChecked(True)
        assert page.name.isVisibleTo(page) and page.prefix.isVisibleTo(page) and not page.name_line.isVisibleTo(page)
        assert page.name.text() == "voice-92890c"

    def test_next_makes_and_tests_the_bucket_and_a_taken_generated_name_is_replaced(self, qapp, qtbot, s3: FakeS3) -> None:
        state = SetupState(region="us-east-1", endpoint=s3.endpoint, access_key_id=KEY_ID, secret_access_key=SECRET)
        assert storage_setup.choose_free_bucket(state) is None
        taken = state.bucket
        s3.taken_names.add(taken)
        page = BucketPage(7, state)
        page.initializePage()
        assert not page.validatePage()
        assert page.busy_label.text().startswith("Waiting for a response from")
        qtbot.waitUntil(lambda: not page.busy, timeout=30000)
        assert page.ready, page.problem.text()
        assert state.bucket != taken and state.bucket in s3.buckets
        assert any(f"already has a bucket named {taken}" in line for line in state.report)
        assert state.report[-1] == "✓ A small object was written, read back and compared."

    def test_a_taken_custom_name_is_refused_in_words_and_the_page_stays(self, qapp, qtbot, s3: FakeS3) -> None:
        s3.taken_names.add("voice-mine01")
        state = SetupState(region="us-east-1", endpoint=s3.endpoint, access_key_id=KEY_ID, secret_access_key=SECRET, bucket="voice-generated1")
        page = BucketPage(7, state)
        page.initializePage()
        page.custom.setChecked(True)
        page.name.setText("voice-mine01")
        page.prefix.setText("הקלטות")
        assert not page.validatePage()
        qtbot.waitUntil(lambda: not page.busy, timeout=30000)
        assert not page.ready
        assert page.problem.text().startswith("Not made: The bucket name voice-mine01 is taken"), page.problem.text()
        assert state.prefix == "הקלטות"


@pytest.mark.gui
class TestTheLastPages:
    def test_the_ready_page_lists_what_was_found_and_next_saves(self, qapp, empty_db: Database) -> None:
        state = SetupState(bucket="voice-abc123", region="us-east-1", access_key_id=KEY_ID, secret_access_key=SECRET, report=["✓ Bucket voice-abc123 is there and private."])
        page = ReadyPage(8, state, empty_db)
        page.initializePage()
        assert "voice-abc123 is there" in page.lines.text()
        assert page.validatePage() and state.saved
        assert storage_setup.saved_state(empty_db).bucket == "voice-abc123"

    def test_the_last_page_says_what_the_service_stores_and_offers_to_set_up_sync(self, qapp) -> None:
        for endpoint, name in [
            ("", "Amazon"),
            ("https://fra1.digitaloceanspaces.com", "DigitalOcean"),
            ("https://s3.us-west-004.backblazeb2.com", "Backblaze"),
            ("https://fsn1.your-objectstorage.com", "Hetzner"),
        ]:
            page = SyncPage(SetupState(endpoint=endpoint), offer_sync=True)
            page.initializePage()
            assert page.sentence.text() == f"{name} stores files only, not notes' content. For full note syncing, be sure to configure sync between devices. Set up sync now?"
            assert page.set_up_sync.isChecked() and page.set_up_sync.text() == "Set up sync now"
        inside = SyncPage(SetupState(), offer_sync=False)
        inside.initializePage()
        assert not inside.set_up_sync.isVisibleTo(inside) and not inside.sentence.text().endswith("?")


@pytest.mark.gui
class TestReplacingTheKey:
    def test_the_new_key_is_checked_as_it_is_typed_then_tested_on_the_bucket_and_saved(self, qapp, qtbot, s3: FakeS3, empty_db: Database) -> None:
        state = SetupState(region="us-east-1", bucket="voice-abc123", endpoint=s3.endpoint)
        assert storage_setup.take_key(state, KEY_ID, SECRET) is None and storage_setup.create_bucket(state) is None
        storage_setup.save(state, empty_db)
        wizard = ReplaceKeyWizard(empty_db)
        qtbot.addWidget(wizard)
        wizard.show()
        page = wizard.page_
        assert "voice-NNNN" in page.subTitle()
        # The saved bucket is on another service, whose keys have no form to check
        # beyond being there: an empty key is refused for every service
        page.keys.key_id.setText("")
        page.keys.secret.setText(SECRET)
        assert not page.isComplete()
        page.keys.key_id.setText(KEY_ID)
        assert page.isComplete()
        assert not page.validatePage(), "the key is tested first"
        assert page.busy_label.text() == "Waiting for a response from 127.0.0.1…"
        qtbot.waitUntil(lambda: page.saved_line.text().startswith("Saved."), timeout=15000)
        assert page.problem.text() == ""


@pytest.mark.gui
class TestAllSyncingPaths:
    def test_the_paths_are_tested_in_the_background_and_shown_as_a_table(self, qapp, qtbot, test_config) -> None:
        dialog = SyncPathsDialog(test_config)
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() == "Test all syncing paths"
        assert dialog.busy and dialog.busy_row.isVisibleTo(dialog)
        qtbot.waitUntil(lambda: not dialog.busy, timeout=30000)
        assert dialog.table.rowCount() >= 1
        assert {dialog.table.item(row, 1).text() for row in range(dialog.table.rowCount())} == {"Bucket"}, "no other device yet: the bucket's rows only"
        assert "peer" not in " ".join(texts_of(dialog)).lower()


@pytest.mark.gui
class TestTheCopyIcon:
    @pytest.mark.parametrize("theme", ["dark", "light"])
    def test_the_copy_icon_s_ink_stands_out_from_the_window_in_either_theme(self, qapp, theme: str) -> None:
        """The icon was the system icon theme's, drawn for a light window, and
        could not be seen on Voice's dark theme."""
        from ui.theme import apply_theme

        sheet, palette = qapp.styleSheet(), qapp.palette()
        try:
            apply_theme(qapp, theme)
            window = qapp.palette().window().color()
            image = storage_wizard.copy_button("the policy text", lambda: "").icon().pixmap(32, 32).toImage()
            opaque = [image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height()) if image.pixelColor(x, y).alpha() > 200]
            assert opaque, "the icon draws something"
            gap = max(abs(color.lightness() - window.lightness()) for color in opaque)
            assert gap > 120, f"on the {theme} theme the icon's ink is {gap} lightness steps from the window (of 255)"
        finally:
            qapp.setStyleSheet(sheet)
            qapp.setPalette(palette)

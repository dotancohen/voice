"""The Issues window (ISSUE-1)."""

from __future__ import annotations

import pytest

from core.database import Database
from ui.issues_dialog import IssuesDialog


@pytest.mark.gui
class TestIssuesDialog:
    def test_nothing_to_report_says_so(self, qapp, empty_db: Database, test_config) -> None:
        dialog = IssuesDialog(empty_db, test_config)
        assert dialog.tree.topLevelItemCount() == 0
        assert dialog.summary.text() == "Nothing needs your attention."

    def test_each_kind_is_a_section_with_its_lines(self, qapp, empty_db: Database, test_config) -> None:
        spaced = empty_db.create_tag("פגישת צוות", None)
        empty_db.create_audio_file("בלי פתק.ogg", 1735689600)
        dialog = IssuesDialog(empty_db, test_config)
        titles = [dialog.tree.topLevelItem(i).text(0) for i in range(dialog.tree.topLevelItemCount())]
        assert titles == ["Recordings not in cloud storage (1)", "Recordings no note holds (1)", "Tags whose names contain spaces (1)"]
        tags = dialog.tree.topLevelItem(2)
        assert tags.child(0).text(0) == "פגישת צוות"
        assert dialog.summary.text() == "3 things need your attention."

        empty_db.delete_tag(spaced)
        dialog.reload()
        assert dialog.tree.topLevelItemCount() == 2, "an issue dealt with is gone at the next look"

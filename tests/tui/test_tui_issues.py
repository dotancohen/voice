"""The Issues screen of the text interface (ISSUE-1): F8 opens it."""

from __future__ import annotations

import pytest

from src.core.config import Config
from src.core.database import Database
from src.tui import IssuesScreen, VoiceTUI

pytestmark = pytest.mark.tui


class TestIssuesScreen:
    async def test_f8_opens_the_issues_and_lists_a_tag_with_a_space(self, populated_db: Database, test_config: Config) -> None:
        populated_db.create_tag("פגישת צוות", None)
        app = VoiceTUI(populated_db, test_config)
        async with app.run_test() as pilot:
            await pilot.press("f8")
            await pilot.pause()
            assert isinstance(app.screen, IssuesScreen)
            body = str(app.screen.query_one("#issues-body").render())
            assert "Tags whose names contain spaces" in body
            assert "פגישת צוות" in body
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, IssuesScreen)

"""Integration tests for TagsPane.

Tests the tags pane UI component including:
- Tag tree display
- Tag hierarchy
- Signal emission on tag clicks
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtTest import QSignalSpy

from core.database import Database
from ui.tags_pane import TagsPane
from tests.helpers import get_tag_uuid_hex


@pytest.mark.gui
class TestTagsPaneInit:
    """Test TagsPane initialization."""

    def test_creates_tags_pane(self, qapp, populated_db: Database) -> None:
        """Test that TagsPane can be created."""
        pane = TagsPane(populated_db)
        assert pane is not None
        assert pane.tree_view is not None
        assert pane.model is not None

    def test_loads_tags_on_init(self, qapp, populated_db: Database) -> None:
        """Test that tags are loaded on initialization."""
        pane = TagsPane(populated_db)
        # Model should have root items
        assert pane.model.rowCount() > 0


@pytest.mark.gui
class TestTagTreeDisplay:
    """Test tag tree display."""

    def test_displays_root_tags(self, qapp, populated_db: Database) -> None:
        """Test that root-level tags are displayed."""
        pane = TagsPane(populated_db)

        # Get all root items
        root_items = []
        for i in range(pane.model.rowCount()):
            item = pane.model.item(i)
            root_items.append(item.text())

        # Work, Personal, Geography should be at root
        assert "Work" in root_items
        assert "Personal" in root_items
        assert "Geography" in root_items

    def test_displays_hierarchy(self, qapp, populated_db: Database) -> None:
        """Test that tag hierarchy is displayed correctly."""
        pane = TagsPane(populated_db)

        # Find Work tag
        work_item = None
        for i in range(pane.model.rowCount()):
            item = pane.model.item(i)
            if item.text() == "Work":
                work_item = item
                break

        assert work_item is not None
        assert work_item.hasChildren()

        # Check children of Work
        child_names = []
        for i in range(work_item.rowCount()):
            child = work_item.child(i)
            child_names.append(child.text())

        assert "Projects" in child_names
        assert "Meetings" in child_names

    def test_displays_deep_hierarchy(self, qapp, populated_db: Database) -> None:
        """Test display of deep hierarchies (3+ levels)."""
        pane = TagsPane(populated_db)

        # Find Geography -> Europe -> France -> Paris
        geography_item = None
        for i in range(pane.model.rowCount()):
            item = pane.model.item(i)
            if item.text() == "Geography":
                geography_item = item
                break

        assert geography_item is not None

        # Find Europe child
        europe_item = None
        for i in range(geography_item.rowCount()):
            child = geography_item.child(i)
            if child.text() == "Europe":
                europe_item = child
                break

        assert europe_item is not None

        # Find France child
        france_item = None
        for i in range(europe_item.rowCount()):
            child = europe_item.child(i)
            if child.text() == "France":
                france_item = child
                break

        assert france_item is not None

        # Check Paris is child of France
        paris_found = False
        for i in range(france_item.rowCount()):
            child = france_item.child(i)
            if child.text() == "Paris":
                paris_found = True
                break

        assert paris_found

    def test_tree_is_expanded(self, qapp, populated_db: Database) -> None:
        """Test that tree is expanded by default."""
        pane = TagsPane(populated_db)
        # Tree should be expanded on load
        # Check that first item is expanded
        if pane.model.rowCount() > 0:
            first_index = pane.model.index(0, 0)
            assert pane.tree_view.isExpanded(first_index)


@pytest.mark.gui
class TestTagSelection:
    """Test tag selection functionality."""

    def test_clicking_tag_emits_signal(self, qapp, populated_db: Database) -> None:
        """Test that clicking a tag emits tag_selected signal."""
        pane = TagsPane(populated_db)
        spy = QSignalSpy(pane.tag_selected)

        # Find Work tag
        work_item = None
        for i in range(pane.model.rowCount()):
            item = pane.model.item(i)
            if item.text() == "Work":
                work_item = item
                break

        assert work_item is not None

        # Simulate click
        index = pane.model.indexFromItem(work_item)
        pane.on_tag_clicked(index)

        # Check signal was emitted
        assert spy.count() == 1
        args = spy.at(0)
        assert args[0] == get_tag_uuid_hex("Work")

    def test_emits_correct_tag_id(self, qapp, populated_db: Database) -> None:
        """Test that correct tag ID is emitted."""
        pane = TagsPane(populated_db)
        spy = QSignalSpy(pane.tag_selected)

        # Find Geography tag (ID 8)
        geography_item = None
        for i in range(pane.model.rowCount()):
            item = pane.model.item(i)
            if item.text() == "Geography":
                geography_item = item
                break

        assert geography_item is not None

        # Click it
        index = pane.model.indexFromItem(geography_item)
        pane.on_tag_clicked(index)

        # Check correct ID emitted (UUID hex string)
        assert spy.count() == 1
        args = spy.at(0)
        assert args[0] == get_tag_uuid_hex("Geography")

    def test_clicking_child_tag_emits_signal(self, qapp, populated_db: Database) -> None:
        """Test that clicking child tag works."""
        pane = TagsPane(populated_db)
        spy = QSignalSpy(pane.tag_selected)

        # Find Work -> Projects
        work_item = None
        for i in range(pane.model.rowCount()):
            item = pane.model.item(i)
            if item.text() == "Work":
                work_item = item
                break

        projects_item = None
        for i in range(work_item.rowCount()):
            child = work_item.child(i)
            if child.text() == "Projects":
                projects_item = child
                break

        assert projects_item is not None

        # Click Projects
        index = pane.model.indexFromItem(projects_item)
        pane.on_tag_clicked(index)

        # Check signal emitted with Projects UUID hex string
        assert spy.count() == 1
        args = spy.at(0)
        assert args[0] == get_tag_uuid_hex("Projects")


@pytest.mark.gui
class TestTagsPaneReadOnly:
    """Test that tags pane is read-only."""

    def test_tree_is_not_editable(self, qapp, populated_db: Database) -> None:
        """Test that tree view has no edit triggers."""
        pane = TagsPane(populated_db)
        from PySide6.QtWidgets import QTreeView

        edit_triggers = pane.tree_view.editTriggers()
        assert edit_triggers == QTreeView.EditTrigger.NoEditTriggers


@pytest.mark.gui
class TestTagShiftClick:
    """Test shift-click to add tag functionality."""

    def test_shift_click_emits_tag_add_requested(self, qapp, populated_db: Database) -> None:
        """Test that shift-clicking a tag emits tag_add_requested signal."""
        pane = TagsPane(populated_db)
        spy = QSignalSpy(pane.tag_add_requested)

        # Find Work tag
        work_item = None
        for i in range(pane.model.rowCount()):
            item = pane.model.item(i)
            if item.text() == "Work":
                work_item = item
                break

        assert work_item is not None

        # Simulate shift-click by calling the handler directly
        index = pane.model.indexFromItem(work_item)
        pane.on_tag_shift_clicked(index)

        # Check signal was emitted
        assert spy.count() == 1
        args = spy.at(0)
        assert args[0] == get_tag_uuid_hex("Work")

    def test_shift_click_child_tag_emits_signal(self, qapp, populated_db: Database) -> None:
        """Test that shift-clicking a child tag works."""
        pane = TagsPane(populated_db)
        spy = QSignalSpy(pane.tag_add_requested)

        # Find Work -> Projects
        work_item = None
        for i in range(pane.model.rowCount()):
            item = pane.model.item(i)
            if item.text() == "Work":
                work_item = item
                break

        projects_item = None
        for i in range(work_item.rowCount()):
            child = work_item.child(i)
            if child.text() == "Projects":
                projects_item = child
                break

        assert projects_item is not None

        # Simulate shift-click
        index = pane.model.indexFromItem(projects_item)
        pane.on_tag_shift_clicked(index)

        # Check signal emitted with Projects UUID
        assert spy.count() == 1
        args = spy.at(0)
        assert args[0] == get_tag_uuid_hex("Projects")

    def test_tag_selected_not_emitted_on_shift_click(self, qapp, populated_db: Database) -> None:
        """Test that tag_selected is NOT emitted on shift-click (only tag_add_requested)."""
        pane = TagsPane(populated_db)
        selected_spy = QSignalSpy(pane.tag_selected)
        add_spy = QSignalSpy(pane.tag_add_requested)

        # Find Work tag
        work_item = None
        for i in range(pane.model.rowCount()):
            item = pane.model.item(i)
            if item.text() == "Work":
                work_item = item
                break

        # Simulate shift-click
        index = pane.model.indexFromItem(work_item)
        pane.on_tag_shift_clicked(index)

        # tag_add_requested should be emitted
        assert add_spy.count() == 1
        # tag_selected should NOT be emitted
        assert selected_spy.count() == 0

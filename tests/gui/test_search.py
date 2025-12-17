"""Integration tests for search functionality.

Tests the complete search flow including:
- Tag syntax parsing
- Hierarchical tag search
- AND logic for multiple terms
- Combined text and tag search
"""

from __future__ import annotations

import pytest

from core.config import Config
from core.database import Database
from ui.notes_list_pane import NotesListPane


@pytest.mark.gui
class TestTagSyntax:
    """Test tag: syntax parsing and search."""

    def test_single_tag_search(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test search with single tag: syntax."""
        pane = NotesListPane(test_config, populated_db)

        pane.search_field.setPlainText("tag:Work")
        pane.perform_search()

        # Should find Work-tagged notes (1, 2)
        assert pane.list_widget.count() >= 2

    def test_hierarchical_tag_path(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test tag: with hierarchical path."""
        pane = NotesListPane(test_config, populated_db)

        pane.search_field.setPlainText("tag:Geography/Europe/France/Paris")
        pane.perform_search()

        # Should find note 4 (Paris)
        assert pane.list_widget.count() == 1
        item = pane.list_widget.item(0)
        assert "Paris" in item.text()

    def test_case_insensitive_tag_search(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that tag search is case-insensitive."""
        pane = NotesListPane(test_config, populated_db)

        test_cases = ["tag:work", "tag:WORK", "tag:WoRk"]
        for query in test_cases:
            pane.search_field.setPlainText(query)
            pane.perform_search()
            assert pane.list_widget.count() >= 2


@pytest.mark.gui
class TestHierarchicalSearch:
    """Test hierarchical tag search (parent includes children)."""

    def test_parent_tag_includes_children(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that searching parent tag includes child tags."""
        pane = NotesListPane(test_config, populated_db)

        # Search for Personal (should include Family, Health children)
        # Note 4 has Family, Note 3 has Health, Notes 5 and 6 have Personal
        pane.search_field.setPlainText("tag:Personal")
        pane.perform_search()

        # Should find 4 notes (3, 4, 5, 6)
        assert pane.list_widget.count() == 4

    def test_parent_tag_includes_deep_children(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that parent includes deeply nested children."""
        pane = NotesListPane(test_config, populated_db)

        # Search for Geography (root of Europe->France->Paris, Asia->Israel, US->Texas->Paris)
        pane.search_field.setPlainText("tag:Geography")
        pane.perform_search()

        # Should find notes 4, 5, 9 (France Paris, Israel, Texas Paris paths)
        assert pane.list_widget.count() == 3


@pytest.mark.gui
class TestMultipleTagsAND:
    """Test AND logic for multiple tag terms."""

    def test_two_tags_and_logic(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that multiple tags require ALL tags (AND logic)."""
        pane = NotesListPane(test_config, populated_db)

        # Search for Work AND Projects
        # Note 1 has Work, Projects, Meetings
        # Note 2 has Work, Projects, VoiceRewrite
        pane.search_field.setPlainText("tag:Work tag:Work/Projects")
        pane.perform_search()

        # Notes 1 and 2 have both Work and Projects
        assert pane.list_widget.count() == 2

    def test_parent_and_child_tag_search(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test searching for parent AND specific child."""
        pane = NotesListPane(test_config, populated_db)

        # Search for Work AND Meetings (child of Work)
        # Note 1 has Work, Projects, Meetings
        pane.search_field.setPlainText("tag:Work tag:Work/Meetings")
        pane.perform_search()

        # Should find note 1 only
        assert pane.list_widget.count() == 1

    def test_three_tags_and_logic(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test AND logic with three tags."""
        pane = NotesListPane(test_config, populated_db)

        # Note 4 has Personal (5), Family (6), France (10), Paris (11)
        # Search for three tags it has
        pane.search_field.setPlainText("tag:Personal tag:Geography tag:Geography/Europe/France/Paris")
        pane.perform_search()

        # Should find only note 4
        assert pane.list_widget.count() == 1
        item = pane.list_widget.item(0)
        assert "reunion" in item.text()


@pytest.mark.gui
class TestCombinedSearch:
    """Test combined text and tag search."""

    def test_text_and_single_tag(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test combining text search with tag."""
        pane = NotesListPane(test_config, populated_db)

        # Search for "meeting" in Work notes
        pane.search_field.setPlainText("meeting tag:Work")
        pane.perform_search()

        # Should find only note 1
        assert pane.list_widget.count() == 1
        item = pane.list_widget.item(0)
        assert "Meeting notes" in item.text()

    def test_text_and_multiple_tags(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test text search with multiple tags."""
        pane = NotesListPane(test_config, populated_db)

        # Search for "reunion" in Personal + Geography notes
        # Note 4 has "reunion" and tags Personal, Family, France, Paris
        pane.search_field.setPlainText("reunion tag:Personal tag:Geography")
        pane.perform_search()

        # Should find note 4
        assert pane.list_widget.count() == 1

    def test_text_with_hierarchical_tag(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test text search with hierarchical tag path."""
        pane = NotesListPane(test_config, populated_db)

        pane.search_field.setPlainText("reunion tag:Geography/Europe/France/Paris")
        pane.perform_search()

        # Should find note 4
        assert pane.list_widget.count() == 1

    def test_multiple_text_words_with_tags(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test multiple text words with tags."""
        pane = NotesListPane(test_config, populated_db)

        # Both words must be in content
        pane.search_field.setPlainText("Family reunion tag:Personal")
        pane.perform_search()

        assert pane.list_widget.count() == 1


@pytest.mark.gui
class TestSearchParsing:
    """Test search input parsing."""

    def test_parses_mixed_text_and_tags(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test parsing mixed text and tag terms."""
        pane = NotesListPane(test_config, populated_db)

        # Parse "hello tag:Work world tag:Projects"
        tag_names, free_text = pane._parse_search_input(
            "hello tag:Work world tag:Projects"
        )

        assert tag_names == ["Work", "Projects"]
        assert free_text == "hello world"

    def test_parses_hierarchical_paths(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test parsing hierarchical tag paths."""
        pane = NotesListPane(test_config, populated_db)

        tag_names, free_text = pane._parse_search_input(
            "tag:Geography/Europe/France/Paris reunion"
        )

        assert tag_names == ["Geography/Europe/France/Paris"]
        assert free_text == "reunion"

    def test_parses_empty_string(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test parsing empty search string."""
        pane = NotesListPane(test_config, populated_db)

        tag_names, free_text = pane._parse_search_input("")

        assert tag_names == []
        assert free_text == ""


@pytest.mark.gui
class TestSearchEdgeCases:
    """Test edge cases in search functionality."""

    def test_nonexistent_tag_returns_no_results(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test search with non-existent tag."""
        pane = NotesListPane(test_config, populated_db)

        pane.search_field.setPlainText("tag:NonExistentTag")
        pane.perform_search()

        # Should return no results
        assert pane.list_widget.count() == 0

    def test_empty_search_shows_all_notes(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that empty search shows all notes."""
        pane = NotesListPane(test_config, populated_db)

        # Start with filtered view
        pane.search_field.setPlainText("tag:Work")
        pane.perform_search()
        assert pane.list_widget.count() < 6

        # Clear and search empty
        pane.search_field.clear()
        pane.perform_search()

        # Should show all notes
        assert pane.list_widget.count() == 9

    def test_tag_with_no_matching_notes(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test tag that exists but has no notes."""
        pane = NotesListPane(test_config, populated_db)

        # Germany (12) has no notes
        pane.search_field.setPlainText("tag:Germany")
        pane.perform_search()

        assert pane.list_widget.count() == 0

    def test_conflicting_criteria_returns_nothing(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test search with conflicting criteria."""
        pane = NotesListPane(test_config, populated_db)

        # No note has both VoiceRewrite (work child) and Health (personal child)
        pane.search_field.setPlainText("tag:VoiceRewrite tag:Health")
        pane.perform_search()

        assert pane.list_widget.count() == 0


@pytest.mark.gui
class TestAmbiguousTagSearch:
    """Test search with ambiguous tag names (multiple tags with same name)."""

    def test_search_ambiguous_paris_finds_both_locations(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that ambiguous 'Paris' search finds notes from both France and Texas."""
        pane = NotesListPane(test_config, populated_db)

        # Search for ambiguous "Paris" - should match both locations with OR logic
        pane.search_field.setPlainText("tag:Paris")
        pane.perform_search()

        # Should find notes 4 (France Paris) and 9 (Texas Paris)
        assert pane.list_widget.count() == 2
        texts = [pane.list_widget.item(i).text() for i in range(pane.list_widget.count())]
        assert any("reunion" in text for text in texts)  # Note 4
        assert any("Cowboys" in text for text in texts)  # Note 9

    def test_search_full_path_france_paris_finds_one(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that full path 'Geography/Europe/France/Paris' finds only France Paris."""
        pane = NotesListPane(test_config, populated_db)

        # Use full path to disambiguate
        pane.search_field.setPlainText("tag:Geography/Europe/France/Paris")
        pane.perform_search()

        # Should find only note 4 (France Paris)
        assert pane.list_widget.count() == 1
        item_text = pane.list_widget.item(0).text()
        assert "reunion" in item_text

    def test_search_full_path_texas_paris_finds_one(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that full path 'Geography/US/Texas/Paris' finds only Texas Paris."""
        pane = NotesListPane(test_config, populated_db)

        # Use full path to disambiguate
        pane.search_field.setPlainText("tag:Geography/US/Texas/Paris")
        pane.perform_search()

        # Should find only note 9 (Texas Paris)
        assert pane.list_widget.count() == 1
        item_text = pane.list_widget.item(0).text()
        assert "Cowboys" in item_text

    def test_search_ambiguous_bar_finds_both(
        self, qapp, test_config: Config, populated_db: Database
    ) -> None:
        """Test that ambiguous 'Bar' search finds notes from both Foo/Bar and Boom/Bar."""
        pane = NotesListPane(test_config, populated_db)

        # Search for ambiguous "Bar"
        pane.search_field.setPlainText("tag:Bar")
        pane.perform_search()

        # Should find notes 7 (Foo/Bar) and 8 (Boom/Bar)
        assert pane.list_widget.count() == 2
        texts = [pane.list_widget.item(i).text() for i in range(pane.list_widget.count())]
        assert any("Testing ambiguous tag with Foo/bar" in text for text in texts)  # Note 7
        assert any("Another note with Boom/bar" in text for text in texts)  # Note 8

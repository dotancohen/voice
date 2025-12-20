"""Performance and scalability tests.

Tests system behavior with large datasets.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest

from core.database import Database
from core.search import execute_search


def generate_uuid(prefix: int, index: int) -> bytes:
    """Generate a deterministic UUID bytes for testing.

    Args:
        prefix: First digit of the UUID's counter part (0-99)
        index: Index to generate unique UUID (0-9999)

    Returns:
        16-byte UUID
    """
    # Format: 00000000-0000-7000-8000-0000PP00IIII
    # Must be 32 hex characters (16 bytes)
    hex_str = f"000000000000700080000000{prefix:02d}00{index:04d}"
    return uuid.UUID(hex_str).bytes


@pytest.mark.integration
@pytest.mark.slow
class TestLargeDatabasePerformance:
    """Test performance with large datasets."""

    def test_get_all_notes_performance(
        self,
        large_db: Database,
    ) -> None:
        """Getting all notes from 1000-note database is fast."""
        start = time.perf_counter()
        notes = large_db.get_all_notes()
        elapsed = time.perf_counter() - start

        assert len(notes) == 1000
        assert elapsed < 1.0, f"get_all_notes took {elapsed:.2f}s, should be < 1s"

    def test_get_all_tags_performance(
        self,
        large_db: Database,
    ) -> None:
        """Getting all tags from 100-tag database is fast."""
        start = time.perf_counter()
        tags = large_db.get_all_tags()
        elapsed = time.perf_counter() - start

        assert len(tags) == 100
        assert elapsed < 0.5, f"get_all_tags took {elapsed:.2f}s, should be < 0.5s"

    def test_text_search_performance(
        self,
        large_db: Database,
    ) -> None:
        """Text search on 1000 notes is fast."""
        start = time.perf_counter()
        result = execute_search(large_db, "Note 500")
        elapsed = time.perf_counter() - start

        assert len(result.notes) >= 1
        assert elapsed < 0.5, f"Text search took {elapsed:.2f}s, should be < 0.5s"

    def test_tag_search_performance(
        self,
        large_db: Database,
    ) -> None:
        """Tag search with descendants is fast."""
        start = time.perf_counter()
        # Search for a top-level tag that has 10 descendants
        result = execute_search(large_db, "tag:Tag_B0_L0")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"Tag search took {elapsed:.2f}s, should be < 0.5s"

    def test_deep_hierarchy_traversal_performance(
        self,
        large_db: Database,
    ) -> None:
        """Traversing deep tag hierarchy is fast."""
        # Get descendants of a tag at top of 10-level hierarchy
        # First tag is at index 0, which is Branch 0, Level 0
        first_tag_id = generate_uuid(1, 0)
        start = time.perf_counter()
        descendants = large_db.get_tag_descendants(first_tag_id)
        elapsed = time.perf_counter() - start

        assert len(descendants) == 10  # Tag plus 9 descendants
        assert elapsed < 0.2, f"Hierarchy traversal took {elapsed:.2f}s, should be < 0.2s"

    def test_multiple_tag_filters_performance(
        self,
        large_db: Database,
    ) -> None:
        """Search with multiple tag filters is fast."""
        # Use UUIDs for tags at different positions
        tag_group_1 = [generate_uuid(1, i) for i in range(3)]
        tag_group_2 = [generate_uuid(1, i) for i in range(10, 13)]
        tag_group_3 = [generate_uuid(1, i) for i in range(20, 23)]

        start = time.perf_counter()
        # Search with multiple tag constraints
        notes = large_db.search_notes(
            tag_id_groups=[tag_group_1, tag_group_2, tag_group_3]
        )
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"Multi-tag search took {elapsed:.2f}s, should be < 0.5s"

    def test_combined_search_performance(
        self,
        large_db: Database,
    ) -> None:
        """Combined text and tag search is fast."""
        start = time.perf_counter()
        result = execute_search(large_db, "Note tag:Tag_B0_L0")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"Combined search took {elapsed:.2f}s, should be < 0.5s"


@pytest.mark.integration
@pytest.mark.slow
class TestScalabilityLimits:
    """Test behavior at scalability limits."""

    def test_many_search_iterations(
        self,
        large_db: Database,
    ) -> None:
        """Multiple sequential searches remain fast."""
        start = time.perf_counter()

        for i in range(100):
            result = execute_search(large_db, f"Note {i}")

        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, f"100 searches took {elapsed:.2f}s, should be < 5s"

    def test_get_single_note_performance(
        self,
        large_db: Database,
    ) -> None:
        """Getting a single note is fast regardless of database size."""
        times = []

        for note_num in [1, 500, 1000]:
            note_id = generate_uuid(2, note_num)
            start = time.perf_counter()
            note = large_db.get_note(note_id)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert note is not None

        # All lookups should be similarly fast
        for t in times:
            assert t < 0.1, f"Note lookup took {t:.3f}s, should be < 0.1s"

    def test_tag_descendants_at_depth(
        self,
        large_db: Database,
    ) -> None:
        """Getting descendants works at all depths."""
        # Test at different depths of the hierarchy
        for branch in range(5):
            # Top of each branch is at index branch * 10
            tag_id = generate_uuid(1, branch * 10)
            start = time.perf_counter()
            descendants = large_db.get_tag_descendants(tag_id)
            elapsed = time.perf_counter() - start

            assert len(descendants) == 10  # Full branch
            assert elapsed < 0.1, f"Descendants at depth took {elapsed:.3f}s"


@pytest.mark.integration
class TestNormalDatabasePerformance:
    """Test performance with normal-sized database."""

    def test_search_response_time(
        self,
        populated_db: Database,
    ) -> None:
        """Search responds within acceptable time for normal use."""
        queries = [
            "Doctor",
            "tag:Work",
            "reunion tag:Personal",
            "tag:Geography/Europe/France/Paris",
        ]

        for query in queries:
            start = time.perf_counter()
            result = execute_search(populated_db, query)
            elapsed = time.perf_counter() - start

            assert elapsed < 0.1, f"Query '{query}' took {elapsed:.3f}s, should be < 0.1s"

    def test_get_all_data_response_time(
        self,
        populated_db: Database,
    ) -> None:
        """Getting all data responds quickly."""
        start = time.perf_counter()
        notes = populated_db.get_all_notes()
        tags = populated_db.get_all_tags()
        elapsed = time.perf_counter() - start

        assert len(notes) == 9
        assert len(tags) == 21
        assert elapsed < 0.1, f"Getting all data took {elapsed:.3f}s, should be < 0.1s"

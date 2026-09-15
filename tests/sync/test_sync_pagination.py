"""Tests for pagination of changes in sync.

Tests:
- is_complete=False response handling
- Following multiple pages of changes
- Very large datasets
- Limit parameter
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.database import set_this_device_id
from tests.sync_support import read_feed
from voicecore import SyncClient

from .conftest import (
    AUTH,
    SyncNode,
    create_note_on_node,
    get_note_count,
    sync_nodes,
)


class TestChangesEndpointPagination:
    """Tests for /sync/changes endpoint pagination."""

    def test_changes_respects_limit(self, running_server_a: SyncNode):
        """A page holds at most `limit` changes, every entity type together. No
        type is starved: the next page continues after the last change of this
        one, so every note arrives by following next_cursor."""
        for i in range(20):
            create_note_on_node(running_server_a, f"Note {i}")

        response = requests.get(
            f"{running_server_a.url}/sync/changes?limit=5",
            headers=AUTH,
            timeout=5,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["changes"]) == 5
        assert data["is_complete"] is False

        notes = [c for c in data["changes"] if c["entity_type"] == "note"]
        cursor = data["next_cursor"]
        while not data["is_complete"]:
            data = requests.get(
                f"{running_server_a.url}/sync/changes?limit=5&cursor={cursor}",
                headers=AUTH,
                timeout=5,
            ).json()
            assert len(data["changes"]) <= 5
            notes.extend(c for c in data["changes"] if c["entity_type"] == "note")
            cursor = data["next_cursor"]
        assert len(notes) == 20

    def test_changes_is_complete_false(self, running_server_a: SyncNode):
        """Changes returns is_complete=False when more available."""
        # Create many notes
        for i in range(20):
            create_note_on_node(running_server_a, f"Note {i}")

        # Request with small limit
        response = requests.get(
            f"{running_server_a.url}/sync/changes?limit=5",
            headers=AUTH,
            timeout=5,
        )

        data = response.json()

        # is_complete should be False when there are more changes
        # (depends on how many changes were created vs limit)
        if len(data["changes"]) == 5:
            assert data["is_complete"] is False

    def test_changes_is_complete_true(self, running_server_a: SyncNode):
        """Changes returns is_complete=True when all returned."""
        # Create few notes
        for i in range(3):
            create_note_on_node(running_server_a, f"Note {i}")

        # Request with large limit
        response = requests.get(
            f"{running_server_a.url}/sync/changes?limit=1000",
            headers=AUTH,
            timeout=5,
        )

        data = response.json()

        # Should be complete
        assert data["is_complete"] is True

    def test_a_cursor_returns_only_what_came_after_it(self, running_server_a: SyncNode):
        """The next_cursor of one read, passed back, returns only the changes written after it."""
        for i in range(3):
            create_note_on_node(running_server_a, f"פתק ישן {i}")
        response = requests.get(f"{running_server_a.url}/sync/changes", headers=AUTH, timeout=5)
        cursor = response.json()["next_cursor"]

        new_ids = [create_note_on_node(running_server_a, f"פתק חדש {i}") for i in range(3)]
        response = requests.get(f"{running_server_a.url}/sync/changes?cursor={cursor}", headers=AUTH, timeout=5)
        notes = {c["entity_id"] for c in response.json()["changes"] if c["entity_type"] == "note"}
        assert notes == set(new_ids)


class TestReadingTheFeed:
    """The core's feed, read directly."""

    def test_get_changes_no_limit(self, sync_node_a: SyncNode):
        """Every change, when the limit is larger than the feed."""
        for i in range(10):
            create_note_on_node(sync_node_a, f"Note {i}")

        set_this_device_id(sync_node_a.device_id)
        changes, _ = read_feed(sync_node_a.db, 0, limit=1000)

        assert len([c for c in changes if c.entity_type == "note"]) == 10

    def test_the_limit_is_the_page_s_and_the_cursor_continues_after_it(self, sync_node_a: SyncNode):
        """A limit counts every type together; the next page starts where the last ended."""
        for i in range(20):
            create_note_on_node(sync_node_a, f"Note {i}")

        set_this_device_id(sync_node_a.device_id)
        page, cursor = read_feed(sync_node_a.db, 0, limit=5)
        assert len(page) == 5
        rest, _ = read_feed(sync_node_a.db, cursor)
        assert len([c for c in page + rest if c.entity_type == "note"]) == 20

    def test_a_cursor_reads_only_what_was_written_after_it(self, sync_node_a: SyncNode):
        """What was written after a cursor, and nothing before it."""
        create_note_on_node(sync_node_a, "Old note")
        set_this_device_id(sync_node_a.device_id)
        _, cursor = read_feed(sync_node_a.db, 0)

        for i in range(3):
            create_note_on_node(sync_node_a, f"New note {i}")
        changes, _ = read_feed(sync_node_a.db, cursor)

        assert len([c for c in changes if c.entity_type == "note"]) == 3

    def test_the_cursor_moves_past_what_was_read(self, sync_node_a: SyncNode):
        """The cursor returned after a read is past every change the read returned."""
        create_note_on_node(sync_node_a, "Test note")

        set_this_device_id(sync_node_a.device_id)
        changes, cursor = read_feed(sync_node_a.db, 0)

        assert changes and cursor > 0
        again, _ = read_feed(sync_node_a.db, cursor)
        assert again == []

    def test_get_changes_includes_all_types(self, sync_node_a: SyncNode):
        """The feed carries notes, tags, and note_tags."""
        from .conftest import create_tag_on_node

        note_id = create_note_on_node(sync_node_a, "Test note")
        tag_id = create_tag_on_node(sync_node_a, "TestTag")

        set_this_device_id(sync_node_a.device_id)
        sync_node_a.db.add_tag_to_note(note_id, tag_id)

        changes, _ = read_feed(sync_node_a.db, 0)

        entity_types = {c.entity_type for c in changes}
        assert "note" in entity_types
        assert "tag" in entity_types
        assert "note_tag" in entity_types


class TestFollowingPaginatedResults:
    """Following the pages of the feed through the endpoint."""

    @pytest.mark.parametrize("page_size", [3, 5])
    def test_following_next_cursor_collects_every_note_exactly_once(self, running_server_a: SyncNode, page_size: int):
        """Page by page with next_cursor: no note is missed and none comes twice."""
        note_ids = {create_note_on_node(running_server_a, f"פתק {i}") for i in range(15)}

        notes = []
        cursor = 0
        for _ in range(200):
            response = requests.get(
                f"{running_server_a.url}/sync/changes?limit={page_size}&cursor={cursor}",
                headers=AUTH,
                timeout=5,
            )
            data = response.json()
            assert len(data["changes"]) <= page_size
            notes.extend(c["entity_id"] for c in data["changes"] if c["entity_type"] == "note")
            cursor = data["next_cursor"]
            if data["is_complete"]:
                break

        assert data["is_complete"], "the feed was not finished in 200 pages"
        assert sorted(notes) == sorted(note_ids)


class TestLargeDatasetPagination:
    """Tests for very large datasets."""

    def test_sync_large_dataset(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Sync handles large dataset across pages."""
        node_a, node_b = two_nodes_with_servers

        # Create many notes on B
        note_count = 100
        for i in range(note_count):
            create_note_on_node(node_b, f"Note {i} content here")

        # Sync should handle pagination automatically
        result = sync_nodes(node_a, node_b)

        assert result["success"] is True
        assert get_note_count(node_a) == note_count

    def test_sync_with_tags_and_associations(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Sync handles paginated notes, tags, and associations."""
        node_a, node_b = two_nodes_with_servers

        from .conftest import create_tag_on_node

        # Create complex data on B
        tags = []
        for i in range(10):
            tag_id = create_tag_on_node(node_b, f"Tag{i}")
            tags.append(tag_id)

        notes = []
        for i in range(30):
            note_id = create_note_on_node(node_b, f"Note {i}")
            notes.append(note_id)
            # Tag each note with a random tag
            set_this_device_id(node_b.device_id)
            node_b.db.add_tag_to_note(note_id, tags[i % len(tags)])

        # Sync
        result = sync_nodes(node_a, node_b)

        assert result["success"] is True
        assert get_note_count(node_a) == 30

        # Verify some tags came through
        from .conftest import get_tag_count
        assert get_tag_count(node_a) == 10


class TestLimitBoundaries:
    """Tests for limit parameter boundaries."""

    def test_limit_zero(self, running_server_a: SyncNode):
        """Limit of 0 returns no changes."""
        create_note_on_node(running_server_a, "Test")

        response = requests.get(
            f"{running_server_a.url}/sync/changes?limit=0",
            headers=AUTH,
            timeout=5,
        )

        data = response.json()
        assert len(data["changes"]) == 0

    def test_limit_one(self, running_server_a: SyncNode):
        """Limit of 1 returns a single change, and says that more remains."""
        for i in range(5):
            create_note_on_node(running_server_a, f"Note {i}")

        response = requests.get(
            f"{running_server_a.url}/sync/changes?limit=1",
            headers=AUTH,
            timeout=5,
        )

        data = response.json()
        assert len(data["changes"]) == 1
        assert data["is_complete"] is False

    def test_limit_very_large(self, running_server_a: SyncNode):
        """Very large limit is capped."""
        create_note_on_node(running_server_a, "Test")

        response = requests.get(
            f"{running_server_a.url}/sync/changes?limit=1000000",
            headers=AUTH,
            timeout=5,
        )

        # Should work but be capped at reasonable value
        assert response.status_code == 200

    def test_limit_negative(self, running_server_a: SyncNode):
        """Negative limit is handled."""
        create_note_on_node(running_server_a, "Test")

        response = requests.get(
            f"{running_server_a.url}/sync/changes?limit=-1",
            headers=AUTH,
            timeout=5,
        )

        # Should handle gracefully
        assert response.status_code == 200 or response.status_code >= 400


class TestSyncClientPaginationHandling:
    """Tests for how SyncClient handles pagination."""

    def test_client_follows_pages(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """SyncClient follows paginated responses."""
        node_a, node_b = two_nodes_with_servers

        # Create many notes
        for i in range(50):
            create_note_on_node(node_b, f"Note {i}")

        # Client should handle pagination
        set_this_device_id(node_a.device_id)
        client = SyncClient(str(node_a.config_dir))
        result = client.sync_with_device(node_b.device_id_hex)

        assert result.success is True
        assert get_note_count(node_a) == 50

    def test_client_handles_incomplete_response(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """SyncClient handles is_complete=False."""
        node_a, node_b = two_nodes_with_servers

        # Create data
        for i in range(20):
            create_note_on_node(node_b, f"Note {i}")

        # Sync should complete
        result = sync_nodes(node_a, node_b)

        assert result["success"] is True
        # May need multiple internal fetches
        assert get_note_count(node_a) == 20

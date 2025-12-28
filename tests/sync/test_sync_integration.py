"""Integration tests for bi-directional sync.

Tests real-world sync scenarios with two or more nodes:
- Creating content on one node and syncing to another
- Bi-directional sync with content on both sides
- Three-way sync scenarios
- Complex workflows with multiple sync operations
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Generator, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.database import set_local_device_id

from .conftest import (
    SyncNode,
    create_note_on_node,
    create_tag_on_node,
    get_note_count,
    get_tag_count,
    sync_nodes,
)


class TestTwoNodeSync:
    """Tests for sync between two nodes."""

    def test_create_note_sync_verify(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Create note on A, sync to B, verify B has it."""
        node_a, node_b = two_nodes_with_servers

        # Create on A
        note_id = create_note_on_node(node_a, "Hello from A")

        # A initially has 1 note, B has 0
        assert get_note_count(node_a) == 1
        assert get_note_count(node_b) == 0

        # Sync A -> B (A pushes to B)
        result = sync_nodes(node_a, node_b)
        assert result["success"] is True

        # Now B should have the note
        note = node_b.db.get_note(note_id)
        assert note is not None
        assert note["content"] == "Hello from A"

    def test_bidirectional_unique_notes(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Both nodes create different notes, sync exchanges them."""
        node_a, node_b = two_nodes_with_servers

        # Create different notes on each
        note_a = create_note_on_node(node_a, "Note from A")
        note_b = create_note_on_node(node_b, "Note from B")

        # Initial state
        assert get_note_count(node_a) == 1
        assert get_note_count(node_b) == 1

        # Sync A -> B
        sync_nodes(node_a, node_b)

        # Sync B -> A
        sync_nodes(node_b, node_a)

        # Both should have both notes
        assert get_note_count(node_a) == 2
        assert get_note_count(node_b) == 2

        assert node_a.db.get_note(note_b) is not None
        assert node_b.db.get_note(note_a) is not None

    def test_tag_hierarchy_sync(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Tag hierarchies sync correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create hierarchy on A
        work = create_tag_on_node(node_a, "Work")
        projects = create_tag_on_node(node_a, "Projects", work)
        voice = create_tag_on_node(node_a, "Voice", projects)

        # Sync to B
        sync_nodes(node_a, node_b)

        # Verify hierarchy on B
        assert get_tag_count(node_b) == 3

        tags_b = node_b.db.get_all_tags()
        tag_names = {t["name"] for t in tags_b}
        assert tag_names == {"Work", "Projects", "Voice"}

    def test_note_with_tags_sync(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Notes with tags sync correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create tag and note on A
        tag_id = create_tag_on_node(node_a, "Important")
        note_id = create_note_on_node(node_a, "Important note")

        # Associate tag with note
        set_local_device_id(node_a.device_id)
        node_a.db.add_tag_to_note(note_id, tag_id)

        # Sync to B
        sync_nodes(node_a, node_b)

        # Verify note has tag on B
        note_b = node_b.db.get_note(note_id)
        assert note_b is not None
        # Note's tags should include "Important"
        assert "Important" in note_b.get("tag_names", "")

    def test_update_propagation(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Updates propagate when only one side changed (using last_sync_at tracking)."""
        node_a, node_b = two_nodes_with_servers

        # Create note on A
        note_id = create_note_on_node(node_a, "Original content")

        # Sync to B
        sync_nodes(node_a, node_b)

        # Reload B's db to see changes from server subprocess
        node_b.reload_db()
        # Verify on B
        note_b = node_b.db.get_note(note_id)
        assert note_b["content"] == "Original content"

        # Wait a full second (timestamps are second-precision)
        time.sleep(1.1)

        # Update on A
        set_local_device_id(node_a.device_id)
        node_a.db.update_note(note_id, "Updated content")

        # Sync again - update propagates cleanly (B hasn't edited since last sync)
        sync_nodes(node_a, node_b)

        # Reload B's db to see changes from server subprocess
        node_b.reload_db()
        # Update propagates (only A changed, B unchanged since last sync)
        note_b = node_b.db.get_note(note_id)
        assert note_b["content"] == "Updated content"

    def test_delete_propagation(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Deletions propagate when other node hasn't edited the note."""
        node_a, node_b = two_nodes_with_servers

        # Create note on A
        note_id = create_note_on_node(node_a, "Will be deleted")

        # Sync to B
        sync_nodes(node_a, node_b)

        # Reload B's db to see changes from server subprocess
        node_b.reload_db()
        # Verify on B
        assert node_b.db.get_note(note_id) is not None
        assert get_note_count(node_b) == 1

        # Wait a full second (timestamps are second-precision)
        time.sleep(1.1)

        # Delete on A (B has same content - never edited)
        set_local_device_id(node_a.device_id)
        node_a.db.delete_note(note_id)

        # Sync again - delete propagates because B didn't edit
        sync_nodes(node_a, node_b)

        # Reload B's db to see changes from server subprocess
        node_b.reload_db()
        # B's note is now deleted (propagated from A)
        assert get_note_count(node_b) == 0  # Note deleted
        note_b = node_b.db.get_note(note_id)
        assert note_b is not None  # Soft delete - record exists
        assert note_b.get("deleted_at") is not None  # But marked deleted

    def test_multiple_sync_cycles(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Multiple sync cycles work correctly."""
        node_a, node_b = two_nodes_with_servers

        # Cycle 1: A creates, sync, B creates, sync
        note_a1 = create_note_on_node(node_a, "A note 1")
        sync_nodes(node_a, node_b)

        # Wait for timestamp precision
        time.sleep(1.1)

        note_b1 = create_note_on_node(node_b, "B note 1")
        sync_nodes(node_b, node_a)
        sync_nodes(node_a, node_b)

        # Reload databases to see changes from server subprocesses
        node_a.reload_db()
        node_b.reload_db()
        # Both have 2 notes
        assert get_note_count(node_a) == 2
        assert get_note_count(node_b) == 2

        # Wait for timestamp precision
        time.sleep(1.1)

        # Cycle 2: More notes
        note_a2 = create_note_on_node(node_a, "A note 2")
        note_b2 = create_note_on_node(node_b, "B note 2")

        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)

        # Reload databases to see changes from server subprocesses
        node_a.reload_db()
        node_b.reload_db()
        # Both have 4 notes
        assert get_note_count(node_a) == 4
        assert get_note_count(node_b) == 4

    def test_large_note_content(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Large note content syncs correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create large note (10KB)
        large_content = "x" * 10000
        note_id = create_note_on_node(node_a, large_content)

        # Sync to B
        sync_nodes(node_a, node_b)

        # Verify exact content
        note_b = node_b.db.get_note(note_id)
        assert note_b is not None
        assert note_b["content"] == large_content
        assert len(note_b["content"]) == 10000

    def test_unicode_content(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Unicode content syncs correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create notes with various unicode
        contents = [
            "Hebrew: שלום עולם",
            "Chinese: 你好世界",
            "Arabic: مرحبا بالعالم",
            "Emoji: 🎉🎊🎁",
            "Mixed: Hello שלום 你好 🌍",
        ]

        note_ids = []
        for content in contents:
            note_id = create_note_on_node(node_a, content)
            note_ids.append(note_id)

        # Sync to B
        sync_nodes(node_a, node_b)

        # Verify all content
        for note_id, expected in zip(note_ids, contents):
            note_b = node_b.db.get_note(note_id)
            assert note_b is not None
            assert note_b["content"] == expected


class TestThreeNodeSync:
    """Tests for sync between three nodes."""

    def test_three_way_propagation(
        self, three_nodes_with_servers: Tuple[SyncNode, SyncNode, SyncNode]
    ):
        """Content propagates through all three nodes."""
        node_a, node_b, node_c = three_nodes_with_servers

        # Create on A
        note_id = create_note_on_node(node_a, "Note from A")

        # Sync A -> B
        sync_nodes(node_a, node_b)

        # Verify B has it
        assert node_b.db.get_note(note_id) is not None

        # Sync B -> C
        sync_nodes(node_b, node_c)

        # Verify C has it
        assert node_c.db.get_note(note_id) is not None

    def test_all_nodes_create_content(
        self, three_nodes_with_servers: Tuple[SyncNode, SyncNode, SyncNode]
    ):
        """All three nodes create content, sync converges."""
        node_a, node_b, node_c = three_nodes_with_servers

        # Each creates a note
        note_a = create_note_on_node(node_a, "From A")
        note_b = create_note_on_node(node_b, "From B")
        note_c = create_note_on_node(node_c, "From C")

        # Full mesh sync
        for source in [node_a, node_b, node_c]:
            for target in [node_a, node_b, node_c]:
                if source != target:
                    sync_nodes(source, target)

        # All should have all 3 notes
        for node in [node_a, node_b, node_c]:
            assert get_note_count(node) == 3
            assert node.db.get_note(note_a) is not None
            assert node.db.get_note(note_b) is not None
            assert node.db.get_note(note_c) is not None

    def test_star_topology_sync(
        self, three_nodes_with_servers: Tuple[SyncNode, SyncNode, SyncNode]
    ):
        """Sync in star topology (B is hub)."""
        node_a, node_b, node_c = three_nodes_with_servers

        # A creates note and syncs with B first
        note_a = create_note_on_node(node_a, "From A")

        # Wait for timestamp precision
        time.sleep(1.1)

        # A syncs with B
        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)

        # Wait for timestamp precision - C's note must be AFTER A's sync
        time.sleep(1.1)

        # C creates note and syncs with B
        note_c = create_note_on_node(node_c, "From C")
        sync_nodes(node_c, node_b)
        sync_nodes(node_b, node_c)

        # Wait for timestamp precision
        time.sleep(1.1)

        # A syncs with B again to get C's content
        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)

        # Reload databases to see changes from server subprocesses
        node_a.reload_db()
        node_b.reload_db()
        node_c.reload_db()
        # All should have both notes
        for node in [node_a, node_b, node_c]:
            assert get_note_count(node) == 2


class TestComplexWorkflows:
    """Tests for complex sync workflows."""

    def test_offline_edit_then_sync_propagates(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Offline editing then syncing propagates cleanly (only one side edited)."""
        node_a, node_b = two_nodes_with_servers

        # Initial sync
        note_id = create_note_on_node(node_a, "Initial content")
        sync_nodes(node_a, node_b)

        # Wait for timestamp precision
        time.sleep(1.1)

        # "Offline" editing - multiple updates without sync
        set_local_device_id(node_a.device_id)
        node_a.db.update_note(note_id, "Edit 1")
        node_a.db.update_note(note_id, "Edit 2")
        node_a.db.update_note(note_id, "Final edit")

        # Sync after "coming online"
        sync_nodes(node_a, node_b)

        # Reload B's db to see changes from server subprocess
        node_b.reload_db()
        # B hasn't edited since last sync, so A's update propagates cleanly
        note_b = node_b.db.get_note(note_id)
        assert note_b["content"] == "Final edit"

    def test_bulk_import_then_sync(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Simulate bulk import then sync."""
        node_a, node_b = two_nodes_with_servers

        # Bulk create on A
        note_ids = []
        for i in range(50):
            note_id = create_note_on_node(node_a, f"Imported note {i}")
            note_ids.append(note_id)

        # Single sync should transfer all
        sync_nodes(node_a, node_b)

        # Verify all transferred
        assert get_note_count(node_b) == 50
        for note_id in note_ids:
            assert node_b.db.get_note(note_id) is not None

    def test_one_side_edit_propagates(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """When only one side edits, the edit propagates cleanly."""
        node_a, node_b = two_nodes_with_servers

        # Create on A
        note_id = create_note_on_node(node_a, "Version 1")
        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)

        # Wait for timestamp precision
        time.sleep(1.1)

        # B needs to reload to see the note before editing
        node_b.reload_db()
        # Edit on B
        set_local_device_id(node_b.device_id)
        node_b.db.update_note(note_id, "Version 2 from B")
        sync_nodes(node_b, node_a)

        # A hasn't edited since last sync, so B's update propagates cleanly
        node_a.reload_db()
        note_a = node_a.db.get_note(note_id)
        assert note_a["content"] == "Version 2 from B"

        # B keeps its own edit
        note_b = node_b.db.get_note(note_id)
        assert note_b["content"] == "Version 2 from B"

    def test_concurrent_edits_create_conflict(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """When both sides edit, a conflict is created with both versions."""
        node_a, node_b = two_nodes_with_servers

        # Create on A
        note_id = create_note_on_node(node_a, "Version 1")
        sync_nodes(node_a, node_b)
        sync_nodes(node_b, node_a)
        node_b.reload_db()

        # Wait for timestamp precision
        time.sleep(1.1)

        # BOTH sides edit (creating a real conflict scenario)
        set_local_device_id(node_a.device_id)
        node_a.db.update_note(note_id, "Edit from A")

        set_local_device_id(node_b.device_id)
        node_b.db.update_note(note_id, "Edit from B")

        # Sync - both edited since last sync, so conflict is created
        sync_nodes(node_a, node_b)
        node_a.reload_db()

        # A should have both versions (conflict markers)
        note_a = node_a.db.get_note(note_id)
        assert "Edit from A" in note_a["content"]
        assert "Edit from B" in note_a["content"]
        assert "<<<<<<< LOCAL" in note_a["content"]

    def test_tag_reorganization_sync(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Tag hierarchy changes sync correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create initial hierarchy on A
        work = create_tag_on_node(node_a, "Work")
        project = create_tag_on_node(node_a, "Project", work)

        # Sync to B
        sync_nodes(node_a, node_b)

        # Reload B's db to see changes from server subprocess
        node_b.reload_db()
        # Verify on B
        assert get_tag_count(node_b) == 2

        # Wait for timestamp precision
        time.sleep(1.1)

        # Create another tag on A
        urgent = create_tag_on_node(node_a, "Urgent", project)

        # Sync again
        sync_nodes(node_a, node_b)

        # Reload B's db to see changes from server subprocess
        node_b.reload_db()
        # Verify full hierarchy on B
        assert get_tag_count(node_b) == 3

    def test_rapid_sync_cycles(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Rapid sync cycles don't cause issues."""
        node_a, node_b = two_nodes_with_servers

        # Create initial content
        note_id = create_note_on_node(node_a, "Rapid sync test")

        # Many rapid syncs
        for i in range(10):
            sync_nodes(node_a, node_b)
            sync_nodes(node_b, node_a)

        # Should still have exactly 1 note on each
        assert get_note_count(node_a) == 1
        assert get_note_count(node_b) == 1

    def test_sync_after_restart(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Sync works after server restart."""
        node_a, node_b = two_nodes_with_servers

        # Create and sync
        note_id = create_note_on_node(node_a, "Before restart")
        sync_nodes(node_a, node_b)

        # Wait a full second (timestamps are second-precision)
        time.sleep(1.1)

        # Restart server B
        from .conftest import start_sync_server
        node_b.stop_server()
        start_sync_server(node_b)
        node_b.wait_for_server()

        # Create more content and sync
        note_id2 = create_note_on_node(node_a, "After restart")
        sync_nodes(node_a, node_b)

        # Reload node_b's db to see changes written by server subprocess
        node_b.reload_db()
        # Both notes should be on B
        assert node_b.db.get_note(note_id) is not None
        assert node_b.db.get_note(note_id2) is not None


class TestAudioFileSyncIntegration:
    """Tests for audio file sync with full HTTP client-server flow.

    These tests verify that audio files sync correctly through the complete
    sync protocol, including metadata sync and binary file transfer.
    """

    @pytest.fixture
    def two_nodes_with_audiofiles(
        self, tmp_path: Path
    ) -> Generator[Tuple[SyncNode, SyncNode], None, None]:
        """Two sync nodes with audiofile_directory configured."""
        from .conftest import (
            DEVICE_A_ID,
            DEVICE_B_ID,
            create_sync_node,
            start_sync_server,
        )

        node_a = create_sync_node("NodeA", DEVICE_A_ID, tmp_path)
        node_b = create_sync_node("NodeB", DEVICE_B_ID, tmp_path)

        # Create audiofile directories
        audiodir_a = tmp_path / "audiofiles_a"
        audiodir_b = tmp_path / "audiofiles_b"
        audiodir_a.mkdir()
        audiodir_b.mkdir()

        # Configure audiofile directories
        node_a.config.set_audiofile_directory(str(audiodir_a))
        node_b.config.set_audiofile_directory(str(audiodir_b))

        # Configure as peers
        node_a.config.add_peer(
            peer_id=node_b.device_id_hex,
            peer_name=node_b.name,
            peer_url=node_b.url,
        )
        node_b.config.add_peer(
            peer_id=node_a.device_id_hex,
            peer_name=node_a.name,
            peer_url=node_a.url,
        )

        # Start servers
        start_sync_server(node_a)
        start_sync_server(node_b)

        if not node_a.wait_for_server():
            pytest.fail("Failed to start sync server A")
        if not node_b.wait_for_server():
            pytest.fail("Failed to start sync server B")

        yield node_a, node_b

        node_a.stop_server()
        node_b.stop_server()
        node_a.db.close()
        node_b.db.close()

    def test_client_uploads_audio_to_server_during_sync(
        self, two_nodes_with_audiofiles: Tuple[SyncNode, SyncNode]
    ) -> None:
        """Test that audio file on client is uploaded to server during sync.

        This tests the full flow:
        1. Client creates a note with an audio file attachment
        2. Client syncs to server
        3. Server receives both metadata AND binary file
        """
        from voicecore import SyncClient

        node_a, node_b = two_nodes_with_audiofiles

        # Create audio file content
        test_audio_content = b"FAKE_AUDIO_DATA_FOR_TESTING_" * 100

        # Create note and audio file on node A (client)
        set_local_device_id(node_a.device_id)
        note_id = node_a.db.create_note("Note with audio attachment")
        audio_id = node_a.db.create_audio_file(
            "recording.ogg", file_created_at="2024-06-15 10:30:00"
        )
        node_a.db.attach_to_note(note_id, audio_id, "audio_file")

        # Store the actual binary file in A's audiofile_directory
        audiodir_a = Path(node_a.config.get_audiofile_directory())
        audio_file_a = audiodir_a / f"{audio_id}.ogg"
        audio_file_a.write_bytes(test_audio_content)

        # Verify initial state
        assert node_a.db.get_note(note_id) is not None
        assert node_a.db.get_audio_file(audio_id) is not None
        assert len(node_a.db.get_audio_files_for_note(note_id)) == 1

        # Sync A -> B (client pushes to server)
        result = sync_nodes(node_a, node_b)
        assert result["success"] is True, f"Sync failed: {result}"

        # Now upload the binary file
        sync_client = SyncClient(str(node_a.config_dir))
        upload_result = sync_client.upload_audio_file(
            node_b.url, audio_id, str(audio_file_a)
        )
        assert upload_result["success"], f"Upload failed: {upload_result}"

        # Reload B's database to see changes from server subprocess
        node_b.reload_db()

        # Verify B has the note
        note_b = node_b.db.get_note(note_id)
        assert note_b is not None, "Note should exist on server after sync"
        assert note_b["content"] == "Note with audio attachment"

        # Verify B has the audio file metadata
        audio_b = node_b.db.get_audio_file(audio_id)
        assert audio_b is not None, "Audio file should exist on server after sync"
        assert audio_b["filename"] == "recording.ogg"

        # Verify B has the attachment association
        attachments_b = node_b.db.get_audio_files_for_note(note_id)
        assert len(attachments_b) == 1, "Note should have one audio attachment"

        # Verify B has the actual binary file
        audiodir_b = Path(node_b.config.get_audiofile_directory())
        audio_file_b = audiodir_b / f"{audio_id}.ogg"
        assert audio_file_b.exists(), (
            f"Binary audio file should exist on server at {audio_file_b}"
        )
        assert audio_file_b.read_bytes() == test_audio_content, (
            "Audio file content should match"
        )

    def test_client_downloads_audio_from_server_during_sync(
        self, two_nodes_with_audiofiles: Tuple[SyncNode, SyncNode]
    ) -> None:
        """Test that audio file on server is downloaded to client during sync.

        This tests the full flow:
        1. Server has a note with an audio file attachment
        2. Client syncs from server
        3. Client receives both metadata AND binary file
        """
        from voicecore import SyncClient

        node_a, node_b = two_nodes_with_audiofiles

        # Create audio file content
        test_audio_content = b"SERVER_AUDIO_DATA_FOR_TESTING_" * 100

        # Create note and audio file on node B (server)
        set_local_device_id(node_b.device_id)
        note_id = node_b.db.create_note("Server note with audio")
        audio_id = node_b.db.create_audio_file(
            "server-recording.mp3", file_created_at="2024-07-20 14:00:00"
        )
        node_b.db.attach_to_note(note_id, audio_id, "audio_file")

        # Store the actual binary file in B's audiofile_directory
        audiodir_b = Path(node_b.config.get_audiofile_directory())
        audio_file_b = audiodir_b / f"{audio_id}.mp3"
        audio_file_b.write_bytes(test_audio_content)

        # Verify initial state on B
        assert node_b.db.get_note(note_id) is not None
        assert node_b.db.get_audio_file(audio_id) is not None

        # A should not have anything yet
        assert node_a.db.get_note(note_id) is None

        # Sync A -> B (A pulls from B)
        result = sync_nodes(node_a, node_b)
        assert result["success"] is True, f"Sync failed: {result}"

        # Verify A has the note
        note_a = node_a.db.get_note(note_id)
        assert note_a is not None, "Note should exist on client after sync"
        assert note_a["content"] == "Server note with audio"

        # Verify A has the audio file metadata
        audio_a = node_a.db.get_audio_file(audio_id)
        assert audio_a is not None, "Audio file metadata should exist on client"
        assert audio_a["filename"] == "server-recording.mp3"

        # Verify A has the attachment association
        attachments_a = node_a.db.get_audio_files_for_note(note_id)
        assert len(attachments_a) == 1, "Note should have one audio attachment"

        # Now download the binary file
        sync_client = SyncClient(str(node_a.config_dir))
        audiodir_a = Path(node_a.config.get_audiofile_directory())
        audio_file_a = audiodir_a / f"{audio_id}.mp3"

        download_result = sync_client.download_audio_file(
            node_b.url, audio_id, str(audio_file_a)
        )
        assert download_result["success"], f"Download failed: {download_result}"

        # Verify A has the actual binary file
        assert audio_file_a.exists(), (
            f"Binary audio file should exist on client at {audio_file_a}"
        )
        assert audio_file_a.read_bytes() == test_audio_content, (
            "Downloaded audio file content should match server's"
        )

    def test_audio_attachment_sync_handles_out_of_order_changes(
        self, two_nodes_with_audiofiles: Tuple[SyncNode, SyncNode]
    ) -> None:
        """Test that audio file sync works even when changes arrive out of order.

        This is a regression test for the FOREIGN KEY constraint bug where
        note_attachment changes arrived before note/audio_file changes.
        """
        node_a, node_b = two_nodes_with_audiofiles

        # Create note and audio file on node A
        set_local_device_id(node_a.device_id)
        note_id = node_a.db.create_note("Note for ordering test")
        audio_id = node_a.db.create_audio_file("ordering-test.wav")
        node_a.db.attach_to_note(note_id, audio_id, "audio_file")

        # Sync A -> B
        result = sync_nodes(node_a, node_b)
        assert result["success"] is True, f"Sync failed: {result}"
        assert len(result["errors"]) == 0, f"Sync had errors: {result['errors']}"

        # Reload B's database
        node_b.reload_db()

        # Verify everything synced correctly
        note_b = node_b.db.get_note(note_id)
        assert note_b is not None, "Note should exist after sync"

        audio_b = node_b.db.get_audio_file(audio_id)
        assert audio_b is not None, "Audio file should exist after sync"

        attachments_b = node_b.db.get_audio_files_for_note(note_id)
        assert len(attachments_b) == 1, "Attachment should exist after sync"

    def test_multiple_audio_files_sync(
        self, two_nodes_with_audiofiles: Tuple[SyncNode, SyncNode]
    ) -> None:
        """Test syncing a note with multiple audio attachments."""
        node_a, node_b = two_nodes_with_audiofiles

        # Create note with multiple audio files on node A
        set_local_device_id(node_a.device_id)
        note_id = node_a.db.create_note("Note with multiple audio files")

        audio_ids = []
        for i in range(5):
            audio_id = node_a.db.create_audio_file(f"recording_{i}.mp3")
            node_a.db.attach_to_note(note_id, audio_id, "audio_file")
            audio_ids.append(audio_id)

        # Sync A -> B
        result = sync_nodes(node_a, node_b)
        assert result["success"] is True

        # Reload B's database
        node_b.reload_db()

        # Verify all audio files synced
        attachments_b = node_b.db.get_audio_files_for_note(note_id)
        assert len(attachments_b) == 5, "All 5 audio files should be attached"

        for audio_id in audio_ids:
            audio_b = node_b.db.get_audio_file(audio_id)
            assert audio_b is not None, f"Audio file {audio_id} should exist"

    def test_automatic_binary_sync_on_push(
        self, two_nodes_with_audiofiles: Tuple[SyncNode, SyncNode]
    ) -> None:
        """Test that binary files are automatically uploaded during sync.

        This verifies the fix for the atomicity issue where metadata would
        sync but binary files required a separate manual upload.
        """
        node_a, node_b = two_nodes_with_audiofiles

        # Create audio file with binary content on node A
        test_content = b"AUTOMATIC_BINARY_SYNC_TEST_DATA_" * 50

        set_local_device_id(node_a.device_id)
        note_id = node_a.db.create_note("Auto binary sync test")
        audio_id = node_a.db.create_audio_file("auto-sync.mp3")
        node_a.db.attach_to_note(note_id, audio_id, "audio_file")

        # Write binary file to A's directory
        audiodir_a = Path(node_a.config.get_audiofile_directory())
        (audiodir_a / f"{audio_id}.mp3").write_bytes(test_content)

        # Sync A -> B (should automatically upload binary)
        result = sync_nodes(node_a, node_b)
        assert result["success"] is True, f"Sync failed: {result}"

        # Verify binary file exists on B (without manual upload)
        audiodir_b = Path(node_b.config.get_audiofile_directory())
        binary_b = audiodir_b / f"{audio_id}.mp3"
        assert binary_b.exists(), (
            "Binary file should be automatically uploaded during sync"
        )
        assert binary_b.read_bytes() == test_content

    def test_automatic_binary_sync_on_pull(
        self, two_nodes_with_audiofiles: Tuple[SyncNode, SyncNode]
    ) -> None:
        """Test that binary files are automatically downloaded during sync.

        This verifies the fix for the atomicity issue where metadata would
        sync but binary files required a separate manual download.
        """
        node_a, node_b = two_nodes_with_audiofiles

        # Create audio file with binary content on node B (server)
        test_content = b"AUTOMATIC_BINARY_DOWNLOAD_TEST_" * 50

        set_local_device_id(node_b.device_id)
        note_id = node_b.db.create_note("Auto binary download test")
        audio_id = node_b.db.create_audio_file("auto-download.ogg")
        node_b.db.attach_to_note(note_id, audio_id, "audio_file")

        # Write binary file to B's directory
        audiodir_b = Path(node_b.config.get_audiofile_directory())
        (audiodir_b / f"{audio_id}.ogg").write_bytes(test_content)

        # A should not have the file yet
        audiodir_a = Path(node_a.config.get_audiofile_directory())
        binary_a = audiodir_a / f"{audio_id}.ogg"
        assert not binary_a.exists()

        # Sync A -> B (A pulls from B, should automatically download binary)
        result = sync_nodes(node_a, node_b)
        assert result["success"] is True, f"Sync failed: {result}"

        # Verify binary file was automatically downloaded to A
        assert binary_a.exists(), (
            "Binary file should be automatically downloaded during sync"
        )
        assert binary_a.read_bytes() == test_content

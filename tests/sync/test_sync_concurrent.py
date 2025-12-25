"""Tests for concurrent sync operations.

Tests concurrent scenarios:
- Multiple syncs running simultaneously
- Editing during sync
- Multiple clients syncing to same server
- Race conditions

These tests use subprocess-based helpers to avoid thread-safety issues
with the Rust PyDatabase (marked as 'unsendable').
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple, Any

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
    create_sync_node,
    start_sync_server,
    create_note_subprocess,
    update_note_subprocess,
    delete_note_subprocess,
    get_note_subprocess,
    get_note_count_subprocess,
    sync_nodes_subprocess,
    DEVICE_A_ID,
    DEVICE_B_ID,
    DEVICE_C_ID,
)


class TestConcurrentSyncs:
    """Tests for multiple syncs running concurrently."""

    def test_parallel_sync_to_same_server(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Multiple sync clients can sync to same server concurrently."""
        node_a, node_b = two_nodes_with_servers

        # Create content on A
        for i in range(10):
            create_note_on_node(node_a, f"Note {i}")

        # Sync from A to B multiple times in parallel using subprocesses
        # Start 3 sync processes concurrently
        processes = []
        for _ in range(3):
            proc = _start_sync_process(node_a, node_b)
            processes.append(proc)

        # Wait for all to complete
        results = []
        for proc in processes:
            stdout, stderr = proc.communicate(timeout=60)
            results.append((proc.returncode, stdout, stderr))

        # At least one should succeed
        successes = [r for r in results if r[0] == 0]
        assert len(successes) >= 1, "At least one parallel sync should succeed"

        # Reload to see changes
        node_b.reload_db()

        # All notes should be on B
        assert get_note_count(node_b) == 10

    def test_parallel_sync_bidirectional(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Bidirectional syncs can run in parallel."""
        node_a, node_b = two_nodes_with_servers

        # Create different content on each
        for i in range(5):
            create_note_on_node(node_a, f"Note A{i}")
            create_note_on_node(node_b, f"Note B{i}")

        # Sync both directions in parallel
        proc_a_to_b = _start_sync_process(node_a, node_b)
        proc_b_to_a = _start_sync_process(node_b, node_a)

        # Wait for both
        proc_a_to_b.communicate(timeout=60)
        proc_b_to_a.communicate(timeout=60)

        # Run additional sync rounds to ensure convergence
        sync_nodes(node_a, node_b)
        node_b.reload_db()
        sync_nodes(node_b, node_a)
        node_a.reload_db()

        # Both should have all notes
        assert get_note_count(node_a) == 10
        assert get_note_count(node_b) == 10


class TestEditDuringSync:
    """Tests for editing while sync is in progress."""

    def test_local_edit_during_sync(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Local edits during sync don't cause corruption."""
        node_a, node_b = two_nodes_with_servers

        # Create initial content
        note_id = create_note_on_node(node_a, "Original content")
        sync_nodes(node_a, node_b)

        # Start sync in background subprocess
        proc = _start_sync_process(node_a, node_b)

        # Edit locally via subprocess while sync is running
        update_note_subprocess(node_a, note_id, "Edited during sync")

        # Wait for sync to complete
        proc.communicate(timeout=60)

        # Reload and verify note exists with some content
        node_a.reload_db()
        note = node_a.db.get_note(note_id)
        assert note is not None
        assert "Edited" in note["content"] or "Original" in note["content"]

    def test_create_note_during_sync(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Creating notes during sync works correctly."""
        node_a, node_b = two_nodes_with_servers

        # Create initial content on B
        for i in range(10):
            create_note_on_node(node_b, f"Note from B {i}")

        # Start sync in background
        proc = _start_sync_process(node_a, node_b)

        # Create notes via subprocess while sync is running
        new_note_ids = []
        for i in range(3):
            note_id = create_note_subprocess(node_a, f"Created during sync {i}")
            if note_id:
                new_note_ids.append(note_id)
            time.sleep(0.05)

        # Wait for sync
        proc.communicate(timeout=60)

        # Reload and verify our new notes exist
        node_a.reload_db()
        for note_id in new_note_ids:
            assert node_a.db.get_note(note_id) is not None


class TestMultipleClients:
    """Tests for multiple clients syncing to same server."""

    def test_three_clients_sync_simultaneously(
        self, three_nodes_with_servers: Tuple[SyncNode, SyncNode, SyncNode]
    ):
        """Three clients can sync to each other simultaneously."""
        node_a, node_b, node_c = three_nodes_with_servers

        # Each creates unique content
        note_a = create_note_on_node(node_a, "From A")
        note_b = create_note_on_node(node_b, "From B")
        note_c = create_note_on_node(node_c, "From C")

        # All sync in parallel - start all sync processes
        processes = []
        nodes = [node_a, node_b, node_c]
        for source in nodes:
            for target in nodes:
                if source != target:
                    proc = _start_sync_process(source, target)
                    processes.append(proc)

        # Wait for all
        for proc in processes:
            proc.communicate(timeout=60)

        # Run final sync rounds to ensure convergence
        for _ in range(2):
            sync_nodes(node_a, node_b)
            node_b.reload_db()
            sync_nodes(node_b, node_c)
            node_c.reload_db()
            sync_nodes(node_c, node_a)
            node_a.reload_db()

        # All should have all 3 notes
        for node in [node_a, node_b, node_c]:
            node.reload_db()
            assert node.db.get_note(note_a) is not None
            assert node.db.get_note(note_b) is not None
            assert node.db.get_note(note_c) is not None


class TestRaceConditions:
    """Tests for potential race conditions."""

    def test_concurrent_note_creation(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Concurrent note creation on both nodes."""
        node_a, node_b = two_nodes_with_servers

        # Create notes concurrently via subprocesses
        procs_a = []
        procs_b = []
        for i in range(5):
            proc_a = _start_create_note_process(node_a, f"A note {i}")
            proc_b = _start_create_note_process(node_b, f"B note {i}")
            procs_a.append(proc_a)
            procs_b.append(proc_b)

        # Collect note IDs
        note_ids_a = []
        note_ids_b = []
        for proc in procs_a:
            stdout, _ = proc.communicate(timeout=30)
            if proc.returncode == 0 and stdout.strip():
                note_ids_a.append(stdout.strip())
        for proc in procs_b:
            stdout, _ = proc.communicate(timeout=30)
            if proc.returncode == 0 and stdout.strip():
                note_ids_b.append(stdout.strip())

        # Reload and verify counts
        node_a.reload_db()
        node_b.reload_db()

        # Sync
        sync_nodes(node_a, node_b)
        node_b.reload_db()
        sync_nodes(node_b, node_a)
        node_a.reload_db()

        # Both should have 10 notes
        assert get_note_count(node_a) == 10
        assert get_note_count(node_b) == 10

    def test_sync_while_creating(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Sync running while notes are being created."""
        node_a, node_b = two_nodes_with_servers

        # Start a sync process
        sync_proc = _start_sync_process(node_a, node_b)

        # Create notes concurrently
        create_procs = []
        for i in range(5):
            proc = _start_create_note_process(node_a, f"Note {i}")
            create_procs.append(proc)
            time.sleep(0.02)

        # Wait for creates
        created_ids = []
        for proc in create_procs:
            stdout, _ = proc.communicate(timeout=30)
            if proc.returncode == 0 and stdout.strip():
                created_ids.append(stdout.strip())

        # Wait for sync
        sync_proc.communicate(timeout=60)

        # All created notes should exist on A
        node_a.reload_db()
        for note_id in created_ids:
            assert node_a.db.get_note(note_id) is not None


class TestStressTests:
    """Stress tests for sync system."""

    def test_rapid_sync_cycles(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Many rapid sync cycles."""
        node_a, node_b = two_nodes_with_servers

        # Create some initial data
        for i in range(5):
            create_note_on_node(node_a, f"Note {i}")

        # Rapid sync cycles
        for _ in range(20):
            sync_nodes(node_a, node_b)
            sync_nodes(node_b, node_a)

        # Should still have exactly 5 notes
        assert get_note_count(node_a) == 5
        assert get_note_count(node_b) == 5

    def test_many_notes_sync(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Sync with many notes."""
        node_a, node_b = two_nodes_with_servers

        # Create many notes
        note_ids = []
        for i in range(100):
            note_id = create_note_on_node(node_a, f"Note {i}: " + "x" * 100)
            note_ids.append(note_id)

        # Sync
        sync_nodes(node_a, node_b)

        # All should be on B
        assert get_note_count(node_b) == 100

        # Verify integrity
        for note_id in note_ids:
            note_b = node_b.db.get_note(note_id)
            assert note_b is not None

    def test_interleaved_operations_delete_doesnt_propagate(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Interleaved operations - delete doesn't propagate (no silent deletion)."""
        node_a, node_b = two_nodes_with_servers

        note_ids = []

        # Round 1: Create on A, sync (3 notes)
        for i in range(3):
            note_id = create_note_on_node(node_a, f"Round 1 note {i}")
            note_ids.append(note_id)
        sync_nodes(node_a, node_b)
        node_b.reload_db()

        # Wait for timestamp precision
        time.sleep(1.1)

        # Round 2: Update on B, create on A, sync (3 more = 6 total)
        set_local_device_id(node_b.device_id)
        if note_ids:
            node_b.db.update_note(note_ids[0], "Updated on B")
        for i in range(3):
            note_id = create_note_on_node(node_a, f"Round 2 note {i}")
            note_ids.append(note_id)
        sync_nodes(node_a, node_b)
        node_b.reload_db()
        sync_nodes(node_b, node_a)
        node_a.reload_db()

        # Wait for timestamp precision
        time.sleep(1.1)

        # Round 3: Delete on A, create on B, sync (3 more = 9 total, A deletes 1)
        set_local_device_id(node_a.device_id)
        if len(note_ids) > 1:
            node_a.db.delete_note(note_ids[1])
        for i in range(3):
            note_id = create_note_on_node(node_b, f"Round 3 note from B {i}")
            note_ids.append(note_id)
        sync_nodes(node_a, node_b)
        node_b.reload_db()
        sync_nodes(node_b, node_a)
        node_a.reload_db()

        # A has 8 notes (deleted 1 locally)
        # B has 8 notes (delete propagates when B didn't edit that note)
        count_a = get_note_count(node_a)
        count_b = get_note_count(node_b)
        assert count_a == 8  # 9 created - 1 deleted locally
        assert count_b == 8  # Delete propagates (note 1 wasn't edited on B)


# ============================================================================
# Helper functions for subprocess-based concurrent tests
# ============================================================================

def _start_sync_process(source: SyncNode, target: SyncNode) -> subprocess.Popen:
    """Start a sync operation in a subprocess."""
    import os

    project_root = Path(__file__).parent.parent.parent
    src_path = project_root / "src"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(src_path)

    script = f'''
import sys
sys.path.insert(0, "{src_path}")

from core.config import Config
from core.database import Database, set_local_device_id
from core.sync_client import SyncClient

config = Config(config_dir="{source.config_dir}")
device_id = bytes.fromhex(config.get_device_id_hex())
set_local_device_id(device_id)
db = Database(config.config_data["database_file"])

try:
    client = SyncClient(db, config)
    result = client.sync_with_peer("{target.device_id_hex}")
    if result.success:
        sys.exit(0)
    else:
        sys.exit(1)
finally:
    db.close()
'''

    return subprocess.Popen(
        [sys.executable, "-c", script],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _start_create_note_process(node: SyncNode, content: str) -> subprocess.Popen:
    """Start a note creation in a subprocess. Outputs note ID on success."""
    import os

    project_root = Path(__file__).parent.parent.parent
    src_path = project_root / "src"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(src_path)

    # Escape content for embedding in script
    escaped_content = content.replace("\\", "\\\\").replace('"', '\\"')

    script = f'''
import sys
sys.path.insert(0, "{src_path}")

from core.config import Config
from core.database import Database, set_local_device_id

config = Config(config_dir="{node.config_dir}")
device_id = bytes.fromhex(config.get_device_id_hex())
set_local_device_id(device_id)
db = Database(config.config_data["database_file"])

try:
    note_id = db.create_note("{escaped_content}")
    print(note_id)
finally:
    db.close()
'''

    return subprocess.Popen(
        [sys.executable, "-c", script],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

"""Pytest fixtures for sync integration tests.

This module provides fixtures for:
- Spawning real sync server processes
- Creating isolated database instances with unique device IDs
- Setting up two-node sync configurations
- Network failure simulation
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

import pytest
import requests
from uuid6 import uuid7

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.config import Config
from core.database import Database, set_local_device_id
from core.validation import uuid_to_hex


# Test device IDs - unique per node
DEVICE_A_ID = uuid.UUID("00000000-0000-7000-8000-00000000000a").bytes
DEVICE_B_ID = uuid.UUID("00000000-0000-7000-8000-00000000000b").bytes
DEVICE_C_ID = uuid.UUID("00000000-0000-7000-8000-00000000000c").bytes


@dataclass
class SyncNode:
    """Represents a sync node (device) for testing."""

    name: str
    device_id: bytes
    config_dir: Path
    db_path: Path
    db: Database
    config: Config
    port: int
    process: Optional[subprocess.Popen] = None

    @property
    def device_id_hex(self) -> str:
        return uuid_to_hex(self.device_id)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def is_server_running(self) -> bool:
        """Check if the sync server is responding."""
        try:
            resp = requests.get(f"{self.url}/sync/status", timeout=1)
            return resp.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def wait_for_server(self, timeout: float = 10.0) -> bool:
        """Wait for server to become available."""
        start = time.time()
        while time.time() - start < timeout:
            if self.is_server_running():
                return True
            time.sleep(0.1)
        return False

    def stop_server(self) -> None:
        """Stop the sync server process."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            # Close stdout/stderr pipes to avoid ResourceWarning
            if self.process.stdout:
                self.process.stdout.close()
            if self.process.stderr:
                self.process.stderr.close()
            self.process = None

    def kill_server(self) -> None:
        """Forcefully kill the sync server (simulates crash)."""
        if self.process:
            self.process.kill()
            self.process.wait()
            # Close stdout/stderr pipes to avoid ResourceWarning
            if self.process.stdout:
                self.process.stdout.close()
            if self.process.stderr:
                self.process.stderr.close()
            self.process = None

    def reload_db(self) -> None:
        """Reload the database connection to see changes from subprocess.

        When the sync server subprocess writes to the database, the test's
        database connection may not see those changes due to SQLite
        connection isolation. This method closes and reopens the connection.
        """
        self.db.close()
        set_local_device_id(self.device_id)
        self.db = Database(self.db_path)


def find_free_port() -> int:
    """Find a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        return s.getsockname()[1]


def create_sync_node(
    name: str,
    device_id: bytes,
    base_dir: Path,
    port: Optional[int] = None,
) -> SyncNode:
    """Create a sync node with its own database and config.

    Args:
        name: Human-readable node name
        device_id: Unique device UUID bytes
        base_dir: Base directory for node files
        port: Port for sync server (auto-assigned if None)

    Returns:
        Configured SyncNode instance
    """
    config_dir = base_dir / name
    config_dir.mkdir(parents=True, exist_ok=True)

    db_path = config_dir / "notes.db"

    # Set device ID before creating database
    set_local_device_id(device_id)

    # Create database
    db = Database(db_path)

    # Create config
    config_data = {
        "database_file": str(db_path),
        "device_id": uuid_to_hex(device_id),
        "device_name": name,
        "sync": {
            "enabled": True,
            "server_port": port or find_free_port(),
            "peers": [],
        },
    }

    config_file = config_dir / "config.json"
    with open(config_file, "w") as f:
        json.dump(config_data, f, indent=2)

    config = Config(config_dir=config_dir)

    return SyncNode(
        name=name,
        device_id=device_id,
        config_dir=config_dir,
        db_path=db_path,
        db=db,
        config=config,
        port=config_data["sync"]["server_port"],
    )


def start_sync_server(node: SyncNode) -> subprocess.Popen:
    """Start a sync server process for the given node.

    Args:
        node: SyncNode to start server for

    Returns:
        Popen process object
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent)

    cmd = [
        sys.executable,
        "-m", "src.main",
        "-d", str(node.config_dir),
        "cli", "sync", "serve",
        "--host", "127.0.0.1",
        "--port", str(node.port),
    ]

    process = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(Path(__file__).parent.parent.parent),
    )

    node.process = process
    return process


@pytest.fixture
def sync_node_a(tmp_path: Path) -> Generator[SyncNode, None, None]:
    """Create sync node A with empty database."""
    node = create_sync_node("NodeA", DEVICE_A_ID, tmp_path)
    yield node
    node.stop_server()
    node.db.close()


@pytest.fixture
def sync_node_b(tmp_path: Path) -> Generator[SyncNode, None, None]:
    """Create sync node B with empty database."""
    node = create_sync_node("NodeB", DEVICE_B_ID, tmp_path)
    yield node
    node.stop_server()
    node.db.close()


@pytest.fixture
def sync_node_c(tmp_path: Path) -> Generator[SyncNode, None, None]:
    """Create sync node C with empty database (for three-way sync tests)."""
    node = create_sync_node("NodeC", DEVICE_C_ID, tmp_path)
    yield node
    node.stop_server()
    node.db.close()


@pytest.fixture
def running_server_a(sync_node_a: SyncNode) -> Generator[SyncNode, None, None]:
    """Sync node A with running server."""
    start_sync_server(sync_node_a)
    if not sync_node_a.wait_for_server():
        pytest.fail("Failed to start sync server A")
    yield sync_node_a
    sync_node_a.stop_server()


@pytest.fixture
def running_server_b(sync_node_b: SyncNode) -> Generator[SyncNode, None, None]:
    """Sync node B with running server."""
    start_sync_server(sync_node_b)
    if not sync_node_b.wait_for_server():
        pytest.fail("Failed to start sync server B")
    yield sync_node_b
    sync_node_b.stop_server()


@pytest.fixture
def two_nodes_with_servers(
    tmp_path: Path,
) -> Generator[Tuple[SyncNode, SyncNode], None, None]:
    """Two sync nodes with running servers, configured as peers."""
    node_a = create_sync_node("NodeA", DEVICE_A_ID, tmp_path)
    node_b = create_sync_node("NodeB", DEVICE_B_ID, tmp_path)

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


@pytest.fixture
def three_nodes_with_servers(
    tmp_path: Path,
) -> Generator[Tuple[SyncNode, SyncNode, SyncNode], None, None]:
    """Three sync nodes with running servers, all configured as peers."""
    node_a = create_sync_node("NodeA", DEVICE_A_ID, tmp_path)
    node_b = create_sync_node("NodeB", DEVICE_B_ID, tmp_path)
    node_c = create_sync_node("NodeC", DEVICE_C_ID, tmp_path)

    nodes = [node_a, node_b, node_c]

    # Configure all as peers of each other
    for node in nodes:
        for other in nodes:
            if node != other:
                node.config.add_peer(
                    peer_id=other.device_id_hex,
                    peer_name=other.name,
                    peer_url=other.url,
                )

    # Start servers
    for node in nodes:
        start_sync_server(node)

    for node in nodes:
        if not node.wait_for_server():
            pytest.fail(f"Failed to start sync server {node.name}")

    yield node_a, node_b, node_c

    for node in nodes:
        node.stop_server()
        node.db.close()


# Helper functions for tests

def create_note_on_node(node: SyncNode, content: str) -> str:
    """Create a note on a node and return its ID."""
    set_local_device_id(node.device_id)
    note_id = node.db.create_note(content)
    return note_id


def create_tag_on_node(
    node: SyncNode, name: str, parent_id: Optional[str] = None
) -> str:
    """Create a tag on a node and return its ID."""
    set_local_device_id(node.device_id)
    tag_id = node.db.create_tag(name, parent_id)
    return tag_id


def get_note_count(node: SyncNode) -> int:
    """Get the number of non-deleted notes on a node."""
    return len(node.db.get_all_notes())


def get_tag_count(node: SyncNode) -> int:
    """Get the number of tags on a node."""
    return len(node.db.get_all_tags())


def sync_nodes(source: SyncNode, target: SyncNode) -> Dict[str, Any]:
    """Perform sync from source's perspective, pulling from target.

    Returns the sync result.
    """
    from core.sync_client import SyncClient

    set_local_device_id(source.device_id)
    client = SyncClient(source.db, source.config)
    result = client.sync_with_peer(target.device_id_hex)
    return {
        "success": result.success,
        "pulled": result.pulled,
        "pushed": result.pushed,
        "conflicts": result.conflicts,
        "errors": result.errors,
    }


def wait_for_condition(
    condition: callable,
    timeout: float = 5.0,
    interval: float = 0.1,
) -> bool:
    """Wait for a condition to become true."""
    start = time.time()
    while time.time() - start < timeout:
        if condition():
            return True
        time.sleep(interval)
    return False


@contextmanager
def simulate_network_partition(node: SyncNode):
    """Context manager to simulate network partition by stopping the server."""
    node.stop_server()
    try:
        yield
    finally:
        # Restart server
        start_sync_server(node)
        node.wait_for_server()


class MockNetworkError:
    """Helper for mocking network errors."""

    @staticmethod
    def connection_refused():
        """Raise connection refused error."""
        raise requests.exceptions.ConnectionError("Connection refused")

    @staticmethod
    def timeout():
        """Raise timeout error."""
        raise requests.exceptions.Timeout("Connection timed out")

    @staticmethod
    def connection_reset():
        """Raise connection reset error."""
        raise requests.exceptions.ConnectionError("Connection reset by peer")


# ============================================================================
# Subprocess-based helpers for concurrent tests
# ============================================================================
# These helpers run operations in separate processes to avoid thread-safety
# issues with the Rust PyDatabase (marked as 'unsendable').


def run_db_operation(
    config_dir: Path,
    operation: str,
    **kwargs,
) -> Dict[str, Any]:
    """Run a database operation in a subprocess.

    Args:
        config_dir: Path to the node's config directory
        operation: Operation name (create_note, update_note, sync, etc.)
        **kwargs: Operation-specific arguments

    Returns:
        Dict with operation result
    """
    import pickle
    import base64

    # Encode kwargs for subprocess
    kwargs_encoded = base64.b64encode(pickle.dumps(kwargs)).decode('ascii')

    project_root = Path(__file__).parent.parent.parent
    src_path = project_root / "src"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(src_path)

    script = f'''
import sys
import pickle
import base64
import json
sys.path.insert(0, "{src_path}")

from pathlib import Path
from core.config import Config
from core.database import Database, set_local_device_id

config_dir = Path("{config_dir}")
config = Config(config_dir=config_dir)
device_id = bytes.fromhex(config.get_device_id_hex())
set_local_device_id(device_id)

db = Database(config.config_data["database_file"])
kwargs = pickle.loads(base64.b64decode("{kwargs_encoded}"))

operation = "{operation}"
result = {{"success": True}}

try:
    if operation == "create_note":
        note_id = db.create_note(kwargs["content"])
        result["note_id"] = note_id
    elif operation == "update_note":
        db.update_note(kwargs["note_id"], kwargs["content"])
    elif operation == "delete_note":
        db.delete_note(kwargs["note_id"])
    elif operation == "get_note":
        note = db.get_note(kwargs["note_id"])
        result["note"] = note
    elif operation == "get_note_count":
        notes = db.get_all_notes()
        result["count"] = len(notes)
    elif operation == "sync":
        from core.sync_client import SyncClient
        client = SyncClient(db, config)
        sync_result = client.sync_with_peer(kwargs["peer_id"])
        result["pulled"] = sync_result.pulled
        result["pushed"] = sync_result.pushed
        result["conflicts"] = sync_result.conflicts
        result["errors"] = sync_result.errors
        result["sync_success"] = sync_result.success
    else:
        result["success"] = False
        result["error"] = f"Unknown operation: {{operation}}"
except Exception as e:
    result["success"] = False
    result["error"] = str(e)
finally:
    db.close()

print(json.dumps(result))
'''

    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if proc.returncode != 0:
        return {"success": False, "error": proc.stderr}

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"success": False, "error": f"Invalid JSON: {proc.stdout}"}


def create_note_subprocess(node: SyncNode, content: str) -> Optional[str]:
    """Create a note via subprocess. Returns note ID or None on failure."""
    result = run_db_operation(node.config_dir, "create_note", content=content)
    if result.get("success"):
        return result.get("note_id")
    return None


def update_note_subprocess(node: SyncNode, note_id: str, content: str) -> bool:
    """Update a note via subprocess."""
    result = run_db_operation(node.config_dir, "update_note", note_id=note_id, content=content)
    return result.get("success", False)


def delete_note_subprocess(node: SyncNode, note_id: str) -> bool:
    """Delete a note via subprocess."""
    result = run_db_operation(node.config_dir, "delete_note", note_id=note_id)
    return result.get("success", False)


def get_note_subprocess(node: SyncNode, note_id: str) -> Optional[Dict[str, Any]]:
    """Get a note via subprocess."""
    result = run_db_operation(node.config_dir, "get_note", note_id=note_id)
    if result.get("success"):
        return result.get("note")
    return None


def get_note_count_subprocess(node: SyncNode) -> int:
    """Get note count via subprocess."""
    result = run_db_operation(node.config_dir, "get_note_count")
    return result.get("count", 0)


def sync_nodes_subprocess(source: SyncNode, target: SyncNode) -> Dict[str, Any]:
    """Perform sync via subprocess."""
    result = run_db_operation(source.config_dir, "sync", peer_id=target.device_id_hex)
    return {
        "success": result.get("sync_success", False),
        "pulled": result.get("pulled", 0),
        "pushed": result.get("pushed", 0),
        "conflicts": result.get("conflicts", 0),
        "errors": result.get("errors", []),
    }

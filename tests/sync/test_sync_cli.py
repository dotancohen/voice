"""Tests for sync CLI commands via subprocess.

Tests all sync CLI subcommands:
- sync status
- sync list-peers
- sync add-peer
- sync remove-peer
- sync now
- sync conflicts
- sync resolve
- sync serve
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.database import set_local_device_id

from .conftest import (
    SyncNode,
    create_sync_node,
    create_note_on_node,
    start_sync_server,
    DEVICE_A_ID,
    DEVICE_B_ID,
)


def run_cli_command(
    config_dir: Path,
    args: List[str],
    timeout: float = 30.0,
    input_data: Optional[str] = None,
) -> Tuple[int, str, str]:
    """Run a CLI command and return (exit_code, stdout, stderr).

    Args:
        config_dir: Configuration directory for the command
        args: CLI arguments (after 'cli')
        timeout: Command timeout in seconds
        input_data: Optional stdin input

    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent)

    cmd = [
        sys.executable,
        "-m", "src.main",
        "-d", str(config_dir),
        "cli",
    ] + args

    result = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_data,
        cwd=str(Path(__file__).parent.parent.parent),
    )

    return result.returncode, result.stdout, result.stderr


class TestSyncStatusCLI:
    """Tests for 'sync status' command."""

    def test_sync_status_basic(self, sync_node_a: SyncNode):
        """Basic sync status shows device info."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "status"],
        )

        assert code == 0
        assert "Device ID:" in stdout
        assert "Device Name:" in stdout
        assert "NodeA" in stdout

    def test_sync_status_json_format(self, sync_node_a: SyncNode):
        """Sync status outputs valid JSON."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["--format", "json", "sync", "status"],
        )

        assert code == 0
        data = json.loads(stdout)
        assert "device_id" in data
        assert "device_name" in data
        assert data["device_name"] == "NodeA"

    def test_sync_status_shows_peer_count(self, sync_node_a: SyncNode):
        """Sync status shows number of configured peers."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "status"],
        )

        assert code == 0
        assert "Configured Peers:" in stdout

    def test_sync_status_shows_conflicts(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Sync status shows conflict counts."""
        node_a, node_b = two_nodes_with_servers

        code, stdout, stderr = run_cli_command(
            node_a.config_dir,
            ["--format", "json", "sync", "status"],
        )

        assert code == 0
        data = json.loads(stdout)
        assert "conflicts" in data
        assert "total" in data["conflicts"]


class TestSyncListPeersCLI:
    """Tests for 'sync list-peers' command."""

    def test_list_peers_empty(self, sync_node_a: SyncNode):
        """List peers when none configured."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "list-peers"],
        )

        assert code == 0
        assert "No sync peers configured" in stdout

    def test_list_peers_with_peer(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """List peers shows configured peer."""
        node_a, node_b = two_nodes_with_servers

        code, stdout, stderr = run_cli_command(
            node_a.config_dir,
            ["sync", "list-peers"],
        )

        assert code == 0
        assert "NodeB" in stdout
        assert node_b.device_id_hex in stdout

    def test_list_peers_json(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """List peers in JSON format."""
        node_a, node_b = two_nodes_with_servers

        code, stdout, stderr = run_cli_command(
            node_a.config_dir,
            ["--format", "json", "sync", "list-peers"],
        )

        assert code == 0
        data = json.loads(stdout)
        assert len(data) == 1
        assert data[0]["peer_name"] == "NodeB"

    def test_list_peers_csv(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """List peers in CSV format."""
        node_a, node_b = two_nodes_with_servers

        code, stdout, stderr = run_cli_command(
            node_a.config_dir,
            ["--format", "csv", "sync", "list-peers"],
        )

        assert code == 0
        assert "peer_id,peer_name,peer_url" in stdout
        assert "NodeB" in stdout


class TestSyncAddPeerCLI:
    """Tests for 'sync add-peer' command."""

    def test_add_peer_success(self, sync_node_a: SyncNode):
        """Add a peer successfully."""
        peer_id = "00000000000070008000000000000099"
        peer_name = "TestPeer"
        peer_url = "http://192.168.1.100:8384"

        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "add-peer", peer_id, peer_name, peer_url],
        )

        assert code == 0
        assert "Added peer:" in stdout
        assert peer_name in stdout

    def test_add_peer_json_output(self, sync_node_a: SyncNode):
        """Add peer with JSON output."""
        peer_id = "00000000000070008000000000000099"
        peer_name = "TestPeer"
        peer_url = "http://192.168.1.100:8384"

        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["--format", "json", "sync", "add-peer", peer_id, peer_name, peer_url],
        )

        assert code == 0
        data = json.loads(stdout)
        assert data["added"] is True
        assert data["peer_name"] == peer_name

    def test_add_peer_with_fingerprint(self, sync_node_a: SyncNode):
        """Add peer with certificate fingerprint."""
        peer_id = "00000000000070008000000000000099"
        peer_name = "SecurePeer"
        peer_url = "https://192.168.1.100:8384"
        fingerprint = "SHA256:aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99"

        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "add-peer", peer_id, peer_name, peer_url,
             "--fingerprint", fingerprint],
        )

        assert code == 0
        assert "Added peer:" in stdout

    def test_add_peer_invalid_id(self, sync_node_a: SyncNode):
        """Add peer with invalid device ID fails."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "add-peer", "invalid-id", "TestPeer", "http://localhost:8384"],
        )

        assert code == 1
        assert "Error" in stderr or "error" in stderr.lower() or "invalid" in stderr.lower()

    def test_add_peer_duplicate_fails(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Adding same peer twice fails."""
        node_a, node_b = two_nodes_with_servers

        # Try to add node_b again (already a peer)
        code, stdout, stderr = run_cli_command(
            node_a.config_dir,
            ["sync", "add-peer", node_b.device_id_hex, "NodeB2", node_b.url],
        )

        assert code == 1
        assert "Error" in stderr or "already" in stderr.lower()


class TestSyncRemovePeerCLI:
    """Tests for 'sync remove-peer' command."""

    def test_remove_peer_success(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Remove a peer successfully."""
        node_a, node_b = two_nodes_with_servers

        code, stdout, stderr = run_cli_command(
            node_a.config_dir,
            ["sync", "remove-peer", node_b.device_id_hex],
        )

        assert code == 0
        assert "Removed peer:" in stdout

    def test_remove_peer_json_output(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Remove peer with JSON output."""
        node_a, node_b = two_nodes_with_servers

        code, stdout, stderr = run_cli_command(
            node_a.config_dir,
            ["--format", "json", "sync", "remove-peer", node_b.device_id_hex],
        )

        assert code == 0
        data = json.loads(stdout)
        assert data["removed"] is True

    def test_remove_peer_not_found(self, sync_node_a: SyncNode):
        """Remove non-existent peer fails."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "remove-peer", "00000000000070008000000000000099"],
        )

        assert code == 1
        assert "not found" in stderr.lower()


class TestSyncNowCLI:
    """Tests for 'sync now' command."""

    def test_sync_now_no_peers(self, sync_node_a: SyncNode):
        """Sync now with no peers configured."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "now"],
        )

        assert code == 0
        assert "No peers configured" in stdout

    def test_sync_now_success(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Sync now completes successfully."""
        node_a, node_b = two_nodes_with_servers

        # Create note on B
        create_note_on_node(node_b, "Test note from B")

        code, stdout, stderr = run_cli_command(
            node_a.config_dir,
            ["sync", "now"],
        )

        assert code == 0
        assert "Sync completed" in stdout or "OK" in stdout

    def test_sync_now_with_peer_id(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Sync with specific peer."""
        node_a, node_b = two_nodes_with_servers

        code, stdout, stderr = run_cli_command(
            node_a.config_dir,
            ["sync", "now", "--peer", node_b.device_id_hex],
        )

        assert code == 0
        assert "Sync with" in stdout or "completed" in stdout.lower()

    def test_sync_now_json_output(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Sync now with JSON output."""
        node_a, node_b = two_nodes_with_servers

        code, stdout, stderr = run_cli_command(
            node_a.config_dir,
            ["--format", "json", "sync", "now"],
        )

        assert code == 0
        data = json.loads(stdout)
        # Should have results for node_b
        assert node_b.device_id_hex in data

    def test_sync_now_server_unreachable(self, sync_node_a: SyncNode):
        """Sync fails when server is unreachable."""
        # Add peer with non-existent server
        sync_node_a.config.add_peer(
            peer_id="00000000000070008000000000000099",
            peer_name="DeadServer",
            peer_url="http://127.0.0.1:59999",  # Non-existent port
        )

        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "now"],
            timeout=10,
        )

        # Should complete but report failure
        assert "FAILED" in stdout or code == 1


class TestSyncConflictsCLI:
    """Tests for 'sync conflicts' command."""

    def test_conflicts_empty(self, sync_node_a: SyncNode):
        """List conflicts when none exist."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "conflicts"],
        )

        assert code == 0
        assert "No unresolved conflicts" in stdout

    def test_conflicts_json_empty(self, sync_node_a: SyncNode):
        """List conflicts in JSON when none exist."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["--format", "json", "sync", "conflicts"],
        )

        assert code == 0
        data = json.loads(stdout)
        assert "note_content" in data
        assert "note_delete" in data
        assert "tag_rename" in data
        assert len(data["note_content"]) == 0


class TestSyncResolveCLI:
    """Tests for 'sync resolve' command."""

    def test_resolve_not_found(self, sync_node_a: SyncNode):
        """Resolve non-existent conflict fails."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "resolve", "00000000000070008000000000000099", "local"],
        )

        assert code == 1
        assert "not found" in stderr.lower()

    def test_resolve_invalid_choice(self, sync_node_a: SyncNode):
        """Resolve with invalid choice fails."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "resolve", "00000000000070008000000000000099", "invalid"],
        )

        # argparse should reject invalid choice
        assert code != 0


class TestSyncServeCLI:
    """Tests for 'sync serve' command."""

    def test_serve_starts_server(self, sync_node_a: SyncNode):
        """Sync serve starts a server that responds."""
        import requests

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent)

        # Start server in background
        cmd = [
            sys.executable,
            "-m", "src.main",
            "-d", str(sync_node_a.config_dir),
            "cli", "sync", "serve",
            "--host", "127.0.0.1",
            "--port", str(sync_node_a.port),
        ]

        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(Path(__file__).parent.parent.parent),
        )

        try:
            # Wait for server to start
            time.sleep(2)

            # Check server is responding
            resp = requests.get(
                f"http://127.0.0.1:{sync_node_a.port}/sync/status",
                timeout=5,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"

        finally:
            process.terminate()
            process.wait(timeout=5)
            # Close pipes to avoid ResourceWarning
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()

    def test_serve_custom_port(self, sync_node_a: SyncNode, tmp_path: Path):
        """Sync serve uses custom port."""
        import socket

        # Find a free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            custom_port = s.getsockname()[1]

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent)

        cmd = [
            sys.executable,
            "-m", "src.main",
            "-d", str(sync_node_a.config_dir),
            "cli", "sync", "serve",
            "--host", "127.0.0.1",
            "--port", str(custom_port),
        ]

        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(Path(__file__).parent.parent.parent),
        )

        try:
            time.sleep(2)

            import requests
            resp = requests.get(
                f"http://127.0.0.1:{custom_port}/sync/status",
                timeout=5,
            )
            assert resp.status_code == 200

        finally:
            process.terminate()
            process.wait(timeout=5)
            # Close pipes to avoid ResourceWarning
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()


class TestCLIHelp:
    """Tests for CLI help messages."""

    def test_sync_help(self, sync_node_a: SyncNode):
        """Sync command shows help."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "--help"],
        )

        # Help might go to stdout or cause exit 0
        assert code == 0 or "usage" in (stdout + stderr).lower()

    def test_sync_no_subcommand(self, sync_node_a: SyncNode):
        """Sync without subcommand shows error."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync"],
        )

        # Should fail or show help
        assert code == 1 or "No sync command" in stderr


class TestCLIEdgeCases:
    """Edge case tests for CLI."""

    def test_invalid_config_dir(self, tmp_path: Path):
        """CLI with non-existent config dir creates it."""
        config_dir = tmp_path / "nonexistent"

        code, stdout, stderr = run_cli_command(
            config_dir,
            ["sync", "status"],
        )

        # Should work - config is created automatically
        assert code == 0 or "Device ID:" in stdout

    def test_concurrent_cli_commands(
        self, two_nodes_with_servers: Tuple[SyncNode, SyncNode]
    ):
        """Multiple CLI commands can run concurrently."""
        node_a, node_b = two_nodes_with_servers

        # Use subprocess.Popen to run truly concurrent processes
        # (avoids ThreadPoolExecutor cleanup issues with Rust extension)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent)

        cmd = [
            sys.executable,
            "-m", "src.main",
            "-d", str(node_a.config_dir),
            "cli",
            "sync", "status",
        ]

        # Start 3 processes concurrently
        processes = []
        for _ in range(3):
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(Path(__file__).parent.parent.parent),
            )
            processes.append(proc)

        # Wait for all to complete and collect results
        results = []
        for proc in processes:
            stdout, stderr = proc.communicate(timeout=30)
            results.append((proc.returncode, stdout, stderr))

        # All should succeed
        for code, stdout, stderr in results:
            assert code == 0

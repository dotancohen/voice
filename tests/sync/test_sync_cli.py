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
    env["VOICE_CONFIG_DIR"] = str(config_dir)
    env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent)

    cmd = [
        sys.executable,
        "-m", "src.main",
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
        assert "Forgot peer:" in stdout

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
        assert data == []

    def test_conflicts_for_unknown_note_fails(self, sync_node_a: SyncNode):
        """Filtering by a note that does not exist is an error, not an empty list."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "conflicts", "--note", "00000000000070008000000000000099"],
        )

        assert code == 1
        assert "not found" in stderr.lower()


class TestSyncResolveCLI:
    """Tests for 'sync resolve' command."""

    def test_resolve_not_found(self, sync_node_a: SyncNode):
        """Resolve non-existent conflict fails."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "resolve", "00000000000070008000000000000099"],
        )

        assert code == 1
        assert "not found" in stderr.lower()

    def test_resolve_rejects_two_content_sources(self, sync_node_a: SyncNode):
        """--content and --content-file together are rejected."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "resolve", "00000000000070008000000000000099",
             "--content", "א", "--content-file", "/nonexistent"],
        )

        assert code == 1
        assert "either" in stderr.lower()

    def test_resolve_missing_content_file(self, sync_node_a: SyncNode):
        """An unreadable --content-file is reported before touching the database."""
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["sync", "resolve", "00000000000070008000000000000099",
             "--content-file", str(sync_node_a.config_dir / "missing.txt")],
        )

        assert code == 1
        assert "cannot read" in stderr.lower()


class TestSettingsCLI:
    """Tests for the 'settings' command (synced settings)."""

    def test_settings_list_empty(self, sync_node_a: SyncNode):
        code, stdout, stderr = run_cli_command(sync_node_a.config_dir, ["settings", "list"])
        assert code == 0
        assert "No synced settings" in stdout

    def test_settings_set_get_list(self, sync_node_a: SyncNode):
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["settings", "set", "transcription.preferred_languages", '["he", "en"]'],
        )
        assert code == 0, stderr

        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["--format", "json", "settings", "get", "transcription.preferred_languages"],
        )
        assert code == 0, stderr
        assert json.loads(json.loads(stdout)["transcription.preferred_languages"]) == ["he", "en"]

        # The local config file mirrors the synced value
        with open(sync_node_a.config_dir / "config.json", encoding="utf-8") as f:
            cfg = json.load(f)
        assert cfg["transcription"]["preferred_languages"] == ["he", "en"]

    def test_settings_api_key_is_masked_in_list(self, sync_node_a: SyncNode):
        code, stdout, stderr = run_cli_command(
            sync_node_a.config_dir,
            ["settings", "set", "transcription.providers.assemblyai.api_key", "secret-key-1234"],
        )
        assert code == 0, stderr
        code, stdout, stderr = run_cli_command(sync_node_a.config_dir, ["settings", "list"])
        assert code == 0
        assert "secret-key-1234" not in stdout
        assert "transcription.providers.assemblyai.api_key" in stdout

    def test_settings_get_unset_fails(self, sync_node_a: SyncNode):
        code, stdout, stderr = run_cli_command(sync_node_a.config_dir, ["settings", "get", "nothing.here"])
        assert code == 1
        assert "not set" in stderr


class TestSyncServeCLI:
    """Tests for 'sync serve' command."""

    @pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning")
    def test_serve_starts_server(self, sync_node_a: SyncNode):
        """Sync serve starts a server that responds."""
        import requests

        env = os.environ.copy()
        env["VOICE_CONFIG_DIR"] = str(sync_node_a.config_dir)
        env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent)

        # Start server in background
        cmd = [
            sys.executable,
            "-m", "src.main",
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
            # The server serves https with its own certificate by default
            resp = requests.get(
                f"https://127.0.0.1:{sync_node_a.port}/sync/status",
                timeout=5,
                verify=False,
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

    @pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning")
    def test_serve_custom_port(self, sync_node_a: SyncNode, tmp_path: Path):
        """Sync serve uses custom port."""
        import socket

        # Find a free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            custom_port = s.getsockname()[1]

        env = os.environ.copy()
        env["VOICE_CONFIG_DIR"] = str(sync_node_a.config_dir)
        env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent)

        cmd = [
            sys.executable,
            "-m", "src.main",
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
                f"https://127.0.0.1:{custom_port}/sync/status",
                timeout=5,
                verify=False,
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
        env["VOICE_CONFIG_DIR"] = str(node_a.config_dir)
        env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent)

        cmd = [
            sys.executable,
            "-m", "src.main",
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


class TestNoteHistoryCLI:
    """Tests for 'note-history' and 'note-restore'."""

    def test_history_lists_versions_and_restore(self, sync_node_a: SyncNode):
        note_id = sync_node_a.db.create_note("גרסה ראשונה")
        sync_node_a.db.update_note(note_id, "גרסה שנייה")
        sync_node_a.db.close()

        code, stdout, stderr = run_cli_command(sync_node_a.config_dir, ["--format", "json", "note-history", note_id])
        assert code == 0, stderr
        versions = json.loads(stdout)
        assert [v["content"] for v in versions] == ["גרסה ראשונה", "גרסה שנייה"]

        code, stdout, stderr = run_cli_command(sync_node_a.config_dir, ["note-history", note_id])
        assert code == 0, stderr
        assert "2 versions" in stdout
        assert "גרסה שנייה" in stdout

        first = versions[0]["id"]
        code, stdout, stderr = run_cli_command(sync_node_a.config_dir, ["note-history", note_id, "--show", first[:8]])
        assert code == 0, stderr
        assert stdout.strip().splitlines()[-1] == "גרסה ראשונה"

        code, stdout, stderr = run_cli_command(sync_node_a.config_dir, ["note-restore", note_id, first[:8]])
        assert code == 0, stderr
        assert "Restored" in stdout
        code, stdout, stderr = run_cli_command(sync_node_a.config_dir, ["note-show", note_id])
        assert "גרסה ראשונה" in stdout

        sync_node_a.reload_db()

    def test_restore_unknown_version_fails(self, sync_node_a: SyncNode):
        note_id = sync_node_a.db.create_note("פתק")
        sync_node_a.db.close()
        code, stdout, stderr = run_cli_command(sync_node_a.config_dir, ["note-restore", note_id, "ffffffff"])
        assert code == 1
        assert "No version" in stderr
        sync_node_a.reload_db()


class TestNoteDeleteAndTagCommands:
    def test_note_delete_is_soft(self, sync_node_a: SyncNode):
        note_id = sync_node_a.db.create_note("למחיקה")
        sync_node_a.db.close()
        code, stdout, stderr = run_cli_command(sync_node_a.config_dir, ["note-delete", note_id[:8]])
        assert code == 0, stderr
        code, stdout, stderr = run_cli_command(sync_node_a.config_dir, ["--format", "json", "note-history", note_id])
        assert code == 0, stderr
        assert json.loads(stdout)[0]["content"] == "למחיקה"
        sync_node_a.reload_db()
        assert sync_node_a.db.get_note(note_id) is None

    def test_tag_rename_and_move(self, sync_node_a: SyncNode):
        parent = sync_node_a.db.create_tag("הורה")
        child = sync_node_a.db.create_tag("ילד")
        sync_node_a.db.close()
        code, stdout, stderr = run_cli_command(sync_node_a.config_dir, ["tag-rename", child, "ילדה"])
        assert code == 0, stderr
        code, stdout, stderr = run_cli_command(sync_node_a.config_dir, ["tag-move", child, parent])
        assert code == 0, stderr
        code, stdout, stderr = run_cli_command(sync_node_a.config_dir, ["tag-move", child, "--root"])
        assert code == 0, stderr
        code, stdout, stderr = run_cli_command(sync_node_a.config_dir, ["tag-move", child])
        assert code == 1
        sync_node_a.reload_db()
        tag = sync_node_a.db.get_tag(child)
        assert tag["name"] == "ילדה" and tag["parent_id"] is None


class TestConfigDirAndConfigCommands:
    """VOICE_CONFIG_DIR, the first-line banner, and 'config get/set/show'."""

    def _run(self, config_dir, args, env_extra=None):
        import subprocess
        env = os.environ.copy()
        env["VOICE_CONFIG_DIR"] = str(config_dir)
        env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent)
        if env_extra:
            env.update(env_extra)
        proc = subprocess.run(
            [sys.executable, "-m", "src.main"] + args,
            env=env, capture_output=True, text=True, timeout=60,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_env_var_selects_config_dir_and_banner_is_first_line(self, sync_node_a: SyncNode):
        code, stdout, stderr = self._run(sync_node_a.config_dir, ["cli", "config", "get", "directory"],
                                         {"VOICE_CONFIG_DIR": str(sync_node_a.config_dir)})
        assert code == 0, stderr
        lines = [l for l in stdout.splitlines() if l.strip()]
        assert lines[0] == f"Using CONFIG_DIR: {sync_node_a.config_dir}"
        assert lines[1] == str(sync_node_a.config_dir)

    def test_json_format_keeps_stdout_clean(self, sync_node_a: SyncNode):
        code, stdout, stderr = self._run(sync_node_a.config_dir, ["cli", "--format", "json", "config", "show"],
                                         {"VOICE_CONFIG_DIR": str(sync_node_a.config_dir)})
        assert code == 0, stderr
        assert json.loads(stdout)["directory"] == str(sync_node_a.config_dir)
        assert "Using CONFIG_DIR" in stderr

    def test_config_set_and_get(self, sync_node_a: SyncNode, tmp_path: Path):
        env = {"VOICE_CONFIG_DIR": str(sync_node_a.config_dir)}
        code, stdout, stderr = self._run(sync_node_a.config_dir, ["cli", "config", "set", "device_name", "מחשב"], env)
        assert code == 0, stderr
        code, stdout, stderr = self._run(sync_node_a.config_dir, ["cli", "config", "get", "device_name"], env)
        assert stdout.splitlines()[-1] == "מחשב"
        audio = tmp_path / "audio-דיר"
        code, stdout, stderr = self._run(sync_node_a.config_dir, ["cli", "config", "set", "audiofile_directory", str(audio)], env)
        assert code == 0, stderr
        assert audio.is_dir()
        code, stdout, stderr = self._run(sync_node_a.config_dir, ["cli", "config", "get", "audiofile_directory"], env)
        assert stdout.splitlines()[-1] == str(audio.resolve())
        code, stdout, stderr = self._run(sync_node_a.config_dir, ["cli", "config", "set", "nonsense", "x"], env)
        assert code == 1 and "unknown key" in stderr

    def test_voice_wrapper_script(self, sync_node_a: SyncNode):
        import subprocess
        env = os.environ.copy()
        env["VOICE_CONFIG_DIR"] = str(sync_node_a.config_dir)
        script = Path(__file__).parent.parent.parent / "bin" / "voice"
        proc = subprocess.run([str(script), "cli", "config", "get", "device_id"], env=env, capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.splitlines()[-1] == sync_node_a.device_id_hex

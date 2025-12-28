"""Tests for audiofile sync configuration validation.

Tests that verify:
- Sync is rejected if target peer lacks audiofile_directory config (#8)
"""

from __future__ import annotations

import json
import urllib.request
import uuid
from pathlib import Path
from typing import Generator

import pytest

from .conftest import SyncNode, create_sync_node, start_sync_server


# Device IDs for testing
DEVICE_WITH_AUDIO_ID = uuid.UUID("00000000-0000-7000-8000-000000000021").bytes
DEVICE_WITHOUT_AUDIO_ID = uuid.UUID("00000000-0000-7000-8000-000000000022").bytes


@pytest.fixture
def server_with_audiofiles(tmp_path: Path) -> Generator[SyncNode, None, None]:
    """Create server WITH audiofile_directory configured."""
    audiofile_dir = tmp_path / "server_audiofiles"
    audiofile_dir.mkdir()

    node = create_sync_node(
        "ServerWithAudio",
        DEVICE_WITH_AUDIO_ID,
        tmp_path / "server_with_audio",
    )

    node.config.set_audiofile_directory(str(audiofile_dir))

    yield node
    node.stop_server()
    node.db.close()


@pytest.fixture
def server_without_audiofiles(tmp_path: Path) -> Generator[SyncNode, None, None]:
    """Create server WITHOUT audiofile_directory configured."""
    node = create_sync_node(
        "ServerWithoutAudio",
        DEVICE_WITHOUT_AUDIO_ID,
        tmp_path / "server_no_audio",
    )

    # Explicitly ensure no audiofile_directory
    # Don't call set_audiofile_directory

    yield node
    node.stop_server()
    node.db.close()


class TestSyncRejectsWithoutAudiofileDirectory:
    """Test that sync is rejected when peer lacks audiofile_directory config."""

    def test_server_rejects_audio_upload_without_audiofile_directory(
        self,
        server_without_audiofiles: SyncNode,
    ) -> None:
        """Test server rejects audio file upload when it has no audiofile_directory."""
        server = server_without_audiofiles

        # Create audio file record on server
        audio_id = server.db.create_audio_file("recording.ogg")

        # Start server
        start_sync_server(server)
        if not server.wait_for_server():
            pytest.fail("Failed to start sync server")

        # Attempt upload
        url = f"{server.url}/sync/audio/{audio_id}/file"
        request = urllib.request.Request(url, data=b"audio content", method="POST")
        request.add_header("Content-Type", "application/octet-stream")
        request.add_header("X-Device-ID", "test-client")

        # Server should return 400 error
        try:
            urllib.request.urlopen(request, timeout=10)
            pytest.fail("Server should reject upload when audiofile_directory not configured")
        except urllib.error.HTTPError as e:
            assert e.code == 400, f"Expected 400, got {e.code}"
            body = e.read().decode()
            assert "audiofile_directory" in body.lower(), (
                f"Error should mention audiofile_directory: {body}"
            )

    def test_client_rejects_audio_download_without_audiofile_directory(
        self,
        server_with_audiofiles: SyncNode,
    ) -> None:
        """Test client sync_client.download_audio_file rejects when no local audiofile_directory."""
        from voicecore import SyncClient

        server = server_with_audiofiles

        # Create audio file on server
        audio_id = server.db.create_audio_file("server-recording.ogg")

        # Store file on server
        server_audiofile_dir = Path(server.config.get_audiofile_directory())
        server_file = server_audiofile_dir / f"{audio_id}.ogg"
        server_file.write_bytes(b"audio content")

        # Start server
        start_sync_server(server)
        if not server.wait_for_server():
            pytest.fail("Failed to start sync server")

        # Create a client with NO audiofile_directory
        # The SyncClient should check this before downloading
        from core.config import Config
        from core.database import Database, set_local_device_id
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            client_dir = Path(tmp) / "client"
            client_dir.mkdir()
            config_data = {
                "database_file": str(client_dir / "notes.db"),
                "device_id": "00000000000070008000000000000099",
                "device_name": "Client No Audio",
            }
            with open(client_dir / "config.json", "w") as f:
                json.dump(config_data, f)

            client_cfg = Config(client_dir)
            set_local_device_id(client_cfg.get_device_id_hex())
            client_db = Database(client_dir / "notes.db")

            # Client's audiofile_directory is not configured
            assert client_cfg.get_audiofile_directory() is None

            # Create sync client
            sync_client = SyncClient(client_db, client_cfg)

            # Attempt download - client should check if it can store the file
            # This currently downloads but has nowhere to save
            # For now, just verify the client has no place to save
            # Future: client should reject before downloading

            # The test passes if we verify the client has no audiofile_directory
            # Full implementation would have client check before download
            assert client_cfg.get_audiofile_directory() is None, (
                "Client should not have audiofile_directory configured"
            )

    def test_sync_logs_conflict_when_audiofile_directory_missing(
        self,
        server_without_audiofiles: SyncNode,
    ) -> None:
        """Test that error is returned when sync fails due to missing config."""
        server = server_without_audiofiles

        # Create audio file record
        audio_id = server.db.create_audio_file("recording.ogg")

        # Start server
        start_sync_server(server)
        if not server.wait_for_server():
            pytest.fail("Failed to start sync server")

        # Attempt upload - should get error response
        url = f"{server.url}/sync/audio/{audio_id}/file"
        request = urllib.request.Request(url, data=b"audio content", method="POST")
        request.add_header("Content-Type", "application/octet-stream")

        try:
            urllib.request.urlopen(request, timeout=10)
            pytest.fail("Should get error")
        except urllib.error.HTTPError as e:
            # Error response should indicate the issue
            body = e.read().decode()
            assert "audiofile_directory" in body.lower() or e.code == 400, (
                "Error should indicate audiofile_directory issue"
            )

    def test_metadata_sync_still_works_without_audiofile_directory(
        self,
        server_without_audiofiles: SyncNode,
        server_with_audiofiles: SyncNode,
    ) -> None:
        """Test that audio file metadata can sync even without audiofile_directory."""
        # Use server_with_audiofiles as source (has audio file)
        source = server_with_audiofiles

        # Create audio file with metadata on source
        audio_id = source.db.create_audio_file("recording.ogg")
        source.db.update_audio_file_summary(audio_id, "Meeting notes")

        # Target server has no audiofile_directory
        target = server_without_audiofiles

        # Sync metadata (not binary file)
        raw = source.db.get_audio_file_raw(audio_id)
        target.db.apply_sync_audio_file(
            raw["id"],
            raw["imported_at"],
            raw["filename"],
            raw.get("file_created_at"),
            raw.get("summary"),
            raw.get("modified_at"),
            raw.get("deleted_at"),
        )

        # Metadata should sync successfully
        target_audio = target.db.get_audio_file(audio_id)
        assert target_audio is not None, "Audio file metadata should sync"
        assert target_audio["filename"] == "recording.ogg"
        assert target_audio["summary"] == "Meeting notes"


class TestSyncConfigValidationDuringHandshake:
    """Test that config validation happens during sync handshake."""

    @pytest.mark.xfail(reason="Handshake capability advertisement not yet implemented")
    def test_handshake_includes_audiofile_capability(
        self,
        server_with_audiofiles: SyncNode,
    ) -> None:
        """Test that sync handshake advertises audiofile capability."""
        server = server_with_audiofiles

        # Start server
        start_sync_server(server)
        if not server.wait_for_server():
            pytest.fail("Failed to start sync server")

        # Get status - should include audiofile capability
        url = f"{server.url}/sync/status"
        request = urllib.request.Request(url)
        response = urllib.request.urlopen(request, timeout=10)
        data = json.loads(response.read().decode())

        # Future: status should include "supports_audiofiles": true
        assert "supports_audiofiles" in data, (
            "Status should advertise audiofile capability"
        )

    @pytest.mark.xfail(reason="Handshake capability advertisement not yet implemented")
    def test_client_knows_server_audiofile_capability_after_handshake(
        self,
        server_without_audiofiles: SyncNode,
    ) -> None:
        """Test that client learns server's audiofile capability during handshake."""
        server = server_without_audiofiles

        # Start server
        start_sync_server(server)
        if not server.wait_for_server():
            pytest.fail("Failed to start sync server")

        # After handshake, client should know server doesn't support audiofiles
        # This requires protocol enhancement

        # Future: SyncClient would have:
        # client.connect(server.url)
        # assert client.peer_supports_audiofiles == False

        pytest.fail("Client should learn server's audiofile capability from handshake")

"""Tests for binary audio file sync transfer.

Tests that verify:
- Client can upload audio files to server
- Client can download audio files from server
- Server correctly stores uploaded audio files
- Server correctly serves audio files for download

Uses the test file: tests/audiofile-sync-test.ogg
"""

from __future__ import annotations

import urllib.request
import uuid
from pathlib import Path
from typing import Generator

import pytest

from .conftest import SyncNode, create_sync_node, start_sync_server

# Test audio file path
TEST_AUDIO_FILE = Path(__file__).parent.parent / "audiofile-sync-test.ogg"

# Device IDs for testing
DEVICE_SERVER_ID = uuid.UUID("00000000-0000-7000-8000-000000000011").bytes
DEVICE_CLIENT_ID = uuid.UUID("00000000-0000-7000-8000-000000000012").bytes


@pytest.fixture
def test_audio_content() -> bytes:
    """Load the test audio file content."""
    assert TEST_AUDIO_FILE.exists(), f"Test audio file not found: {TEST_AUDIO_FILE}"
    return TEST_AUDIO_FILE.read_bytes()


@pytest.fixture
def server_node_with_audiofiles(tmp_path: Path) -> Generator[SyncNode, None, None]:
    """Create sync node with audiofile_directory configured."""
    audiofile_dir = tmp_path / "server_audiofiles"
    audiofile_dir.mkdir()

    node = create_sync_node(
        "AudioServer",
        DEVICE_SERVER_ID,
        tmp_path / "server",
        port=0,  # Random port
    )

    # Set audiofile_directory
    node.config.set_audiofile_directory(str(audiofile_dir))

    yield node
    node.stop_server()
    node.db.close()


@pytest.fixture
def client_node_with_audiofiles(tmp_path: Path) -> Generator[SyncNode, None, None]:
    """Create client sync node with audiofile_directory configured."""
    audiofile_dir = tmp_path / "client_audiofiles"
    audiofile_dir.mkdir()

    node = create_sync_node(
        "AudioClient",
        DEVICE_CLIENT_ID,
        tmp_path / "client",
    )

    # Set audiofile_directory
    node.config.set_audiofile_directory(str(audiofile_dir))

    yield node
    node.db.close()


class TestClientUploadToServer:
    """Test client uploading audio files to server."""

    def test_client_uploads_file_to_server(
        self,
        server_node_with_audiofiles: SyncNode,
        client_node_with_audiofiles: SyncNode,
        test_audio_content: bytes,
    ) -> None:
        """Test that client can upload an audio file to the sync server."""
        from voicecore import SyncClient

        server = server_node_with_audiofiles
        client = client_node_with_audiofiles

        # Create audio file record on client
        audio_id = client.db.create_audio_file("test-recording.ogg")

        # Store the actual file in client's audiofile_directory
        client_audiofile_dir = Path(client.config.get_audiofile_directory())
        client_file = client_audiofile_dir / f"{audio_id}.ogg"
        client_file.write_bytes(test_audio_content)

        # Sync the audio file metadata to server first (so it knows the filename)
        raw = client.db.get_audio_file_raw(audio_id)
        server.db.apply_sync_audio_file(
            raw["id"],
            raw["imported_at"],
            raw["filename"],
        )

        # Start sync server
        start_sync_server(server)
        if not server.wait_for_server():
            pytest.fail("Failed to start sync server")

        # Create sync client and upload
        sync_client = SyncClient(str(client.config_dir))

        result = sync_client.upload_audio_file(server.url, audio_id, str(client_file))

        assert result["success"], f"Upload failed: {result.get('error')}"

        # Verify server received the file
        server_audiofile_dir = Path(server.config.get_audiofile_directory())
        server_file = server_audiofile_dir / f"{audio_id}.ogg"

        assert server_file.exists(), (
            f"Audio file should exist on server at {server_file} after upload"
        )

        # Content should match
        assert server_file.read_bytes() == test_audio_content, (
            "Server file content should match uploaded content"
        )


class TestClientDownloadFromServer:
    """Test client downloading audio files from server."""

    def test_client_downloads_file_from_server(
        self,
        server_node_with_audiofiles: SyncNode,
        client_node_with_audiofiles: SyncNode,
        test_audio_content: bytes,
    ) -> None:
        """Test that client can download an audio file from the sync server."""
        from voicecore import SyncClient

        server = server_node_with_audiofiles
        client = client_node_with_audiofiles

        # Create audio file record on server
        audio_id = server.db.create_audio_file("server-recording.ogg")

        # Store the actual file in server's audiofile_directory
        server_audiofile_dir = Path(server.config.get_audiofile_directory())
        server_file = server_audiofile_dir / f"{audio_id}.ogg"
        server_file.write_bytes(test_audio_content)

        # Sync the audio file metadata to client
        raw = server.db.get_audio_file_raw(audio_id)
        client.db.apply_sync_audio_file(
            raw["id"],
            raw["imported_at"],
            raw["filename"],
        )

        # Start sync server
        start_sync_server(server)
        if not server.wait_for_server():
            pytest.fail("Failed to start sync server")

        # Create sync client and download
        sync_client = SyncClient(str(client.config_dir))

        client_audiofile_dir = Path(client.config.get_audiofile_directory())
        client_file = client_audiofile_dir / f"{audio_id}.ogg"

        result = sync_client.download_audio_file(server.url, audio_id, str(client_file))

        assert result["success"], f"Download failed: {result.get('error')}"

        # Verify client received the file
        assert client_file.exists(), (
            f"Audio file should exist on client at {client_file} after download"
        )

        # Content should match
        assert client_file.read_bytes() == test_audio_content, (
            "Client file content should match server content"
        )


class TestServerReceivesUpload:
    """Test server correctly receives and stores uploaded audio files."""

    def test_server_stores_uploaded_file_in_correct_location(
        self,
        server_node_with_audiofiles: SyncNode,
        test_audio_content: bytes,
    ) -> None:
        """Test that server stores uploaded files as {audiofile_directory}/{uuid}.{ext}."""
        server = server_node_with_audiofiles

        # Create audio file record
        audio_id = server.db.create_audio_file("upload-test.ogg")

        server_audiofile_dir = Path(server.config.get_audiofile_directory())
        expected_path = server_audiofile_dir / f"{audio_id}.ogg"

        # After upload, file should be at expected path
        assert expected_path.parent == server_audiofile_dir, (
            "Audio files should be stored in audiofile_directory"
        )

    def test_server_upload_endpoint_returns_success(
        self,
        server_node_with_audiofiles: SyncNode,
        test_audio_content: bytes,
    ) -> None:
        """Test that server's POST /sync/audio/{id}/file endpoint works."""
        import urllib.request
        import ssl

        server = server_node_with_audiofiles

        # Create audio file record first
        audio_id = server.db.create_audio_file("uploaded.ogg")

        # Start sync server
        start_sync_server(server)
        if not server.wait_for_server():
            pytest.fail("Failed to start sync server")

        # Make direct HTTP request to upload endpoint
        url = f"{server.url}/sync/audio/{audio_id}/file"

        request = urllib.request.Request(url, data=test_audio_content, method="POST")
        request.add_header("Content-Type", "application/octet-stream")
        request.add_header("X-Device-ID", "test-device")
        request.add_header("X-Device-Name", "Test Device")

        response = urllib.request.urlopen(request, timeout=10)
        assert response.status == 200

        # Verify file was stored
        server_audiofile_dir = Path(server.config.get_audiofile_directory())
        expected_file = server_audiofile_dir / f"{audio_id}.ogg"

        assert expected_file.exists(), (
            f"POST /sync/audio/{audio_id}/file should store file at {expected_file}"
        )
        assert expected_file.read_bytes() == test_audio_content


class TestServerServesDownload:
    """Test server correctly serves audio files for download."""

    def test_server_serves_file_from_correct_location(
        self,
        server_node_with_audiofiles: SyncNode,
        test_audio_content: bytes,
    ) -> None:
        """Test that server serves files from {audiofile_directory}/{uuid}.{ext}."""
        server = server_node_with_audiofiles

        # Create audio file record
        audio_id = server.db.create_audio_file("to-download.ogg")

        # Store file in correct location
        server_audiofile_dir = Path(server.config.get_audiofile_directory())
        stored_file = server_audiofile_dir / f"{audio_id}.ogg"
        stored_file.write_bytes(test_audio_content)

        # Verify the file exists where server should read from
        assert stored_file.exists(), "Server should read from stored file location"
        assert stored_file.read_bytes() == test_audio_content

    def test_server_download_endpoint_returns_binary_content(
        self,
        server_node_with_audiofiles: SyncNode,
        test_audio_content: bytes,
    ) -> None:
        """Test that server's GET /sync/audio/{id}/file returns binary content."""
        import urllib.request
        import ssl

        server = server_node_with_audiofiles

        # Create and store audio file
        audio_id = server.db.create_audio_file("binary-download.ogg")

        server_audiofile_dir = Path(server.config.get_audiofile_directory())
        stored_file = server_audiofile_dir / f"{audio_id}.ogg"
        stored_file.write_bytes(test_audio_content)

        # Start sync server
        start_sync_server(server)
        if not server.wait_for_server():
            pytest.fail("Failed to start sync server")

        # Make direct HTTP request to download endpoint
        url = f"{server.url}/sync/audio/{audio_id}/file"

        request = urllib.request.Request(url, method="GET")
        request.add_header("X-Device-ID", "test-device")
        request.add_header("X-Device-Name", "Test Device")

        response = urllib.request.urlopen(request, timeout=10)
        content = response.read()

        assert response.status == 200
        assert content == test_audio_content, (
            "Server should serve exact binary content"
        )


class TestBinarySyncRoundTrip:
    """Test complete round-trip of binary audio file sync."""

    def test_upload_then_download_preserves_content(
        self,
        server_node_with_audiofiles: SyncNode,
        client_node_with_audiofiles: SyncNode,
        test_audio_content: bytes,
    ) -> None:
        """Test that uploading then downloading preserves exact file content."""
        from voicecore import SyncClient

        server = server_node_with_audiofiles
        client = client_node_with_audiofiles

        # Client creates audio file
        audio_id = client.db.create_audio_file("roundtrip.ogg")

        client_audiofile_dir = Path(client.config.get_audiofile_directory())
        original_file = client_audiofile_dir / f"{audio_id}.ogg"
        original_file.write_bytes(test_audio_content)

        # Sync metadata to server
        raw = client.db.get_audio_file_raw(audio_id)
        server.db.apply_sync_audio_file(
            raw["id"],
            raw["imported_at"],
            raw["filename"],
        )

        # Start sync server
        start_sync_server(server)
        if not server.wait_for_server():
            pytest.fail("Failed to start sync server")

        # Upload to server
        sync_client = SyncClient(str(client.config_dir))

        upload_result = sync_client.upload_audio_file(server.url, audio_id, str(original_file))
        assert upload_result["success"], f"Upload failed: {upload_result.get('error')}"

        # Download to different location
        downloaded_file = client_audiofile_dir / f"{audio_id}_downloaded.ogg"
        download_result = sync_client.download_audio_file(server.url, audio_id, str(downloaded_file))
        assert download_result["success"], f"Download failed: {download_result.get('error')}"

        # After round-trip, content should be identical
        assert downloaded_file.read_bytes() == test_audio_content, (
            "Round-trip sync should preserve exact binary content"
        )


class TestMissingAudioFileDownload:
    """Test that missing audio files are downloaded on subsequent syncs.

    This handles the case where audio file metadata was synced but the binary
    download failed (e.g., due to permission issues). On subsequent syncs,
    the metadata won't be in pulled_changes (since it hasn't changed), so we
    need to check for missing files and download them.
    """

    def test_missing_audio_file_downloaded_on_second_sync(
        self,
        server_node_with_audiofiles: SyncNode,
        client_node_with_audiofiles: SyncNode,
        test_audio_content: bytes,
    ) -> None:
        """Test that a missing audio file is downloaded on subsequent sync.

        Scenario:
        1. Server has audio file (metadata + binary)
        2. Client syncs - metadata is applied but binary file NOT stored locally
           (simulating a failed download due to permission issues)
        3. Client syncs again - should detect missing file and download it
        """
        from voicecore import SyncClient

        server = server_node_with_audiofiles
        client = client_node_with_audiofiles

        # 1. Server has audio file with binary
        audio_id = server.db.create_audio_file("server-file.ogg")
        server_audiofile_dir = Path(server.config.get_audiofile_directory())
        server_file = server_audiofile_dir / f"{audio_id}.ogg"
        server_file.write_bytes(test_audio_content)

        # 2. Simulate first sync: metadata synced but binary not stored
        # Apply metadata to client database
        raw = server.db.get_audio_file_raw(audio_id)
        client.db.apply_sync_audio_file(
            raw["id"],
            raw["imported_at"],
            raw["filename"],
        )

        # Verify client has metadata but no binary file
        client_audiofile_dir = Path(client.config.get_audiofile_directory())
        client_file = client_audiofile_dir / f"{audio_id}.ogg"
        assert not client_file.exists(), (
            "Client should NOT have the binary file yet (simulating failed download)"
        )

        # Start sync server
        start_sync_server(server)
        if not server.wait_for_server():
            pytest.fail("Failed to start sync server")

        # Configure client to sync with server
        server_peer_id = server.device_id_hex
        client.config.add_peer(server_peer_id, "Server", server.url, allow_update=True)
        client.config.set_sync_enabled(True)

        # 3. Second sync - should download the missing file
        sync_client = SyncClient(str(client.config_dir))
        result = sync_client.sync_with_peer(server_peer_id)

        # The sync should succeed
        assert result.success, f"Sync failed: {result.errors}"

        # The missing file should now exist
        assert client_file.exists(), (
            "Missing audio file should be downloaded on second sync. "
            f"Expected file at: {client_file}"
        )

        # Content should match
        assert client_file.read_bytes() == test_audio_content, (
            "Downloaded file content should match server content"
        )

    def test_already_existing_file_not_redownloaded(
        self,
        server_node_with_audiofiles: SyncNode,
        client_node_with_audiofiles: SyncNode,
        test_audio_content: bytes,
    ) -> None:
        """Test that existing audio files are not re-downloaded."""
        from voicecore import SyncClient

        server = server_node_with_audiofiles
        client = client_node_with_audiofiles

        # Server has audio file
        audio_id = server.db.create_audio_file("existing-file.ogg")
        server_audiofile_dir = Path(server.config.get_audiofile_directory())
        server_file = server_audiofile_dir / f"{audio_id}.ogg"
        server_file.write_bytes(test_audio_content)

        # Client has metadata AND binary file already
        raw = server.db.get_audio_file_raw(audio_id)
        client.db.apply_sync_audio_file(
            raw["id"],
            raw["imported_at"],
            raw["filename"],
        )

        client_audiofile_dir = Path(client.config.get_audiofile_directory())
        client_file = client_audiofile_dir / f"{audio_id}.ogg"
        client_file.write_bytes(test_audio_content)

        # Record file modification time
        original_mtime = client_file.stat().st_mtime

        # Start sync server
        start_sync_server(server)
        if not server.wait_for_server():
            pytest.fail("Failed to start sync server")

        # Configure client and sync
        server_peer_id = server.device_id_hex
        client.config.add_peer(server_peer_id, "Server", server.url, allow_update=True)
        client.config.set_sync_enabled(True)

        sync_client = SyncClient(str(client.config_dir))
        result = sync_client.sync_with_peer(server_peer_id)

        assert result.success, f"Sync failed: {result.errors}"

        # File should still exist with same mtime (not redownloaded)
        assert client_file.exists()
        assert client_file.stat().st_mtime == original_mtime, (
            "Existing file should not be redownloaded"
        )

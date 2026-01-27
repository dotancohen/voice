"""Integration tests for cloud file storage.

These tests require a valid S3 bucket and credentials in tests/test_config.toml.
They are skipped if the config file is missing.

To run these tests:
1. Copy tests/test_config.example.toml to tests/test_config.toml
2. Fill in your S3 credentials
3. Run: pytest tests/integration/test_file_storage.py -v
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

# Try to import toml (or tomllib for Python 3.11+)
try:
    import tomllib
except ImportError:
    try:
        import toml as tomllib
    except ImportError:
        tomllib = None


def load_test_config() -> Optional[Dict[str, Any]]:
    """Load test configuration from tests/test_config.toml."""
    if tomllib is None:
        return None

    config_path = Path(__file__).parent.parent / "test_config.toml"
    if not config_path.exists():
        return None

    try:
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return None


def get_s3_config() -> Optional[Dict[str, str]]:
    """Get S3 configuration from test config."""
    config = load_test_config()
    if config is None or "s3" not in config:
        return None

    s3 = config["s3"]
    required = ["bucket", "region", "access_key_id", "secret_access_key"]
    if not all(k in s3 for k in required):
        return None

    return s3


# Skip all tests in this module if S3 config is not available
s3_config = get_s3_config()
pytestmark = pytest.mark.skipif(
    s3_config is None,
    reason="S3 credentials not configured in tests/test_config.toml"
)


@pytest.fixture
def test_db():
    """Create a test database with S3 storage configured."""
    from src.core.database import Database

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path)

        # Configure S3 storage
        s3_json = json.dumps({
            "bucket": s3_config["bucket"],
            "region": s3_config["region"],
            "access_key_id": s3_config["access_key_id"],
            "secret_access_key": s3_config["secret_access_key"],
            "prefix": s3_config.get("prefix"),
            "endpoint": s3_config.get("endpoint"),
        })
        db.set_file_storage_config("s3", s3_json)

        yield db

        db.close()


class TestFileStorageConfiguration:
    """Test storage configuration in database."""

    def test_storage_config_persists(self, test_db):
        """Test that storage configuration is saved and loaded correctly."""
        config = test_db.get_file_storage_config()
        assert config is not None
        assert config.get("provider") == "s3"

        stored_config = config.get("config", {})
        assert stored_config.get("bucket") == s3_config["bucket"]
        assert stored_config.get("region") == s3_config["region"]

    def test_storage_enabled(self, test_db):
        """Test that storage is reported as enabled."""
        assert test_db.is_file_storage_enabled() is True
        assert test_db.get_file_storage_provider() == "s3"


class TestS3Integration:
    """Test actual S3 operations.

    These tests make real requests to S3. They create and delete test objects.
    """

    @pytest.mark.skip(reason="S3 upload/download not yet implemented in Python bindings")
    def test_upload_download_cycle(self, test_db):
        """Test uploading and downloading an audio file."""
        # TODO: Implement when S3 upload/download is exposed to Python
        pass

    @pytest.mark.skip(reason="S3 upload/download not yet implemented in Python bindings")
    def test_presigned_url_generation(self, test_db):
        """Test generating pre-signed URLs for downloads."""
        # TODO: Implement when pre-signed URL generation is exposed to Python
        pass


class TestAudioFilePendingUpload:
    """Test tracking of audio files pending cloud upload."""

    def test_new_audio_file_pending_upload(self, test_db):
        """Test that new audio files are marked as pending upload."""
        # Create a note with an audio file
        note_id = test_db.create_note("Test note with audio")

        # Create an audio file (simulating import)
        audio_id = test_db.create_audio_file("test_audio.mp3", None)

        # Check that it appears in pending uploads
        pending = test_db.get_audio_files_pending_upload()
        pending_ids = [af["id"] for af in pending]
        assert audio_id in pending_ids

    def test_mark_audio_file_uploaded(self, test_db):
        """Test marking an audio file as uploaded."""
        # Create audio file
        audio_id = test_db.create_audio_file("test_audio.mp3", None)

        # Verify it's pending
        pending = test_db.get_audio_files_pending_upload()
        assert any(af["id"] == audio_id for af in pending)

        # Mark as uploaded
        test_db.update_audio_file_storage(
            audio_id,
            "s3",
            f"{s3_config.get('prefix', '')}test_audio.mp3"
        )

        # Verify no longer pending
        pending = test_db.get_audio_files_pending_upload()
        assert not any(af["id"] == audio_id for af in pending)

    def test_clear_audio_file_storage(self, test_db):
        """Test clearing storage info makes file pending again."""
        # Create and mark as uploaded
        audio_id = test_db.create_audio_file("test_audio.mp3", None)
        test_db.update_audio_file_storage(audio_id, "s3", "audio/test.mp3")

        # Verify not pending
        pending = test_db.get_audio_files_pending_upload()
        assert not any(af["id"] == audio_id for af in pending)

        # Clear storage info
        test_db.clear_audio_file_storage(audio_id)

        # Verify pending again
        pending = test_db.get_audio_files_pending_upload()
        assert any(af["id"] == audio_id for af in pending)

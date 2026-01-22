"""Sync server and client implementation for Voice.

This module provides peer-to-peer synchronization using a pull-based model.
Each device runs a sync server that other devices can connect to for
fetching and applying changes.

Sync Protocol:
1. Handshake: Exchange device info and capabilities
2. Changes: Request changes since a timestamp
3. Apply: Send local changes to be applied
4. Full: Request full dataset for initial sync

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from uuid6 import uuid7

from flask import Blueprint, Flask, jsonify, request

from .database import Database
from .validation import uuid_to_hex, validate_uuid_hex

# Import Rust sync functions
from voicecore import apply_sync_changes as _rust_apply_sync_changes

logger = logging.getLogger(__name__)


@dataclass
class SyncChange:
    """Represents a single change to sync."""

    entity_type: str  # "note", "tag", "note_tag"
    entity_id: str  # UUID hex string
    operation: str  # "create", "update", "delete"
    data: Dict[str, Any]  # Full entity data
    timestamp: int  # Unix timestamp (seconds since epoch)
    device_id: str  # UUID hex of device that made change
    device_name: Optional[str] = None


@dataclass
class SyncBatch:
    """A batch of changes to sync."""

    changes: List[SyncChange] = field(default_factory=list)
    from_timestamp: Optional[int] = None
    to_timestamp: Optional[int] = None
    device_id: Optional[str] = None
    device_name: Optional[str] = None
    is_complete: bool = True  # False if more changes available


@dataclass
class HandshakeRequest:
    """Handshake request from a peer."""

    device_id: str
    device_name: str
    protocol_version: str = "1.0"


@dataclass
class HandshakeResponse:
    """Handshake response to a peer."""

    device_id: str
    device_name: str
    protocol_version: str = "1.0"
    last_sync_timestamp: Optional[int] = None
    server_timestamp: Optional[int] = None  # For clock skew detection
    supports_audiofiles: bool = False  # Whether server supports audiofile sync


def create_sync_blueprint(
    db: Database,
    device_id: str,
    device_name: str,
    audiofile_directory: Optional[str] = None,
) -> Blueprint:
    """Create Flask blueprint for sync endpoints.

    Args:
        db: Database instance
        device_id: This device's UUID hex string
        device_name: Human-readable device name
        audiofile_directory: Path to audio file storage directory

    Returns:
        Flask Blueprint with sync routes
    """
    from pathlib import Path

    sync_bp = Blueprint("sync", __name__, url_prefix="/sync")

    @sync_bp.route("/handshake", methods=["POST"])
    def handshake() -> Tuple[Any, int]:
        """Exchange device information with a peer.

        Request body:
            {
                "device_id": "...",
                "device_name": "...",
                "protocol_version": "1.0"
            }

        Response:
            {
                "device_id": "...",
                "device_name": "...",
                "protocol_version": "1.0",
                "last_sync_timestamp": "..."
            }
        """
        try:
            data = request.get_json(silent=True)
            if not data:
                error_msg = "Missing JSON request body in handshake"
                logger.warning(f"Handshake rejected: {error_msg}")
                return jsonify({"error": error_msg}), 400

            peer_device_id = data.get("device_id")
            peer_device_name = data.get("device_name", "Unknown")
            peer_protocol_version = data.get("protocol_version", "1.0")

            if not peer_device_id:
                error_msg = "Missing device_id in handshake request"
                logger.warning(f"Handshake rejected from {peer_device_name}: {error_msg}")
                return jsonify({"error": error_msg}), 400

            # Validate device_id format
            try:
                validate_uuid_hex(peer_device_id, "device_id")
            except Exception as e:
                error_msg = f"Invalid device_id format: {e}"
                logger.warning(f"Handshake rejected from {peer_device_name}: {error_msg}")
                return jsonify({"error": error_msg}), 400

            logger.info(f"Handshake from peer: {peer_device_name} ({peer_device_id})")

            # Get last sync timestamp for this peer from database
            last_sync = get_peer_last_sync(db, peer_device_id)

            response = HandshakeResponse(
                device_id=device_id,
                device_name=device_name,
                protocol_version="1.0",
                last_sync_timestamp=last_sync,
                server_timestamp=int(datetime.now().timestamp()),
                supports_audiofiles=audiofile_directory is not None,
            )

            return jsonify(asdict(response)), 200

        except Exception as e:
            error_msg = f"Internal server error during handshake: {e}"
            logger.error(error_msg)
            return jsonify({"error": error_msg}), 500

    @sync_bp.route("/changes", methods=["GET"])
    def get_changes() -> Tuple[Any, int]:
        """Get changes since a timestamp.

        Query params:
            since: Unix timestamp to get changes after (optional)
            limit: Maximum number of changes to return (default 1000)

        Response:
            {
                "changes": [...],
                "from_timestamp": <int>,
                "to_timestamp": <int>,
                "device_id": "...",
                "device_name": "...",
                "is_complete": true/false
            }
        """
        try:
            since_str = request.args.get("since")
            limit_str = request.args.get("limit", "1000")

            # Convert since to int if provided
            since: Optional[int] = None
            if since_str:
                try:
                    since = int(since_str)
                except ValueError:
                    error_msg = f"Invalid since parameter: '{since_str}' - must be a Unix timestamp (integer)"
                    logger.warning(f"Get changes rejected: {error_msg}")
                    return jsonify({"error": error_msg}), 400

            try:
                limit = min(int(limit_str), 10000)
            except ValueError:
                error_msg = f"Invalid limit parameter: '{limit_str}' - must be an integer"
                logger.warning(f"Get changes rejected: {error_msg}")
                return jsonify({"error": error_msg}), 400

            changes, latest_timestamp = get_changes_since(db, since, limit)

            batch = SyncBatch(
                changes=changes,
                from_timestamp=since,
                to_timestamp=latest_timestamp,
                device_id=device_id,
                device_name=device_name,
                is_complete=len(changes) < limit,
            )

            logger.debug(f"Returning {len(changes)} changes since {since}")
            return jsonify(asdict(batch)), 200

        except Exception as e:
            error_msg = f"Internal server error getting changes: {e}"
            logger.error(error_msg)
            return jsonify({"error": error_msg}), 500

    @sync_bp.route("/apply", methods=["POST"])
    def apply_changes() -> Tuple[Any, int]:
        """Apply changes from a peer.

        Request body:
            {
                "changes": [...],
                "device_id": "...",
                "device_name": "..."
            }

        Response:
            {
                "applied": 10,
                "conflicts": 2,
                "errors": []
            }
        """
        try:
            data = request.get_json(silent=True)
            if not data:
                error_msg = "Missing JSON request body in apply"
                logger.warning(f"Apply rejected: {error_msg}")
                return jsonify({"error": error_msg}), 400

            changes_data = data.get("changes", [])
            peer_device_id = data.get("device_id")
            peer_device_name = data.get("device_name", "Unknown")

            if not peer_device_id:
                error_msg = "Missing device_id in apply request"
                logger.warning(f"Apply rejected from {peer_device_name}: {error_msg}")
                return jsonify({"error": error_msg}), 400

            logger.info(f"Applying {len(changes_data)} changes from {peer_device_name} ({peer_device_id})")

            # Parse changes
            changes = []
            for i, c in enumerate(changes_data):
                try:
                    changes.append(SyncChange(
                        entity_type=c["entity_type"],
                        entity_id=c["entity_id"],
                        operation=c["operation"],
                        data=c["data"],
                        timestamp=c["timestamp"],
                        device_id=c["device_id"],
                        device_name=c.get("device_name"),
                    ))
                except KeyError as e:
                    error_msg = f"Invalid change at index {i}: missing required field {e}"
                    logger.warning(f"Apply rejected from {peer_device_name}: {error_msg}")
                    return jsonify({"error": error_msg}), 400

            applied, conflicts, errors = apply_sync_changes(
                db, changes, peer_device_id, peer_device_name
            )

            response_data = {
                "applied": applied,
                "conflicts": conflicts,
                "errors": errors,
            }

            # Log summary
            if errors:
                logger.warning(
                    f"Apply from {peer_device_name}: {applied} applied, {conflicts} conflicts, "
                    f"{len(errors)} errors: {errors[:3]}{'...' if len(errors) > 3 else ''}"
                )
            else:
                logger.info(f"Apply from {peer_device_name}: {applied} applied, {conflicts} conflicts")

            # Return appropriate HTTP status:
            # - 200: All changes applied successfully
            # - 207: Partial success (some applied, some failed)
            # - 422: All changes failed (unprocessable)
            if errors:
                if applied > 0:
                    # Partial success
                    return jsonify(response_data), 207
                else:
                    # All failed
                    return jsonify(response_data), 422
            else:
                return jsonify(response_data), 200

        except Exception as e:
            error_msg = f"Internal server error applying changes: {e}"
            logger.error(error_msg)
            return jsonify({"error": error_msg}), 500

    @sync_bp.route("/full", methods=["GET"])
    def get_full_sync() -> Tuple[Any, int]:
        """Get full dataset for initial sync.

        Response:
            {
                "notes": [...],
                "tags": [...],
                "note_tags": [...],
                "audio_files": [...],
                "note_attachments": [...],
                "device_id": "...",
                "device_name": "...",
                "timestamp": "..."
            }
        """
        try:
            full_data = get_full_dataset(db)

            notes_count = len(full_data["notes"])
            tags_count = len(full_data["tags"])
            audio_count = len(full_data.get("audio_files", []))
            logger.info(
                f"Full sync requested: returning {notes_count} notes, "
                f"{tags_count} tags, {audio_count} audio files"
            )

            return jsonify({
                "notes": full_data["notes"],
                "tags": full_data["tags"],
                "note_tags": full_data["note_tags"],
                "audio_files": full_data.get("audio_files", []),
                "note_attachments": full_data.get("note_attachments", []),
                "device_id": device_id,
                "device_name": device_name,
                "timestamp": int(datetime.now().timestamp()),
            }), 200

        except Exception as e:
            error_msg = f"Internal server error getting full dataset: {e}"
            logger.error(error_msg)
            return jsonify({"error": error_msg}), 500

    @sync_bp.route("/status", methods=["GET"])
    def status() -> Tuple[Any, int]:
        """Get sync server status.

        Response:
            {
                "status": "ok",
                "device_id": "...",
                "device_name": "...",
                "protocol_version": "1.0",
                "supports_audiofiles": true/false
            }
        """
        return jsonify({
            "status": "ok",
            "device_id": device_id,
            "device_name": device_name,
            "protocol_version": "1.0",
            "supports_audiofiles": audiofile_directory is not None,
        }), 200

    @sync_bp.route("/audio/<audio_id>/file", methods=["GET"])
    def download_audio_file(audio_id: str) -> Tuple[Any, int]:
        """Download an audio file.

        Args:
            audio_id: Audio file UUID hex string

        Response:
            Binary audio file content with 200 OK, or:
            - 400 Bad Request if audio_id is invalid
            - 404 Not Found if audiofile_directory not configured or file not found
        """
        from flask import Response

        # Get peer info from headers for logging
        peer_device_id = request.headers.get("X-Device-ID", "unknown")
        peer_device_name = request.headers.get("X-Device-Name", "unknown")
        # HTTP headers use Latin-1 encoding, but device names may contain UTF-8
        try:
            peer_device_name = peer_device_name.encode('latin-1').decode('utf-8')
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass  # Keep original if decoding fails

        # Validate audio_id
        try:
            validate_uuid_hex(audio_id)
        except Exception:
            error_msg = f"Invalid audio ID format: {audio_id}"
            logger.warning(f"Download rejected from {peer_device_name}: {error_msg}")
            return jsonify({"error": error_msg}), 400

        # Check audiofile_directory is configured
        if not audiofile_directory:
            error_msg = "audiofile_directory not configured on server"
            logger.warning(f"Download rejected from {peer_device_name}: {error_msg}")
            return jsonify({"error": error_msg}), 404

        # Find the file (look for {audio_id}.*)
        audiofile_path = Path(audiofile_directory)
        found_file = None
        if audiofile_path.exists():
            for f in audiofile_path.iterdir():
                if f.name.startswith(audio_id) and "." in f.name:
                    found_file = f
                    break

        if not found_file or not found_file.exists():
            error_msg = f"Audio file not found: {audio_id}"
            logger.warning(f"Download from {peer_device_name}: {error_msg}")
            return jsonify({"error": error_msg}), 404

        # Read and return file content
        try:
            content = found_file.read_bytes()
            logger.info(f"Sent audio file {audio_id} to {peer_device_name} ({len(content)} bytes)")
            return Response(content, status=200, mimetype="application/octet-stream")
        except Exception as e:
            error_msg = f"Failed to read file: {e}"
            logger.error(f"Download error for {peer_device_name}: {error_msg}")
            return jsonify({"error": error_msg}), 500

    @sync_bp.route("/audio/<audio_id>/file", methods=["POST"])
    def upload_audio_file(audio_id: str) -> Tuple[Any, int]:
        """Upload an audio file.

        Args:
            audio_id: Audio file UUID hex string

        Request body:
            Binary audio file content

        Response:
            200 OK on success, or:
            - 400 Bad Request if audio_id is invalid or audiofile_directory not configured
            - 404 Not Found if audio file record not found
            - 500 Internal Server Error on file write failure
        """
        # Get peer info from headers for logging
        peer_device_id = request.headers.get("X-Device-ID", "unknown")
        peer_device_name = request.headers.get("X-Device-Name", "unknown")
        # HTTP headers use Latin-1 encoding, but device names may contain UTF-8
        try:
            peer_device_name = peer_device_name.encode('latin-1').decode('utf-8')
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass  # Keep original if decoding fails

        # Validate audio_id
        try:
            validate_uuid_hex(audio_id)
        except Exception:
            error_msg = f"Invalid audio ID format: {audio_id}"
            logger.warning(f"Upload rejected from {peer_device_name}: {error_msg}")
            return jsonify({"error": error_msg}), 400

        # Check audiofile_directory is configured
        if not audiofile_directory:
            error_msg = "audiofile_directory not configured on server - cannot receive audio files"
            logger.warning(f"Upload rejected from {peer_device_name}: {error_msg}")
            return jsonify({"error": error_msg}), 400

        # Get audio file record to determine extension
        audio_file = db.get_audio_file(audio_id)
        if not audio_file:
            error_msg = f"Audio file record not found in database: {audio_id}"
            logger.warning(f"Upload rejected from {peer_device_name}: {error_msg}")
            return jsonify({"error": error_msg}), 404

        # Extract extension from filename
        filename = audio_file.get("filename", "")
        if "." in filename:
            ext = filename.rsplit(".", 1)[-1].lower()
        else:
            ext = "bin"

        # Ensure directory exists
        audiofile_path = Path(audiofile_directory)
        audiofile_path.mkdir(parents=True, exist_ok=True)

        # Write file
        file_path = audiofile_path / f"{audio_id}.{ext}"
        try:
            file_path.write_bytes(request.data)
            logger.info(f"Received audio file {audio_id} from {peer_device_name} ({len(request.data)} bytes)")
            return "OK", 200
        except Exception as e:
            error_msg = f"Failed to write file: {e}"
            logger.error(f"Upload error from {peer_device_name}: {error_msg}")
            return jsonify({"error": error_msg}), 500

    return sync_bp


def get_peer_last_sync(db: Database, peer_device_id: str) -> Optional[int]:
    """Get the last sync timestamp for a peer.

    Args:
        db: Database instance
        peer_device_id: Peer's device UUID hex string

    Returns:
        Unix timestamp of last sync, or None if never synced.
    """
    try:
        return db.get_peer_last_sync(peer_device_id)
    except Exception as e:
        logger.warning(f"Error getting peer last sync: {e}")
    return None


def get_changes_since(
    db: Database, since: Optional[int], limit: int = 1000
) -> Tuple[List[SyncChange], Optional[int]]:
    """Get all changes since a timestamp.

    Args:
        db: Database instance
        since: Unix timestamp to get changes after (None for all)
        limit: Maximum number of changes to return

    Returns:
        Tuple of (list of changes, latest timestamp)
    """
    result = db.get_changes_since(since, limit)
    raw_changes = result["changes"]
    latest_timestamp = result.get("latest_timestamp")

    changes: List[SyncChange] = []
    for c in raw_changes:
        changes.append(SyncChange(
            entity_type=c["entity_type"],
            entity_id=c["entity_id"],
            operation=c["operation"],
            data=c["data"],
            timestamp=c["timestamp"],
            device_id="",  # device_id no longer stored in main tables
        ))

    # Sort all changes by timestamp
    changes.sort(key=lambda c: c.timestamp)

    return changes, latest_timestamp


def apply_sync_changes(
    db: Database,
    changes: List[SyncChange],
    peer_device_id: str,
    peer_device_name: Optional[str] = None,
) -> Tuple[int, int, List[str]]:
    """Apply changes from a peer.

    Uses last_sync_at to detect which side(s) changed since last sync:
    - Only remote changed → apply remote
    - Only local changed → skip (keep local)
    - Both changed → create conflict (merge for notes, combined name for tags)

    Args:
        db: Database instance
        changes: List of changes to apply
        peer_device_id: Peer's device UUID hex string
        peer_device_name: Peer's human-readable name

    Returns:
        Tuple of (applied count, conflict count, error messages)
    """
    # Delegate to Rust implementation via voicecore
    # The Rust function accepts both dict and dataclass objects
    result = _rust_apply_sync_changes(
        db._rust_db,
        list(changes),  # Ensure it's a list
        peer_device_id,
        peer_device_name,
    )
    return result["applied"], result["conflicts"], result["errors"]


def get_full_dataset(db: Database) -> Dict[str, List[Dict[str, Any]]]:
    """Get the full dataset for initial sync.

    Returns:
        Dictionary with notes, tags, note_tags, note_attachments, and audio_files lists.
    """
    return db.get_full_dataset()


def update_peer_last_sync(
    db: Database, peer_device_id: str, peer_device_name: Optional[str] = None
) -> None:
    """Update or create peer's last sync timestamp.

    Args:
        db: Database instance
        peer_device_id: Peer's device UUID hex string
        peer_device_name: Peer's human-readable name
    """
    db.update_peer_sync_time(peer_device_id, peer_device_name)


def create_sync_server(
    db: Database,
    config: Any,
    host: str = "0.0.0.0",
    port: int = 8384,
) -> Flask:
    """Create a standalone Flask sync server.

    Args:
        db: Database instance
        config: Config instance
        host: Host to bind to
        port: Port to bind to

    Returns:
        Flask application instance
    """
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    device_id = config.get_device_id_hex()
    device_name = config.get_device_name()
    audiofile_directory = config.get_audiofile_directory()

    sync_bp = create_sync_blueprint(db, device_id, device_name, audiofile_directory)
    app.register_blueprint(sync_bp)

    return app

"""Sync server and client implementation for Voice Rewrite.

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
from .merge import merge_content
from .validation import uuid_to_hex, validate_uuid_hex

logger = logging.getLogger(__name__)


@dataclass
class SyncChange:
    """Represents a single change to sync."""

    entity_type: str  # "note", "tag", "note_tag"
    entity_id: str  # UUID hex string
    operation: str  # "create", "update", "delete"
    data: Dict[str, Any]  # Full entity data
    timestamp: str  # ISO format datetime
    device_id: str  # UUID hex of device that made change
    device_name: Optional[str] = None


@dataclass
class SyncBatch:
    """A batch of changes to sync."""

    changes: List[SyncChange] = field(default_factory=list)
    from_timestamp: Optional[str] = None
    to_timestamp: Optional[str] = None
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
    last_sync_timestamp: Optional[str] = None
    server_timestamp: Optional[str] = None  # For clock skew detection


def create_sync_blueprint(db: Database, device_id: str, device_name: str) -> Blueprint:
    """Create Flask blueprint for sync endpoints.

    Args:
        db: Database instance
        device_id: This device's UUID hex string
        device_name: Human-readable device name

    Returns:
        Flask Blueprint with sync routes
    """
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
                return jsonify({"error": "Missing request body"}), 400

            peer_device_id = data.get("device_id")
            peer_device_name = data.get("device_name", "Unknown")
            peer_protocol_version = data.get("protocol_version", "1.0")

            if not peer_device_id:
                return jsonify({"error": "Missing device_id"}), 400

            # Validate device_id format
            try:
                validate_uuid_hex(peer_device_id, "device_id")
            except Exception as e:
                return jsonify({"error": f"Invalid device_id: {e}"}), 400

            logger.info(f"Handshake from peer: {peer_device_name} ({peer_device_id})")

            # Get last sync timestamp for this peer from database
            last_sync = get_peer_last_sync(db, peer_device_id)

            response = HandshakeResponse(
                device_id=device_id,
                device_name=device_name,
                protocol_version="1.0",
                last_sync_timestamp=last_sync,
                server_timestamp=datetime.now().isoformat(),
            )

            return jsonify(asdict(response)), 200

        except Exception as e:
            logger.error(f"Handshake error: {e}")
            return jsonify({"error": str(e)}), 500

    @sync_bp.route("/changes", methods=["GET"])
    def get_changes() -> Tuple[Any, int]:
        """Get changes since a timestamp.

        Query params:
            since: ISO timestamp to get changes after (optional)
            limit: Maximum number of changes to return (default 1000)

        Response:
            {
                "changes": [...],
                "from_timestamp": "...",
                "to_timestamp": "...",
                "device_id": "...",
                "device_name": "...",
                "is_complete": true/false
            }
        """
        try:
            since = request.args.get("since")
            limit = min(int(request.args.get("limit", 1000)), 10000)

            changes, latest_timestamp = get_changes_since(db, since, limit)

            batch = SyncBatch(
                changes=changes,
                from_timestamp=since,
                to_timestamp=latest_timestamp,
                device_id=device_id,
                device_name=device_name,
                is_complete=len(changes) < limit,
            )

            return jsonify(asdict(batch)), 200

        except Exception as e:
            logger.error(f"Get changes error: {e}")
            return jsonify({"error": str(e)}), 500

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
                return jsonify({"error": "Missing request body"}), 400

            changes_data = data.get("changes", [])
            peer_device_id = data.get("device_id")
            peer_device_name = data.get("device_name")

            if not peer_device_id:
                return jsonify({"error": "Missing device_id"}), 400

            # Parse changes
            changes = []
            for c in changes_data:
                changes.append(SyncChange(
                    entity_type=c["entity_type"],
                    entity_id=c["entity_id"],
                    operation=c["operation"],
                    data=c["data"],
                    timestamp=c["timestamp"],
                    device_id=c["device_id"],
                    device_name=c.get("device_name"),
                ))

            applied, conflicts, errors = apply_sync_changes(
                db, changes, peer_device_id, peer_device_name
            )

            return jsonify({
                "applied": applied,
                "conflicts": conflicts,
                "errors": errors,
            }), 200

        except Exception as e:
            logger.error(f"Apply changes error: {e}")
            return jsonify({"error": str(e)}), 500

    @sync_bp.route("/full", methods=["GET"])
    def get_full_sync() -> Tuple[Any, int]:
        """Get full dataset for initial sync.

        Response:
            {
                "notes": [...],
                "tags": [...],
                "note_tags": [...],
                "device_id": "...",
                "device_name": "...",
                "timestamp": "..."
            }
        """
        try:
            full_data = get_full_dataset(db)

            return jsonify({
                "notes": full_data["notes"],
                "tags": full_data["tags"],
                "note_tags": full_data["note_tags"],
                "device_id": device_id,
                "device_name": device_name,
                "timestamp": datetime.now().isoformat(),
            }), 200

        except Exception as e:
            logger.error(f"Full sync error: {e}")
            return jsonify({"error": str(e)}), 500

    @sync_bp.route("/status", methods=["GET"])
    def status() -> Tuple[Any, int]:
        """Get sync server status.

        Response:
            {
                "status": "ok",
                "device_id": "...",
                "device_name": "...",
                "protocol_version": "1.0"
            }
        """
        return jsonify({
            "status": "ok",
            "device_id": device_id,
            "device_name": device_name,
            "protocol_version": "1.0",
        }), 200

    return sync_bp


def get_peer_last_sync(db: Database, peer_device_id: str) -> Optional[str]:
    """Get the last sync timestamp for a peer.

    Args:
        db: Database instance
        peer_device_id: Peer's device UUID hex string

    Returns:
        ISO timestamp of last sync, or None if never synced.
    """
    try:
        peer_id_bytes = uuid.UUID(hex=peer_device_id).bytes
        query = "SELECT last_sync_at FROM sync_peers WHERE peer_id = ?"
        with db.conn:
            cursor = db.conn.cursor()
            cursor.execute(query, (peer_id_bytes,))
            row = cursor.fetchone()
            if row and row.get("last_sync_at"):
                return row["last_sync_at"]
    except Exception as e:
        logger.warning(f"Error getting peer last sync: {e}")
    return None


def get_changes_since(
    db: Database, since: Optional[str], limit: int = 1000
) -> Tuple[List[SyncChange], Optional[str]]:
    """Get all changes since a timestamp.

    Args:
        db: Database instance
        since: ISO timestamp to get changes after (None for all)
        limit: Maximum number of changes to return

    Returns:
        Tuple of (list of changes, latest timestamp)
    """
    changes: List[SyncChange] = []
    latest_timestamp: Optional[str] = None

    with db.conn:
        cursor = db.conn.cursor()

        # Get note changes
        if since:
            note_query = """
                SELECT id, created_at, content, modified_at, deleted_at
                FROM notes
                WHERE modified_at >= ? OR (modified_at IS NULL AND created_at >= ?)
                ORDER BY COALESCE(modified_at, created_at)
                LIMIT ?
            """
            cursor.execute(note_query, (since, since, limit))
        else:
            note_query = """
                SELECT id, created_at, content, modified_at, deleted_at
                FROM notes
                ORDER BY COALESCE(modified_at, created_at)
                LIMIT ?
            """
            cursor.execute(note_query, (limit,))

        for row in cursor.fetchall():
            timestamp = row.get("modified_at") or row["created_at"]
            if row.get("deleted_at"):
                operation = "delete"
            elif row.get("modified_at"):
                operation = "update"
            else:
                operation = "create"

            changes.append(SyncChange(
                entity_type="note",
                entity_id=uuid_to_hex(row["id"]),
                operation=operation,
                data={
                    "id": uuid_to_hex(row["id"]),
                    "created_at": row["created_at"],
                    "content": row["content"],
                    "modified_at": row.get("modified_at"),
                    "deleted_at": row.get("deleted_at"),
                },
                timestamp=timestamp,
                device_id="",  # device_id no longer stored in main tables
            ))
            latest_timestamp = timestamp

        # Get tag changes
        if since:
            tag_query = """
                SELECT id, name, parent_id, created_at, modified_at
                FROM tags
                WHERE modified_at >= ? OR (modified_at IS NULL AND created_at >= ?)
                ORDER BY COALESCE(modified_at, created_at)
                LIMIT ?
            """
            cursor.execute(tag_query, (since, since, limit - len(changes)))
        else:
            tag_query = """
                SELECT id, name, parent_id, created_at, modified_at
                FROM tags
                ORDER BY COALESCE(modified_at, created_at)
                LIMIT ?
            """
            cursor.execute(tag_query, (limit - len(changes),))

        for row in cursor.fetchall():
            timestamp = row.get("modified_at") or row["created_at"]
            operation = "update" if row.get("modified_at") else "create"

            changes.append(SyncChange(
                entity_type="tag",
                entity_id=uuid_to_hex(row["id"]),
                operation=operation,
                data={
                    "id": uuid_to_hex(row["id"]),
                    "name": row["name"],
                    "parent_id": uuid_to_hex(row["parent_id"]) if row.get("parent_id") else None,
                    "created_at": row["created_at"],
                    "modified_at": row.get("modified_at"),
                },
                timestamp=timestamp,
                device_id="",  # device_id no longer stored in main tables
            ))
            if timestamp and (not latest_timestamp or timestamp > latest_timestamp):
                latest_timestamp = timestamp

        # Get note_tag changes (including reactivations via modified_at)
        if since:
            nt_query = """
                SELECT note_id, tag_id, created_at, modified_at, deleted_at
                FROM note_tags
                WHERE created_at >= ? OR deleted_at >= ? OR modified_at >= ?
                ORDER BY COALESCE(modified_at, deleted_at, created_at)
                LIMIT ?
            """
            cursor.execute(nt_query, (since, since, since, limit - len(changes)))
        else:
            nt_query = """
                SELECT note_id, tag_id, created_at, modified_at, deleted_at
                FROM note_tags
                ORDER BY COALESCE(modified_at, deleted_at, created_at)
                LIMIT ?
            """
            cursor.execute(nt_query, (limit - len(changes),))

        for row in cursor.fetchall():
            # Determine timestamp and operation based on state
            if row.get("deleted_at"):
                # Deleted - use deleted_at as timestamp
                timestamp = row["deleted_at"]
                operation = "delete"
            elif row.get("modified_at"):
                # Reactivated (was deleted, now active) - use modified_at
                timestamp = row["modified_at"]
                operation = "create"
            else:
                # Newly created
                timestamp = row["created_at"]
                operation = "create"

            changes.append(SyncChange(
                entity_type="note_tag",
                entity_id=f"{uuid_to_hex(row['note_id'])}:{uuid_to_hex(row['tag_id'])}",
                operation=operation,
                data={
                    "note_id": uuid_to_hex(row["note_id"]),
                    "tag_id": uuid_to_hex(row["tag_id"]),
                    "created_at": row["created_at"],
                    "modified_at": row.get("modified_at"),
                    "deleted_at": row.get("deleted_at"),
                },
                timestamp=timestamp,
                device_id="",  # device_id no longer stored in main tables
            ))
            if timestamp and (not latest_timestamp or timestamp > latest_timestamp):
                latest_timestamp = timestamp

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
    applied = 0
    conflicts = 0
    errors: List[str] = []

    # Get last sync timestamp with this peer (for detecting unchanged local)
    last_sync_at = get_peer_last_sync(db, peer_device_id)

    with db.conn:
        cursor = db.conn.cursor()

        for change in changes:
            try:
                if change.entity_type == "note":
                    result = apply_note_change(
                        cursor, change, peer_device_name, last_sync_at
                    )
                elif change.entity_type == "tag":
                    result = apply_tag_change(
                        cursor, change, peer_device_name, last_sync_at
                    )
                elif change.entity_type == "note_tag":
                    result = apply_note_tag_change(
                        cursor, change, peer_device_name, last_sync_at
                    )
                else:
                    errors.append(f"Unknown entity type: {change.entity_type}")
                    continue

                if result == "applied":
                    applied += 1
                elif result == "conflict":
                    conflicts += 1
                # "skipped" means no action needed (already up to date)

            except Exception as e:
                errors.append(f"Error applying {change.entity_type} {change.entity_id}: {e}")
                logger.error(f"Error applying change: {e}")

        db.conn.commit()

    # Update peer's last sync timestamp
    update_peer_last_sync(db, peer_device_id, peer_device_name)

    return applied, conflicts, errors


def apply_note_change(
    cursor: Any,
    change: SyncChange,
    peer_device_name: Optional[str] = None,
    last_sync_at: Optional[str] = None,
) -> str:
    """Apply a note change.

    Args:
        cursor: Database cursor
        change: The sync change to apply
        peer_device_name: Human-readable name of the peer device
        last_sync_at: When we last synced with this peer (for detecting unchanged local)

    Returns: "applied", "conflict", or "skipped"
    """
    note_id = uuid.UUID(hex=change.entity_id).bytes
    data = change.data

    # Check if note exists locally
    cursor.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
    existing = cursor.fetchone()

    if change.operation == "create":
        if existing:
            # Note already exists - check if it's deleted
            if existing.get("deleted_at") is None:
                return "skipped"  # Already have this active note

            # Local deleted - compare content to see if remote edited
            local_deleted_content = existing["content"]
            remote_content = data["content"]

            if local_deleted_content == remote_content:
                # Remote didn't edit - keep deleted
                return "skipped"

            # Remote edited, local deleted - resurrect and create conflict
            local_deleted = existing["deleted_at"]
            remote_modified = data.get("modified_at") or data["created_at"]

            cursor.execute(
                """UPDATE notes SET content = ?, modified_at = ?, deleted_at = NULL
                   WHERE id = ?""",
                (
                    remote_content,
                    data.get("modified_at"),
                    note_id,
                ),
            )

            # Create delete conflict record
            conflict_id = uuid7().bytes
            remote_device_id_bytes = uuid.UUID(hex=change.device_id).bytes if change.device_id else None
            cursor.execute(
                """INSERT INTO conflicts_note_delete
                   (id, note_id, surviving_content, surviving_modified_at, surviving_device_id,
                    deleted_content, deleted_at, deleting_device_id, deleting_device_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (
                    conflict_id,
                    note_id,
                    remote_content,  # Remote edited content survives
                    remote_modified,
                    remote_device_id_bytes,  # Remote device has surviving content
                    local_deleted_content,  # Local content before deletion
                    local_deleted,
                    None,  # Local device deleted (no device_id tracked)
                    None,  # Local device name unknown
                ),
            )
            return "conflict"
        else:
            # Create new note
            cursor.execute(
                """INSERT INTO notes (id, created_at, content, modified_at, deleted_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    note_id,
                    data["created_at"],
                    data["content"],
                    data.get("modified_at"),
                    data.get("deleted_at"),
                ),
            )
            return "applied"

    elif change.operation == "update":
        if not existing:
            # Note doesn't exist - create it
            cursor.execute(
                """INSERT INTO notes (id, created_at, content, modified_at, deleted_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    note_id,
                    data["created_at"],
                    data["content"],
                    data.get("modified_at"),
                    data.get("deleted_at"),
                ),
            )
            return "applied"

        # Check if local note is deleted
        if existing.get("deleted_at"):
            local_deleted_content = existing["content"]
            remote_content = data["content"]

            if local_deleted_content == remote_content:
                # Remote didn't edit - keep deleted
                return "skipped"

            # Remote edited, local deleted - resurrect and create conflict
            local_deleted = existing["deleted_at"]
            remote_modified = data.get("modified_at") or data["created_at"]

            # Resurrect the note with remote content
            cursor.execute(
                """UPDATE notes SET content = ?, modified_at = ?, deleted_at = NULL
                   WHERE id = ?""",
                (remote_content, remote_modified, note_id),
            )

            # Create delete conflict record
            conflict_id = uuid7().bytes
            remote_device_id_bytes = uuid.UUID(hex=change.device_id).bytes if change.device_id else None
            cursor.execute(
                """INSERT INTO conflicts_note_delete
                   (id, note_id, surviving_content, surviving_modified_at, surviving_device_id,
                    deleted_content, deleted_at, deleting_device_id, deleting_device_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (
                    conflict_id,
                    note_id,
                    remote_content,  # Remote edited content survives
                    remote_modified,
                    remote_device_id_bytes,
                    local_deleted_content,  # Local content before deletion
                    local_deleted,
                    None,  # local device deleted it
                    None,
                ),
            )
            return "conflict"

        local_content = existing["content"]
        remote_content = data["content"]
        local_modified = existing.get("modified_at") or existing["created_at"]
        remote_modified = data.get("modified_at") or data["created_at"]

        # If content is the same, no merge needed
        if local_content == remote_content:
            return "skipped"

        # Content differs - determine who changed since last sync
        # If last_sync_at is None (never synced), treat as "changed" to be safe
        # Use > (not >=) because timestamps are second-precision
        local_changed = (
            last_sync_at is None
            or (local_modified is not None and local_modified > last_sync_at)
        )
        remote_changed = (
            last_sync_at is None
            or (remote_modified is not None and remote_modified > last_sync_at)
        )

        if not local_changed and remote_changed:
            # Only remote changed → update local without conflict
            cursor.execute(
                """UPDATE notes SET content = ?, modified_at = ?
                   WHERE id = ?""",
                (remote_content, remote_modified, note_id),
            )
            return "applied"

        if local_changed and not remote_changed:
            # Only local changed → skip, we'll push our version
            return "skipped"

        if not local_changed and not remote_changed:
            # Neither changed but content differs? Shouldn't happen, but skip
            return "skipped"

        # Both changed - merge line-by-line, adding conflict markers
        # only around lines that actually differ (not the entire content)
        merge_result = merge_content(local_content, remote_content)
        merged_content = merge_result.content

        cursor.execute(
            """UPDATE notes SET content = ?, modified_at = datetime('now')
               WHERE id = ?""",
            (merged_content, note_id),
        )

        # Create conflict record for tracking
        conflict_id = uuid7().bytes
        remote_device_id_bytes = uuid.UUID(hex=change.device_id).bytes if change.device_id else None
        cursor.execute(
            """INSERT INTO conflicts_note_content
               (id, note_id, local_content, local_modified_at, local_device_id,
                remote_content, remote_modified_at, remote_device_id, remote_device_name, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                conflict_id,
                note_id,
                local_content,
                local_modified,
                None,  # local_device_id no longer tracked
                remote_content,
                remote_modified,
                remote_device_id_bytes,
                peer_device_name,
            ),
        )
        return "conflict"

    elif change.operation == "delete":
        if not existing:
            # Note doesn't exist locally - create it as deleted
            cursor.execute(
                """INSERT INTO notes (id, created_at, content, modified_at, deleted_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    note_id,
                    data["created_at"],
                    data["content"],
                    data.get("modified_at"),
                    data.get("deleted_at"),
                ),
            )
            return "applied"

        if existing.get("deleted_at"):
            return "skipped"  # Already deleted

        # Compare content to determine if local edited
        local_content = existing["content"]
        remote_content = data.get("content")

        if local_content == remote_content:
            # Local didn't edit - propagate the delete
            cursor.execute(
                """UPDATE notes SET deleted_at = ?, modified_at = ?
                   WHERE id = ?""",
                (data.get("deleted_at"), data.get("deleted_at"), note_id),
            )
            return "applied"

        # Local edited, remote wants to delete - create conflict
        # Preserve local edits, don't silently delete
        local_modified = existing.get("modified_at") or existing["created_at"]
        remote_deleted = data.get("deleted_at")

        conflict_id = uuid7().bytes
        remote_device_id_bytes = uuid.UUID(hex=change.device_id).bytes if change.device_id else None
        cursor.execute(
            """INSERT INTO conflicts_note_delete
               (id, note_id, surviving_content, surviving_modified_at, surviving_device_id,
                deleted_content, deleted_at, deleting_device_id, deleting_device_name, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                conflict_id,
                note_id,
                local_content,  # Local edited content survives
                local_modified,
                None,  # surviving_device_id no longer tracked
                remote_content,  # Remote content before deletion
                remote_deleted,
                remote_device_id_bytes,
                peer_device_name,
            ),
        )
        return "conflict"

    return "skipped"


def apply_tag_change(
    cursor: Any,
    change: SyncChange,
    peer_device_name: Optional[str] = None,
    last_sync_at: Optional[str] = None,
) -> str:
    """Apply a tag change.

    Args:
        cursor: Database cursor
        change: The sync change to apply
        peer_device_name: Human-readable name of the peer device
        last_sync_at: When we last synced with this peer (for detecting unchanged local)

    Returns: "applied", "conflict", or "skipped"
    """
    tag_id = uuid.UUID(hex=change.entity_id).bytes
    data = change.data

    # Check if tag exists locally
    cursor.execute("SELECT * FROM tags WHERE id = ?", (tag_id,))
    existing = cursor.fetchone()

    parent_id_bytes = None
    if data.get("parent_id"):
        parent_id_bytes = uuid.UUID(hex=data["parent_id"]).bytes

    if change.operation == "create":
        if existing:
            return "skipped"  # Already have this tag
        else:
            cursor.execute(
                """INSERT INTO tags (id, name, parent_id, created_at, modified_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    tag_id,
                    data["name"],
                    parent_id_bytes,
                    data["created_at"],
                    data.get("modified_at"),
                ),
            )
            return "applied"

    elif change.operation == "update":
        if not existing:
            # Tag doesn't exist - create it
            cursor.execute(
                """INSERT INTO tags (id, name, parent_id, created_at, modified_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    tag_id,
                    data["name"],
                    parent_id_bytes,
                    data["created_at"],
                    data.get("modified_at"),
                ),
            )
            return "applied"

        # If names are the same, no rename needed
        if data["name"] == existing["name"]:
            return "skipped"

        # Names differ - determine who changed since last sync
        local_modified = existing.get("modified_at") or existing["created_at"]
        remote_modified = data.get("modified_at") or data["created_at"]

        # Check if each side was modified since last sync
        # If last_sync_at is None (never synced), treat as "changed" to be safe
        # Use > (not >=) because timestamps are second-precision
        local_changed = (
            last_sync_at is None
            or (local_modified is not None and local_modified > last_sync_at)
        )
        remote_changed = (
            last_sync_at is None
            or (remote_modified is not None and remote_modified > last_sync_at)
        )

        if not local_changed and remote_changed:
            # Only remote changed → apply remote's name
            cursor.execute(
                """UPDATE tags SET name = ?, modified_at = ?
                   WHERE id = ?""",
                (data["name"], remote_modified, tag_id),
            )
            return "applied"

        if local_changed and not remote_changed:
            # Only local changed → skip, we'll push our version
            return "skipped"

        if not local_changed and not remote_changed:
            # Neither changed but names differ? Shouldn't happen, but skip
            return "skipped"

        # Both changed → combine names and create conflict
        combined_name = f"{existing['name']} | {data['name']}"
        cursor.execute(
            """UPDATE tags SET name = ?, modified_at = datetime('now')
               WHERE id = ?""",
            (combined_name, tag_id),
        )

        conflict_id = uuid7().bytes
        remote_device_id_bytes = uuid.UUID(hex=change.device_id).bytes if change.device_id else None
        cursor.execute(
            """INSERT INTO conflicts_tag_rename
               (id, tag_id, local_name, local_modified_at, local_device_id,
                remote_name, remote_modified_at, remote_device_id, remote_device_name, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                conflict_id,
                tag_id,
                existing["name"],
                local_modified,
                None,  # local_device_id no longer tracked
                data["name"],
                remote_modified,
                remote_device_id_bytes,
                peer_device_name,
            ),
        )
        return "conflict"

    return "skipped"


def apply_note_tag_change(
    cursor: Any,
    change: SyncChange,
    peer_device_name: Optional[str] = None,
    last_sync_at: Optional[str] = None,
) -> str:
    """Apply a note-tag association change.

    Uses last_sync_at to determine if changes are new:
    - Changes from before last_sync are skipped (already processed)
    - Changes after last_sync are applied if local hasn't also changed
    - If both changed, favor preservation (add wins) and record conflict

    Returns: "applied", "skipped", or "conflict"
    """
    # Parse entity_id (format: "note_id:tag_id")
    parts = change.entity_id.split(":")
    if len(parts) != 2:
        return "skipped"

    note_id = uuid.UUID(hex=parts[0]).bytes
    tag_id = uuid.UUID(hex=parts[1]).bytes
    data = change.data

    # Determine the timestamp of this incoming change
    if change.operation == "delete":
        incoming_time = data.get("deleted_at") or data.get("modified_at")
    else:
        incoming_time = data.get("modified_at") or data.get("created_at")

    # If this change happened before or at last_sync, skip it (already processed)
    if last_sync_at and incoming_time and incoming_time <= last_sync_at:
        return "skipped"

    # Check if association exists locally
    cursor.execute(
        "SELECT created_at, modified_at, deleted_at FROM note_tags WHERE note_id = ? AND tag_id = ?",
        (note_id, tag_id),
    )
    existing = cursor.fetchone()

    # Determine if local changed since last_sync
    local_changed = False
    if existing:
        local_time = existing.get("modified_at") or existing.get("deleted_at") or existing.get("created_at")
        local_changed = last_sync_at is None or (local_time and local_time > last_sync_at)

    # Helper to create conflict record
    def create_conflict_record():
        remote_device_id_bytes = uuid.UUID(hex=change.device_id).bytes if change.device_id else None
        conflict_id = uuid7().bytes
        cursor.execute(
            """INSERT INTO conflicts_note_tag
               (id, note_id, tag_id,
                local_created_at, local_modified_at, local_deleted_at,
                remote_created_at, remote_modified_at, remote_deleted_at, remote_device_id, remote_device_name,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                conflict_id,
                note_id,
                tag_id,
                existing.get("created_at") if existing else None,
                existing.get("modified_at") if existing else None,
                existing.get("deleted_at") if existing else None,
                data.get("created_at"),
                data.get("modified_at"),
                data.get("deleted_at"),
                remote_device_id_bytes,
                peer_device_name,
            ),
        )

    if change.operation == "create":
        if existing:
            if existing.get("deleted_at") is None:
                # Already active - nothing to do
                return "skipped"
            else:
                # Local is deleted, remote wants active
                if local_changed:
                    # Both changed - record conflict, favor preservation (add wins)
                    create_conflict_record()
                    cursor.execute(
                        """UPDATE note_tags SET deleted_at = NULL, modified_at = datetime('now')
                           WHERE note_id = ? AND tag_id = ?""",
                        (note_id, tag_id),
                    )
                    return "conflict"
                # Only remote changed - reactivate
                cursor.execute(
                    """UPDATE note_tags SET deleted_at = NULL, modified_at = datetime('now')
                       WHERE note_id = ? AND tag_id = ?""",
                    (note_id, tag_id),
                )
                return "applied"
        else:
            # New association - insert as active
            cursor.execute(
                """INSERT INTO note_tags (note_id, tag_id, created_at, modified_at, deleted_at)
                   VALUES (?, ?, ?, ?, NULL)""",
                (
                    note_id,
                    tag_id,
                    data["created_at"],
                    data.get("modified_at"),
                ),
            )
            return "applied"

    elif change.operation == "delete":
        if not existing:
            # Doesn't exist - create as deleted (for sync consistency)
            cursor.execute(
                """INSERT INTO note_tags (note_id, tag_id, created_at, modified_at, deleted_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    note_id,
                    tag_id,
                    data["created_at"],
                    data.get("modified_at"),
                    data.get("deleted_at"),
                ),
            )
            return "applied"

        if existing.get("deleted_at"):
            return "skipped"  # Already deleted

        # Local is active, remote wants to delete
        if local_changed:
            # Both changed - record conflict, favor preservation (keep local active)
            create_conflict_record()
            return "conflict"

        # Only remote changed - apply the delete
        cursor.execute(
            """UPDATE note_tags SET deleted_at = ?, modified_at = ?
               WHERE note_id = ? AND tag_id = ?""",
            (
                data.get("deleted_at"),
                data.get("modified_at") or data.get("deleted_at"),
                note_id,
                tag_id,
            ),
        )
        return "applied"

    return "skipped"


def get_full_dataset(db: Database) -> Dict[str, List[Dict[str, Any]]]:
    """Get the full dataset for initial sync.

    Returns:
        Dictionary with notes, tags, and note_tags lists.
    """
    result: Dict[str, List[Dict[str, Any]]] = {
        "notes": [],
        "tags": [],
        "note_tags": [],
    }

    with db.conn:
        cursor = db.conn.cursor()

        # Get all notes (including deleted for sync purposes)
        cursor.execute(
            """SELECT id, created_at, content, modified_at, deleted_at
               FROM notes ORDER BY created_at"""
        )
        for row in cursor.fetchall():
            result["notes"].append({
                "id": uuid_to_hex(row["id"]),
                "created_at": row["created_at"],
                "content": row["content"],
                "modified_at": row.get("modified_at"),
                "deleted_at": row.get("deleted_at"),
            })

        # Get all tags
        cursor.execute(
            """SELECT id, name, parent_id, created_at, modified_at
               FROM tags ORDER BY created_at"""
        )
        for row in cursor.fetchall():
            result["tags"].append({
                "id": uuid_to_hex(row["id"]),
                "name": row["name"],
                "parent_id": uuid_to_hex(row["parent_id"]) if row.get("parent_id") else None,
                "created_at": row["created_at"],
                "modified_at": row.get("modified_at"),
            })

        # Get all note_tags (including deleted for sync purposes)
        cursor.execute(
            """SELECT note_id, tag_id, created_at, modified_at, deleted_at
               FROM note_tags ORDER BY created_at"""
        )
        for row in cursor.fetchall():
            result["note_tags"].append({
                "note_id": uuid_to_hex(row["note_id"]),
                "tag_id": uuid_to_hex(row["tag_id"]),
                "created_at": row["created_at"],
                "modified_at": row.get("modified_at"),
                "deleted_at": row.get("deleted_at"),
            })

    return result


def update_peer_last_sync(
    db: Database, peer_device_id: str, peer_device_name: Optional[str] = None
) -> None:
    """Update or create peer's last sync timestamp.

    Args:
        db: Database instance
        peer_device_id: Peer's device UUID hex string
        peer_device_name: Peer's human-readable name
    """
    peer_id_bytes = uuid.UUID(hex=peer_device_id).bytes

    with db.conn:
        cursor = db.conn.cursor()

        # Check if peer exists
        cursor.execute("SELECT peer_id FROM sync_peers WHERE peer_id = ?", (peer_id_bytes,))
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                """UPDATE sync_peers SET last_sync_at = datetime('now'), peer_name = ?
                   WHERE peer_id = ?""",
                (peer_device_name, peer_id_bytes),
            )
        else:
            cursor.execute(
                """INSERT INTO sync_peers (peer_id, peer_name, peer_url, last_sync_at)
                   VALUES (?, ?, '', datetime('now'))""",
                (peer_id_bytes, peer_device_name),
            )

        db.conn.commit()


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

    sync_bp = create_sync_blueprint(db, device_id, device_name)
    app.register_blueprint(sync_bp)

    return app

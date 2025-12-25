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
        return db.get_peer_last_sync(peer_device_id)
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
    applied = 0
    conflicts = 0
    errors: List[str] = []

    # Get last sync timestamp with this peer (for detecting unchanged local)
    last_sync_at = get_peer_last_sync(db, peer_device_id)

    for change in changes:
        try:
            if change.entity_type == "note":
                result = apply_note_change(
                    db, change, peer_device_name, last_sync_at
                )
            elif change.entity_type == "tag":
                result = apply_tag_change(
                    db, change, peer_device_name, last_sync_at
                )
            elif change.entity_type == "note_tag":
                result = apply_note_tag_change(
                    db, change, peer_device_name, last_sync_at
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

    # Update peer's last sync timestamp
    update_peer_last_sync(db, peer_device_id, peer_device_name)

    return applied, conflicts, errors


def apply_note_change(
    db: Database,
    change: SyncChange,
    peer_device_name: Optional[str] = None,
    last_sync_at: Optional[str] = None,
) -> str:
    """Apply a note change.

    Args:
        db: Database instance
        change: The sync change to apply
        peer_device_name: Human-readable name of the peer device
        last_sync_at: When we last synced with this peer (for detecting unchanged local)

    Returns: "applied", "conflict", or "skipped"
    """
    note_id = change.entity_id
    data = change.data

    # Check if note exists locally (including deleted)
    existing = db.get_note_raw(note_id)

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

            db.apply_sync_note(
                note_id, data["created_at"], remote_content,
                data.get("modified_at"), None  # Clear deleted_at
            )

            # Create delete conflict record
            db.create_note_delete_conflict(
                note_id,
                remote_content,  # surviving_content
                remote_modified,  # surviving_modified_at
                change.device_id if change.device_id else None,  # surviving_device_id
                local_deleted_content,  # deleted_content
                local_deleted,  # deleted_at
                None,  # deleting_device_id (local)
                None,  # deleting_device_name
            )
            return "conflict"
        else:
            # Create new note
            db.apply_sync_note(
                note_id, data["created_at"], data["content"],
                data.get("modified_at"), data.get("deleted_at")
            )
            return "applied"

    elif change.operation == "update":
        if not existing:
            # Note doesn't exist - create it
            db.apply_sync_note(
                note_id, data["created_at"], data["content"],
                data.get("modified_at"), data.get("deleted_at")
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
            db.apply_sync_note(
                note_id, existing["created_at"], remote_content,
                remote_modified, None  # Clear deleted_at
            )

            # Create delete conflict record
            db.create_note_delete_conflict(
                note_id,
                remote_content,  # surviving_content
                remote_modified,  # surviving_modified_at
                change.device_id if change.device_id else None,  # surviving_device_id
                local_deleted_content,  # deleted_content
                local_deleted,  # deleted_at
                None,  # deleting_device_id (local)
                None,  # deleting_device_name
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
            db.apply_sync_note(
                note_id, existing["created_at"], remote_content,
                remote_modified, None
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

        db.apply_sync_note(
            note_id, existing["created_at"], merged_content,
            datetime.now().isoformat(), None
        )

        # Create conflict record for tracking
        db.create_note_content_conflict(
            note_id,
            local_content,
            local_modified,
            remote_content,
            remote_modified,
            change.device_id if change.device_id else None,
            peer_device_name,
        )
        return "conflict"

    elif change.operation == "delete":
        if not existing:
            # Note doesn't exist locally - create it as deleted
            db.apply_sync_note(
                note_id, data["created_at"], data["content"],
                data.get("modified_at"), data.get("deleted_at")
            )
            return "applied"

        if existing.get("deleted_at"):
            return "skipped"  # Already deleted

        # Compare content to determine if local edited
        local_content = existing["content"]
        remote_content = data.get("content")

        if local_content == remote_content:
            # Local didn't edit - propagate the delete
            db.apply_sync_note(
                note_id, existing["created_at"], existing["content"],
                data.get("deleted_at"), data.get("deleted_at")
            )
            return "applied"

        # Local edited, remote wants to delete - create conflict
        # Preserve local edits, don't silently delete
        local_modified = existing.get("modified_at") or existing["created_at"]
        remote_deleted = data.get("deleted_at")

        db.create_note_delete_conflict(
            note_id,
            local_content,  # surviving_content
            local_modified,  # surviving_modified_at
            None,  # surviving_device_id (local)
            remote_content,  # deleted_content
            remote_deleted,  # deleted_at
            change.device_id if change.device_id else None,  # deleting_device_id
            peer_device_name,  # deleting_device_name
        )
        return "conflict"

    return "skipped"


def apply_tag_change(
    db: Database,
    change: SyncChange,
    peer_device_name: Optional[str] = None,
    last_sync_at: Optional[str] = None,
) -> str:
    """Apply a tag change.

    Args:
        db: Database instance
        change: The sync change to apply
        peer_device_name: Human-readable name of the peer device
        last_sync_at: When we last synced with this peer (for detecting unchanged local)

    Returns: "applied", "conflict", or "skipped"
    """
    tag_id = change.entity_id
    data = change.data

    # Check if tag exists locally
    existing = db.get_tag_raw(tag_id)

    if change.operation == "create":
        if existing:
            return "skipped"  # Already have this tag
        else:
            db.apply_sync_tag(
                tag_id, data["name"], data.get("parent_id"),
                data["created_at"], data.get("modified_at")
            )
            return "applied"

    elif change.operation == "update":
        if not existing:
            # Tag doesn't exist - create it
            db.apply_sync_tag(
                tag_id, data["name"], data.get("parent_id"),
                data["created_at"], data.get("modified_at")
            )
            return "applied"

        local_name = existing["name"]
        remote_name = data["name"]
        local_parent_id = existing.get("parent_id")
        remote_parent_id = data.get("parent_id")
        local_modified = existing.get("modified_at") or existing["created_at"]
        remote_modified = data.get("modified_at") or data["created_at"]

        # Check if local changed since last sync
        local_changed = (
            last_sync_at is None
            or (local_modified is not None and local_modified > last_sync_at)
        )
        remote_changed = (
            last_sync_at is None
            or (remote_modified is not None and remote_modified > last_sync_at)
        )

        if not local_changed and remote_changed:
            # Only remote changed → apply remote's changes
            db.apply_sync_tag(
                tag_id, remote_name, remote_parent_id,
                existing["created_at"], remote_modified
            )
            return "applied"

        if local_changed and not remote_changed:
            # Only local changed → skip, we'll push our version
            return "skipped"

        if not local_changed and not remote_changed:
            # Neither changed - skip
            return "skipped"

        # Both changed - check for conflicts
        has_name_conflict = False
        has_parent_conflict = False
        final_name = local_name

        # Check for name conflict
        if local_name != remote_name:
            db.create_tag_rename_conflict(
                tag_id,
                local_name,
                local_modified,
                remote_name,
                remote_modified,
                change.device_id if change.device_id else None,
                peer_device_name,
            )
            has_name_conflict = True
            # Combine both names so no rename is lost
            final_name = f"{local_name} | {remote_name}"

        # Check for parent_id conflict
        if local_parent_id != remote_parent_id:
            db.create_tag_parent_conflict(
                tag_id,
                local_parent_id,
                local_modified,
                remote_parent_id,
                remote_modified,
                change.device_id if change.device_id else None,
                peer_device_name,
            )
            has_parent_conflict = True

        if has_name_conflict or has_parent_conflict:
            # Apply combined name (for name conflicts) but keep local parent
            # Use the later timestamp as modified_at
            final_modified = max(local_modified, remote_modified) if local_modified and remote_modified else (local_modified or remote_modified)
            db.apply_sync_tag(
                tag_id, final_name, local_parent_id,
                existing["created_at"], final_modified
            )
            return "conflict"

        # No conflicts - apply (same name and parent)
        db.apply_sync_tag(
            tag_id, remote_name, remote_parent_id,
            existing["created_at"], remote_modified
        )
        return "applied"

    return "skipped"


def apply_note_tag_change(
    db: Database,
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

    note_id = parts[0]
    tag_id = parts[1]
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
    existing = db.get_note_tag_raw(note_id, tag_id)

    # Determine if local changed since last_sync
    local_changed = False
    if existing:
        local_time = existing.get("modified_at") or existing.get("deleted_at") or existing.get("created_at")
        local_changed = last_sync_at is None or (local_time and local_time > last_sync_at)

    # Helper to create conflict record
    def create_conflict_record():
        db.create_note_tag_conflict(
            note_id,
            tag_id,
            existing.get("created_at") if existing else None,
            existing.get("modified_at") if existing else None,
            existing.get("deleted_at") if existing else None,
            data.get("created_at"),
            data.get("modified_at"),
            data.get("deleted_at"),
            change.device_id if change.device_id else None,
            peer_device_name,
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
                    db.apply_sync_note_tag(
                        note_id, tag_id, existing["created_at"],
                        datetime.now().isoformat(), None  # Clear deleted_at
                    )
                    return "conflict"
                # Only remote changed - reactivate
                db.apply_sync_note_tag(
                    note_id, tag_id, existing["created_at"],
                    datetime.now().isoformat(), None  # Clear deleted_at
                )
                return "applied"
        else:
            # New association - insert as active
            db.apply_sync_note_tag(
                note_id, tag_id, data["created_at"],
                data.get("modified_at"), None
            )
            return "applied"

    elif change.operation == "delete":
        if not existing:
            # Doesn't exist - create as deleted (for sync consistency)
            db.apply_sync_note_tag(
                note_id, tag_id, data["created_at"],
                data.get("modified_at"), data.get("deleted_at")
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
        db.apply_sync_note_tag(
            note_id, tag_id, existing["created_at"],
            data.get("modified_at") or data.get("deleted_at"), data.get("deleted_at")
        )
        return "applied"

    elif change.operation == "update":
        # Update operation - typically reactivation (deleted_at cleared)
        if not existing:
            # Doesn't exist - create with the remote state
            db.apply_sync_note_tag(
                note_id, tag_id, data["created_at"],
                data.get("modified_at"), data.get("deleted_at")
            )
            return "applied"

        # Check if remote is reactivating (deleted_at is None)
        remote_deleted = data.get("deleted_at")
        local_deleted = existing.get("deleted_at")

        if remote_deleted is None and local_deleted is not None:
            # Remote reactivated, local still deleted
            if local_changed:
                # Both changed - record conflict, favor preservation (reactivate)
                create_conflict_record()
                db.apply_sync_note_tag(
                    note_id, tag_id, existing["created_at"],
                    data.get("modified_at"), None  # Clear deleted_at
                )
                return "conflict"
            # Only remote changed - reactivate
            db.apply_sync_note_tag(
                note_id, tag_id, existing["created_at"],
                data.get("modified_at"), None  # Clear deleted_at
            )
            return "applied"

        if remote_deleted is not None and local_deleted is None:
            # Remote wants to delete, local is active
            if local_changed:
                # Both changed - record conflict, favor preservation (keep active)
                create_conflict_record()
                return "conflict"
            # Only remote changed - apply the delete
            db.apply_sync_note_tag(
                note_id, tag_id, existing["created_at"],
                data.get("modified_at"), data.get("deleted_at")
            )
            return "applied"

        # Both have same deleted state - just update timestamps if needed
        db.apply_sync_note_tag(
            note_id, tag_id, existing["created_at"],
            data.get("modified_at"), data.get("deleted_at")
        )
        return "applied"

    return "skipped"


def get_full_dataset(db: Database) -> Dict[str, List[Dict[str, Any]]]:
    """Get the full dataset for initial sync.

    Returns:
        Dictionary with notes, tags, and note_tags lists.
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

    sync_bp = create_sync_blueprint(db, device_id, device_name)
    app.register_blueprint(sync_bp)

    return app

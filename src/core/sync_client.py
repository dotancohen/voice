"""Sync client for Voice Rewrite peer-to-peer synchronization.

This module provides the client side of the sync protocol, allowing
this device to:
- Connect to peer sync servers
- Pull changes from peers
- Push local changes to peers
- Handle TOFU certificate verification

CRITICAL: This module must have NO Qt/PySide6 dependencies.
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .config import Config
from .database import Database
from .sync import (
    SyncChange,
    SyncBatch,
    apply_sync_changes,
    get_changes_since,
)
from .tls import (
    TOFUVerifier,
    create_client_ssl_context,
    compute_fingerprint_from_pem,
)

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of a sync operation."""

    success: bool
    pulled: int = 0  # Changes pulled from peer
    pushed: int = 0  # Changes pushed to peer
    conflicts: int = 0
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


@dataclass
class PeerInfo:
    """Information about a sync peer."""

    peer_id: str
    peer_name: str
    peer_url: str
    certificate_fingerprint: Optional[str] = None
    last_sync_at: Optional[str] = None


class SyncClient:
    """Client for syncing with peer devices.

    Handles connecting to peer sync servers, pulling/pushing changes,
    and managing the sync state.
    """

    def __init__(self, db: Database, config: Config) -> None:
        """Initialize sync client.

        Args:
            db: Database instance
            config: Config instance
        """
        self.db = db
        self.config = config
        self.tofu_verifier = TOFUVerifier(config)
        self.device_id = config.get_device_id_hex()
        self.device_name = config.get_device_name()

    def sync_with_peer(self, peer_id: str) -> SyncResult:
        """Perform full sync with a peer.

        This does a bidirectional sync:
        1. Pull changes from peer
        2. Push local changes to peer

        Args:
            peer_id: UUID hex string of peer to sync with

        Returns:
            SyncResult with summary of sync operation
        """
        peer = self.config.get_peer(peer_id)
        if not peer:
            return SyncResult(
                success=False,
                errors=[f"Unknown peer: {peer_id}"],
            )

        peer_url = peer.get("peer_url")
        if not peer_url:
            return SyncResult(
                success=False,
                errors=[f"Peer {peer_id} has no URL configured"],
            )

        logger.info(f"Starting sync with peer: {peer.get('peer_name')} ({peer_id})")

        result = SyncResult(success=True)

        try:
            # Step 1: Handshake
            handshake_result = self._handshake(peer_url, peer_id)
            if not handshake_result["success"]:
                return SyncResult(
                    success=False,
                    errors=[handshake_result.get("error", "Handshake failed")],
                )

            last_sync = handshake_result.get("last_sync_timestamp")

            # Step 2: Pull changes from peer
            pull_result = self._pull_changes(peer_url, peer_id, last_sync)
            if pull_result["success"]:
                result.pulled = pull_result.get("applied", 0)
                result.conflicts += pull_result.get("conflicts", 0)
            else:
                result.errors.append(f"Pull failed: {pull_result.get('error')}")

            # Step 3: Push local changes to peer
            push_result = self._push_changes(peer_url, peer_id, last_sync)
            if push_result["success"]:
                result.pushed = push_result.get("applied", 0)
                result.conflicts += push_result.get("conflicts", 0)
            else:
                result.errors.append(f"Push failed: {push_result.get('error')}")

            # Update last sync time for peer
            self._update_peer_sync_time(peer_id)

            if result.errors:
                result.success = False

            logger.info(
                f"Sync complete: pulled={result.pulled}, pushed={result.pushed}, "
                f"conflicts={result.conflicts}"
            )

        except Exception as e:
            logger.error(f"Sync error: {e}")
            result.success = False
            result.errors.append(str(e))

        return result

    def pull_from_peer(self, peer_id: str) -> SyncResult:
        """Pull changes from a peer (one-way sync).

        Args:
            peer_id: UUID hex string of peer

        Returns:
            SyncResult with summary
        """
        peer = self.config.get_peer(peer_id)
        if not peer:
            return SyncResult(
                success=False,
                errors=[f"Unknown peer: {peer_id}"],
            )

        peer_url = peer.get("peer_url")
        result = SyncResult(success=True)

        try:
            # Handshake first
            handshake_result = self._handshake(peer_url, peer_id)
            if not handshake_result["success"]:
                return SyncResult(
                    success=False,
                    errors=[handshake_result.get("error", "Handshake failed")],
                )

            last_sync = handshake_result.get("last_sync_timestamp")

            # Pull changes
            pull_result = self._pull_changes(peer_url, peer_id, last_sync)
            if pull_result["success"]:
                result.pulled = pull_result.get("applied", 0)
                result.conflicts = pull_result.get("conflicts", 0)
            else:
                result.success = False
                result.errors.append(pull_result.get("error", "Pull failed"))

        except Exception as e:
            result.success = False
            result.errors.append(str(e))

        return result

    def push_to_peer(self, peer_id: str) -> SyncResult:
        """Push local changes to a peer (one-way sync).

        Args:
            peer_id: UUID hex string of peer

        Returns:
            SyncResult with summary
        """
        peer = self.config.get_peer(peer_id)
        if not peer:
            return SyncResult(
                success=False,
                errors=[f"Unknown peer: {peer_id}"],
            )

        peer_url = peer.get("peer_url")
        result = SyncResult(success=True)

        try:
            # Handshake first
            handshake_result = self._handshake(peer_url, peer_id)
            if not handshake_result["success"]:
                return SyncResult(
                    success=False,
                    errors=[handshake_result.get("error", "Handshake failed")],
                )

            last_sync = handshake_result.get("last_sync_timestamp")

            # Push changes
            push_result = self._push_changes(peer_url, peer_id, last_sync)
            if push_result["success"]:
                result.pushed = push_result.get("applied", 0)
                result.conflicts = push_result.get("conflicts", 0)
            else:
                result.success = False
                result.errors.append(push_result.get("error", "Push failed"))

        except Exception as e:
            result.success = False
            result.errors.append(str(e))

        return result

    def initial_sync(self, peer_id: str) -> SyncResult:
        """Perform initial full sync with a new peer.

        Gets the complete dataset from the peer for first-time sync.

        Args:
            peer_id: UUID hex string of peer

        Returns:
            SyncResult with summary
        """
        peer = self.config.get_peer(peer_id)
        if not peer:
            return SyncResult(
                success=False,
                errors=[f"Unknown peer: {peer_id}"],
            )

        peer_url = peer.get("peer_url")
        result = SyncResult(success=True)

        try:
            # Handshake first
            handshake_result = self._handshake(peer_url, peer_id)
            if not handshake_result["success"]:
                return SyncResult(
                    success=False,
                    errors=[handshake_result.get("error", "Handshake failed")],
                )

            # Get full dataset
            full_result = self._get_full_sync(peer_url, peer_id)
            if full_result["success"]:
                # Apply all data
                applied, conflicts, errors = self._apply_full_sync(
                    full_result["data"], peer_id
                )
                result.pulled = applied
                result.conflicts = conflicts
                if errors:
                    result.errors.extend(errors)
            else:
                result.success = False
                result.errors.append(full_result.get("error", "Full sync failed"))

            # Push our changes to peer
            push_result = self._push_changes(peer_url, peer_id, None)
            if push_result["success"]:
                result.pushed = push_result.get("applied", 0)
            else:
                result.errors.append(f"Push failed: {push_result.get('error')}")

            self._update_peer_sync_time(peer_id)

        except Exception as e:
            result.success = False
            result.errors.append(str(e))

        return result

    def check_peer_status(self, peer_id: str) -> Dict[str, Any]:
        """Check if a peer is reachable and get its status.

        Args:
            peer_id: UUID hex string of peer

        Returns:
            Dict with status info or error
        """
        peer = self.config.get_peer(peer_id)
        if not peer:
            return {"reachable": False, "error": "Unknown peer"}

        peer_url = peer.get("peer_url")
        try:
            response = self._make_request(
                f"{peer_url}/sync/status",
                peer_id,
                method="GET",
            )
            if response.get("success"):
                return {
                    "reachable": True,
                    "device_id": response["data"].get("device_id"),
                    "device_name": response["data"].get("device_name"),
                    "protocol_version": response["data"].get("protocol_version"),
                }
            else:
                return {"reachable": False, "error": response.get("error")}
        except Exception as e:
            return {"reachable": False, "error": str(e)}

    def _handshake(self, peer_url: str, peer_id: str) -> Dict[str, Any]:
        """Perform handshake with peer.

        Args:
            peer_url: Base URL of peer
            peer_id: Peer's device ID

        Returns:
            Dict with handshake result
        """
        response = self._make_request(
            f"{peer_url}/sync/handshake",
            peer_id,
            method="POST",
            data={
                "device_id": self.device_id,
                "device_name": self.device_name,
                "protocol_version": "1.0",
            },
        )

        if response.get("success"):
            return {
                "success": True,
                "peer_device_id": response["data"].get("device_id"),
                "peer_device_name": response["data"].get("device_name"),
                "last_sync_timestamp": response["data"].get("last_sync_timestamp"),
            }
        else:
            return {"success": False, "error": response.get("error")}

    def _pull_changes(
        self, peer_url: str, peer_id: str, since: Optional[str]
    ) -> Dict[str, Any]:
        """Pull changes from peer.

        Args:
            peer_url: Base URL of peer
            peer_id: Peer's device ID
            since: Timestamp to get changes since

        Returns:
            Dict with pull result
        """
        url = f"{peer_url}/sync/changes"
        if since:
            url += f"?since={urllib.parse.quote(since)}"

        response = self._make_request(url, peer_id, method="GET")

        if not response.get("success"):
            return {"success": False, "error": response.get("error")}

        data = response["data"]
        changes_data = data.get("changes", [])

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

        # Apply changes
        applied, conflicts, errors = apply_sync_changes(
            self.db,
            changes,
            peer_id,
            data.get("device_name"),
        )

        return {
            "success": True,
            "applied": applied,
            "conflicts": conflicts,
            "errors": errors,
        }

    def _push_changes(
        self, peer_url: str, peer_id: str, since: Optional[str]
    ) -> Dict[str, Any]:
        """Push local changes to peer.

        Args:
            peer_url: Base URL of peer
            peer_id: Peer's device ID
            since: Timestamp to get changes since

        Returns:
            Dict with push result
        """
        # Get local changes
        changes, _ = get_changes_since(self.db, since)

        if not changes:
            return {"success": True, "applied": 0, "conflicts": 0}

        # Convert changes to dicts for JSON
        changes_data = []
        for c in changes:
            changes_data.append({
                "entity_type": c.entity_type,
                "entity_id": c.entity_id,
                "operation": c.operation,
                "data": c.data,
                "timestamp": c.timestamp,
                "device_id": c.device_id,
                "device_name": c.device_name,
            })

        response = self._make_request(
            f"{peer_url}/sync/apply",
            peer_id,
            method="POST",
            data={
                "device_id": self.device_id,
                "device_name": self.device_name,
                "changes": changes_data,
            },
        )

        if response.get("success"):
            return {
                "success": True,
                "applied": response["data"].get("applied", 0),
                "conflicts": response["data"].get("conflicts", 0),
            }
        else:
            return {"success": False, "error": response.get("error")}

    def _get_full_sync(self, peer_url: str, peer_id: str) -> Dict[str, Any]:
        """Get full dataset from peer.

        Args:
            peer_url: Base URL of peer
            peer_id: Peer's device ID

        Returns:
            Dict with full sync data
        """
        response = self._make_request(
            f"{peer_url}/sync/full",
            peer_id,
            method="GET",
        )

        if response.get("success"):
            return {"success": True, "data": response["data"]}
        else:
            return {"success": False, "error": response.get("error")}

    def _apply_full_sync(
        self, data: Dict[str, Any], peer_id: str
    ) -> Tuple[int, int, List[str]]:
        """Apply full sync data.

        Args:
            data: Full sync data with notes, tags, note_tags
            peer_id: Peer's device ID

        Returns:
            Tuple of (applied, conflicts, errors)
        """
        applied = 0
        conflicts = 0
        errors = []

        # Create changes from full data
        changes = []

        # Process notes
        for note in data.get("notes", []):
            changes.append(SyncChange(
                entity_type="note",
                entity_id=note["id"],
                operation="create",
                data=note,
                timestamp=note.get("modified_at") or note["created_at"],
                device_id=note["device_id"],
            ))

        # Process tags
        for tag in data.get("tags", []):
            changes.append(SyncChange(
                entity_type="tag",
                entity_id=tag["id"],
                operation="create",
                data=tag,
                timestamp=tag.get("modified_at") or tag["created_at"],
                device_id=tag["device_id"],
            ))

        # Process note_tags
        for nt in data.get("note_tags", []):
            changes.append(SyncChange(
                entity_type="note_tag",
                entity_id=f"{nt['note_id']}:{nt['tag_id']}",
                operation="create" if not nt.get("deleted_at") else "delete",
                data=nt,
                timestamp=nt.get("deleted_at") or nt["created_at"],
                device_id=nt["device_id"],
            ))

        # Apply all changes
        if changes:
            applied, conflicts, errors = apply_sync_changes(
                self.db,
                changes,
                peer_id,
                data.get("device_name"),
            )

        return applied, conflicts, errors

    def _update_peer_sync_time(self, peer_id: str) -> None:
        """Update the last sync time for a peer in the database.

        Args:
            peer_id: Peer's device ID
        """
        import uuid
        peer_id_bytes = uuid.UUID(hex=peer_id).bytes

        with self.db.conn:
            cursor = self.db.conn.cursor()
            cursor.execute(
                """UPDATE sync_peers SET last_sync_at = datetime('now')
                   WHERE peer_id = ?""",
                (peer_id_bytes,),
            )
            if cursor.rowcount == 0:
                # Peer doesn't exist in sync_peers, add it
                peer = self.config.get_peer(peer_id)
                peer_name = peer.get("peer_name") if peer else None
                peer_url = peer.get("peer_url") if peer else ""
                cursor.execute(
                    """INSERT INTO sync_peers (peer_id, peer_name, peer_url, last_sync_at)
                       VALUES (?, ?, ?, datetime('now'))""",
                    (peer_id_bytes, peer_name, peer_url),
                )
            self.db.conn.commit()

    def _make_request(
        self,
        url: str,
        peer_id: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Make an HTTP(S) request to a peer.

        Handles TOFU certificate verification for HTTPS connections.

        Args:
            url: Full URL to request
            peer_id: Peer's device ID for TOFU verification
            method: HTTP method
            data: JSON data to send (for POST)
            timeout: Request timeout in seconds

        Returns:
            Dict with success status and response data or error
        """
        try:
            # Create SSL context for HTTPS
            ssl_context = None
            if url.startswith("https://"):
                peer = self.config.get_peer(peer_id)
                trusted_fingerprint = peer.get("certificate_fingerprint") if peer else None
                ssl_context = create_client_ssl_context(
                    trusted_fingerprint=trusted_fingerprint,
                    verify_mode=bool(trusted_fingerprint),
                )

            # Prepare request
            if data:
                json_data = json.dumps(data).encode("utf-8")
                request = urllib.request.Request(
                    url,
                    data=json_data,
                    method=method,
                    headers={"Content-Type": "application/json"},
                )
            else:
                request = urllib.request.Request(url, method=method)

            # Make request
            if ssl_context:
                response = urllib.request.urlopen(
                    request, timeout=timeout, context=ssl_context
                )
            else:
                response = urllib.request.urlopen(request, timeout=timeout)

            # Parse response
            response_data = json.loads(response.read().decode("utf-8"))

            # For HTTPS, verify certificate fingerprint (TOFU)
            if url.startswith("https://") and hasattr(response, "fp"):
                # Get peer certificate for TOFU verification
                # Note: In production, we'd extract the cert from the connection
                # For now, TOFU verification happens via the config
                pass

            return {"success": True, "data": response_data}

        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
                error_data = json.loads(error_body)
                error_msg = error_data.get("error", str(e))
            except Exception:
                error_msg = f"HTTP {e.code}: {e.reason}"
            return {"success": False, "error": error_msg}

        except urllib.error.URLError as e:
            return {"success": False, "error": f"Connection error: {e.reason}"}

        except Exception as e:
            return {"success": False, "error": str(e)}


def sync_all_peers(db: Database, config: Config) -> Dict[str, SyncResult]:
    """Sync with all configured peers.

    Args:
        db: Database instance
        config: Config instance

    Returns:
        Dict mapping peer_id to SyncResult
    """
    client = SyncClient(db, config)
    results = {}

    for peer in config.get_peers():
        peer_id = peer.get("peer_id")
        if peer_id:
            logger.info(f"Syncing with peer: {peer.get('peer_name')} ({peer_id})")
            results[peer_id] = client.sync_with_peer(peer_id)

    return results

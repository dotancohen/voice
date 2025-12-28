"""Sync client for Voice peer-to-peer synchronization.

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
from datetime import datetime, timedelta
from pathlib import Path
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

    def _adjust_timestamp_for_skew(
        self, timestamp: Optional[str], clock_skew_seconds: float
    ) -> Optional[str]:
        """Adjust a timestamp to account for clock skew and race conditions.

        Always goes back at least 2 seconds to handle race conditions during
        sync. Additionally goes back by 2x the absolute skew if clock skew
        exceeds 1 second.

        Args:
            timestamp: ISO format timestamp string, or None
            clock_skew_seconds: Measured clock skew (positive = peer ahead)

        Returns:
            Adjusted timestamp string, or None if input was None
        """
        if timestamp is None:
            return None

        try:
            ts = datetime.fromisoformat(timestamp)
            # Always go back at least 2 seconds to handle race conditions
            base_adjustment = 2.0
            # Add 2x skew if significant (> 1 second)
            skew_adjustment = (
                2 * abs(clock_skew_seconds) if abs(clock_skew_seconds) > 1.0 else 0
            )
            adjustment = timedelta(seconds=base_adjustment + skew_adjustment)
            adjusted = ts - adjustment
            # Use space separator to match SQLite datetime format
            # (isoformat uses 'T' which breaks string comparison)
            return adjusted.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError) as e:
            # Log warning - malformed timestamp may cause sync issues
            logger.warning(
                f"Failed to parse timestamp for skew adjustment: '{timestamp}': {e}. "
                f"Using original timestamp, which may cause sync inconsistencies."
            )
            return timestamp  # If parsing fails, return original

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
            clock_skew = handshake_result.get("clock_skew_seconds", 0.0)

            # Adjust pull timestamp to go back further and catch changes
            # that might appear earlier due to clock skew
            adjusted_since = self._adjust_timestamp_for_skew(last_sync, clock_skew)

            # Step 2: Pull changes from peer (use adjusted timestamp)
            pull_result = self._pull_changes(peer_url, peer_id, adjusted_since)
            if pull_result["success"]:
                result.pulled = pull_result.get("applied", 0)
                result.conflicts += pull_result.get("conflicts", 0)
            else:
                result.errors.append(f"Pull failed: {pull_result.get('error')}")

            # Step 3: Push local changes to peer (use original timestamp)
            push_result = self._push_changes(peer_url, peer_id, last_sync)
            if push_result["success"]:
                result.pushed = push_result.get("applied", 0)
                result.conflicts += push_result.get("conflicts", 0)
            else:
                result.errors.append(f"Push failed: {push_result.get('error')}")

            # Step 4: Sync binary files (audio files)
            # Download binary files for audio_files we pulled
            pulled_changes = pull_result.get("changes", [])
            if pulled_changes:
                binary_errors = self._sync_binary_files_after_pull(
                    peer_url, pulled_changes
                )
                result.errors.extend(binary_errors)

            # Upload binary files for audio_files we pushed
            pushed_changes = push_result.get("changes", [])
            if pushed_changes:
                binary_errors = self._sync_binary_files_after_push(
                    peer_url, pushed_changes
                )
                result.errors.extend(binary_errors)

            if result.errors:
                result.success = False
            else:
                # Only update last sync time if sync was completely successful
                # This ensures we retry failed changes on next sync
                self._update_peer_sync_time(peer_id)

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
            clock_skew = handshake_result.get("clock_skew_seconds", 0.0)
            adjusted_since = self._adjust_timestamp_for_skew(last_sync, clock_skew)

            # Pull changes (use adjusted timestamp)
            pull_result = self._pull_changes(peer_url, peer_id, adjusted_since)
            if pull_result["success"]:
                result.pulled = pull_result.get("applied", 0)
                result.conflicts = pull_result.get("conflicts", 0)

                # Sync binary files for pulled audio_files
                pulled_changes = pull_result.get("changes", [])
                if pulled_changes:
                    binary_errors = self._sync_binary_files_after_pull(
                        peer_url, pulled_changes
                    )
                    result.errors.extend(binary_errors)

                # Only update timestamp if completely successful
                if not result.errors:
                    self._update_peer_sync_time(peer_id)
            else:
                result.success = False
                result.errors.append(pull_result.get("error", "Pull failed"))

            # Mark as failed if any errors occurred
            if result.errors:
                result.success = False

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

                # Sync binary files for pushed audio_files
                pushed_changes = push_result.get("changes", [])
                if pushed_changes:
                    binary_errors = self._sync_binary_files_after_push(
                        peer_url, pushed_changes
                    )
                    result.errors.extend(binary_errors)

                # Only update timestamp if completely successful
                if not result.errors:
                    self._update_peer_sync_time(peer_id)
            else:
                result.success = False
                result.errors.append(push_result.get("error", "Push failed"))

            # Mark as failed if any errors occurred
            if result.errors:
                result.success = False

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
            pulled_changes = []
            if full_result["success"]:
                # Apply all data
                applied, conflicts, errors = self._apply_full_sync(
                    full_result["data"], peer_id
                )
                result.pulled = applied
                result.conflicts = conflicts
                if errors:
                    result.errors.extend(errors)

                # Build list of audio_file changes for binary sync
                for af in full_result["data"].get("audio_files", []):
                    pulled_changes.append(SyncChange(
                        entity_type="audio_file",
                        entity_id=af["id"],
                        operation="create",
                        data=af,
                        timestamp=af.get("modified_at") or af.get("imported_at", ""),
                        device_id="",
                    ))
            else:
                result.success = False
                result.errors.append(full_result.get("error", "Full sync failed"))

            # Push our changes to peer
            push_result = self._push_changes(peer_url, peer_id, None)
            if push_result["success"]:
                result.pushed = push_result.get("applied", 0)
            else:
                result.errors.append(f"Push failed: {push_result.get('error')}")

            # Sync binary files for audio_files
            # Download binary files for audio_files we pulled
            if pulled_changes:
                binary_errors = self._sync_binary_files_after_pull(
                    peer_url, pulled_changes
                )
                result.errors.extend(binary_errors)

            # Upload binary files for audio_files we pushed
            pushed_changes = push_result.get("changes", [])
            if pushed_changes:
                binary_errors = self._sync_binary_files_after_push(
                    peer_url, pushed_changes
                )
                result.errors.extend(binary_errors)

            # Mark as failed if there were any errors
            if result.errors:
                result.success = False
            else:
                # Only update last sync time if sync was completely successful
                # This ensures we retry failed changes on next sync
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
            Dict with handshake result including clock_skew_seconds
        """
        local_time_before = datetime.now()

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

        local_time_after = datetime.now()

        if response.get("success"):
            # Calculate clock skew from server timestamp
            clock_skew_seconds = 0.0
            server_timestamp_str = response["data"].get("server_timestamp")
            if server_timestamp_str:
                try:
                    server_time = datetime.fromisoformat(server_timestamp_str)
                    # Use midpoint of request for more accurate skew calculation
                    local_midpoint = local_time_before + (local_time_after - local_time_before) / 2
                    skew = server_time - local_midpoint
                    clock_skew_seconds = skew.total_seconds()
                except (ValueError, TypeError) as e:
                    # Log warning - unparseable timestamp could indicate protocol issue
                    # or significant version mismatch. Proceeding with 0 skew may cause
                    # changes to be missed if actual skew is significant.
                    logger.warning(
                        f"Failed to parse server timestamp '{server_timestamp_str}': {e}. "
                        f"Proceeding with clock_skew=0, which may cause sync issues."
                    )

            return {
                "success": True,
                "peer_device_id": response["data"].get("device_id"),
                "peer_device_name": response["data"].get("device_name"),
                "last_sync_timestamp": response["data"].get("last_sync_timestamp"),
                "clock_skew_seconds": clock_skew_seconds,
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

        # success is False if there were any errors applying changes
        return {
            "success": len(errors) == 0,
            "applied": applied,
            "conflicts": conflicts,
            "errors": errors,
            "error": "; ".join(errors) if errors else None,
            "changes": changes,  # Return changes for binary sync
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
            return {"success": True, "applied": 0, "conflicts": 0, "changes": []}

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
            data = response["data"]
            server_errors = data.get("errors", [])
            # success is False if server had any errors applying changes
            return {
                "success": len(server_errors) == 0,
                "applied": data.get("applied", 0),
                "conflicts": data.get("conflicts", 0),
                "errors": server_errors,
                "error": "; ".join(server_errors) if server_errors else None,
                "changes": changes,  # Return changes for binary sync
            }
        else:
            return {"success": False, "error": response.get("error"), "changes": changes}

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
        """Apply full sync data using change detection logic.

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

        # Process notes - use proper operation type for change detection
        for note in data.get("notes", []):
            if note.get("deleted_at"):
                operation = "delete"
            elif note.get("modified_at"):
                operation = "update"
            else:
                operation = "create"

            changes.append(SyncChange(
                entity_type="note",
                entity_id=note["id"],
                operation=operation,
                data=note,
                timestamp=note.get("modified_at") or note["created_at"],
                device_id="",  # device_id no longer stored in main tables
            ))

        # Process tags - use "update" to trigger change detection when modified
        for tag in data.get("tags", []):
            operation = "update" if tag.get("modified_at") else "create"

            changes.append(SyncChange(
                entity_type="tag",
                entity_id=tag["id"],
                operation=operation,
                data=tag,
                timestamp=tag.get("modified_at") or tag["created_at"],
                device_id="",  # device_id no longer stored in main tables
            ))

        # Process note_tags - include modified_at in timestamp calculation
        for nt in data.get("note_tags", []):
            if nt.get("deleted_at"):
                operation = "delete"
            else:
                operation = "create"

            changes.append(SyncChange(
                entity_type="note_tag",
                entity_id=f"{nt['note_id']}:{nt['tag_id']}",
                operation=operation,
                data=nt,
                timestamp=nt.get("modified_at") or nt.get("deleted_at") or nt["created_at"],
                device_id="",  # device_id no longer stored in main tables
            ))

        # Process audio_files
        for af in data.get("audio_files", []):
            if af.get("deleted_at"):
                operation = "delete"
            elif af.get("modified_at"):
                operation = "update"
            else:
                operation = "create"

            changes.append(SyncChange(
                entity_type="audio_file",
                entity_id=af["id"],
                operation=operation,
                data=af,
                timestamp=af.get("modified_at") or af.get("imported_at", ""),
                device_id="",
            ))

        # Process note_attachments
        for na in data.get("note_attachments", []):
            if na.get("deleted_at"):
                operation = "delete"
            else:
                operation = "create"

            changes.append(SyncChange(
                entity_type="note_attachment",
                entity_id=na["id"],
                operation=operation,
                data=na,
                timestamp=na.get("modified_at") or na.get("created_at", ""),
                device_id="",
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
        peer = self.config.get_peer(peer_id)
        peer_name = peer.get("peer_name") if peer else None
        self.db.update_peer_sync_time(peer_id, peer_name)

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
            try:
                error_body = e.read().decode("utf-8")
                error_data = json.loads(error_body)
                # For 422 (Unprocessable Entity) or 207 (Partial Success),
                # return the full response so caller can see applied count and individual errors
                if e.code in (207, 422):
                    return {
                        "success": True,  # HTTP request succeeded
                        "data": error_data,  # Contains applied, conflicts, errors
                    }
                # Extract detailed error message from server response
                error_msg = error_data.get("error", f"HTTP {e.code}: {e.reason}")
            except Exception:
                error_msg = f"HTTP {e.code}: {e.reason}"

            # Log the error with URL context
            logger.error(f"Request to {url} failed: {error_msg}")
            return {"success": False, "error": f"Server error: {error_msg}"}

        except urllib.error.URLError as e:
            error_msg = f"Connection failed to {url}: {e.reason}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        except Exception as e:
            error_msg = f"Request to {url} failed: {e}"
            logger.error(error_msg)
            return {"success": False, "error": str(e)}

    def download_audio_file(
        self, peer_url: str, audio_id: str, dest_path: Path
    ) -> Dict[str, Any]:
        """Download an audio file from a peer.

        Args:
            peer_url: Base URL of the peer sync server
            audio_id: Audio file UUID hex string
            dest_path: Local path to save the file

        Returns:
            Dict with 'success' and 'error' or 'bytes_downloaded'
        """
        import tempfile
        import os

        url = f"{peer_url}/sync/audio/{audio_id}/file"

        try:
            request = urllib.request.Request(url, method="GET")
            request.add_header("X-Device-ID", self.device_id)
            request.add_header("X-Device-Name", self.device_name)

            # Create SSL context
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

            response = urllib.request.urlopen(request, context=context, timeout=60)
            content = response.read()

            # Ensure parent directory exists
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Write to temp file first, then rename atomically
            # This prevents partial files if interrupted mid-write
            temp_fd, temp_path = tempfile.mkstemp(
                dir=dest_path.parent, prefix=f".{audio_id}_"
            )
            try:
                os.write(temp_fd, content)
                os.close(temp_fd)
                os.rename(temp_path, dest_path)
            except Exception:
                # Clean up temp file on failure
                os.close(temp_fd)
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

            return {"success": True, "bytes_downloaded": len(content)}

        except urllib.error.HTTPError as e:
            # Try to get detailed error message from response body
            error_msg = f"HTTP {e.code}: {e.reason}"
            try:
                error_body = e.read().decode("utf-8")
                error_data = json.loads(error_body)
                if "error" in error_data:
                    error_msg = f"Server error: {error_data['error']}"
            except Exception:
                pass
            logger.error(f"Failed to download audio {audio_id}: {error_msg}")
            return {"success": False, "error": error_msg}
        except Exception as e:
            logger.error(f"Failed to download audio {audio_id}: {e}")
            return {"success": False, "error": str(e)}

    def upload_audio_file(
        self, peer_url: str, audio_id: str, source_path: Path
    ) -> Dict[str, Any]:
        """Upload an audio file to a peer.

        Args:
            peer_url: Base URL of the peer sync server
            audio_id: Audio file UUID hex string
            source_path: Local path of the file to upload

        Returns:
            Dict with 'success' and 'error' or 'bytes_uploaded'
        """
        url = f"{peer_url}/sync/audio/{audio_id}/file"

        try:
            content = source_path.read_bytes()

            request = urllib.request.Request(url, data=content, method="POST")
            request.add_header("X-Device-ID", self.device_id)
            request.add_header("X-Device-Name", self.device_name)
            request.add_header("Content-Type", "application/octet-stream")

            # Create SSL context
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

            response = urllib.request.urlopen(request, context=context, timeout=60)
            response.read()  # Consume response

            return {"success": True, "bytes_uploaded": len(content)}

        except urllib.error.HTTPError as e:
            # Try to get detailed error message from response body
            error_msg = f"HTTP {e.code}: {e.reason}"
            try:
                error_body = e.read().decode("utf-8")
                error_data = json.loads(error_body)
                if "error" in error_data:
                    error_msg = f"Server error: {error_data['error']}"
            except Exception:
                pass
            logger.error(f"Failed to upload audio {audio_id}: {error_msg}")
            return {"success": False, "error": error_msg}
        except Exception as e:
            logger.error(f"Failed to upload audio {audio_id}: {e}")
            return {"success": False, "error": str(e)}

    def _sync_binary_files_after_pull(
        self, peer_url: str, pulled_changes: List[SyncChange]
    ) -> List[str]:
        """Download binary files for audio_file entities that were pulled.

        Args:
            peer_url: Base URL of the peer sync server
            pulled_changes: List of changes that were pulled from peer

        Returns:
            List of error messages (empty if all succeeded)
        """
        errors = []

        # Get audiofile_directory from config
        audiofile_dir = self.config.get_audiofile_directory()
        if not audiofile_dir:
            # No audiofile directory configured - skip binary sync
            logger.debug("No audiofile_directory configured, skipping binary downloads")
            return errors

        audiofile_path = Path(audiofile_dir)
        if not audiofile_path.exists():
            audiofile_path.mkdir(parents=True, exist_ok=True)

        # Find audio_file changes that were pulled
        for change in pulled_changes:
            if change.entity_type != "audio_file":
                continue
            if change.operation == "delete":
                continue  # Don't download deleted files

            audio_id = change.entity_id
            filename = change.data.get("filename", "")

            # Determine file extension
            ext = Path(filename).suffix if filename else ".bin"

            # Check if we already have this file
            local_file = audiofile_path / f"{audio_id}{ext}"
            if local_file.exists():
                logger.debug(f"Binary file {audio_id} already exists locally")
                continue

            # Download the file
            logger.info(f"Downloading binary file: {audio_id}")
            result = self.download_audio_file(peer_url, audio_id, local_file)

            if not result.get("success"):
                error_msg = result.get("error", "Unknown error")
                # 404 is expected if peer doesn't have the binary
                if "404" not in error_msg:
                    errors.append(f"Failed to download audio {audio_id}: {error_msg}")
                else:
                    logger.warning(f"Binary file {audio_id} not available on peer")

        return errors

    def _sync_binary_files_after_push(
        self, peer_url: str, pushed_changes: List[SyncChange]
    ) -> List[str]:
        """Upload binary files for audio_file entities that were pushed.

        Args:
            peer_url: Base URL of the peer sync server
            pushed_changes: List of changes that were pushed to peer

        Returns:
            List of error messages (empty if all succeeded)
        """
        errors = []

        # Get audiofile_directory from config
        audiofile_dir = self.config.get_audiofile_directory()
        if not audiofile_dir:
            # No audiofile directory configured - skip binary sync
            logger.debug("No audiofile_directory configured, skipping binary uploads")
            return errors

        audiofile_path = Path(audiofile_dir)

        # Find audio_file changes that were pushed
        for change in pushed_changes:
            if change.entity_type != "audio_file":
                continue
            if change.operation == "delete":
                continue  # Don't upload deleted files

            audio_id = change.entity_id
            filename = change.data.get("filename", "")

            # Determine file extension
            ext = Path(filename).suffix if filename else ".bin"

            # Check if we have this file locally
            local_file = audiofile_path / f"{audio_id}{ext}"
            if not local_file.exists():
                logger.warning(f"Local binary file {audio_id} not found, skipping upload")
                continue

            # Upload the file
            logger.info(f"Uploading binary file: {audio_id}")
            result = self.upload_audio_file(peer_url, audio_id, local_file)

            if not result.get("success"):
                error_msg = result.get("error", "Unknown error")
                errors.append(f"Failed to upload audio {audio_id}: {error_msg}")

        return errors

    def _get_changes_for_binary_sync(
        self, since: Optional[str]
    ) -> List[SyncChange]:
        """Get local audio_file changes for binary sync.

        Args:
            since: Timestamp to get changes since (None for all)

        Returns:
            List of audio_file SyncChange objects
        """
        changes, _ = get_changes_since(self.db, since)
        return [c for c in changes if c.entity_type == "audio_file"]


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

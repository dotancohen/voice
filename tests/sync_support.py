"""Helpers for tests that drive the core's sync logic from Python.

The product exchanges changes through the Rust client and server. These
helpers let a test hand a batch straight to the core's apply function, or read
the feed straight from the database, without a server in between. They exist
for tests only; nothing in `src/` uses them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from voicecore import apply_sync_changes as _rust_apply_sync_changes

from core.database import Database


@dataclass
class SyncChange:
    """One change as it travels in the feed."""

    entity_type: str
    entity_id: str
    operation: str
    data: Dict[str, Any]
    timestamp: int
    device_id: str
    device_name: Optional[str] = None


def read_feed(db: Database, cursor: int = 0, limit: int = 100000) -> Tuple[List[SyncChange], int]:
    """Read the write-order feed after `cursor` (0 for everything), oldest
    first; returns the changes and the cursor to continue from."""
    result = db.get_changes_after_seq(cursor, None, limit)
    changes = [
        SyncChange(
            entity_type=c["entity_type"],
            entity_id=c["entity_id"],
            operation=c["operation"],
            data=c["data"],
            timestamp=c["timestamp"],
            device_id="",
        )
        for c in result["changes"]
    ]
    return changes, result["next_cursor"]


def apply_sync_changes(
    db: Database,
    changes: List[SyncChange],
    peer_device_id: str,
    peer_device_name: Optional[str] = None,
) -> Tuple[int, int, List[str]]:
    """Apply a batch from a peer through the core. Returns (applied, conflicts, errors)."""
    result = _rust_apply_sync_changes(
        db._rust_db, list(changes), peer_device_id, peer_device_name
    )
    return result["applied"], result["conflicts"], result["errors"]


def get_peer_last_sync(db: Database, peer_device_id: str) -> Optional[int]:
    """When this database last synced with the peer, or None."""
    return db.get_peer_last_sync(peer_device_id)


def update_peer_last_sync(
    db: Database, peer_device_id: str, peer_device_name: Optional[str] = None
) -> None:
    """Record a sync with the peer as having happened now."""
    db.update_peer_sync_time(peer_device_id, peer_device_name)

# Voice Sync System - Implementation Plan

This document contains the complete design and implementation plan for adding distributed peer-to-peer sync to Voice. Load this file into Claude Code to resume implementation.

---

## Project Context

Voice is a note-taking application with multiple interfaces:
- **GUI** (PySide6) - 3-pane layout
- **TUI** (Textual) - terminal interface with RTL support
- **CLI** - command-line operations
- **Web API** (Flask) - RESTful JSON API

Key files:
- `src/main.py` - unified entry point
- `src/core/database.py` - data access layer (~584 lines)
- `src/core/config.py` - configuration management (~178 lines)
- `src/core/models.py` - Note and Tag dataclasses
- `src/web.py` - Flask API (~334 lines)
- Config location: `~/.config/voice/config.json` (customizable with `-d` flag)
- Database: SQLite, location configurable

---

## Current Database Schema (Before Sync)

```sql
CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME NOT NULL,
    content TEXT NOT NULL,
    modified_at DATETIME,
    deleted_at DATETIME,
    CHECK (length(content) <= 102400)
);

CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    parent_id INTEGER,
    FOREIGN KEY (parent_id) REFERENCES tags (id) ON DELETE CASCADE,
    CHECK (length(name) <= 100),
    CHECK (name NOT LIKE '%/%')
);

CREATE TABLE note_tags (
    note_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (note_id, tag_id),
    FOREIGN KEY (note_id) REFERENCES notes (id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE
);

-- Existing indexes
CREATE INDEX idx_notes_created_at ON notes(created_at);
CREATE INDEX idx_notes_deleted_at ON notes(deleted_at);
CREATE INDEX idx_tags_parent_id ON tags(parent_id);
CREATE INDEX idx_tags_name_nocase ON tags(name COLLATE NOCASE);
CREATE INDEX idx_note_tags_note_id ON note_tags(note_id);
CREATE INDEX idx_note_tags_tag_id ON note_tags(tag_id);
```

---

## Design Decisions Summary

| Aspect | Decision |
|--------|----------|
| **Primary Keys** | UUID7 (replacing auto-increment integers) |
| **Device Identity** | UUID7 + friendly name, generated on first run, stored in config |
| **Sync Protocol** | Custom HTTP REST over existing Flask API |
| **Change Tracking** | Timestamps (`modified_at`), with clock validation |
| **Clock Tolerance** | Configurable, default 10 seconds, uses system time |
| **Sync Trigger** | Manual only |
| **Sync Scope** | Incremental (since last sync), full sync available |
| **Direction** | Full bidirectional |
| **Content Conflicts** | diff3 merge, fallback to `conflicts_note_content` table |
| **Delete Conflicts** | Store in `conflicts_note_delete` table |
| **Tag Rename Conflicts** | Store in `conflicts_tag_rename` table |
| **Duplicate Root Tags** | Merge them (reassign children to single UUID) |
| **Authentication** | Per-peer API keys, `Authorization: Bearer` header |
| **Transport Security** | HTTPS with TOFU (Trust On First Use) certificate trust |
| **Peer Config** | Static list in config.json |
| **Failure Handling** | Warn user, continue with other peers |
| **UI Feedback** | Last sync time per server, pending changes count |
| **Sync Logging** | Separate file in config directory (e.g., `sync.log`) |
| **Server Flags** | `--enable-sync` and `--enable-web-ui` (at least one required) |
| **Future** | Android app support planned |

---

## New Database Schema (After Sync)

### Modified Tables

UUIDs stored as BLOB (16 bytes) for efficiency. Validation (length checks, etc.) handled in application layer (`src/core/validation.py`).

```sql
-- notes table: change id to UUID7 BLOB, add device_id
CREATE TABLE notes (
    id BLOB PRIMARY KEY,                    -- UUID7, 16 bytes
    created_at DATETIME NOT NULL,
    content TEXT NOT NULL,
    modified_at DATETIME,
    deleted_at DATETIME,
    device_id BLOB NOT NULL                 -- UUID7 of device that last modified
);

-- tags table: change id to UUID7 BLOB, add timestamps and device_id
CREATE TABLE tags (
    id BLOB PRIMARY KEY,                    -- UUID7, 16 bytes
    name TEXT NOT NULL,
    parent_id BLOB,                         -- UUID7 reference
    created_at DATETIME NOT NULL,
    modified_at DATETIME,
    device_id BLOB NOT NULL,                -- UUID7 of device that last modified
    FOREIGN KEY (parent_id) REFERENCES tags (id) ON DELETE CASCADE
);

-- note_tags: change to UUID7 BLOB references, add timestamps for sync
CREATE TABLE note_tags (
    note_id BLOB NOT NULL,                  -- UUID7, 16 bytes
    tag_id BLOB NOT NULL,                   -- UUID7, 16 bytes
    created_at DATETIME NOT NULL,
    deleted_at DATETIME,                    -- Soft delete for sync (NULL = active)
    device_id BLOB NOT NULL,                -- UUID7 of device that last modified
    PRIMARY KEY (note_id, tag_id),
    FOREIGN KEY (note_id) REFERENCES notes (id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE
);
```

### New Indexes

```sql
CREATE INDEX idx_notes_modified_at ON notes(modified_at);
CREATE INDEX idx_tags_modified_at ON tags(modified_at);
CREATE INDEX idx_note_tags_created_at ON note_tags(created_at);
CREATE INDEX idx_note_tags_deleted_at ON note_tags(deleted_at);
```

### New Tables

```sql
-- Track sync state per peer
CREATE TABLE sync_peers (
    peer_id BLOB PRIMARY KEY,               -- UUID7 of the peer device, 16 bytes
    peer_name TEXT,                         -- Friendly name (e.g., "Dotan's Desktop")
    peer_url TEXT NOT NULL,
    last_sync_at DATETIME,
    last_received_timestamp DATETIME,       -- Their latest change we've received
    last_sent_timestamp DATETIME,           -- Our latest change we've sent
    certificate_fingerprint BLOB            -- TOFU: SHA-256 hash, 32 bytes
);

-- Content edit conflicts (both sides edited the same note)
CREATE TABLE conflicts_note_content (
    id BLOB PRIMARY KEY,                    -- UUID7, 16 bytes
    note_id BLOB NOT NULL,                  -- The note in conflict
    local_content TEXT NOT NULL,
    local_modified_at DATETIME NOT NULL,
    local_device_id BLOB NOT NULL,
    local_device_name TEXT,
    remote_content TEXT NOT NULL,
    remote_modified_at DATETIME NOT NULL,
    remote_device_id BLOB NOT NULL,
    remote_device_name TEXT,
    created_at DATETIME NOT NULL,
    resolved_at DATETIME,
    FOREIGN KEY (note_id) REFERENCES notes(id)
);

-- Delete conflicts (one side edited, other side deleted)
CREATE TABLE conflicts_note_delete (
    id BLOB PRIMARY KEY,                    -- UUID7, 16 bytes
    note_id BLOB NOT NULL,
    surviving_content TEXT NOT NULL,        -- The content from the edit
    surviving_modified_at DATETIME NOT NULL,
    surviving_device_id BLOB NOT NULL,
    surviving_device_name TEXT,
    deleted_at DATETIME NOT NULL,
    deleting_device_id BLOB NOT NULL,
    deleting_device_name TEXT,
    created_at DATETIME NOT NULL,
    resolved_at DATETIME,
    FOREIGN KEY (note_id) REFERENCES notes(id)
);

-- Tag rename conflicts
CREATE TABLE conflicts_tag_rename (
    id BLOB PRIMARY KEY,                    -- UUID7, 16 bytes
    tag_id BLOB NOT NULL,
    local_name TEXT NOT NULL,
    local_modified_at DATETIME NOT NULL,
    local_device_id BLOB NOT NULL,
    local_device_name TEXT,
    remote_name TEXT NOT NULL,
    remote_modified_at DATETIME NOT NULL,
    remote_device_id BLOB NOT NULL,
    remote_device_name TEXT,
    created_at DATETIME NOT NULL,
    resolved_at DATETIME,
    FOREIGN KEY (tag_id) REFERENCES tags(id)
);

-- Sync failures (changes that couldn't be applied, for later resolution)
CREATE TABLE sync_failures (
    id BLOB PRIMARY KEY,                    -- UUID7, 16 bytes
    peer_id BLOB NOT NULL,                  -- Which peer the change came from
    peer_name TEXT,
    entity_type TEXT NOT NULL,              -- 'note', 'tag', 'note_tag'
    entity_id BLOB,                         -- UUID of the entity (if known)
    operation TEXT NOT NULL,                -- 'INSERT', 'UPDATE', 'DELETE'
    payload TEXT NOT NULL,                  -- JSON of the change that failed
    error_message TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    resolved_at DATETIME,
    FOREIGN KEY (peer_id) REFERENCES sync_peers(peer_id)
);
```

---

## Config Schema Addition

Add to `config.json`:

```json
{
  "sync": {
    "device_id": "01937a3e-xxxx-7xxx-xxxx-xxxxxxxxxxxx",
    "device_name": "Dotan's Desktop",
    "clock_tolerance_seconds": 10,
    "peers": [
      {
        "url": "https://192.168.1.50:5000",
        "api_key": "secret123",
        "enabled": true
      }
    ]
  }
}
```

Notes:
- `device_id` and `device_name` are for THIS device
- `device_id` is auto-generated (UUID7) on first run if not present
- `device_name` defaults to system hostname if not set (via `socket.gethostname()`)
- `api_key` is auto-generated (32-char random hex string) when adding a peer
- Peer metadata (their ID, name, fingerprint, timestamps) stored in `sync_peers` table

---

## API Endpoints

### Existing Endpoints (Web UI)
- `GET /api/notes` - List all non-deleted notes
- `POST /api/notes` - Create new note
- `GET /api/notes/<id>` - Get specific note
- `PUT /api/notes/<id>` - Update note
- `GET /api/tags` - List all tags
- `GET /api/search` - Search notes
- `GET /api/health` - Health check

### New Sync Endpoints

All require `Authorization: Bearer <api_key>` header.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/sync/handshake` | Clock validation, exchange device info |
| `GET` | `/api/sync/changes?since=<unix_timestamp>` | Get changes since timestamp |
| `POST` | `/api/sync/apply` | Apply incoming changes |
| `GET` | `/api/sync/full` | Full database dump for initial sync |

### Handshake Request/Response

```json
// GET /api/sync/handshake
// Response:
{
  "device_id": "01937a3e-...",
  "device_name": "Dotan's Desktop",
  "current_timestamp": 1703001234,
  "protocol_version": 1
}
```

Client sends its timestamp in header: `X-Client-Timestamp: 1703001230`
Server rejects if `abs(client_timestamp - server_timestamp) > clock_tolerance_seconds`

### Changes Response Format

UUIDs transmitted as hex strings (32 chars, no hyphens) in JSON, converted to/from 16-byte BLOB for storage.

```json
// GET /api/sync/changes?since=1703000000
{
  "notes": [
    {
      "id": "01937a3e12347abc8def567890abcdef",
      "created_at": "2024-12-19T10:00:00",
      "content": "Note content",
      "modified_at": "2024-12-19T11:00:00",
      "deleted_at": null,
      "device_id": "01937a3e12347abc8def567890abcdef",
      "tags": ["01937b2f12347abc8def567890abcdef"]
    }
  ],
  "tags": [
    {
      "id": "01937b2f12347abc8def567890abcdef",
      "name": "Projects",
      "parent_id": null,
      "created_at": "2024-12-19T09:00:00",
      "modified_at": "2024-12-19T09:00:00",
      "device_id": "01937a3e12347abc8def567890abcdef"
    }
  ],
  "server_timestamp": 1703001234
}
```

Python conversion:
```python
import uuid

# BLOB to hex string (for JSON)
uuid_hex = uuid.UUID(bytes=blob_value).hex

# Hex string to BLOB (for storage)
blob_value = uuid.UUID(hex=uuid_hex).bytes
```

### Apply Request Format

```json
// POST /api/sync/apply
{
  "notes": [...],
  "tags": [...],
  "client_device_id": "01937xyz-...",
  "client_device_name": "Meirav's Phone"
}
```

---

## Sync Algorithm

1. **Handshake**
   - Client sends `GET /api/sync/handshake` with `X-Client-Timestamp` header
   - Server validates clock difference <= `clock_tolerance_seconds`
   - Exchange device IDs and names
   - Store/update peer info in `sync_peers` table

2. **Pull Changes**
   - Client sends `GET /api/sync/changes?since=<last_received_timestamp>`
   - `last_received_timestamp` comes from `sync_peers.last_received_timestamp`
   - For first sync, use timestamp 0 or use `/api/sync/full`

3. **Apply Incoming Changes**
   For each incoming entity:
   - **New entity** (UUID not in local DB): Insert it
   - **Existing, incoming is newer** (`modified_at` > local): Update local
   - **Existing, local is newer**: Skip (we have newer version)
   - **Same timestamp, different content**: CONFLICT
     - For notes: Attempt diff3 merge using common ancestor (if available) or create `conflicts_note_content` record
     - For tags: Create `conflicts_tag_rename` record
   - **Edit vs Delete conflict**: Create `conflicts_note_delete` record
   - **Duplicate root tags** (same name, different UUIDs): Merge by reassigning children to one UUID, delete the other

4. **Push Changes**
   - Client sends `POST /api/sync/apply` with changes since `last_sent_timestamp`
   - Server applies using same logic
   - Server returns any conflicts detected

5. **Update State**
   - Update `sync_peers.last_received_timestamp` to `server_timestamp` from response
   - Update `sync_peers.last_sent_timestamp` to current time
   - Update `sync_peers.last_sync_at`

---

## Server Startup Changes

Modify `src/main.py` and `src/web.py`:

```bash
# Web UI only
voice web --enable-web-ui

# Sync server only
voice web --enable-sync

# Both
voice web --enable-web-ui --enable-sync

# Neither (error)
voice web
# Error: At least one of --enable-web-ui or --enable-sync is required
```

---

## HTTPS / TLS Implementation

### Self-Signed Certificate Generation
On first run with `--enable-sync`, generate a self-signed certificate:
- Store in config directory: `~/.config/voice/server.crt` and `server.key`
- Calculate SHA-256 fingerprint for TOFU

### TOFU (Trust On First Use)
- On first connection to a peer, accept their certificate
- Store fingerprint in `sync_peers.certificate_fingerprint`
- On subsequent connections, verify fingerprint matches
- If fingerprint changes, warn user loudly and refuse connection (possible MITM)

### Client Connection
```python
import ssl
import requests

# Custom SSL context that verifies against stored fingerprint
# If no stored fingerprint, accept and store (TOFU)
# If stored fingerprint exists, verify match
```

---

## Dependencies to Add

```
uuid6  # For UUID7 support - well-maintained, follows RFC 9562
```

### diff3 Merge Library

The merge implementation must be **pluggable** to allow alternative implementations if issues arise (especially with Hebrew/RTL text).

Architecture:
```python
# src/core/merge.py
from abc import ABC, abstractmethod

class MergeStrategy(ABC):
    @abstractmethod
    def merge(self, base: str, local: str, remote: str) -> tuple[str, bool]:
        """Returns (merged_content, success). If success=False, content is None."""
        pass

class DiffMatchPatchMerge(MergeStrategy):
    """Google's diff-match-patch library. Good Unicode/Hebrew support."""
    pass

class Merge3Strategy(MergeStrategy):
    """Python merge3 library. Line-based."""
    pass

# Config or code can select which strategy to use
```

**Primary choice**: `diff-match-patch` (good Unicode support, character-level diff)
**Fallback**: `merge3` (line-based, simpler)

NOTE: If Hebrew/RTL issues occur, the pluggable architecture allows switching without code changes to sync logic.

---

## Implementation Order

### Phase 1: Database Migration
1. Add `uuid-extensions` (or similar) dependency for UUID7
2. Create new database schema with UUID7 primary keys
3. Update `src/core/database.py` to generate UUID7 for new records
4. Update `src/core/models.py` - change `id: int` to `id: str`
5. Add `device_id` field to notes and tags
6. Add `created_at`, `modified_at` to tags
7. Update all database queries to use TEXT ids
8. Update all tests

### Phase 2: Config Changes
1. Update `src/core/config.py` with sync schema
2. Auto-generate `device_id` (UUID7) on first run
3. Prompt for or default `device_name`
4. Add sync peer configuration

### Phase 3: Sync Server Endpoints
1. Add `--enable-sync` and `--enable-web-ui` flags to `src/main.py`
2. Create `src/core/sync.py` for sync logic
3. Add sync endpoints to `src/web.py`:
   - `/api/sync/handshake`
   - `/api/sync/changes`
   - `/api/sync/apply`
   - `/api/sync/full`
4. Implement API key authentication middleware
5. Implement clock validation

### Phase 4: TLS/HTTPS
1. Generate self-signed certificate on first `--enable-sync` run
2. Implement TOFU certificate verification
3. Configure Flask to use HTTPS

### Phase 5: Sync Client
1. Create sync client in `src/core/sync_client.py`
2. Implement handshake with clock validation
3. Implement pull (fetch changes)
4. Implement push (send changes)
5. Implement change application logic

### Phase 6: Conflict Handling
1. Implement diff3 merge for note content
2. Create conflict records when merge fails
3. Implement tag merge (reassign children for duplicate root tags)
4. Implement tag rename conflict detection

### Phase 7: CLI/TUI/GUI Integration
1. Add sync command to CLI: `voice sync [--peer URL]`
2. Add sync status display (last sync time, pending count)
3. Add sync trigger to TUI
4. Add sync trigger to GUI
5. Implement sync logging to `sync.log`

### Phase 8: Testing
1. Unit tests for sync logic
2. Integration tests with two instances
3. Conflict resolution tests
4. TLS/certificate tests

---

## Key Design Rationale

### Why UUID7 over UUID4?
UUID7 is time-ordered (first 48 bits are millisecond timestamp), so:
- B-tree indexes don't fragment on insert
- Better insert performance at scale (84,000+ notes)
- Roughly sortable by creation time

### Why BLOB over TEXT for UUIDs?
- BLOB: 16 bytes per UUID
- TEXT (hex): 32 bytes per UUID
- TEXT (with hyphens): 36 bytes per UUID
- At 84,000 notes, BLOB saves ~1.7 MB on IDs alone
- Validation happens in application layer, not database constraints

### Why Timestamps over Vector Clocks?
- Simpler implementation
- Clock validation ensures accuracy
- Sufficient for manual sync (not real-time collaboration)
- Easier to implement on Android

### Why TOFU over Manual Fingerprint Exchange?
- Better UX for infrequent syncs
- SSH-like familiarity
- Still secure against MITM after first connection
- User warned on fingerprint change

### Why diff3 Merge?
- Handles non-overlapping edits automatically
- Falls back to conflict record when edits overlap
- No automatic data loss

---

## Notes for Implementation

- The current database has no data worth preserving (test only)
- Existing tests are in `tests/` directory
- Flask app is in `src/web.py` with CORS enabled
- Database abstraction is clean - all access through `Database` class
- Models are immutable dataclasses

---

## Commands to Resume Implementation

```bash
# Run tests
python -m pytest

# Run specific test file
python -m pytest tests/test_database.py

# Run the web server (current, before changes)
python -m src.main web

# Run TUI
python -m src.main tui
```

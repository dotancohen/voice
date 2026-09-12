# Sync System Design Document

## Final Design Decisions

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
| **Sync Logging** | Separate file in config directory (e.g., `~/.config/voice/sync.log`) |
| **Server Flags** | `--enable-sync` and `--enable-web-ui` (at least one required) |
| **Future** | Android app support |

---

## Database Schema Changes

### Primary Key Migration
All tables change from `INTEGER PRIMARY KEY AUTOINCREMENT` to `TEXT PRIMARY KEY` (UUID7).

### New Columns
```sql
-- notes table
ALTER TABLE notes ADD COLUMN device_id TEXT NOT NULL;  -- device that last modified

-- tags table
ALTER TABLE tags ADD COLUMN created_at DATETIME NOT NULL;
ALTER TABLE tags ADD COLUMN modified_at DATETIME;
ALTER TABLE tags ADD COLUMN device_id TEXT NOT NULL;   -- device that last modified
```

### New Indexes
```sql
CREATE INDEX idx_notes_modified_at ON notes(modified_at);
CREATE INDEX idx_tags_modified_at ON tags(modified_at);
```

### New Tables
```sql
-- Track sync state per peer
CREATE TABLE sync_peers (
    peer_id TEXT PRIMARY KEY,           -- UUID7 of the peer device
    peer_name TEXT,                      -- Friendly name (e.g., "Dotan's Desktop")
    peer_url TEXT NOT NULL,
    last_sync_at DATETIME,
    last_received_timestamp DATETIME,    -- Their latest change we've received
    last_sent_timestamp DATETIME,        -- Our latest change we've sent
    certificate_fingerprint TEXT         -- TOFU: stored on first connect
);

-- Content edit conflicts
CREATE TABLE conflicts_note_content (
    id TEXT PRIMARY KEY,                 -- UUID7
    note_id TEXT NOT NULL,               -- The note in conflict
    local_content TEXT NOT NULL,
    local_modified_at DATETIME NOT NULL,
    local_device_id TEXT NOT NULL,
    local_device_name TEXT,
    remote_content TEXT NOT NULL,
    remote_modified_at DATETIME NOT NULL,
    remote_device_id TEXT NOT NULL,
    remote_device_name TEXT,
    created_at DATETIME NOT NULL,
    resolved_at DATETIME,
    FOREIGN KEY (note_id) REFERENCES notes(id)
);

-- Delete conflicts (one side edited, other side deleted)
CREATE TABLE conflicts_note_delete (
    id TEXT PRIMARY KEY,                 -- UUID7
    note_id TEXT NOT NULL,
    surviving_content TEXT NOT NULL,     -- The content from the edit
    surviving_modified_at DATETIME NOT NULL,
    surviving_device_id TEXT NOT NULL,
    surviving_device_name TEXT,
    deleted_at DATETIME NOT NULL,
    deleting_device_id TEXT NOT NULL,
    deleting_device_name TEXT,
    created_at DATETIME NOT NULL,
    resolved_at DATETIME,
    FOREIGN KEY (note_id) REFERENCES notes(id)
);

-- Tag rename conflicts
CREATE TABLE conflicts_tag_rename (
    id TEXT PRIMARY KEY,                 -- UUID7
    tag_id TEXT NOT NULL,
    local_name TEXT NOT NULL,
    local_modified_at DATETIME NOT NULL,
    local_device_id TEXT NOT NULL,
    local_device_name TEXT,
    remote_name TEXT NOT NULL,
    remote_modified_at DATETIME NOT NULL,
    remote_device_id TEXT NOT NULL,
    remote_device_name TEXT,
    created_at DATETIME NOT NULL,
    resolved_at DATETIME,
    FOREIGN KEY (tag_id) REFERENCES tags(id)
);
```

---

## Config Schema

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

Note: `device_name` is this device's friendly name, shown to peers during handshake.
Peer metadata (their `device_id`, `device_name`, `certificate_fingerprint`, sync timestamps)
is stored in the `sync_peers` database table, populated/updated during sync.

---

## API Endpoints (Sync)

All sync endpoints require `Authorization: Bearer <api_key>` header.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/sync/handshake` | Clock validation, exchange device info |
| `GET` | `/api/sync/changes?since=<timestamp>` | Get changes since timestamp |
| `POST` | `/api/sync/apply` | Apply incoming changes |
| `GET` | `/api/sync/full` | Full database dump for initial sync |

---

## Sync Algorithm

1. **Handshake**: Exchange device IDs, names, current timestamps. Reject if clock difference > tolerance.
2. **Pull**: `GET /api/sync/changes?since=<last_received_timestamp>` from peer
3. **Apply**: For each incoming change:
   - If new entity (UUID not in local DB): insert
   - If existing entity with older `modified_at`: skip (we have newer)
   - If existing entity with newer `modified_at`: update local
   - If existing entity with same `modified_at` but different content: conflict!
   - For notes: attempt diff3 merge, else create `conflicts_note_content`
   - For deletes: check for edit/delete conflict
   - For tags: check for rename conflict, merge duplicate root tags
4. **Push**: `POST /api/sync/apply` our changes since `last_sent_timestamp`
5. **Update state**: Store new `last_received_timestamp` and `last_sent_timestamp`

---

## Server Startup

```bash
# Web UI only
voice web --enable-web-ui

# Sync server only
voice web --enable-sync

# Both
voice web --enable-web-ui --enable-sync

# Neither (error with helpful message)
voice web
# Error: At least one of --enable-web-ui or --enable-sync is required
```

---

## Future Considerations

- Android app will use same HTTP sync protocol
- Conflict resolution UI to be implemented in each interface (TUI/GUI/Web)
- QR code for easy peer setup (encode URL + API key)


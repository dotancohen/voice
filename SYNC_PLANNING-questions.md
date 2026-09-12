# Sync System Planning Questions

Please answer inline below each question.

---

## Database Identity Questions

### 1. UUID Migration Strategy
Your current schema uses auto-increment integers. For UUIDs, you have two approaches:
- **Replace IDs entirely** with UUID4 (simpler sync logic, but requires migration)
- **Add a `uuid` column alongside existing IDs** (keeps local queries efficient, adds complexity)

Which do you prefer? Or would you like me to explain the tradeoffs further?

**Answer:**
The current database is for test purposes only, so there is no migration needed. We can assume that there is no data to save. So we can replace IDs entirely with UUID4.

### 2. Existing Data
Do you have existing data that needs to be preserved, or is this still in development where a schema change is acceptable?

**Answer:**
None.

---

## Conflict Resolution Questions

### 3. Edit Conflicts
If the same note is edited on two instances while offline, then they sync, what should happen?
- Last-write-wins (simpler, data loss possible)
- Merge content somehow
- Create duplicate notes for manual resolution
- Flag as conflict and let user choose

**Answer:**
Merge content somehow. If this can not be done, then create duplicate notes for manual resolution, and store in a database table `conflicts_note_content` the fact that these two notes need to be reconciled. The table should store the edit time and device each version was on. The user could then merge the two notes. There should never be automatic data loss!


### 4. Delete Conflicts
If instance A edits a note while instance B deletes it, which wins?
- Delete always wins
- Edit resurrects the note
- Configurable per sync

**Answer:**
Store this information in the database table `conflicts_note_delete`. Let the user resolve it.

### 5. Tag Conflicts
If instance A creates tag `Projects/Work` and instance B creates `Projects/Personal` with the same parent, that's fine. But what if both create `Projects/Work` with different parent_ids, or rename a tag differently?

**Answer:**
Tag rename conflicts should be stored in the database table `conflicts_tag_rename`. Let the user resolve it.
If two users create `Projects/Work` with different parent IDs, then there is no conflict and there is nothing to resolve. In fact, this is expected behaviour: we already allow duplicate tag names under different parents.

---

## Sync Behavior Questions

### 6. Sync Scope
Should syncing be:
- All-or-nothing (full database sync)
- Selective (e.g., only sync certain tags/folders)
- Incremental (only changes since last sync)

**Answer:**
Nominally incremental. But there should be a full sync available as well.

### 7. Tombstones
Your soft-delete pattern is good for sync. Should deleted notes:
- Sync their deletion to other instances?
- Be permanently purged after some period across all instances?
- Remain indefinitely in deleted state?

**Answer:**
Sync their deletion to other instances. So far as the data is concerned, a delete is just adding a non-NULL value to the deleted_at field.

### 8. Sync Direction
You said bidirectional, but should it be:
- Full bidirectional (push my changes, pull their changes)
- Pull-only mode available (for "read-only" instances)
- Push-only mode available

**Answer:**
Full bidirectional.

---

## Security & Network Questions

### 9. Authentication
How should instances authenticate to each other?
- Shared secret/API key in config
- TLS client certificates
- No auth (trusted network only)
- Something else?

**Answer:**
Shared secret/API key in config

### 10. Transport Security
HTTPS required, or is HTTP on trusted networks acceptable?

**Answer:**
HTTPS required

### 11. Instance Discovery
You mentioned configuring servers in config. Should this be:
- Static list of URLs only
- mDNS/Bonjour discovery on local network
- Both options

**Answer:**
Static list of URLs only

---

## Operational Questions

### 12. Scale
Roughly how many notes/tags do you expect per instance? (Affects whether full-sync or delta-sync is practical)

**Answer:**
Tens of thousands of notes. I already personally have 84,000 notes that I need to import into this application.

### 13. Sync Frequency
When you say "synced periodically":
- Manual trigger only?
- Automatic on startup?
- Background periodic sync?
- Real-time (websockets) when connected?

**Answer:**
Manual trigger only.

### 14. Sync Status
Should the UI show:
- Last sync time per server
- Pending changes count
- Sync history/log

**Answer:**
The UI should show last sync time per server. If it is not expensive to calculate, then show pending changes count as well.
Sync history/log should be in a seperate log file, no need to show it in the UI.

### 15. Failure Handling
If sync with one server fails but another succeeds, should it:
- Continue silently and retry later
- Warn the user
- Block until resolved

**Answer:**
Warn the user, but continue to do the other syncs. It is actually expected that some servers will be down at any particular time.

---

## Architecture Questions

### 16. Sync Protocol
Are you open to using an existing protocol like CouchDB-style replication, or do you want a custom sync protocol?

**Answer:**
Please detail the options and I'll try to make an informed decision. There are additional future considerations, such as a future Android app that will sync as well.

### 17. Change Tracking
To enable efficient delta sync, we'd need to track changes. Options:
- Add `version` or `vector_clock` columns
- Add a separate `change_log` table
- Compare timestamps only (simpler but less reliable)

**Answer:**
Give me more information about these options and I'll decide. Thank you.

---

## Additional Notes

Any other constraints, preferences, or context I should know about?

**Answer:**
Yes, in the future there will be an Android application that will need to sync as well.

---

**Additional question of mine:**
Would UUID7 be a better choice than UUID4 for database keys? I've been told it is better for database keys so that the index doesn't have to be rebuilt each time an insert happens, because they are ordered by time.


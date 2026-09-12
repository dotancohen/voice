# TODO: Sync Conflict Resolution UI

This file tracks future work needed for sync conflict resolution.

## Critical: Conflict Resolution UI

The sync system stores conflicts in database tables but does NOT yet have UI to resolve them.
**This is critical functionality that must be implemented before production use.**

### Conflict Tables

1. **`conflicts_note_content`** - Two devices edited the same note
   - Shows: local content, remote content, timestamps, device names
   - User action: Choose local, remote, or merge

2. **`conflicts_note_delete`** - One device edited, another deleted
   - Shows: surviving content, delete timestamp, device names
   - User action: `restore` (undelete) or `delete` (accept deletion)

3. **`conflicts_tag_rename`** - Two devices renamed the same tag differently
   - Shows: local name, remote name, timestamps, device names
   - **Current behavior**: Tag is temporarily renamed to "localName | remoteName" until resolved
   - User action: Choose one name or enter a new name

4. **`sync_failures`** - Changes that failed to apply (validation errors, etc.)
   - Shows: entity type, operation, error message, original payload
   - User action: Retry, skip permanently, or fix manually

### UI Requirements

Each interface (TUI, GUI, Web) needs:

1. **Conflict indicator** - Show count of unresolved conflicts somewhere visible
2. **Conflict list view** - List all conflicts grouped by type
3. **Conflict detail view** - Show both versions side-by-side with diff highlighting
4. **Resolution actions**:
   - For content conflicts: `local`, `remote`, `merge`
   - For delete conflicts: `restore`, `delete`
   - For tag renames: `local`, `remote` (or enter new name)
   - For sync failures: "Retry", "Dismiss", "View Details"
5. **Bulk actions** - Resolve multiple conflicts at once (e.g., "Use all local")

### Implementation Priority

1. CLI commands first (simplest, for testing):
   - `voice conflicts list`
   - `voice conflicts show <id>`
   - `voice conflicts resolve <id> --action <action>`

2. TUI next (primary interface)

3. GUI

4. Web API endpoints (for future Android app)

### Database Queries Needed

```sql
-- Count unresolved conflicts (for indicator)
SELECT
    (SELECT COUNT(*) FROM conflicts_note_content WHERE resolved_at IS NULL) +
    (SELECT COUNT(*) FROM conflicts_note_delete WHERE resolved_at IS NULL) +
    (SELECT COUNT(*) FROM conflicts_tag_rename WHERE resolved_at IS NULL) +
    (SELECT COUNT(*) FROM sync_failures WHERE resolved_at IS NULL) AS total_conflicts;

-- List all unresolved conflicts
SELECT 'note_content' as type, id, note_id as entity_id, created_at
FROM conflicts_note_content WHERE resolved_at IS NULL
UNION ALL
SELECT 'note_delete' as type, id, note_id as entity_id, created_at
FROM conflicts_note_delete WHERE resolved_at IS NULL
UNION ALL
SELECT 'tag_rename' as type, id, tag_id as entity_id, created_at
FROM conflicts_tag_rename WHERE resolved_at IS NULL
UNION ALL
SELECT 'sync_failure' as type, id, entity_id, created_at
FROM sync_failures WHERE resolved_at IS NULL
ORDER BY created_at;
```

### Resolution Logic

When resolving a conflict, set `resolved_at = datetime('now')` and apply the chosen action:

- **Note content - local**: No change needed (local version already in notes table)
- **Note content - remote**: Update note with remote_content
- **Note content - merge**: Keep merged content with conflict markers for manual cleanup
- **Note delete - restore**: Set notes.deleted_at = NULL (undelete)
- **Note delete - delete**: No change needed (already deleted)
- **Tag rename - local**: Update tags.name with local_name (replaces combined name)
- **Tag rename - remote**: Update tags.name with remote_name (replaces combined name)

## Other Future Work

- [ ] QR code for easy peer setup (encode URL + API key)
- [ ] Conflict notification sound/alert
- [ ] Auto-merge option for trivial conflicts (e.g., whitespace only)
- [ ] Conflict history view (show resolved conflicts)

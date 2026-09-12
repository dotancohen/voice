# Voice Sync Specification

Status: describes the behaviour implemented in `submodules/voicecore` as of 2026-09-06 (protocol 1.1: cursor feed, derived versions).
Audience: developers writing tests or extending sync, and reviewers checking that a
change keeps the guarantees below.

Every requirement has an identifier (for example `VER-4`). Tests should name the
identifier they cover. Section 12 maps identifiers to the tests that exist today.
Section 13 lists known limitations and proposed improvements.

Terminology:

- **Device**: one installation (desktop, server, Android). Identified by a UUID7 `device_id`
  and a human `device_name`, both in `config.json`.
- **Peer**: another device this device syncs with, over HTTP(S).
- **Entity**: a row a user can see: note, tag, note-tag link, attachment, audio file,
  transcription, synced setting.
- **Field**: one editable value of an entity (a note's content, a tag's name, ...).
- **Version**: one immutable value of a field, with its parent(s), like a Git commit.
- **Head**: the version currently shown for a field.
- **Conflict**: a recorded merge that needed a human.
- **Binary**: the bytes of an audio file. Never carried by sync; stored in cloud storage.

---

## 1. Goals and non-goals

| ID | Requirement |
|----|-------------|
| GOAL-1 | No user edit is ever lost. Every value a user typed is retained in history and, when two devices disagree, both values remain reachable and visible. |
| GOAL-2 | Devices are offline for hours at a time. Everything must work with arbitrary delays, repeated deliveries, and reordering between peers. |
| GOAL-3 | Concurrent edits are merged automatically when possible (like Git) and flagged for the user when not. Last-write-wins is forbidden for user data. |
| GOAL-4 | All devices converge: after every device has exchanged with every other, every device shows the same values and the same conflicts with the same ids. |
| GOAL-5 | Audio binaries are stored once in cloud storage and downloaded only when the user asks (or when a desktop/server opts into mirroring). |
| GOAL-6 | The design is one implementation shared by desktop (PyO3), server, and Android (UniFFI). |

Non-goals: real-time collaboration, per-character merging, peer-to-peer binary transfer (planned as a later plugin), end-to-end encryption.

---

## 2. Identity

| ID | Requirement |
|----|-------------|
| ID-1 | `device_id` is a UUID7 generated on first run and stored in `config.json`. `device_name` defaults to `"Voice on <hostname>"` and is editable. |
| ID-2 | Loading the config installs the device id and name process-wide (`Config::new` calls `set_local_device_id` / `set_local_device_name`). Every version written afterwards carries them. |
| ID-3 | The device id is set once per process (first wins). The device name follows the last config loaded. |
| ID-4 | Peers are identified by their `device_id`; the URL is configuration, the id is identity. Renaming a device changes only the label on future versions. |
| ACCT-1 | Every database belongs to one **account**, `sync_meta.account_id`: 32 hex characters minted with the database (a UUID7) and the same on every device of the account. It is the identity of the *data*; `device_id` is the identity of the *installation* and `database_id` (PROTO-9) of the *file*. The three are never confused: a differing `database_id` means "re-exchange everything", a differing `account_id` means "exchange nothing". |
| ACCT-2 | The handshake request and response both carry `account_id`. A request that names none is refused (400, `ACCOUNT_MISSING`); one that names another account is refused (403, `ACCOUNT_MISMATCH`) with a sentence naming both, and nothing is exchanged. Every refusal carries a `code` beside its sentence. |
| ACCT-3 | The caller checks the response the same way and refuses a peer of another account before pulling or pushing anything. The account a peer held at its last agreeing handshake is kept in `sync_peers.peer_account_id`, so the refusal can say that the device at a remembered address has changed. The handshake never adopts an account from the other side. |
| ACCT-4 | A database is authoritative for its own account. `Database::new_for_account(path, id)` gives a fresh, unused database the id; a database that holds notes or has synced under another id is refused (`ACCOUNT_DISAGREES`), never corrected. |
| CARD-1 | Every device of an account has a **card**: entity `device`, id = the device id, fields `name`, `certificate_fingerprint`, `addresses` (JSON list of the URLs it listens on), `listens`, `key_hash`, `revoked` and `application`. Each is a versioned field (DM-1) and travels in the feed, so every device of the account knows every other. The `devices` table is the denormalised copy. |
| CARD-2 | A device writes its own card (`auth::ensure_own_device_card`, at every start), except `revoked`, which any device may set and none may clear: the `devices` column keeps `"1"` whatever version becomes the head afterwards, and the field's kind is Membership so concurrent writes settle on `"1"` too. A revoked device id stays revoked. |
| AUTH-1 | Every device holds one **device key** per account: 32 random bytes as 43 base64url characters, made by `ensure_own_device_card` when the device created the account, or issued at pairing. It is held in clear only in that device's `config.json` (`sync.device_key`); every other device holds its hex SHA-256 in the card's `key_hash`. A key can never be listed; a lost one means revoke and pair again. |
| AUTH-2 | The hash is plain SHA-256: the key has 256 bits of entropy, so a slow hash buys nothing. Hashes are compared in constant time. |
| AUTH-3 | Every request but `GET /sync/status` carries `X-Account-ID`, `X-Device-ID` and `Authorization: Bearer <device key>`. The server refuses, in this order: an account it does not hold (404 `ACCOUNT_UNKNOWN`), a missing key or device (401 `KEY_MISSING`), a device with no card (401 `DEVICE_UNKNOWN`), a revoked card (401 `DEVICE_REVOKED`), a key that does not hash to the card (401 `KEY_WRONG`). A handshake whose body names another device than the headers is refused (400 `DEVICE_MISMATCH`). The key is never written to a log or an error. |
| AUTH-4 | The two headers name the account and the device, so a server that hosts several accounts routes and authenticates in one step; today's server holds one account and refuses every other. |
| AUTH-5 | After three refusals from one address, each further refusal is answered after a wait that doubles from one second to eight; a success clears the count; counts are forgotten after ten minutes and the table is emptied past ten thousand addresses. |
| AUTH-6 | `revoke_device` marks a card revoked; every peer refuses the device once the card has reached it. `device list` and `device revoke <id>` on the command line. A revoked device still holds the bucket key, which reached it by sync; the command says so. |
| AUTH-7 | **Certificate verification is never off.** A listener serves HTTPS with its own certificate (`certs/server.crt`, made if missing; its fingerprint is on its card). A caller verifies a peer with a pinned fingerprint against the fingerprint alone (a self-signed certificate has no root), and a peer without one against the system's root certificates. Plain `http://` is accepted only to a loopback address, and a listener serves plain http (`sync serve --plain-http`) only on a loopback address, for a reverse proxy in front or a test; both are refused elsewhere with `TLS_REQUIRED`. A wrong pin is `CERTIFICATE_MISMATCH`. |
| PAIR-1 | A device that holds an account **shows a code**: a setup text `voice://pair?v=1&a=<account>&t=<token>&d=<device id>&u=<url,…>&f=<fingerprint>`, also drawn as a QR code. The fingerprint's 32 bytes travel as 43 base64url characters. Under 300 bytes. No lasting secret is in it. |
| PAIR-2 | The **token** is 32 random bytes. Only its hash is kept, in the local `pairing_offers` table (never synced), with an expiry ten minutes on. One offer at a time: showing a code withdraws the previous one; hiding the code withdraws it; the first right token spends it; the fifth wrong token withdraws it. |
| PAIR-3 | **Claim**: the reading device posts `/pair/claim` with the token, its device id, name, certificate fingerprint and addresses, over TLS pinned to the fingerprint in the text. The route sits outside the device-key middleware and is authenticated by the token alone; a wrong token is refused (403 `TOKEN_INVALID`) and counts against the address like any other refusal. On success the shower makes a device key for the reader, writes the reader's card with the key's hash, and replies with the account id, the key and its own card. |
| PAIR-4 | The reading device refuses, before any network, a code for another account when it holds notes (`DEVICE_HOLDS_NOTES`), and says to show its own code to the other device instead. An empty device takes the account (through `move_to_account`), stores the key, writes the shower's card, adds the shower as a peer with the pinned fingerprint, and writes its own card. A reply naming another account than the code is refused (`ACCOUNT_MISMATCH`). |
| LISTEN-1 | An instance **listens** only while asked: the switch in the desktop's File menu, the switch on the phone's sync screen (a foreground service with a Stop action), or `cli sync serve`. The core never starts a listener by itself. A stopped listener can be started again in the same process. |
| LISTEN-2 | While it listens, the instance's own card says `listens = "1"` and `addresses` holds the URLs peers can use (`https://<private IPv4>:<port>` for each LAN address, and the host name); when it stops, `listens = "0"`. About on the desktop and the sync screen on the phone show the account, the device id, the addresses and the certificate fingerprint, so a person can type them into another device. |
| PAIR-5 | **Grant**, for an empty device that cannot reach the holder (a server): the empty device shows a code and the holder posts to it. Designed; built with hosting. |
| ACCT-5 | The only way a database changes account is `move_to_account`: a snapshot first (SNAP-1), the id rewritten, every peer forgotten so the next sync exchanges everything, the notes kept (their ids cannot collide). On the command line it is `account move --to <id> --current <id>`, where the current id must be typed in full. |

Known limitation: a single process holds one identity, so tests that drive two databases in one process attribute both sides to the same device. See LIM-1.

---

## 3. Data model

### 3.1 Entities and their versioned fields

The registry lives in `versions.rs` (`FIELD_REGISTRY`). Only these fields carry history; every other column is either immutable (ids, `created_at`) or derived (caches).

| Entity type | Field | Kind | Value encoding |
|-------------|-------|------|----------------|
| `note` | `content` | Text | UTF-8 text |
| `note` | `deleted` | Deleted | `"0"` alive, `"1"` deleted |
| `note` | `primary_attachment` | Scalar | The id of the attachment that stands for the note, or `""` for "the first one". Denormalised to `notes.primary_attachment_id` |
| `tag` | `name` | Scalar | text |
| `tag` | `parent` | Scalar | parent tag id (32 hex chars) or `""` for root |
| `tag` | `deleted` | Deleted | `"0"` / `"1"` |
| `note_tag` | `active` | Membership | `"1"` attached, `"0"` detached. Entity id is `"<note_id>:<tag_id>"` |
| `note_attachment` | `active` | Membership | `"1"` / `"0"`. Entity id is the attachment row id |
| `transcription` | `content` | Text | UTF-8 text |
| `transcription` | `state` | Flags | space-separated flags from `original verified verbatim cleaned polished` |
| `transcription` | `deleted` | Deleted | `"0"` / `"1"` |
| `audio_file` | `summary` | Text | UTF-8 text |
| `audio_file` | `deleted` | Deleted | `"0"` / `"1"` |
| `audio_file` | `primary_transcription` | Scalar | The id of the transcription that stands for the recording, or `""` for "the first one". Denormalised to `audio_files.primary_transcription_id` |
| `setting` | `value` | Scalar | text; entity id is the setting key (e.g. `transcription.preferred_languages`) |

| ID | Requirement |
|----|-------------|
| DM-1 | Adding an editable field means: register it in `FIELD_REGISTRY`, route every write through `set_field`/`set_deleted`/`init_field`, denormalise it in `apply_head_to_entity`, and add it to the entity's feed row. A field that is written directly with SQL is a bug. |
| DM-2 | Entity rows (`notes.content`, `tags.name`, ...) are denormalised copies of the heads for display and search. Heads are the truth; rows are rewritten from heads after every sync. |
| DM-3 | Deletion is a versioned field. A deleted note is in the **trash**, still in the database with its history and its recordings, and can be recovered. The only thing that removes a row is a **purge** (PURGE-1..PURGE-9), which the user asks for explicitly from the trash. |
| DM-4 | Metadata that is not in the registry is machine-written and merged **per column** when a row arrives: audio `filename`, `file_created_at`, `duration_seconds`; transcription `service`, `service_arguments`, `service_response`, `content_segments`; attachment `note_id`, `attachment_id`, `attachment_type`. The row with the newer `modified_at` wins a column; an older row only fills in a column that is NULL here. Rows never write versioned columns. Locally, a metadata change stamps `modified_at` (`update_transcription`, `update_audio_file_storage`, ...), and `None` arguments leave a value alone. |
| DM-5 | `file_storage_config` is a single-row table (cloud provider + credentials) applied by newest `modified_at`. It contains no user content. |

### 3.2 Tables

| Table | Purpose |
|-------|---------|
| `field_versions` | Append-only DAG. Columns: `id` (16 bytes), `entity_type`, `entity_id`, `field`, `parent_id`, `merge_parent_id`, `content`, `context`, `conflict_kind`, `device_id`, `device_name`, `created_at`, `created_at_offset`, `created_at_zone`, `sync_received_at`. |
| `field_heads` | One row per (entity_type, entity_id, field): the current head id. |
| `field_conflicts` | One row per merge that needed a human: id, the field, `kind`, `base_version_id`, `version_a_id`, `version_b_id`, `merge_version_id`, devices A and B, `created_at`, `resolved_at`. |
| `synced_settings` | Denormalised heads of `setting.value`. |
| `sync_peers` | Known peers and last sync times. |
| `sync_failures` | Changes that could not be applied, kept for retry. |

### 3.3 Snapshots

A copy of the database before anything that rewrites it in one step, so that
a bad merge, a wrong move or a restore can be undone.

| ID | Requirement |
|----|-------------|
| SNAP-1 | `Database::snapshot` copies the whole database with SQLite's backup API into `snapshots/` beside the file, named `notes-<UTC time>.db`. Readers are never blocked. An in-memory database has no snapshots and skips them silently. |
| SNAP-2 | The newest `SNAPSHOTS_KEPT` (five) are kept; taking the sixth deletes the oldest. Recordings are not included: they are files and never rewritten by sync. |
| SNAP-3 | A snapshot is taken before this device applies anything from a peer: on the caller's side before the first pull of a sync, and on the responder's side at the handshake that starts the caller's operation; and before `move_to_account` and before a restore. |
| SNAP-4 | `restore_snapshot(name)` replaces the database's contents with the snapshot's through the same API, after snapshotting the state being replaced, so a restore is itself undoable. `account snapshots` lists them with their note counts; `account restore <name>` asks first. On the phone both are under Advanced settings. |

### 3.4 Times and timezones

Every timestamp is an `INTEGER` count of seconds since the Unix epoch: an
instant, the same number on every device, which is what sync compares and
orders by.

An instant cannot say what the clock read where something happened, so each
user-visible timestamp carries two more columns.

| ID | Requirement |
|----|-------------|
| TZ-1 | `<stamp>_offset` holds the seconds east of UTC in force on the device at that moment, and `<stamp>_zone` its IANA name when the device knew one. They exist for `created_at`, `modified_at` and `deleted_at` on notes, tags, note-tag links, attachments and transcriptions, for `imported_at` and `file_created_at` on audio files, and for `created_at` on every version. |
| TZ-2 | Sync bookkeeping (`sync_received_at`, `last_sync_at`, `seq`) and `storage_uploaded_at` have none: they are machine events that no screen shows. |
| TZ-3 | A reader renders an instant at its recorded offset, so a note written at 15:20 in Jerusalem still reads 15:20 in New York. A row with no offset, written before these columns or by a device that never reported one, is shown in the reader's own timezone. |
| TZ-4 | Ordering, merging and the cursor feed use the instant alone. Displayed times are therefore not monotonic across a journey, by design. |
| TZ-5 | The offset cannot be recovered from the instant afterwards, so the platform reports it: `timezone::set_local_timezone(offset, name)` from Python when a database is opened, and `VoiceClient.setLocalTimezone` from Android at start. Without a report the core falls back to the operating system's offset and records no name. |
| TZ-6 | A version carries the zone of the device that wrote it. When a version becomes the head, the entity row's `modified_at` and `deleted_at` zones come from that version, so an edit made after travelling records where the edit happened while the note keeps where it was created. |

---

## 4. Versions

| ID | Requirement |
|----|-------------|
| VER-1 | A local edit creates a version whose `parent_id` is the current head, `device_id`/`device_name` are this device's, `created_at` is now, and `id` is a fresh UUID7. Writing the same value as the head creates nothing. |
| VER-2 | A deletion creates a `deleted = "1"` version whose `context` is a JSON object mapping every other field of the entity to its head id at that moment. This records what the deleting user saw. |
| VER-3 | The first value of a freshly created entity is a **root**: no parent, no device, id = `sha256(entity_type, entity_id, field, content)`. Any device deriving the same row from the same data produces the same root. (`init_field`, `ensure_root_version`) |
| VER-4 | A row that arrives from a peer for a field that has **no** versions yet gets a root for its value (pre-versioning data). Once a field has history, rows are hints only: their value is, or will be, carried by a version. A row value that differs from the head is ignored, never merged and never written (protocol 1.1 peers always send versions). |
| VER-5 | Merge versions are deterministic: id = `sha256(parent_a, parent_b, merged_content)` with parents ordered by id. Acceptances (`accept_version_id`) and resurrections are hashes as well. Two devices computing the same merge produce byte-identical versions, so `INSERT OR IGNORE` de-duplicates them. |
| VER-6 | Versions are immutable and never deleted. `content` of a version is never rewritten. |
| VER-7 | A root, and only a root, is applied with timestamp 0: it leaves `modified_at` NULL so the feed reports `"create"`. Any version written by a device (including the first tombstone of an entity, which has no parent but has a device) is applied with its `created_at`. |
| VER-8 | History of a field is `get_field_history(entity_type, entity_id, field)`, ordered by `created_at`, roots first. |
| VER-9 | **Authored vs derived.** A version with a device (edits, accepts) or with no parent (roots) is *authored*. A version with a parent and no device (merges, resurrections) is *derived*: it is computed, never typed. Derived versions are **not synced**; every device recomputes them from the same authored versions and, because their ids are hashes, arrives at the same ones. (`VersionRow::is_derived`) |
| VER-10 | **Publishing.** When an authored version builds on a derived one (an edit or accept on top of a merge, a delete whose context names a merge head), that derived version and its derived ancestors are marked `published` and from then on travel in the feed, ahead of the child. The flag travels with the version, so a hub that already derived it locally marks its own copy and relays it. Without this a peer that folded its pages in a different order could never complete the child. (`publish_derived_ancestors`) |
| VER-11 | A resurrection (HEAD-6) has one id per tombstone, `sha256("resurrect", tombstone_id)`, independent of which edit was current when a device noticed. |

### 4.1 The trash bin and purging

Deleting is reversible; emptying the trash is not. These rules say what
"for good" means when several devices are involved.

| ID | Requirement |
|----|-------------|
| PURGE-1 | The trash is every note whose `deleted` head is `"1"`: `get_deleted_notes`, newest deletion first, ties broken by id so that two devices list them in the same order. Recovery (`undelete_note`) is an ordinary `deleted = "0"` version and travels like any other change. |
| PURGE-2 | Only a note that is in the trash can be purged. Deleting is one step and removing for good is another, so neither can happen by accident. |
| PURGE-3 | A purge writes a row in `purges` (entity type, entity id, when, which device) and removes the entity, its row and its whole history (`field_versions`, `field_heads`, `field_conflicts`). Purge rows are kept for ever; they are the only record that the entity ever existed. |
| PURGE-4 | Purges travel in the feed as entity type `purge`. A peer that has never heard of them ignores them (PROTO-2), so an older device simply keeps its copy until it is upgraded. |
| PURGE-5 | **Nothing comes back.** Before applying any change, the receiver checks the purge records: a change about a purged entity is dropped, as is a version of one, a tag link of a purged note, a transcription of a purged recording, and an attachment of a purged recording. A queued failure about a purged entity is resolved rather than retried for ever. |
| PURGE-6 | **The cascade is recorded, not inferred.** Purging a note also purges the attachments it holds; purging a recording also purges its transcriptions. Each of those is written to `purges` in its own right, so the list travels: a device that holds an attachment the purging device never saw records a purge for it too, and every device ends with the same set (the union). |
| PURGE-7 | A purge is obeyed exactly as it was sent. A receiver never decides for itself that something named in a purge should be kept: two devices that made different decisions could never agree again. The device that empties the trash decides what goes, and it never includes a recording that another live note holds. A recording attached elsewhere in the same moment on another device is the one thing this can lose, and it loses the link, not the recording. |
| PURGE-8 | An entity is *removed* only when a purge record names it. A device applying a note's purge may add attachments to that list (PURGE-6), and those additions travel; what it must not do is delete rows by asking "which attachments point at this note now". An attachment moves between notes (that is what merging does), so that question has different answers on different devices, and the two would never agree again. Tag links (fixed to their note) and transcriptions (fixed to their recording) are removed with their parent, because those relationships never move. |
| PURGE-9 | The files of purged recordings are deleted by the application, not the core: `purge_note` returns the ids of the recordings that went, and each platform removes them from wherever it keeps them. A copy already uploaded to cloud storage is **not** deleted; that is a known gap (LIM). |

### 4.2 Which attachment or transcription stands for its parent

A note can hold several recordings and a recording several transcriptions.
One of each can be marked as the one that stands for the parent: the
recording played when the note is opened, and the transcription shown under
the note in the list.

| ID | Requirement |
|----|-------------|
| PRIMARY-1 | A note names the attachment that stands for it, and a recording the transcription that stands for it. Both are ordinary scalar fields, so a disagreement between two devices is merged and flagged like any other, and neither is silently overwritten. |
| PRIMARY-2 | The value is the id of something that belongs to the parent: `set_primary_attachment` refuses an attachment of another note, and `set_primary_transcription` a transcription of another recording. `""` means "nothing chosen", which every reader takes as "the first one". |
| PRIMARY-3 | "The first one" means the oldest: a note's recordings are ordered by `file_created_at`, falling back to `imported_at`, then by id. Every device therefore agrees which recording is first, and a note reads in the order its recordings were made. |

---

## 5. Head computation and merging

`recompute_head(entity_type, entity_id, field)` runs after every local write and after every sync batch for every touched field.

| ID | Requirement |
|----|-------------|
| HEAD-1 | Only **complete** versions (whose parents are all present) take part. If none is complete, all versions are treated as roots so that data is never hidden waiting for a parent that may never arrive. |
| HEAD-2 | The **authored leaves** are the complete authored versions (VER-9) with no authored descendant. With one, it is the head. With more, they are folded pairwise, smallest ids first, into merge versions until one remains; each merge re-enters the chain in id order, so the fold is canonical. Derived versions never serve as fold inputs: the head is a function of the authored versions alone, whatever order or page size they arrived in. Stale merges from earlier partial states stay in the table and are ignored. |
| HEAD-3 | The base of a merge is the lowest common ancestor of the two leaves; with no common ancestor the base is the empty value. |
| HEAD-4 | The head is written to the entity row (`apply_head_to_entity`) exactly once per recompute, which also rebuilds the display caches. Writing the row twice (for example "deleted" then "alive") would publish it again (APPLY-8). |
| HEAD-5 | Recomputation is idempotent: running it again with no new versions changes nothing, writes nothing, and bumps no sequence number. |
| HEAD-6 | If the fold of a `deleted` field yields `"1"` and the tombstone's `context` is behind the current head of another field of the entity, the delete did not see a concurrent edit: a deterministic **resurrection** version (`deleted = "0"`, `conflict_kind = "delete"`) is created and becomes the head instead. The entity stays alive with the edit. A context head that has not arrived yet means "nothing known": no resurrection until it does (its arrival touches the entity and the check runs again). |
| HEAD-7 | The row is written **before** the head is recorded. A field whose row write fails (a link whose note row, or a tag whose parent row, has not arrived yet) keeps its previous head, is listed in `field_deferred`, and is retried by `recompute_headless_fields` at the end of every later batch; one field can never abort a batch, and a head never disagrees with its row. |
| HEAD-8 | Any recompute of a non-deletion field (a local edit, a batch, a deferred retry) re-evaluates the entity's `deleted` field, so HEAD-6 gives the same answer on the device that edited as on the devices that receive the edit. |
| HEAD-9 | **Tag cycles.** Two devices moving tags under each other would form a parent cycle that every hierarchy query loops on. When the fold of `tag.parent` would close a cycle through the current rows, the tag with the largest id on that cycle gives way: it gets a derived head with no parent (`conflict_kind = "scalar"`, so the user sees the lost move) while its move stays in history. Decided identically on every device, whichever tag is recomputed first. The recursive hierarchy queries are cycle-safe regardless (`UNION`, depth limit). |

### 5.1 Merge rules by kind

`merge_leaves(kind, base, a, b)` returns the merged content and, when a human is needed, a `conflict_kind`. "Later" means the larger `(created_at, id)`.

| Kind | Both equal | Only one side changed from base | Both changed differently |
|------|-----------|--------------------------------|--------------------------|
| **Text** (MERGE-T) | that value | the changed side | diff3 line merge (diffy). Non-overlapping hunks combine silently. Overlapping hunks keep both between `<<<<<<< VERSION A` / `=======` / `>>>>>>> VERSION B`, `conflict_kind = "text"`. Labels are symmetric on every device. Adjacent-line edits count as overlapping, as in Git. |
| **Scalar** (MERGE-S) | that value | the changed side | the later value is live, `conflict_kind = "scalar"`. The other value remains in history and on the conflict record. |
| **Flags** (MERGE-F) | per flag: equal → that | per flag: the side that changed from base | a flag toggled both ways: later side wins for that flag, `conflict_kind = "flags"`. Flags never present on either side are dropped. Output is canonically ordered. |
| **Membership** (MERGE-M) | that value | n/a (two leaves means both acted) | `"1"` (attached), `conflict_kind = "membership"`. A detach never wins silently, even against a detach-then-re-attach. |
| **Deleted** (MERGE-D) | that value | n/a | `"0"` (alive), `conflict_kind = "delete"`. |

| ID | Requirement |
|----|-------------|
| MERGE-1 | Text: base and both sides identical → no conflict, no merge version. |
| MERGE-2 | Text with empty base and different sides → whole content in one conflict hunk (both values kept). |
| MERGE-3 | Merges never invent content: every line of the merged text comes from one of the two sides. |
| MERGE-4 | The merged head is what the user sees immediately, markers included ("markers immediately"). |
| MERGE-5 | Text without a trailing newline (summaries, single-line notes) merges as if it had one, so a marker is never glued to the last line; the added newline is dropped again when no side had one. |

---

## 6. Conflicts

| ID | Requirement |
|----|-------------|
| CONF-1 | Every merge or resurrection **in play** (the head or one of its ancestors) that carries a `conflict_kind` gets exactly one row in `field_conflicts`, with `id = sha256(merge_version_id)`. Every device derives the same merges from the same authored versions (VER-9), so all devices record the same open conflicts with the same ids. |
| CONF-2 | A conflict record names the base, the two sides, the merge, and the two devices (id and name from the side versions). Devices unknown at record time fall back to a short id in the UI. |
| CONF-3 | A conflict is **resolved** when its merge version is no longer the head of its field: either the user moved past it (an edit or an accept descends from it) or more versions arrived and the fold was rebuilt, in which case any remaining disagreement is recorded again on the new merge. Detected after every recompute; marks `resolved_at`. Resolved records of superseded merges are device-local history and may differ between devices. |
| CONF-4 | Resolutions are versions and therefore sync: resolving on one device resolves it everywhere after the next exchange. |
| CONF-5 | Ways to resolve: (a) edit the field (a normal save, e.g. cleaning the markers); (b) **accept** (`accept_conflict`), which writes a version identical to the merge, descending from it; (c) `resolve_conflict_with_content`, which is (a) via the conflict id. There is no keep-local / keep-remote: both sides are already in the merge. |
| CONF-6 | Resolving an already resolved conflict is a no-op that reports failure; the CLI prints an error. |
| CONF-7 | Unresolved conflict counts are grouped by kind (`text`, `scalar`, `flags`, `membership`, `delete`) plus `total`. |
| CONF-8 | A note's conflicts are: conflicts on the note's own fields, on its `note_tag` links, on its attachments, and on transcriptions of its audio files (`get_note_conflicts`). `get_note_conflict_types` maps these to user kinds `content`, `delete`, `tag`, `attachment`, `transcription`, and field names for scalar/flags. |
| CONF-9 | The note display cache lists the note's unresolved conflict kinds and is rebuilt whenever a conflict is flagged or resolved (`refresh_entity_caches`), including when only the conflict changed and the value did not. |
| CONF-10 | Delete-versus-edit produces a `delete` conflict on both devices; the entity stays alive with the edit (HEAD-6). The user who wanted the delete can delete again after seeing the edit, which then propagates without conflict. |

Approved product decisions (2026-09-06):

- Tag renamed or moved on two devices: later value live, conflict flagged, no combined names.
- Tag link removed on one device and re-added on the other: stays attached, flagged.
- Transcription preferred languages and provider API keys are synced settings; paths, models, ports are not.
- The pre-versioning conflict tables were dropped; `field_conflicts` replaces them.

---

## 7. Sync protocol

Transport: HTTP or HTTPS (self-signed certificate pinned on first use, "TOFU"). All timestamps are Unix seconds as JSON integers.

### 7.1 Endpoints (`sync_server.rs`)

| Endpoint | Purpose |
|----------|---------|
| `POST /sync/handshake` | Exchange `device_id`, `device_name`, `protocol_version` (`"1.1"`); returns the server's identity, `database_id`, `cursor` (end of its feed), `supports_audiofiles`, and for older tools `last_sync_timestamp` and `server_timestamp`. |
| `GET /sync/changes?cursor=&limit=` | **Primary feed (protocol 1.1).** Every row and authored version with `seq > cursor`, in write order, at most `limit` (max 10000) changes **and about 4 MB of JSON** (`FEED_BYTE_BUDGET`; at least one change) in total. Returns `next_cursor` (pass it back to continue), `is_complete`, `database_id`. Exact and resumable; independent of clocks. |
| `GET /sync/changes?since=&limit=` | Timestamp filter kept for tools and older clients: changes with any timestamp `>= since`, `limit` **per entity type**. `is_complete = false` when any type hit the limit. |
| `POST /sync/apply` | Apply a batch of changes from the peer. Returns `applied`, `conflicts`, `errors`. HTTP 200 all applied, 207 partial, 422 none. |
| `GET /sync/full` | The whole dataset (all entity types and authored `field_versions`) as one document, plus `database_id` and `cursor`. Kept for tools; the client no longer uses it (FLOW-4), because one document does not fit in memory for a large database. |
| `GET /sync/status` | Health and identity. |
| `GET/POST /sync/audio/:id/file` | Direct binary transfer between peers. Present but unused by the current client (kept for the future peer-transfer plugin). |

### 7.2 Change format

```json
{
  "entity_type": "field_version",
  "entity_id": "<hex id>",
  "operation": "create",
  "timestamp": 1735689600,
  "device_id": "<hex>",
  "device_name": "Phone",
  "data": { "...entity columns, or the version row..." }
}
```

| ID | Requirement |
|----|-------------|
| PROTO-1 | Entity types in the feed: `note`, `tag`, `note_tag`, `note_attachment`, `audio_file`, `transcription`, `file_storage_config`, `field_version`. The list is `ALL_SYNC_ENTITY_TYPES`; a Rust test fails if the feed omits any of them. |
| PROTO-2 | `field_version` changes are create-only. Applying one is `INSERT OR IGNORE`: a version already present is skipped, so replaying a feed is safe. Only authored and published versions are in the feed (VER-9, VER-10). |
| PROTO-3 | Entity rows in the feed carry the current denormalised values so that a reader without history (an old client, a debugging tool) still sees them. Receivers treat them as hints (VER-4); versions are the truth. |
| PROTO-3b | Every timestamp in an entity payload is followed by `<stamp>_offset` and `<stamp>_zone` (TZ-1). A receiver stores them only against the timestamp it actually took from the sender, and a peer that sends none leaves the row's zone as it was. Older peers ignore the extra keys, so the addition is compatible in both directions. |
| PROTO-4 | `operation` is `create` when `modified_at` is NULL, `update` when set, `delete` when `deleted_at` is set. Unknown operations are skipped with a warning and not counted as applied. |
| PROTO-5 | **Sequence numbers.** Every syncable table has a `seq` column stamped from one database-wide counter (`sync_sequence`) by triggers: on insert, and on update of a synced column when its value actually changed. Cache columns and `sync_received_at` never bump it. A change received from A therefore gets a new `seq` on the receiver and is relayed to B by a hub, while an echo of a device's own data (same values) is not re-published. |
| PROTO-6 | Rows received via sync must never keep `modified_at` NULL when the incoming row had a timestamp; otherwise they become invisible to the timestamp feed (see CLAUDE.md history). |
| PROTO-7 | Timestamp feed: per-entity-type limits, so no type is starved by another filling a shared limit. Cursor feed: one global limit, resumable, so nothing is ever skipped. |
| PROTO-9 | `database_id` is a random id minted with the sequence. A peer that sees a different id than it stored knows the database was replaced and restarts both cursors from zero (idempotent application makes the re-exchange safe). |
| PROTO-10 | **Bounded pages.** Both directions use the same feed function, so a push page is bounded in bytes exactly like a pull page. The server body limit (`sync.max_sync_file_size_mb`, default 100 MB) is therefore never reached by a sync page, and no page can be too large to finish within the client timeout (180 s). |
| PROTO-11 | **Bounded memory.** A page is assembled by reading the sequence in ranges of 512 numbers (`collect_changes`), stopping at the count or byte budget; the sender never holds more than one page plus one range in memory, however large the database or its transcriptions. |
| PROTO-8 | Timestamps in the feed and in rows are validated (`validate_datetime`, integer seconds). Malformed changes are rejected individually, not the whole batch. |

### 7.3 Applying a batch (`sync_apply.rs`)

| ID | Requirement |
|----|-------------|
| APPLY-1 | Order: previously failed changes are retried first; then the batch sorted by entity order **versions → notes/tags/audio files/storage config → links/attachments/transcriptions**, then by timestamp. |
| APPLY-2 | Each change is independent. A failure is recorded in `sync_failures` (with the peer and payload) and reported; the rest of the batch continues. Unknown entity types fail and are not queued. |
| APPLY-3 | Queued failures are retried at the start of every later batch from any peer; success removes them. |
| APPLY-4 | After the batch, `recompute_heads` runs once per touched field (non-deleted fields first, then `deleted`), then `recompute_headless_fields` gives a head to anything that was waiting for a row that arrived in this batch (HEAD-7). |
| APPLY-5 | The reported `conflicts` count is the number of `field_conflicts` rows created during the batch, wherever they were created. |
| APPLY-6 | Applying the same batch twice yields the same heads and creates no new versions or conflicts. |
| APPLY-7 | The peer's `sync_peers` row is created if needed before anything is queued against it. |
| APPLY-8 | Applying a batch that contains nothing new writes nothing and bumps no sequence number: all row updates use `NULLIF(..., 0)` / `MAX` forms that leave equal values untouched, so echoes never ping-pong between peers. |
| APPLY-9 | A batch is one write transaction (`BEGIN IMMEDIATE` ... `COMMIT`): thousands of statements cost one fsync. A statement that fails rolls back only itself (APPLY-2 still holds); an error that escapes the batch rolls the whole page back, and the sender, which has not advanced its cursor, sends it again. Other connections (the GUI) wait up to 10 s (`busy_timeout`) instead of failing with "database is locked". |
| APPLY-10 | The scan for headless fields runs only after a batch that had failures, deferrals or retries; otherwise only the small `field_deferred` list is retried. Large databases are not rescanned on every page. |

### 7.4 Client flow (`sync_client.rs`)

| ID | Requirement |
|----|-------------|
| FLOW-1 | `sync_with_peer`: handshake → compare `database_id` with the stored one (PROTO-9) → note `local_end = current_seq()` → **pull** pages `cursor=<stored>` until `is_complete`, applying each page and saving `next_cursor` after it → **push** pages of our changes with `last_sent_seq < seq <= local_end` until complete, saving the high-water mark after each accepted page → record peer sync time. A sync moves database changes only; no file moves in it. |
| FLOW-2 | A sync never uploads, downloads, sends or fetches a file. Each of those is its own action the user starts (FILE-2). |
| FLOW-3 | Pull-only and push-only variants exist and follow the same rules. |
| FLOW-4 | `initial_sync` resets both cursors to zero and pages the peer's whole feed from the beginning, then pushes everything from zero; memory use is bounded by one page whatever the size of the database, and an interrupted initial sync resumes like any other. |
| FLOW-5 | A sync interrupted between pages resumes from the last saved cursor; nothing is fetched or sent twice except the page in flight, which is idempotent. |
| FLOW-6 | Only what existed before the pull (`seq <= local_end`) is pushed; the peer's own data that just arrived is not sent straight back. (Relay to *other* peers still happens through their own cursors.) |
| FLOW-7 | A peer that does not return `next_cursor` (protocol 1.0) makes the sync fail with a clear error; both sides must be 1.1 or newer. |
| FLOW-8 | Server-side retries queued by the peer ("Server queued for retry: ...") are surfaced as warnings on the pushing client. |
| FLOW-9 | Handshake, pull, or push failures make the sync fail with an error; partial progress that did apply is kept (idempotency makes the retry safe). |
| FLOW-10 | **Draining retry queues.** After the last pull page, if this device has changes queued for retry, an empty batch is applied locally so they get another chance now. After the last push page, if the peer queued anything, an empty batch is posted so a passive server retries at once instead of waiting for the next visitor. |

---

## 8. Audio binaries (`file_storage.rs`, `file_storage_s3.rs`)

| ID | Requirement |
|----|-------------|
| FILE-1 | Cloud storage configuration (provider, bucket, region/endpoint, key, secret, prefix) lives in `file_storage_config` and syncs to every device. The secret is distributed by sync (accepted risk; see IMP-9). |
| FILE-2 | **Upload** is an action of its own (`cli storage upload-pending`, the Upload button on the phone): the device uploads each audio file it imported (`storage_provider IS NULL AND deleted_at IS NULL` and the file is on this device). Records without a local file are skipped silently: they belong to another device. A failed upload is reported and tried again at the next upload. |
| FILE-3 | After a successful upload the record gets `storage_provider`, `storage_key`, `storage_uploaded_at`; these sync as part of the `audio_file` row. |
| FILE-4 | Other devices download a binary only when the user asks: CLI `audiofile-download` / `note-audiofiles-download`, TUI `d` / Download button, GUI Download button, Android Download button. |
| FILE-5 | Desktop/server may set `sync.mirror_audio_files = true` (local config, never synced, never Android) to download every missing binary after each sync. |
| FILE-6 | Object and file name is `{audio_id}.{ext}`, `ext` from `audio_file_extension()`: lowercase, last dot wins, `bin` when absent. Every platform uses the shared helper. |
| FILE-7 | Downloads write to `<file>.part`, verify the size against the object, then rename. A crash never leaves a truncated file that looks present. |
| FILE-8 | In a batch download, the first remote failure stops the batch (`deferred` count) so the rest is retried next time instead of timing out one by one. |
| FILE-9 | Every incoming `audio_file` row is applied (DM-4): the cloud location (`storage_provider`, `storage_key`, `storage_uploaded_at`) is set once by the uploader, never erased by a row that has none (an echo, or a peer that edited the summary before receiving the upload), and only replaced by a newer row that has one (a re-upload). Skipping older rows, as before, left such a peer without the key and unable to download until the uploader changed the record again. |
| FILE-10 | "Cloud storage not configured" is a silent no-op for automatic paths and a clear error for on-demand ones. |
| FILE-12 | **Send** and **fetch** (the terms table) move a recording's bytes between two instances of the account, both directions streamed and never held in memory: `GET /sync/audio/:id/file` streams the file to a fetching peer, `POST /sync/audio/:id/file` streams a sent file into `<file>.part`. Before sending, `POST /sync/audio/missing` with the ids the sender holds answers with the ids the receiver lacks and how many bytes of each it already holds, so a thousand recordings cost one round trip. **Deliver** is sync then send; **exchange** is sync then send and fetch. A sync alone moves no file. |
| FILE-13 | A transfer **resumes**: a fetch continues with `Range: bytes=N-` from the part's length, a send with `Content-Range: bytes N-M/total` from the bytes the missing list reported. The sender announces the whole file's hex SHA-256 in `X-File-SHA256`; the receiver verifies the assembled part against it before the rename, and a part that does not agree is deleted so the next attempt starts clean. |
| FILE-14 | Timeouts are explicit: three seconds to connect on this machine or a private address, ten elsewhere; thirty seconds for a read to make progress; no overall timeout on a file. A transfer is tried three times with waits of one, two and four seconds; a refusal (4xx) is not retried; the metadata routes do not retry. The receiver refuses a file that would leave less than 64 MB free, naming both numbers. |
| FILE-11 | The UI distinguishes "missing, in cloud" (offers Download) from "missing, not uploaded by its device yet" (no button). |
| FILE-12 | rust-s3 ≥ 0.37 with webpki roots: TLS works on Android, which has no OS certificate directory. |

---

## 9. Synced settings

| ID | Requirement |
|----|-------------|
| SET-1 | `synced_settings` is a versioned Scalar store keyed by setting name. Concurrent changes: later wins, flagged (MERGE-S). |
| SET-2 | Synced keys: `transcription.preferred_languages` (JSON list of ISO 639-1 codes) and `transcription.providers.<provider>.api_key`. |
| SET-3 | On startup of every desktop interface (`reconcile_transcription_settings`): a synced value overrides the local `config.json` entry; a local value seeds the store only when the store has none. Paths, models, ports, colours never sync. |
| SET-4 | `cli settings set <key> <value>` writes both the store and the local file. `settings list` masks API keys. |
| SET-5 | Android reads and writes settings through `get_setting` / `set_setting` in the UniFFI API. |

---

## 10. User-facing behaviour

| ID | Requirement |
|----|-------------|
| UI-1 | A note with unresolved conflicts shows a banner: kinds, the devices involved, and the two ways to resolve. GUI (Qt), TUI (Textual) and Android show the banner with an **Accept merge** button. |
| UI-2 | Accept is refused while the note is being edited (save or cancel first). |
| UI-3 | Saving a note resolves its content conflict; the banner disappears after reload. |
| UI-4 | CLI: `sync status` shows counts by kind; `sync conflicts [--note ID] [--details] [--all]` lists conflicts (`--details` prints base, both sides with device names, and the merged value); `sync resolve <id>` accepts, `--content-file` / `--content` replaces; `note-show` warns and lists the note's conflicts. Ids may be given as unique prefixes. |
| UI-5 | The web API reports `has_conflicts` and `conflict_types` on a note. |
| UI-6 | Markers are plain text in the note; nothing strips or hides them. |
| UI-7 | **Side-by-side resolution** for text conflicts: GUI (`Resolve…` dialog), TUI (`Resolve…` modal), Android (`Resolve…` dialog) show version A, version B and the common ancestor read-only next to an editable result that starts from the merged text; "Start from A / B / merged" buttons; Save writes the field once (`resolve_conflict_with_content`). The button appears only when the note itself has a text conflict; other kinds use Accept or an edit. |
| UI-8 | **Version history**: GUI (`History…`), TUI (`History`), Android (`History`) list every version of the note's content, oldest first, with time, device and kind, and let the user restore any of them. CLI: `note-history <id> [--show <version>]`, `note-restore <id> <version>`. A restore is an ordinary edit: a new version, synced like any other. |

---

## 11. Invariants for property-based tests

These should hold for any sequence of operations on any number of devices with any exchange order.

| ID | Invariant |
|----|-----------|
| INV-1 | **Convergence.** After every pair of devices has exchanged in both directions until no change flows, all devices have identical `field_heads`, identical entity rows for versioned columns, and identical **open** `field_conflicts` (ids and kinds). |
| INV-2 | **No loss.** Every value ever passed to `set_field` on any device exists as a version on every device. |
| INV-3 | **Reachability.** For a Text conflict, every line a side added or changed relative to the base is present in the merged text; for other kinds the two side versions are on the conflict record. |
| INV-4 | **Idempotence.** Re-applying any batch, or replaying the full dataset, changes nothing. |
| INV-5 | **Determinism.** Two devices that hold the same set of versions compute the same head ids and the same merge/conflict ids without communicating. |
| INV-6 | **Monotone resolution.** A resolved conflict never becomes unresolved. |
| INV-7 | **Delete safety.** An entity whose `deleted` head is `"1"` has no version on any other field created after the tombstone's context (otherwise HEAD-6 resurrects it). |
| INV-8 | **Feed completeness.** Every version and every row changed on a device appears in that device's feed for a `since` at or before its `created_at`/`modified_at`/`sync_received_at`. |
| INV-9 | **Binary integrity.** A file present in `audiofile_directory` without a `.part` suffix has the size recorded in cloud storage. |
| INV-10 | **Forest.** Tag parents form a forest on every device at every quiescent point. |

---

## 12. Test coverage map

| Requirement | Tests |
|-------------|-------|
| VER-1..VER-8, HEAD-*, MERGE-* | `voicecore/src/versions.rs` unit tests; `voicecore/src/sync_server.rs` `test_versions_*` |
| CONF-1..CONF-10 | `tests/unit/test_conflicts.py`, `tests/unit/test_cache_rebuild.py::TestCacheRebuildOnConflictResolution`, `tests/integration/test_sync_integration.py::TestConflictResolution`, `tests/sync/test_sync_conflicts.py` (real servers, device names) |
| PROTO-1 | `sync_server.rs::test_get_changes_since_returns_all_entity_types` |
| PROTO-4, APPLY-2, APPLY-3 | `tests/sync/test_sync_validation.py`, `sync_server.rs::test_versions_failed_change_is_queued_and_retried`, `test_partial_batch_failure_continues_processing` |
| PROTO-7 | `tests/sync/test_sync_pagination.py` |
| APPLY-5, VER-4 | `tests/sync/test_sync_server.py::TestSyncApply` (row-only updates create conflicts) |
| VER-7 | `sync_server.rs::test_versions_first_edit_of_a_field_is_stamped_with_its_time`, `tests/sync/test_sync_server.py::TestSyncChanges::test_changes_include_a_deleted_note` |
| FILE-2..FILE-11 | `tests/unit/test_cloud_storage.py`, `tests/cli/test_cli_storage.py`, `tests/gui/test_note_pane_media.py`, `tests/tui/test_tui_media.py`, `tests/sync/test_audiofile_*.py`, `file_storage.rs` tests |
| SET-1..SET-4 | `tests/unit/test_synced_settings.py`, `tests/unit/test_conflicts.py::TestSettingsSync`, `tests/sync/test_sync_cli.py::TestSettingsCLI` |
| UI-1..UI-3 | `tests/gui/test_note_pane_conflicts.py`, `tests/tui/test_tui_conflicts.py` |
| UI-4 | `tests/sync/test_sync_cli.py::TestSyncConflictsCLI`, `TestSyncResolveCLI` |
| PROTO-10, APPLY-9 | `convergence_tests.rs`: `feed_pages_are_bounded_in_bytes_and_lose_nothing`, `a_batch_is_one_transaction_and_a_bad_change_does_not_abort_it` |
| PRIMARY-1..PRIMARY-3 | `sync_server.rs`: `the_attachment_that_stands_for_a_note_is_remembered_and_travels`, `a_note_can_only_point_at_its_own_attachment`, `the_transcription_that_stands_for_a_recording_travels` |
| PURGE-1..PURGE-9 | `sync_server.rs`: `a_deleted_note_waits_in_the_trash_and_can_be_recovered`, `a_recovery_travels_to_the_other_device`, `purging_a_note_removes_it_and_what_belonged_only_to_it`, `purging_keeps_a_recording_another_note_still_holds`, `a_purge_travels_and_the_note_does_not_come_back`, `a_purged_note_is_refused_even_when_it_arrives_first`; `convergence_tests.rs` (purge is one of the random operations, and must take effect in every run); `tests/unit/test_trash.py`, `tests/cli/test_cli_trash.py`, `tests/web/test_api_trash.py` |
| INV-1..INV-5, INV-10, PROTO-5, PROTO-9, APPLY-6, APPLY-8, FLOW-5 | `voicecore/src/convergence_tests.rs`: random edits, deletes, undeletes, purges (emptying a note out of the trash), note merges, tag renames/moves/deletes, link changes, attachments, transcriptions (text and flags), audio summaries and uploads, settings and accepts on 2 to 4 in-memory devices, exchanged through the cursor feed in random order with pages of 1 to 1000, duplicate deliveries, a hub topology, and a device replaced by an empty database, then quiesced. Asserts identical snapshots, no value lost (except what a purge took, which the databases' own purge records define), conflict sides reachable, no tag cycles, a further round moving nothing, and that every generated operation really took effect at least once. `cursor_feed_is_exact_and_resumable`, `cache_rebuilds_and_echoes_do_not_republish`, `concurrent_tag_moves_never_form_a_cycle`. Set `FLEET_DEBUG=1 FLEET_SEED=<n>` (and `FLEET_TOPOLOGY=hub`, `FLEET_DEVICES`, `FLEET_PAGE`, `FLEET_DUP`, `FLEET_STEPS`) with `cargo test debug_single_seed -- --nocapture` to trace one seed. |
| VER-9, VER-10, VER-11, HEAD-2, HEAD-7, HEAD-8, HEAD-9, MERGE-5, DM-4 | Same fleet tests (each rule fixes a defect the fleet found: version explosion, dropped edits on top of unsynced merges, batches aborted by a link arriving before its note, rows re-published on every echo, resurrection ids that differed by device, heads recorded before a failed row write, markers glued to the last line, tag cycles, a hub not relaying published merges). |
| FILE-9, DM-4 | `sync_server.rs`: `test_files_storage_key_reaches_peer_that_edited_summary_first`, `test_files_older_audio_row_never_erases_storage_key`, `test_older_transcription_row_does_not_overwrite_newer_service_response`, `test_transcription_state_toggle_keeps_service_metadata`, `test_older_attachment_row_does_not_move_attachment_back` |
| UI-7, UI-8 | `tests/gui/test_note_pane_conflicts.py::TestNotePaneHistoryAndResolve`, `tests/tui/test_tui_conflicts.py::TestTuiHistoryAndResolve`, `tests/sync/test_sync_cli.py::TestNoteHistoryCLI` |
| PROTO-1..PROTO-9 (Rust server end to end) | `tests/sync/test_sync_server.py` (`TestSyncHandshake`, `TestSyncApply` incl. row-without-version ignored), `tests/sync/test_sync_conflicts.py`, `tests/sync/test_sync_partial_failures.py` |
| ACCT-1..ACCT-5 | `database.rs::tests::account_identity` (a fresh database takes the account, a used one refuses another, a move keeps the notes and forgets the peers); `sync_server.rs::tests::account_identity` (same account let in, another refused with its code, none refused, and `a_mismatched_pair_exchanges_nothing` over a real socket); `tests/sync/test_sync_accounts.py` |
| LISTEN-1..2 | `sync_server.rs::tests::listener` (the card says listening with the URL, stop on request, start again; the URLs name private addresses and the host, never loopback) |
| FILE-12..14 | `transfer.rs` tests (parts, completion by length and hash, ranges, free space); `sync_server.rs::tests::files_between_instances` (exchange both ways and a second run moving nothing; deliver sends without fetching; a transfer continuing from a part in both directions with only the missing bytes on the wire; a corrupt part discarded and refetched; the missing list in one round trip) |
| PAIR-1..4 | `pairing.rs` tests (round trip of the setup text, what a bad one says, the compact fingerprint, a token spent once / five guesses / expiry, a device with notes refusing, admission by token); `sync_server.rs::tests::pairing` (a claim over TLS pinned from the text, a spent token refused, sync afterwards both ways); `tests/sync/test_sync_pairing.py` (`account show-code` and `account join` between two nodes) |
| CARD-1..2, AUTH-1..7 | `auth.rs` tests (key shape, constant-time compare, the order of checks, a revocation that cannot be undone, the own card made once); `sync_server.rs::tests::authentication` (the health check open and every other route refused without a key; a paired device syncs, an unpaired and a revoked one are refused; a wrong key and the growing delay; a handshake naming another device; TLS with the pin, a wrong pin, no pin; plain http refused off this machine, on both sides); `tests/sync/test_sync_accounts.py` |
| SNAP-1..SNAP-4 | `database.rs::tests::snapshots` (five kept, a restore brings a note back and is itself undoable, a bad name refused); `tests/sync/test_sync_accounts.py::TestSnapshots` (a sync leaves a snapshot on both sides) |

---

## 13. Known limitations and proposed improvements

### Limitations of the current implementation

| ID | Limitation |
|----|------------|
| LIM-1 | One device identity per process (ID-3). In-process multi-database tests cannot attribute versions to different devices; only subprocess/server tests can. |
| LIM-2 | (Resolved by the cursor feed, PROTO-5/FLOW-1.) The timestamp feed remains for tools and is still clock-dependent; the Rust client no longer uses it. |
| LIM-3 | (Resolved: pages are resumable and nothing is skipped.) Stale derived merges from partial pages remain in `field_versions` (ignored by the fold, never synced); they cost space until a compaction exists (IMP-7). |
| LIM-4 | Unversioned metadata (DM-4) and `file_storage_config` (DM-5) use newest-wins-per-column rules. These fields are machine-written, but a user-editable field added later must be registered as a versioned field, not left to this rule. |
| LIM-5 | Scalar conflicts (tag name, tag parent, settings) keep only one value live. The other value is visible in `sync conflicts --details` but nowhere in the normal UI. |
| LIM-6 | Conflict markers live inside the note text. Search, transcription display and any exporter see them. |
| LIM-7 | History grows without bound: every version of every field is kept forever, including large transcriptions. Recomputing a head loads the whole history of that field, so a field edited tens of thousands of times slows every batch that touches it. |
| LIM-13 | Scalar and flag conflicts, and the per-column metadata rules, pick the later `created_at`/`modified_at`. A device with a badly wrong clock wins those decisions. Text merges and convergence do not depend on clocks. |
| LIM-14 | A change that can never be applied (a validation error in a peer's payload) stays in `sync_failures` and is retried at the start of every batch, forever. Cheap, and it never blocks, but there is no cap and no user-facing list of parked changes. |
| LIM-8 | Download integrity is size-only (FILE-7). A corrupted object of the right size is accepted. |
| LIM-9 | Cloud credentials and provider API keys are stored in plain text in every database and travel through sync (FILE-1, SET-2). |
| LIM-10 | The peer-to-peer audio endpoints exist but have no client; the related Python tests are skipped. |
| LIM-11 | (Resolved: history and restore exist on every interface, UI-8.) Transcription history has no interface yet; the API (`get_field_history("transcription", id, "content")`) is there. |
| LIM-12 | Row-only updates from a pre-1.1 peer are ignored (VER-4). Such peers no longer exist on the test systems; the protocol version in the handshake makes the mismatch visible. |

### Suggested improvements

| ID | Suggestion | Why |
|----|------------|-----|
| IMP-1 | *(Done)* Property-based convergence tests in `convergence_tests.rs`. Extend with attachments, transcriptions and audio summaries, and with a simulated crash between pages. | The fleet tests found five real defects on their first runs. |
| IMP-2 | *(Done)* Write-order sequence numbers and cursors (PROTO-5, PROTO-9). | |
| IMP-3 | *(Done)* Resumable paging, cursor saved after every page (FLOW-1, FLOW-5). | |
| IMP-4 | *(Done for text)* Side-by-side resolution (UI-7). Still open: choosing per hunk, and offering the other value for scalar conflicts (tag name, tag parent, settings) in the UI. | LIM-5. |
| IMP-5 | Strip conflict markers from search indexes and transcription previews, or flag notes with markers in the list view. | LIM-6. |
| IMP-6 | *(Done for notes)* History and restore (UI-8). Still open: the same for transcriptions and tag names. | LIM-11. |
| IMP-7 | History compaction: first, delete stale derived merges (not the head, not an ancestor of the head, not published) — safe at any time because no peer has them. Then a policy for authored versions: keep every version for N days, then roots, published merges, conflict sides and one version per day; store big texts once by content hash. Authored compaction must be deterministic or done only on data older than every peer's cursor. | LIM-7, LIM-3. |
| IMP-8 | Store a content hash (SHA-256) on `audio_file` at import, put it in the object metadata on upload, verify it on download. | LIM-8. |
| IMP-9 | Keep secrets out of the synced tables: distribute S3 credentials and API keys through a separately encrypted setting (a shared passphrase entered once per device), or through the OS keyring on desktop and Android Keystore. | LIM-9. |
| IMP-10 | *(Done)* Protocol 1.1; row values are hints once a field has history (VER-4); a 1.0 peer fails the sync with a clear message (FLOW-7). | |
| IMP-11 | Sync log table (per peer: time, pulled, pushed, conflicts, warnings) surfaced in `sync status` and the Android sync screen. | Offline-for-hours devices need a way to see what happened last time. |
| IMP-12 | Background upload/download queue on Android with retry and Wi-Fi-only option. | Today an upload happens only when the user presses Upload. |
| IMP-13 | Make the tag parent a Membership-like field with cycle detection at merge time (a tag moved under its own descendant on another device). | A cross-device move can currently produce a cycle that the UI must guard against. |
| IMP-14 | Peer-transfer plugin using the existing `/sync/audio/:id/file` endpoints, selected per installation, so devices on one LAN can exchange binaries without cloud storage. | Planned second plugin (LIM-10). |
| IMP-15 | Register `audio_file.filename` and `duration_seconds` as versioned Scalars if they ever become user-editable. | Prevents newest-wins from creeping into user data (LIM-4). |

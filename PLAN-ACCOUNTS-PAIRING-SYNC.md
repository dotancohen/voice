# Plan: accounts, pairing, LAN sync, file transfer between instances, and S3 by wizard

Status: **agreed; implementation started 2026-09-12.** Written 2026-09-12; revised the same day after a
review against the code. Stages are marked done in the Order of work as they finish.

Scope: `VoiceCore` (protocol, storage, accounts), `Voice` (desktop and server),
`VoiceAndroid` (the phone). `VoiceTranscription` is untouched. The core is
checked out three times (`VoiceCore/`, `Voice/submodules/voicecore`,
`VoiceAndroid/submodules/voicecore`); a change is made in `VoiceCore/` and copied
to both, then the Python module and the Android library are rebuilt together
(`TECHNICAL-DECISIONS.md` 7.2).

**Everything starts afresh.** There is no existing desktop database, no deployed
server data and no phone data to carry forward. Nothing in this plan migrates
anything.

**The Android interface is about to be replaced** by a non-Compose toolkit the
owner uses elsewhere. Every Android screen in this plan is therefore kept thin:
the logic sits in view models and plain classes with no toolkit import, so the
screens can be redrawn without touching it. Hebrew strings and right-to-left
layout are deferred to that replacement.

---

## Context

On 2026-09-12 a week of recordings was destroyed: an instrumented test run
replaced the Android application, Android deleted its private and external data
with it, and nothing had left the phone. The sync peer was unreachable, no bucket
was configured, and configuring one meant copying five values out of three web
consoles.

The lesson is that **getting a recording into a second place must be easy enough
that it always happens**, and that two people sharing one server must not be
able to merge into each other's notes by accident.

The outcome: one wizard makes the bucket, one QR code pairs a phone, the two
devices find each other on the LAN by themselves, files move directly between
them, one server hosts several accounts, and an account identity makes a
wrong-address sync impossible rather than merely unlikely.

How it will be used: the owner syncs and moves files mostly on the LAN, with
occasional use of the server from both desktop and phone. A second user syncs
her phone with the same server almost exclusively, her desktop occasionally, and
never uses the LAN.

---

## Terms

Every word below has one meaning, in code, tests, documentation and user
interface (`TECHNICAL-DECISIONS.md` 4.4). The current code uses "download" and
"upload" for both the bucket and a peer, and Android's `download_audio_file`
means the bucket while Python's means a peer. Stage 0 renames them.

| Term | Meaning |
|---|---|
| **Account** | One body of notes and recordings, with one 32-character hex id. What a person owns |
| **Device** | One installation: a desktop, a phone, a server. Has a device id. A desktop with two accounts is one device |
| **Instance** | A running Voice program on a device, serving one or more accounts |
| **Peer** | Another instance this instance can reach over HTTPS |
| **Bucket** | The S3 location of an account's recordings |
| **Sync** | Exchange database changes with a peer, both directions. Nothing else moves |
| **Upload** / **Download** | Copy recording files from this instance to the bucket / from the bucket to this instance |
| **Send** / **Fetch** | Copy recording files from this instance to a peer / from a peer to this instance |
| **Deliver** | Sync, then send: the database both ways, the files one way, to a peer |
| **Exchange** | Sync, then send and fetch: the database and the files both ways, with a peer |
| **Listen** | Accept connections from peers on a port. An instance that listens is a listener |
| **Host** | Serve an account that is not this device's own (a server hosts accounts) |
| **Pair** | Give a fresh device an account's id, a key of its own and one peer, by QR or by pasted setup text |

Buttons and commands use exactly these verbs: "Sync", "Upload", "Send",
"Deliver", "Exchange". The phrase "sync now" today means "sync, then upload";
after this plan it means sync only, and "Upload" is its own action.

---

## Decisions taken by the owner

1. Every operation in the terms table happens **on a button press only, never
   automatically**. The phone therefore needs a listener, running only while
   asked.
2. **The QR code carries only what pairing needs, and no lasting secret**: the
   account id, a **pairing token** that is single-use and expires in ten
   minutes, and the one instance that generated the code (its device id, name,
   addresses, port and certificate fingerprint). The reading device presents
   the token and receives a key of its own (Stage 9). A photograph of the
   screen is worthless after the first scan or after ten minutes. No bucket
   credentials and no other peers: the storage configuration is already a
   synced entity and arrives with the first sync; the other devices of the
   account arrive the same way (Stage 5). **Any device that holds an account
   can show its code**, phone or desktop, and any device can read one (camera
   or pasted text).
3. **One S3 key with `s3:CreateBucket`, kept.** The wizard walks the user through
   creating it in the Amazon console as well; nobody is expected to read a manual.
4. **Discovery uses whatever finds the other machine on the LAN**: mDNS first,
   the remembered address second, a typed address last.
5. **Accounts live in `~/.config/voice/<account-id>/`**, indexed by
   `~/.config/voice/accounts.db`. The `-d` flag is removed; `-a` selects an
   account. `$VOICE_CONFIG_DIR` remains the only override of the root, for
   tests and for the deployed server. There is nothing to preserve.
6. **One key per device, per account.** Every device holds its own key, issued
   at pairing. A lost phone is revoked alone; nothing else is paired again.
7. A hosted account is **added by hand** on the server; an unknown account is
   refused. The REST endpoint for a future sign-up website is designed, not built.
8. **Android remains single-account.** A phone has no `accounts.db`; its one
   database carries the account id.
9. **Accounts never merge.** Two databases with different account ids refuse
   each other, always. The only time a device takes on an account id is at
   **pairing**, when it also receives its device key, and only if it holds no
   notes (tags and a storage configuration are allowed). Pairing therefore always flows from the device that holds the
   account to the empty one: the holder shows the code, the empty device reads
   it. A device that already holds notes and reads a code for another account
   is refused before anything goes over the network. Forcing two accounts
   together exists, is deliberate and difficult, and lives nowhere a user
   would find it by accident (Stage 1).
10. A LAN desktop **serves every account it holds**, whichever one its GUI has
    open. A server opens nothing until a connection names an account.
11. Both the desktop and the phone show their own address, port, device id and
    fingerprint **in the sync dialogue and in About** (desktop) and **in the sync
    screen and a Settings entry** (phone).

---

## What already exists, verified against the code on 2026-09-12

| Thing | Where | State |
|---|---|---|
| File transfer between instances over HTTPS | `sync_client.rs:1173` `download_audio_file`, `:1271` `upload_audio_file`; routes `/sync/audio/:id/file` at `sync_server.rs:799`; orchestration `sync_audio_files_after_pull` (1334), `download_missing_audio_files` (1392), `sync_audio_files_after_push` (1449) | Written. PyO3 exposes the two transfer functions (`voice-python/src/lib.rs:1667`, `:1688`); UniFFI does not. **Nothing calls the three orchestration functions.** All four transfer paths buffer the whole file in memory |
| HTTPS with trust-on-first-use | `sync_client.rs:193` sets `danger_accept_invalid_certs(true)` for every peer; `config.rs:77` pins `certificate_fingerprint` per peer | Working, but certificate verification is off for every peer, pinned or not. Stage 3 fixes that |
| Certificate generation in Rust | `tls.rs` (rcgen); fingerprints are `SHA256:aa:bb:…`, lowercase, the same format `Voice/src/core/tls.py` produces | Working; the two implementations agree |
| A peer list, already multi-peer | `Config::peers` (config.rs:458), `add_peer` (463), `remove_peer` (499); PyO3 `get_peers`, `add_peer`, `remove_peer`, `sync_with_peer` | Working. Android's `configure_sync` (android.rs:290) writes one peer and `get_sync_config` (318) reads `peers[0]`; Kotlin keeps `server_url` and `server_peer_id` in SharedPreferences (`SettingsViewModel.kt:21`) |
| Per-database identity and reset detection | `sync_meta.database_id` written in `migrate_add_sync_sequence` (database.rs:6929, insert at 6950); `sync_peers.peer_database_id`; handshake `database_id` | Working. A *differing* `database_id` means "re-exchange everything", the opposite of an account check. It stays and is not reused |
| Handshake types | `sync_server.rs:47` and `:54`; a second copy in `sync_client.rs:68` and `:76` | Two definitions of one protocol message. Stage 0 merges them |
| Server state | `AppState` at `sync_server.rs:37`: one database, one config | Single-account |
| Server start | `start_sync_server` in `voice-python/src/lib.rs:1960` opens one config and one database from one directory; `cli sync serve` calls it. The GUI and TUI never start a listener | Single-account, CLI only |
| Authentication | None. The server reads no header; the client sends `X-Device-ID` and `X-Device-Name` only | Anyone who reaches the port reads and writes everything |
| Body limit | `DefaultBodyLimit` at `sync_server.rs:802` applies `max_sync_file_size_mb` to every route, including the file upload | Caps LAN transfers, which decision 3 of Stage 4 does not want |
| Cloud storage | `file_storage_s3.rs`, `file_storage.rs`, `Voice/src/core/cloud_storage.py`, `cli storage configure-s3` (cli.py:2331); `file_storage_config` is a synced entity (SYNC_SPECIFICATION DM-5) | Works for Amazon; DigitalOcean and Backblaze untested |
| Config directory resolution | `Config::new(None)` → `dirs::config_dir()/voice` (config.rs:296); `-d` and `$VOICE_CONFIG_DIR` in `src/main.py:191`, `:276`; the banner at `:286` | The seam the account layer replaces |
| Android foreground services | Manifest already declares `FOREGROUND_SERVICE_DATA_SYNC` and a `dataSync` service | Stage 6 adds one more service, no new permission for it |
| Android build features | `build-app.sh` builds with default features plus `uniffi`; default includes `server` (axum) | The listener costs no new crate |
| Test isolation | `uitest` build type with `.uitest` suffix (`app/build.gradle.kts:56`); `VoiceAndroid/tools/voice-phone-backup`; `transcription_flags_contract.json` in both trees | In place |

### Dead and duplicate code: removed in Stage 0 on 2026-09-13

Everything in this table is gone, and the audit found more (below the table).

| What | Where | Why it is dead |
|---|---|---|
| Flask sync server | `Voice/src/core/sync.py` (`create_sync_blueprint` and everything it needs) | Not registered by `web.py` or anything else. A second copy of the protocol with no authentication |
| Python TLS | `Voice/src/core/tls.py` | Imported only by tests; the Flask server was its only user |
| Python merge | `Voice/src/core/merge.py` | Imported only by tests; `merge.rs` is the implementation |
| PyO3 `apply_sync_changes` | `voice-python/src/lib.rs` | Its only caller was `sync.py` |
| `SyncClient::apply_changes` | `sync_client.rs:775` | Never called (cargo warning) |
| `parse_sqlite_datetime`, `get_nonsynced_tag_id`, `build_tag_path` | `database.rs:277`, `:3052` | Never called (cargo warnings) |
| Unused imports and variables | `database.rs:10`, `:12`, `:6082`; `tls.rs:136`; `android.rs:9`, `:228`; `sync_server.rs:395` | cargo warnings |
| Handshake structs, twice | `sync_server.rs:47-65` and `sync_client.rs:68-110` | One protocol message, two definitions |
| `ConflictVersions`, `_device_label` | `Voice/src/core/conflicts.py` | Unreferenced |

Also removed by the audit: the Python audio-file "trash" (`soft_delete`,
`restore_from_trash`, `is_in_trash`, `file_exists`, the `_trash` directory),
`Config.get_device_id`, `load_config`, `save_config`, `current_timestamp`,
`set_minimum_minutes`, `waveform_to_ascii`, `NoteTag`, `note_has_conflicts`,
two transcription-service queries, four Qt widget methods, two TUI methods, the
tool `tools/test_android_sync.py` (it started the Flask server), the client's
full-sync conversion and clock-skew helpers, and four unreferenced Kotlin
functions. Decisions taken while removing: the PyO3 `apply_sync_changes`
binding **stays**, as the seam through which the desktop tests drive the core's
apply logic (`tests/sync_support.py`); `Config.config_file` stays, a one-line
path accessor the tests use; the `sync.mirror_audio_files` flag stays until
Stage 4 defines Download, because after this stage a sync no longer calls it;
and the Android build flags in `app/build.gradle.kts` and `DEVELOPMENT.md` were
made to match `build-app.sh` (default features plus `uniffi`), which is the
build that produces the library on the phone.

The tests of a removed module go with it (`tests/unit/test_sync.py`,
`test_tls.py`, `test_merge.py`, `tests/sync/test_sync_*.py` that import
`src.core.sync`). They test code the product does not run. Any test among them
that exercises the *protocol* rather than the Python implementation is rewritten
against the Rust server before the module goes, so no coverage of the product is
lost.

---

## Stage 0 — Remove dead and duplicate code

Before anything is added, in every subproject:

1. Rust: `cargo check --all-features` must report no warnings; remove what it
   names. Python: every function and class in `src/` is referenced from `src/`
   or is deleted; a module referenced only from tests is deleted with its tests
   (see above). Kotlin: the same, using the IDE's inspection. The audit result
   is a list in the commit message, reviewed before deletion.
2. Merge the handshake types into one module used by client and server.
3. Rename to the terms table: `download_audio_file` / `upload_audio_file` (peer)
   become `fetch_audio_file` / `send_audio_file` in the core, the PyO3 binding
   and the server handlers; `sync_audio_files_after_pull` becomes
   `fetch_audio_files_after_sync`, `sync_audio_files_after_push` becomes
   `send_audio_files_after_sync`. Android's cloud `download_audio_file` keeps its
   name, because download means the bucket. `sync_now`, which today syncs and
   uploads, is split into `sync` and `upload`.

## Stage 1 — Account identity

`database_id` already exists and must not be reused: a *differing* one means
"re-exchange everything", which is exactly the accidental merge to be prevented.

- `sync_meta.account_id`, written when the database is created, beside the
  `database_id` insert in `migrate_add_sync_sequence` (`database.rs:6950`).
  `Database::new` takes an optional account id so the account-creation command
  can name the directory before the database exists. `Database::account_id()`
  reads it; this is how a phone, which has no index, knows its account.
- `sync_peers.peer_account_id`, added by a migration in the same style.
- The handshake request **and** response carry `account_id`, so each side can
  refuse the other.
- Comparison, in `sync_client.rs::peer_cursors` and in the server's handshake:
  - equal → proceed;
  - different → **refuse, exchange nothing**, naming both accounts;
  - a known peer whose account id has **changed** → refuse. This is the
    router-reshuffle case the whole stage exists for.
- **Adoption happens only at pairing** (Stage 9), on a device with no notes,
  and it takes the account id and its own device key together. The handshake
  never adopts anything.
- **Forcing two accounts together.** For the person who has notes on both a
  phone and a desktop under different accounts and means to merge them. It is
  a separate action from pairing, with no shortcut to it:
  - Desktop: `cli account move --to <setup text>` on the account to give up. It
    prints how many notes will be merged into which account, and proceeds only
    after the user types the **full 32-character id of the account being given
    up**, by hand. No GUI or TUI path.
  - Phone: under Advanced Settings, "Move this device to another account",
    which asks for the setup text and then for the full id of the current
    account typed by hand, and shows the note count before the last step.
  - What it does: takes a snapshot (Stage 11), pairs with the other account's
    device to obtain a device key for it, rewrites `sync_meta.account_id`,
    clears `sync_peers` so everything re-exchanges, and leaves the notes in
    place; they are UUIDs and cannot collide, so the next sync merges them into
    the other account.
  - **Tags are merged by path, not duplicated.** Before its notes travel, the
    moving device fetches the other account's tag tree in the pairing reply and
    maps every tag of its own whose full path (`parent/child`) exists there to
    the existing id, rewriting its note-tag links. Only tags with no
    counterpart remain new. The user is left with no duplicates to clean up.
  - **Open for confirmation**: the mechanism above, and whether the phone's
    path should require a verified backup first.

## Stage 2 — Accounts in the core

New `VoiceCore/src/accounts.rs`, exposed through PyO3 and UniFFI. Python has no
account logic of its own.

```
~/.config/voice/
  config.json                       machine: device id and name, listen port, mDNS, certs
  accounts.db                       index, never synced, mode 0600
  certs/
  01a0952602bc70808f15a84d31aaa8d2/ notes.db  config.json  audio/  voice.log
  01a09612f4c1718b9e2d71f0c9a4b3e7/ …
```

- **Machine settings and account settings are separated.** Device identity,
  listen port and certificates belong to the machine, because the core installs
  one device id per process (SYNC_SPECIFICATION ID-2, ID-3) and two accounts on
  one desktop are one device. This device's key for the account, the audio
  directory and the storage configuration belong to the account. On the phone the two live in its
  one directory and one file, so `Config` reads both sections from wherever they
  are; nothing on the phone changes shape.
- `accounts.db`: `accounts(account_id PK, label UNIQUE, is_default, hosted,
  created_at, last_opened_at)`. No secrets: a device's own key is in the
  account's `config.json`, and other devices' key hashes are in the account
  database (Stage 5). **Labels are unique**, because `-a` accepts a label and
  two accounts with one label would make the flag ambiguous; a duplicate is
  refused at creation. The directory is always `<root>/<account_id>`, so it is
  not stored. The database inside the directory is **authoritative** for its
  own `account_id`; the index is only an index, and a disagreement is reported,
  never corrected.
- **Resolution**, in the core, one function: given the root and an optional
  selector, return the account directory. With a selector, look it up by id or
  by label; with none, the default; with no index or no default, create and
  register one, so a first desktop run is never a dead end. Where there is no
  `accounts.db` and the root itself holds `notes.db` (the phone), the root is
  the account and its id comes from the database.
- Flags: `-a|--account-id <id-or-label>`; `$VOICE_ACCOUNT_ID` mirrors it. `-d`
  is removed, and with it the "Using CONFIG_DIR" banner, which becomes "Account:
  <label> (<id>)". The root is `~/.config/voice/`; see open question 1 for the
  override tests and the deployed server need.
- Commands: `account list` (marking default and hosted), `account create
  [--label]` (generates the account id and this device's key, writes this
  device's card), `account default <id|label>`, `account show-code` (the QR and
  the setup text of the open account, Stage 9), `account join <setup text>`
  (this device joins an existing account by the claim flow of Stage 9: if the
  open account has no notes it takes the id, otherwise a new account directory
  is created and made default), `account host [--label]` (prints a setup text
  with a token for this server; a holder pastes it and grants the server a key
  by the grant flow of Stage 9), `account unhost`, `account remove` (index
  only; data is deleted only under a separate explicit flag), `account move`
  (Stage 1), `account snapshots` and `account restore` (Stage 11), `device
  list` and `device revoke <id|name>` (Stage 5).
- Audio directories default to `audio/` **inside the account directory**, so two
  accounts never share recordings.

## Stage 3 — One server, several accounts, and authentication

The design must hold on the public internet, for a service with many users and
attackers among them. What was decided, and why:

- **A device key** is 32 bytes from the operating system's random source,
  shown as 43 base64url characters. Every device has its own key for each
  account it holds. The device that creates an account makes its own key on
  the spot; every other device receives one at pairing, issued by the device
  that let it in (Stage 9). A key is held in clear only by its own device, in
  that account's `config.json`, because the device must send it.
- **Everyone else holds only the hash.** The device card (Stage 5) carries
  `sha256(key)` (the key has 256 bits of entropy, so a slow hash buys nothing)
  and travels by sync, so every device of the account, and every server that
  hosts it, can verify every other device. A stolen database or index is not a
  set of keys. A key can never be listed; a device that loses its key is
  revoked and paired again under a new device id.
- **Every request carries three headers**: `X-Account-ID` for routing,
  `X-Device-ID` to name the key, and `Authorization: Bearer <device key>` for
  authentication. Reverse proxies and logging libraries already treat
  `Authorization` as a credential. The receiver finds the account, finds the
  card of that device in it, compares the hash in constant time, and checks
  the card is not revoked. The handshake's `account_id` field stays, so a
  client can also verify it reached the account it meant to. `/sync/status`
  and the pairing routes need no headers; every other route does, on a LAN
  peer as much as on a public server.
- **Failures**: unknown account → 404, unknown or revoked device or wrong key
  → 401. Distinguishing the two tells an attacker whether an account id exists,
  which is harmless when ids are 128 random bits. Each surfaces as a sentence:
  "This server does not host your account", "This device is not paired with
  this account; pair again". The server delays responses to an address after
  repeated failures, and to an account after repeated failures from anywhere
  (bounded counters; a reverse proxy in front of the public server does the
  rest). A request for a hosted account opens that account's database, so the
  cache of open accounts is bounded and an unknown account is refused before
  anything is opened.
- **Every refusal has a code**, a short stable identifier such as
  `ACCOUNT_MISMATCH`, `DEVICE_REVOKED`, `TOKEN_EXPIRED`, sent in the error
  body, shown after the sentence, and written to both logs. A bug report can
  quote it.
- **An audit log per hosted account** on the server: one line per request with
  the time, device id, route, bytes in and out, outcome and refusal code. Never
  a key, never content. Rotated like every other log (`TECHNICAL-DECISIONS.md`
  7.1). It answers "who touched this account and when".
- **Certificate verification is never off.** Today `danger_accept_invalid_certs`
  disables it for every peer. A peer with a pinned fingerprint is verified
  against the fingerprint; a peer without one is verified against the system's
  root certificates, which is what a public server behind a real certificate
  needs and what lets that certificate rotate. `http://` is refused outright: a
  key must not cross a network in clear.
- **Keys never reach a log.** Request logging redacts `Authorization`, and the
  key is never part of an error string.
- **Revocation is one-way and travels by sync.** `device revoke` on any device
  sets the `revoked` field of the target's card. Its merge kind is Membership,
  where `"1"` always wins (MERGE-M), so a stolen phone that syncs afterwards
  cannot un-revoke itself. The revoked device is refused by every peer as soon
  as the card reaches it; the server, which every device syncs with, is where
  that matters. A revoked device id stays revoked; a device paired again
  afterwards generates a new device id first. **Revoking ends with a
  reminder**: the revoked device still holds the bucket key, which reached it
  by sync, and the wizard's "Replace key" page (Stage 14) is one click away.

Server structure:

- `AppState` becomes a map from account id to an opened (database, config),
  filled on demand from `accounts.db` where `hosted = 1`, with a bounded cache
  and an idle timeout. **The server opens nothing at start.** `cli sync serve`
  therefore runs before `main.py` opens any account: it needs only the root, the
  machine config and the index.
- **A desktop listener serves every account in its index**, hosted or its own:
  the second user's phone syncs to the owner's desktop while the owner's GUI has
  the owner's account open. The account the GUI holds is served through a
  second connection to the same file, as `cli sync serve` already does today.
- A pure server never creates a default account: `account host` does not make
  an account the default, and `cli sync serve` does not run the "create a
  default account" branch of resolution.
- For the future sign-up website, recorded but **not built**:
  `POST /admin/accounts {account_id, label}` → `{account_id, setup_text}` (a code for the claim flow),
  `GET /admin/accounts`, `DELETE /admin/accounts/<id>`, with
  `Authorization: Bearer <admin token>`, whose hash, never the token, is in
  the machine configuration. This is the one place an account is created on a
  server; the site then shows the setup text for the person's devices to join
  with.
- **The server publishes its own device card** (Stage 5) into every account it
  hosts, with its public URL from the machine configuration (`public_url`) and
  no fingerprint, because a public server carries a real certificate and is
  verified against the system roots. That is how a phone that has only ever
  paired with a desktop learns that the server exists.

## Stage 4 — Files between instances

- Expose `fetch_audio_file` / `send_audio_file` through UniFFI (PyO3 has them).
- Policy in one place in the core: **fetch** takes a missing recording from a
  LAN peer first, then downloads from the bucket; **send** offers files a peer
  lacks. **Deliver** and **exchange** compose them with sync, as the terms table
  says, and are what the buttons call.
- **Streaming both ways.** An eight-hour recording must not be buffered
  (`TECHNICAL-DECISIONS.md` 3.1). All four paths buffer today: the server reads
  the file with `std::fs::read` and takes the upload body as `Bytes`; the client
  reads the response with `bytes()` and the source file with `std::fs::read`.
  All four are rewritten to stream, and the verification measures it.
- **A recording in progress is never sent or uploaded.** The recorder marks
  the row while the file is open and clears the mark when it closes it; send,
  upload, the missing-list answer and the not-duplicated count all skip a
  marked row. No half file reaches a peer or the bucket.
- **Free space is checked first.** Before a fetch, a download or an apply, the
  receiver compares the size it is about to write, plus a margin, with the free
  space on that disk, and refuses with a sentence naming both numbers.
- **An operation can be cancelled, and shows progress** per page of changes
  and per file, with bytes moved, on both platforms. Cancelling leaves the
  `.part` files for resume and the database at the last committed page.
- **Every database connection uses WAL mode and a busy timeout** of five
  seconds. The GUI and the listener write the same file from one process, and
  without this the second writer gets "database is locked".
- **One question per exchange, not one per file.** Before sending, the sender
  posts the list of recording ids it holds to `/sync/audio/missing` and gets
  back the ids the peer lacks. Thousands of recordings cost one round trip.
- **Transfers resume.** A file travels to a `.part` file beside its final
  name. The sender states the size and the SHA-256 of the whole file in headers
  (computed by one sequential read before sending); a fetch that is interrupted
  continues with a `Range` request from the bytes it has, a send with
  `Content-Range`, and the receiver verifies the hash before the rename.
  Wifi that drops at hour seven costs the remaining hour, not eight.
- **Timeouts are explicit.** Connect in three seconds on the LAN, ten on the
  internet; read in thirty. A transfer retries three times with backoff; the
  metadata routes do not retry, because the user pressed a button and will
  press it again.
- **Send and fetch never touch the storage columns.** `storage_key` and
  `storage_uploaded_at` on an `audio_files` row say whether the bucket holds
  the file; they are written by upload and travel by sync (DM-4). A file that
  arrived by fetch is local, and the mirror step skips it; a row that says
  "uploaded" is skipped by upload on every other device. This is what lets a
  LAN exchange replace a bucket download, and a bucket upload happen once.
- `max_sync_file_size_mb` applies to uploads to the bucket only. The
  `DefaultBodyLimit` moves off the file route; the file route's own ceiling is
  the free space on the receiving disk.

## Stage 5 — The devices of an account, and the address in plain sight

- **Each device publishes a card**, a new synced entity `device` with fields
  `name`, `certificate_fingerprint`, `addresses` (the URLs it listens on, as a
  JSON list), `listens` (`"0"`/`"1"`), `key_hash` (Stage 3) and `revoked`
  (Membership kind, so `"1"` wins), registered in `FIELD_REGISTRY` per DM-1. A
  device writes its own card, except `revoked`, which any device may set and
  none may clear. Cards never conflict in practice and merge like any scalar if
  they ever do. When a device regenerates its certificate it rewrites
  `certificate_fingerprint`, and peers re-pin from the card, which arrived over
  an authenticated connection; no one types a fingerprint twice. This is how "the other servers and
  devices are synced between them": after a sync, every card of the account is a
  peer, and `Config::peers` is filled from the cards. Only the remembered
  reachable address stays local, in `sync_peers`.
- Core bindings for the list: `list_peers`, `add_peer`, `remove_peer`,
  `sync_with_peer(peer_id)`, `deliver`, `exchange`, over UniFFI and PyO3.
- Android (`SyncSettingsScreen.kt`, `SettingsViewModel.kt`): `server_url` and
  `server_peer_id` leave SharedPreferences; the screen reads the core's list.
  With two or more peers, any operation asks which peer first.
- **Every new control carries a content description**, the not-duplicated
  line and every result are announced by the screen reader as they change,
  and the sync screen, the code screen and the wizard are checked with the
  screen reader on and at the largest font size. This is toolkit-independent
  and survives the interface swap.
- **No state is shown by colour alone**: every state has an icon and a word,
  so a colour-blind user and a monochrome screenshot in a bug report both
  read it.
- **A peer can be renamed and forgotten locally.** The local name is shown in
  place of the card's name; forgetting removes the peer from this device's
  list and its cursors, and the card brings it back only if the user adds it
  again. Neither travels.
- **A device name that means something.** The phone's default name is its
  model name as Android reports it; the desktop's is its hostname, as today.
  Cards then read "Galaxy A14" rather than "Voice on localhost".
- **One visible button, naming the last peer.** The five operations are exact
  in the code, the command line and the manual. On the phone's sync screen and
  in the desktop sync dialogue the user sees one button, **"Exchange with
  Desk"**, where Desk is the peer used last; a tap repeats, a long press (or
  the arrow beside it on the desktop) chooses another peer or another
  operation. With one peer there is nothing to choose. This replaces the
  earlier rule that two peers always ask first.
- **Every result is one sentence**: "Received 12 notes and sent 3 recordings
  (410 MB) in 2 minutes", followed by the request id (Stage 12). A refusal is
  one sentence, its code, and the button that fixes it: "Show my code",
  "Check connection", "Pair again".
- Desktop: the same list in the GUI sync dialogue; `cli sync peers` exists.
- **This device's address, port, device id and fingerprint** are shown at the
  bottom of the desktop sync dialogue and in About (`main_window.py:727`
  `show_about`), and on the phone's sync screen and a Settings entry.

## Stage 6 — The phone as a listener

- New UniFFI `start_listener(port)` / `stop_listener()` in `android.rs`, wrapping
  what `start_sync_server` already does for Python. The axum server is already
  compiled into the Android library.
- Its certificate is generated on the phone by `tls.rs`; the fingerprint is
  shown so the desktop can pin it, and published in the device card.
- `SyncListenerService`: a foreground service (type `dataSync`) holding the
  port, with a Stop action, started by a switch on the sync screen. **Never
  started by itself.**
- **The listener can stop itself after an idle time**: never (the default),
  one, four or eight hours, chosen on the sync screen. It is stopping, not
  starting, so decision 1 holds; it saves the battery of a user who forgets.
- **Every operation on the phone runs in a foreground service** with a
  progress notification showing the operation, the peer, and bytes moved, with
  a Cancel action. Without it Android stops the transfer when the screen goes
  off; with it an eight-hour recording reaches the desktop with the phone in a
  pocket. The notification is the operation's own progress and disappears when
  it ends; it is not a reminder.
- **A listener binds to the LAN, not to every interface**, on the phone and on
  the desktop: it listens on the addresses of private networks (RFC 1918 and
  link-local) and refuses a connection whose source address is not private. A
  server with a `public_url` configured listens on every interface. A phone on
  hotel wifi is thereby not a server for the hotel.
- The desktop gains the same switch in its sync dialogue, because today only
  `cli sync serve` listens and the phone must be able to reach a desktop with
  its GUI open.

## Stage 7 — Finding each other

1. **mDNS**: a listener announces `_voicesync._tcp` (desktop: Python `zeroconf`,
   a new dependency; phone: `NsdManager`) with the **SHA-256 of the account
   id**, not the id, and the fingerprint in its TXT record. The other side
   browses and compares hashes; the LAN learns nothing identifying from the
   broadcast.
2. **Remembered address**: the last URL a peer was reached at, in `sync_peers`.
3. **Typed by hand**, from the other device's sync dialogue or About.

The three run **at the same time**, not in turn: the remembered address is
tried while the mDNS browse is running, and the first answer that passes the
account check wins. A sync starts in under a second when the address has not
changed, instead of after a browse timeout.

Every route checks the account id (Stage 1) and the key (Stage 3), so a
right-looking address belonging to the wrong account is refused, not merged.

## Stage 8 — The S3 wizard

`Voice/src/core/storage_setup.py`, driven by a GUI wizard
(`src/ui/storage_wizard.py`) and an interactive `cli storage setup`. It is
complete for a person who has never seen the Amazon console:

1. **Make the key.** The wizard shows, one screen at a time, where to click in
   the console to create a user and a key, and shows the policy text to paste,
   with a copy button. The policy allows `s3:CreateBucket` and the object
   operations on buckets named `voice-*`, and nothing else.
2. Paste the key id and secret; whitespace and a stray `Access key ID:` prefix
   are trimmed, the commonest failure.
3. A region, defaulting to the nearest by round-trip time.
4. A generated bucket name (`voice-<6 random>`), changeable, created private;
   "name taken" suggests another.
5. Write a small object, read it back, compare, delete it.
6. Save through the existing `storage configure-s3` path, a synced entity, so
   every device of the account receives it at its next sync. The phone can
   upload only after that first sync; the wizard says so.
7. Failures in words: `403 SignatureDoesNotMatch` → "the secret is wrong, or has
   a space on the end"; `301 PermanentRedirect` → "the bucket is in another
   region"; a DNS failure → "check the endpoint".
8. Set a **lifecycle rule** on the new bucket: objects move to the
   infrequent-access storage class after thirty days. That roughly halves the
   storage bill, and a download is still immediate; the archive classes are
   not used, because a recording is fetched on demand.
9. Offer to start the listener, and to keep it started.
10. **The wizard resumes** where it stopped if it is closed part way, with the
    values entered so far kept for the session; the secret is never written
    anywhere until the final save.
11. **"Test everything"**, the wizard's last page and a button in the sync
    dialogue: the connection check of Stage 12 against every peer and the
    bucket, as one table.

The desktop sync dialogue opens with a **checklist** at the top: paired
devices, bucket, listener, recordings not duplicated, last exchange. Each row
shows its state and the one button that completes it. Nothing needs reading.

Every button has a command: `sync exchange <peer>`, `sync deliver`, `sync
send`, `sync fetch`, `sync check <peer>`, `storage setup`, `storage upload`,
`storage download`, `account show-code`, `account join`. Anything the user can
do, a script and a bug reproduction can do.

Upload asks the bucket whether the object already exists before sending a row
that has no `storage_key`. After a snapshot restore a row can say "not
uploaded" while the object is there, and the answer costs one request instead
of a whole file.

DigitalOcean and Backblaze keep the manual path in `CLOUD-STORAGE-SETUP.md`
until someone has run them in earnest. The bucket holds recordings only; notes,
tags and transcriptions travel only by sync. The wizard's last screen says that
too.

## Stage 9 — The QR code and the setup text

- **Payload**, and nothing more: version, account id, a pairing token, and the
  generating instance's device id, name, addresses, port and certificate
  fingerprint (32 raw bytes, base64url, not the colon form). Under 300 bytes,
  so the code stays small enough for a poor camera. A server's setup text
  (`account host`) has no account id, because the server does not hold the
  account yet.
- **The pairing token** is 32 random bytes, held only in the memory of the
  instance that shows the code, valid for ten minutes, spent by its first use,
  and discarded when the code is hidden. The showing instance listens while the
  code is shown (the dialogue turns the listener on, and back off if it was
  off). Comparison is constant-time. The screen shows a countdown ("expires
  in 9:40") and a "Show again" button. **Five wrong tokens invalidate the
  code**: it disappears and must be shown again, so a photographed code cannot
  be guessed at while it is on the screen.
- **Two flows, one rule: the empty device ends up with a key issued by a device
  that holds the account.**
  - **Claim** (the usual case; the reader can reach the shower): the reader
    checks the account id in the code against its own notes first, offline,
    and refuses if it holds notes under another account. Then it connects to
    the address in the code, pins the fingerprint, and posts `/pair/claim` with
    the token, its device id, name, fingerprint and addresses. The shower
    verifies the token, generates a device key for the reader, writes the
    reader's card with the key's hash into the account, and replies with the
    account id, the key, its own card and the account's tag tree (for `account
    move`). The reader stores the key, writes the shower's card locally, and
    adds it as a peer. The first exchange can now start from either side.
  - **Grant** (the empty device cannot reach the holder: a server behind a
    public address that a desktop can reach but not the reverse): the empty
    device shows a code with a token and its address; the holder reads it and
    posts `/pair/grant` with the token, the account id, a key it generated for
    the empty device, its own card, and the label. The empty device verifies
    the token, creates the account directory and database, stores the key,
    writes the holder's card so the holder's first handshake authenticates,
    and writes its own. The holder writes the empty device's card locally.
  - The future sign-up site is the claim flow with the server as the shower:
    the site creates the account on the server and shows the code.
- **Any device shows it.** Desktop: `segno` (pure Python, no Pillow, prints to
  a terminal so the TUI and CLI can show one too). Phone: ZXing's encoder, on
  the sync screen. Shown only when asked, beside "treat this like a password",
  hidden again after sixty seconds. A **Copy setup text** button gives the same
  payload as text, for a reader with no working camera and for `account join`
  on a desktop.
- **Any device reads it.** Android: CameraX and ZXing core (pure Java, offline,
  no Play Services), new `CAMERA` permission, and a paste field. Desktop: the
  paste field in the sync dialogue and `account join`; no camera support.
- **Every camera in turn, front-facing last**: order
  `cameraProvider.availableCameraInfos` rear → external → front, and move on
  when one fails to open **or delivers no frame within three seconds**. The
  selection sits behind an interface (`CameraChoice` / `FrameSource`) so it is
  testable without hardware (`TECHNICAL-DECISIONS.md` 6.7).
- **The setup text is a link**: it begins `voice://pair?` and the phone
  registers the scheme, so a setup text shared through any messaging app opens
  Voice at the pairing screen when tapped. "Share" sits beside "Copy" on the
  code screen. Two phones, or a phone whose partner has no camera, pair without
  typing.
- **The phone's first run** shows two choices, "Pair with another device" and
  "Start on my own". The first opens the camera, with the paste field under it.
  A new phone is paired in three taps and never sees a settings screen.
- **After pairing, the next screen is the new peer with one Exchange button**,
  preselected. Nothing runs by itself; the first exchange is one tap.
- A reading device that already holds notes under another account
  **refuses** before any network traffic; the message names both accounts, and
  says to show this device's code to the other one instead, which is the
  answer in nine cases out of ten. It points at `account move` (Stage 1) for
  the tenth.

## Stage 10 — Proof that it worked

- A line at the top of the phone's sync screen and the desktop's sync
  dialogue: **"3 notes and 2 recordings are not duplicated off this device."**
  Nowhere else: no notification, no badge, no reminder. A note counts as
  duplicated when its head version has been sent to any peer (its sequence
  number is at or below some peer's `last_sent_seq`); a recording when its row
  has a `storage_key`, or a local table `audio_file_copies(audio_id, peer_id,
  at)` says a peer has it, written by send and by a peer's fetch. When both
  counts are zero the line reads "Everything is duplicated off this device."
- Below it, per peer and for the bucket: when it was last reached, and what the
  last operation was.
- **Per recording, where its copies are**: this device, the bucket, and each
  peer, from `storage_key` and `audio_file_copies`. Shown in the recording's
  details on both platforms. It answers "is this one safe" for one file.
- The wizard ends by doing it: record on the phone, press Deliver, see the note
  on the desktop and the file in the bucket.

## Stage 11 — A snapshot before anything irreversible

`TECHNICAL-DECISIONS.md` 1.1 says nothing is lost, ever. Sync, `account move`,
`account join` and `account restore` each rewrite the database in one step, and
a bug in any of them, or in this plan, must be undoable.

- Before applying a batch from a peer (client and server side), before `account
  move`, before `account join` rewrites an empty account, and before `account
  restore`, the core copies the database with SQLite's backup API into
  `<account>/snapshots/notes-<timestamp>.db`. A copy of a database this size
  takes well under a second.
- The last five are kept; older ones are deleted. Recordings are not included;
  they are files and are never rewritten by sync.
- `account snapshots` lists them with their note counts; `account restore
  <snapshot>` asks for confirmation, takes a snapshot of the current state
  first, then replaces the database. On the phone both are under Advanced
  Settings.
- **A periodic backup**, separate from the snapshots: every `backup.interval_hours`
  (default 24) each open account's database is quiesced and copied to
  `backup.directory` (default `<root>/backups/<account-id>/`), named by time,
  keeping the newest `backup.keep` copies (default 30). Quiescing means: take
  the write lock, checkpoint the write-ahead log, copy with the backup API,
  release; readers are never blocked and a writer waits well under a second.
  It runs inside `cli sync serve` for every hosted account and inside the
  desktop while it is open; the three values are in the machine
  configuration, and the owner adjusts the interval by watching the size. The
  backup directory is never inside the recordings folder (Stage 13). Nothing
  copies it off the machine: every note on a server is on another device too.

## Stage 12 — Robustness, diagnostics and network cost

- **A page is committed before the next is requested.** The changes feed is
  paged by cursor already; the client applies and commits each page, records
  the cursor, and only then asks for the next, so an interrupted sync loses at
  most one page and continues from where it stopped. The suite proves it by
  killing the connection mid-page.
- **A request id per operation.** The initiator generates one id per button
  press and sends it as `X-Request-ID` on every request of that operation. Both
  sides write it in every log line, and the result sentence ends with it, so
  one exchange can be followed across two machines' logs from a screenshot.
- **Clock skew is reported.** The handshake already carries the responder's
  time; a difference of more than a minute is shown after the result ("this
  device's clock is 4 minutes behind the desktop's"), because version ordering
  uses instants and a wrong clock is otherwise silent.
- **A connection check**, `cli sync check <peer>` and a "Check connection"
  button on both platforms: reachability, certificate or fingerprint, account,
  key, clock skew, free disk on both sides, listener state, each with its
  refusal code. One table instead of a log search.
- **The changes feed is compressed** (gzip, negotiated by `Accept-Encoding`).
  JSON shrinks five to ten times. The file route is never compressed; audio
  already is.

## Stage 13 — Storage cost, and where recordings live

- **Recordings are written to a folder the user can see and that survives the
  application.** The phone's default audio directory becomes the `Voice`
  folder of the shared storage's public Recordings directory, which is
  `/storage/self/primary/Recordings/Voice/` (the same place as
  `/sdcard/Recordings/Voice/`; there is no `/storage/self/Recordings`).
  Android deletes an application's private directories when the application
  is replaced or removed, which is how the week's recordings were lost, and
  leaves the public directories alone. The folder is reachable over a USB
  cable and from any file manager, and `voice-phone-backup` copies it. The
  manifest already holds the storage permissions this needs. **The folder
  holds recordings and nothing else**: no snapshots, no database, no index,
  no cache. The database stays private; the recordings do not.
  `voice-phone-backup` is updated to copy the new location.
- **File names a person can read.** A recording's file is named
  `2026_09_21_14_30_59-abcdefgh.ogg`: the recording's start time in the local
  time it was recorded in (`file_created_at` rendered at its own offset,
  TZ-3), a hyphen, and the **last** eight characters of its id (the random
  part of a UUID7; the first characters are the clock and repeat within a
  minute). The name is kept
  on the row in `audio_files.local_name`, which is local, never synced, and
  the only way a file is found: the server's lookup by id prefix in
  `sync_server.rs` and `audio_local_path` in `models.rs` are replaced by it.
  A file arriving by fetch or download is named the same way from its row.
- **A speech bitrate for recordings.** `RecorderPreferences.kt` offers Opus at
  128 kb/s, AAC at 96 kb/s and 16 kHz WAV. A fourth option is **added**, not
  substituted: Opus at 32 kb/s, 48 kHz, in the same Ogg container, labelled
  "Opus, speech, 32 kb/s". Opus at that rate is transparent for voice, and
  Whisper resamples to 16 kHz regardless, so transcription is unchanged. An
  hour costs about 14 MB instead of 57. The existing three options and the
  current default are untouched (open question 2).
- **A content hash on the recording row.** `audio_files.content_sha256`,
  metadata merged per column (DM-4), written by import and by recording. Two
  devices importing one file share one bucket object, keyed by the hash rather
  than the row id; fetch and the copies list verify a file by it; and the
  resumable transfer of Stage 4 uses it instead of hashing before every send.
- **Multipart upload with resume to the bucket.** Files larger than one part
  (8 MiB; the plan first said 100 MiB, but an hour at the default bitrate is
  57 MB and a dropped connection would have repeated all of it) go up in
  parts; the upload id and completed parts are kept in `upload_parts`, and an
  interrupted upload continues with the next part. Stale multipart uploads
  are abandoned by the lifecycle rule after two days, so they never
  accumulate as hidden cost. **Done 2026-09-13** (FILE-18, FILE-19).
- **Purge reaches the bucket** (closes the gap in PURGE-9), without a delete
  permission: see Stage 14.
- **Bucket versioning stays off.** The wizard neither enables it nor leaves it
  enabled on an existing bucket without saying that versioning doubles the
  bill on every overwrite.

## Stage 14 — Hardening the bucket and the keys

- **The bucket key cannot delete.** The policy the wizard shows grants
  `PutObject`, `GetObject`, `ListBucket`, `PutObjectTagging`, `AbortMultipartUpload`
  and `CreateBucket` on `voice-*`, and nothing else. A stolen phone, which
  holds this key by sync, cannot destroy a single recording.
- **Purge tags, lifecycle deletes.** Purging a recording puts the tag
  `voice-purged=1` on its object; a lifecycle rule set by the wizard expires
  tagged objects after one day. Every device can purge, no device can delete,
  and a purge made by mistake has a day.
- **"Replace key"**: a wizard page that takes a new key id and secret, tests
  them exactly as the first run does, and saves them through the synced
  storage configuration, so every device has the new key at its next sync.
  The old key is deactivated in the console; the page says where.
- **The wizard hardens the bucket** on creation with three calls: block public
  access on, default server-side encryption on, and a bucket policy that
  refuses any request not made over TLS. Each is verified after creation and
  reported as a line on the result screen.
- **The phone wraps its secrets with the Android Keystore.** The device key,
  the bucket secret and the recording key (Stage 15) are stored encrypted
  under a Keystore key that never leaves the hardware where the phone has it.
  The desktop keeps `config.json` at mode 0600 as before. **Device key done
  2026-09-13** (AUTH-9). The bucket secret is not: it is a synced setting
  inside the database, so wrapping it on the phone needs a local shadow the
  feed excludes; open question 4.
- **Dependency audits are tests.** `cargo audit` for the three Rust crates,
  `pip-audit` for the desktop, and the Gradle dependency check for the phone,
  run in each suite and fail it on a known vulnerability.

## Stage 15 — Optional encryption of recordings in the bucket

Off by default. When on, neither Amazon nor a server operator can listen to a
recording; the price is a key that, if lost, makes the bucket's recordings
unreadable for ever. The design makes that loss hard.

- **One recording key per account**, 32 random bytes, made when the owner turns
  encryption on. It is carried to every device by pairing (the claim and grant
  replies include it, over TLS, to a device that has just been let in) and
  stored where the device key is stored.
- **Export is mandatory before encryption turns on.** The switch is disabled
  until the key has been exported once: shown as text and as a QR code
  labelled "Recording key. Keep this on paper. Without it these recordings
  cannot be played." and copied or printed. `account recording-key export`
  and `import` on the desktop; the same under Advanced Settings on the phone.
  Import is how a device that lost everything reads the bucket again.
- **Files are encrypted in chunks**, AES-256-GCM, 1 MiB per chunk, a random
  nonce per file with the chunk index in the associated data, so an
  eight-hour recording is encrypted and decrypted in a stream
  (`TECHNICAL-DECISIONS.md` 3.1). Objects of encrypted files carry the suffix
  `.enc`, and the row records `storage_encrypted = 1`.
- **Local copies are plain.** A device that holds the key decrypts on download
  and on fetch, and encrypts on upload. A server that mirrors the bucket keeps
  the objects as they are and needs no key; a fetch from such a server
  delivers the encrypted bytes, marked by a header, and the fetching device
  decrypts. Send between two devices that both hold the key is plain over TLS,
  as today.
- **Turning it on encrypts nothing already uploaded.** A separate button,
  "Re-upload existing recordings encrypted", does that on request, one file at
  a time, resumable. Turning it off makes new uploads plain and leaves
  encrypted objects readable by any device that keeps the key.
- **Rotation** of the recording key is not in this work; the key is exported,
  imported and carried, never changed.

**Done 2026-09-13** (ENC-1..4). One change from the text above: the chunk
nonce is the file nonce with the chunk index in its last four bytes, not the
file nonce alone with the index only in the associated data, because GCM
must never see one nonce twice under one key. The bucket secret is still not
under the Keystore (open question 4).

## Stage 16 — Protocol version 2, and room for other applications

- **The protocol version becomes `2`.** Headers, device cards, pairing and
  the new entity types change the exchange; a peer that announces `1.x` is
  refused with `PROTOCOL_TOO_OLD` and "Update Voice on <device name>".
  Everything starts afresh, so nothing negotiates with version 1.
- **Other applications will sync with this protocol later**, beginning with
  an image application that shares the account's tag hierarchy. Nothing is
  built for it here, and nothing here may preclude it. Four things are built
  now so that it stays possible:
  1. The handshake carries `application` (`"voice"`, later `"images"`) and
     `entity_types`, the list the peer wants and understands. The changes
     feed takes `?types=tag,...` and returns only those; apply accepts only
     the types the peer declared. An image application that declares
     `["tag"]` receives and sends tags and nothing else, and its note-tag
     links never reach it.
  2. An unknown entity type is never an error. Today a receiver ignores it
     (PROTO-2); that stays. A **hosting server** additionally keeps changes of
     types it does not understand in an opaque table, keyed by type and entity
     id, and relays them in the feed, so two image devices can meet through
     the same server that hosts the account's notes. Designed here; the
     opaque table is built when the first such application exists.
  3. The device card carries `application`, so a peer list can say "Images
     on Meirav's phone".
  4. Tags stay self-contained: `tag.name` and `tag.parent` reference nothing
     that belongs to Voice, and the tag cycle rule (HEAD-9) and the duplicate
     root rule are in the core, where every application gets them.

## Order of work

Stages are numbered by subject. They are built in the order that makes a
recording reach a second place soonest:

1. Stage 0, dead and duplicate code. **Done 2026-09-13.**
2. Stage 1, account identity, and Stage 11, snapshots. **Done 2026-09-13**,
   with two parts deferred: the `account move` command takes the target
   account id and the typed current id today; its setup-text form, the tag
   path mapping and the phone's path come with Stage 9, which brings the
   setup text and the pairing reply they need. The periodic backup of Stage
   11 needs the machine configuration of Stage 2 and comes with it.
3. Stage 3's authentication only (keys, headers, certificate verification),
   with the single-account server as it is. **Done 2026-09-13**: device keys,
   cards (the `device` entity of Stage 5, built here because the hashes live
   on it), the three headers, the refusal codes, the per-address delay, HTTPS
   on the listener, pinned or root-verified clients, and plain http only on
   this machine. The audit log per hosted account comes with hosting.
4. Stage 9, the code and pairing, and Stage 5's device cards, which pairing
   writes. **Claim flow done 2026-09-13**: `account show-code`, `hide-code`
   and `join` on the desktop; a paste field and Join on the phone. **Phone
   done 2026-09-13** (UI-12): ZXing's code on the sync screen with the
   sixty-second countdown, Copy and Share; CameraX with ZXing reading it,
   every camera in turn behind `CameraChoice`, the paste field under the
   camera; the `voice://pair` link; the first run's two choices; the
   post-pairing card with one Exchange button. The desktop GUI's QR image and
   the grant flow were done with Stages 3 and 8.
5. Stage 4, files between instances, and Stage 6, the phone as listener.
   **Stage 4 done 2026-09-13**: fetch, send, deliver and exchange in the
   core, the command line and the phone's bindings; streamed both ways,
   resumable, hash-verified, one missing-list round trip, explicit timeouts
   and retries, free-space check. Not needed after all: the "recording in
   progress" mark, because the phone imports a recording only after the
   recorder has closed the file, so no row exists while it records. Still to
   come: cancel and progress in the interfaces. **Stage 6 done 2026-09-13**:
   `start_listener`/`stop_listener` on the phone with a foreground service
   and a switch, a "Listen for peers" switch in the desktop's File menu, the
   card's `listens` and `addresses` kept by the core, the address and the
   fingerprint shown in About and on the sync screen. Not yet: the idle
   stop, mDNS (Stage 7).

At this point the owner's phone delivers to the owner's desktop. Then:

6. Stage 2, accounts in the core, and the rest of Stage 3, hosting.
   **Stage 2 done 2026-09-13**: `accounts.rs`, `-a` in place of `-d`,
   `$VOICE_CONFIG_DIR` as the root, `account list|create|default|remove`,
   machine settings in the root's config.json. **Hosting done 2026-09-13**:
   a listener over an indexed root serves every account of the index
   (`AccountSource`, opened on first request), `account host` and
   `account grant-host` (PAIR-5, `/pair/grant`), the phone's one text field
   takes a code or a grant text, `audit.log` per hosted account (AUTH-8).
   The index commands and the listener run on a root without an account
   and never create the default one.
7. Stage 7, discovery; Stage 5's remaining interface work; Stage 10, proof;
   Stage 12, diagnostics. **Stage 12 done 2026-09-13**: the page-commit
   proof, the request id on every request and result, the clock skew
   warning, `sync check` and "Check connection" (DIAG-1..5), the gzipped
   feed. **Stage 10 done 2026-09-13** (PROOF-1..3): the line on the phone's
   sync screen and in `sync status`, `audio_file_copies`, the copies in a
   recording's details on the command line, the peers' last operation; the
   phone's "changes pending" button colour and the desktop's are gone, the
   line is the only place. **Stage 5's interface work done 2026-09-13**:
   the cards are the peer list (CARD-3), the one button naming the last
   peer with the chooser beside it, one-sentence results with the fixing
   button, rename and forget, a peer typed by hand, the desktop's sync
   dialogue (File → Sync…, with the proof line, the code, the check and
   the listener switch), the phone's peers card, the hostname and the
   model name as default device names (UI-9..11). Content descriptions
   are on the new controls; the screen-reader and large-font pass waits
   for the interface swap. **Stage 7 done 2026-09-13** (DISC-1..3): the
   announcement with the account's hash (zeroconf on the desktop,
   NsdManager on the phone), the browse when the remembered address is
   silent, `sync discover` and "Find on this network"; and Stage 6's
   LAN-only listener (LISTEN-3).
8. Stage 8, the wizard, with Stage 14's bucket hardening and Stage 13's
   bucket items. **Done 2026-09-13** (BUCKET-1..5): the wizard in the GUI
   and as `storage setup`, the key that cannot delete, purge by tag and
   lifecycle, the three hardening settings verified, the lifecycle rules,
   the round trip, "Replace key", "Test everything", `sync check --all`,
   the checklist at the top of the sync dialogue, upload asking first.
   **Stage 13's content hash and upload in parts done 2026-09-13** (FILE-18,
   FILE-19). **The Keystore for the device key done 2026-09-13** (AUTH-9).
   Not yet: the bucket secret under the Keystore (open question 4) and the
   dependency audits (Stage 14; `cargo audit` and `pip-audit` are not
   installed on this machine). **Stage 13's folder and
   file names done 2026-09-13** (FILE-15, FILE-16, TECHNICAL-DECISIONS
   3.1a): `audio_files.local_name`, the shared Recordings/Voice folder on
   the phone, `voice-phone-backup` copying it.
9. Stage 13's bitrate option can go in at any point; it touches only the
   recorder.
10. Stage 15, encryption, last. **Done 2026-09-13** (ENC-1..4): the cipher
    module, the key in the configuration and in the pairing replies, the
    encrypted upload through the parts loop, the download and fetch that
    open on arrival, the keyless server that serves as it holds, export and
    import on every interface, the switch that waits for the export, and
    "Re-upload existing recordings encrypted". Stage 16's version bump goes in with step 3,
    and its handshake fields with step 4. **Stage 16 done 2026-09-13**
    (PROTO-12, PROTO-13): version 2.0, `PROTOCOL_TOO_OLD` both ways,
    `application` and `entity_types` in the handshake, `?types=` on the
    feed, apply refusing undeclared types. The opaque relay table waits for
    the first other application, as planned. **Stage 13's speech bitrate
    done 2026-09-13**: "Opus, speech, 32 kb/s" beside the three. **Stage 11's
    periodic backup done 2026-09-13** (SNAP-5): inside the listener for every
    open account, inside the desktop while open, `account backup` now.
    **Stage 1's move by code done 2026-09-13** (ACCT-10): `account move
    --to <setup text>` with the tag paths merged, and the phone's Advanced
    Settings entry. **Stage 4's cancel and progress and Stage 6's idle stop
    done 2026-09-13** (FILE-17, LISTEN-4): a progress sink and a cancel flag
    in the core, the phone's operation service with a progress notification
    and a Cancel action, the desktop dialogue's worker thread, progress
    label and Cancel, the idle-stop choice on both.

---

## Carried into implementation

1. **Keys must never reach the logs** (Stage 3).
2. **Revoking a device** is the only key operation. There is no account-wide
   rotation, because there is no account-wide key.
3. **Audio directories per account** (Stage 2).
4. **A server needs no account of its own** (Stage 3).
5. **Nothing limits disk per account** on a shared server. Not in this work; the
   `account` commands are where it will live.
6. **The `-d` flag is removed** and every document that mentions it
   (`DEVELOPMENT.md`, `README.md`, `USER_MANUAL.md`, `TESTING.md`, the CLI help)
   is corrected in the same change.
7. **The manual is part of every stage.** `USER_MANUAL.md`, `DEVELOPMENT.md`
   and `SYNC_SPECIFICATION.md` are updated in the same change as the code, or
   the stage is not done. Cross-project decisions (the terms, account identity,
   keys, the recordings folder) go into `TECHNICAL-DECISIONS.md` as they are
   implemented.

## Risks and accepted trade-offs

- **The QR holds a ten-minute, single-use token.** Whoever photographs the
  screen and reaches the showing device within ten minutes, before the intended
  device does, gets paired and appears as a device on every card list, where
  `device revoke` removes it. It holds no bucket credentials and no lasting key.
- **A server holds only hashes.** Its operator can read the account's notes,
  which hosting requires, but cannot impersonate any device of the account.
- **The S3 key can create buckets**; it can touch nothing else in the account
  (decision 3).
- **A listener on the phone** is a port and a service; off unless switched on.
- `config.json` holds this device's key in clear, at mode 0600; nothing else
  holds any key.

## Open questions

1. **Forcing two accounts together** (Stage 1): confirm the mechanism, and
   whether the phone's path requires a verified backup first.
2. **The recorder's default format** (Stage 13): the speech option is added;
   whether it becomes the default for new installs is not decided.
3. Resolved 2026-09-12: the periodic backup runs on the desktop and the
   server only; the four old sync design documents are kept; work is committed
   per stage on a branch `accounts-pairing-sync` in each repository, never
   pushed; the Android library and JVM tests may be built and run, the phone
   never touched.
4. **The bucket secret on the phone** (Stage 14): it is a synced setting
   inside the database, so every peer must read it in clear; wrapping it
   under the Keystore needs a local shadow row that the feed excludes and
   the phone reads first. Whether that is worth doing is not decided; the
   device key is wrapped (AUTH-9), the bucket secret is not.
5. Resolved 2026-09-13: two recorder formats may share `.ogg`; an extension
   names the container, not the bitrate. The test that held otherwise was
   written with the tests of 2026-09-12, not from a requirement, and now
   says what the extension is for.
6. **Dependency audits** (Stage 14, for later): `cargo audit` for the three
   Rust crates, `pip-audit` for the desktop, and Gradle's dependency check
   for the phone, run in each suite and failing it on a known
   vulnerability. Neither tool is installed on the development machine, and
   each needs the network for its vulnerability list, so the tests must be
   marked to run on request (`-m audit`) rather than in every offline run.
   Install with `cargo install cargo-audit` and `.venv/bin/pip install
   pip-audit`.

Resolved on 2026-09-12: `$VOICE_CONFIG_DIR` is the only root override; any
device can show its code; the tests of removed modules go with them, with the
protocol tests among them rewritten against the Rust server first.

## Verification

Two rules over all of it: **no test runs against live data** (instrumented
Android tests install as `com.dotancohen.voiceandroid.uitest`,
`TECHNICAL-DECISIONS.md` 7.6) and **nothing touches the phone before
`VoiceAndroid/tools/voice-phone-backup` has run and verified.**

| What | How |
|---|---|
| Stage 0 | `cargo check --all-features` clean; no module in `src/` referenced only by tests; every renamed function has no caller under the old name in any of the three projects |
| Account identity | Rust unit tests: equal, different-refuses, changed-refuses; the handshake never adopts. Pairing: an empty device adopts (with tags and storage config present); a device with one note refuses. `account move` refuses a mistyped id. A mismatched pair in `convergence_tests.rs` asserting nothing is exchanged |
| Accounts in the core | `-a` by id and by label; default selection; a first run with no index; an index whose id disagrees with its database is reported; the phone path (no index, id from the database) through UniFFI on the emulator |
| One server, two accounts | Two accounts hosted on one server, a client each: each sees only its own notes, and `sqlite3` confirms no row crossed. Unknown account → 404; wrong key → 401; revoked device → 401; `http://` refused; a pinned fingerprint mismatch refused; an unpinned self-signed certificate refused; the key absent from the log after a verbose run; every refusal carries its code |
| Pairing | Claim and grant each round-trip between Rust, Python and Kotlin against `sync_protocol_contract.json`, which holds one valid handshake, claim and grant exchange and every error body. A token is refused the second time, after ten minutes, and after the code is hidden. A revoked card stays revoked after the revoked device writes `"0"` and syncs |
| Snapshots | A snapshot exists after every apply and before `account move`; the sixth deletes the first; `account restore` brings back a note deleted by a bad merge and leaves a snapshot of the state it replaced |
| Resume | A fetch and a send each killed at 40% continue from 40% (bytes on the wire measured) and the result's hash matches; a corrupted `.part` is discarded and refetched |
| Pages | A sync killed after page two resumes at page three; the database after the interrupted run plus the resumed run equals the database after an uninterrupted run |
| Listener binding | A connection from a non-private address to a LAN listener is refused; accepted once `public_url` is set |
| Diagnostics | Every log line of one exchange on both machines carries the same request id; the connection check reports each failure it is designed to detect, injected one at a time; a clock set five minutes off is reported after a sync |
| Cost | The changes feed is served compressed to a client that accepts it; a bucket created by the wizard has the lifecycle rule, checked by the S3 API; an upload of a row whose object exists sends no file |
| Missing list | A sender with 5,000 recordings asks once and sends only the ids the receiver named |
| Storage cost | A one-hour recording in the speech option is under 16 MB and transcribes to the same text as the 128 kb/s option (fixture recording, both transcripts compared); two imports of one file produce one object; a multipart upload killed after part three resumes at part four; a purged recording's object carries the tag and the bucket has the expiry rule |
| Bucket hardening | Against MinIO and once against Amazon: a delete with the wizard's key is refused; a plain-HTTP request is refused; public access is blocked; encryption at rest is reported on; "Replace key" reaches the phone by sync and the old key then fails |
| Recording folder | On the emulator: a recording lands in the public folder under its readable name; uninstalling and reinstalling the `uitest` application leaves the file where it was; nothing but recordings is ever written there (the folder is listed after every suite run) |
| Rough edges | A sync started while recording sends every file but the open one; a fetch onto a nearly full disk is refused with both numbers; a cancelled exchange resumes; two writers in one process never see "database is locked" (a thousand interleaved writes); the listener stops after the chosen idle time; a renamed peer keeps its name after a sync |
| Backup | With the interval set to one minute in a test configuration, a copy appears, opens, and holds every note; a writer during the copy waits under a second; the thirty-first deletes the first; nothing is ever written into the recordings folder |
| Protocol | A 1.1 handshake is refused with its code; a peer declaring `["tag"]` receives only tags and its apply of a note is refused; an unknown entity type in the feed is ignored without error |
| Accessibility | Every control on the new screens is reachable by the screen reader with a description (semantics tree asserted); the screens render at the largest font size without clipping (screenshot compared) |
| Interface | The last-peer button repeats the last peer and long-press offers the rest; every result and refusal is one sentence with its code; a transfer continues with the screen off (emulator, screen timeout set to 15 seconds); a `voice://pair` link opens the pairing screen with the text filled in; first run shows the two choices |
| Keystore | On the emulator, the secrets are absent from every file under the application's directories and the application still authenticates after a restart |
| Audits | Each suite runs its audit and fails on an injected known-vulnerable version |
| Encryption | Round trip of a 2 GB file with resident memory flat; a device with the wrong key gets a clear refusal, not garbage; a device that imports the exported key plays a recording uploaded by another device; the switch cannot be turned on before export; a server without the key mirrors and serves the encrypted object and the fetching device plays it |
| A desktop serving a second account | The GUI holds account A; a client for account B syncs to the same process and sees only B |
| Files between instances | Two desktops on localhost: fetch, send, deliver, exchange each do exactly what the terms table says and nothing more; a 2 GB file transfers with resident memory flat (measured) on both sides. The not-duplicated line counts correctly after each operation, and reads zero only when everything has a second copy |
| Account move | Two accounts with overlapping tag paths: after the move no duplicate path exists and every note keeps its tags |
| Unique labels | `account create --label` with an existing label is refused; `-a <label>` is never ambiguous |
| Device cards | Three devices of one account: after each has synced with one other, all three list all three as peers. A phone paired only with a desktop lists the server after the desktop has synced with it |
| Bucket once, LAN instead of download | Phone uploads a file, exchanges with the desktop over the LAN: the desktop's mirror step downloads nothing and its upload step uploads nothing (bucket request log empty) |
| The phone as listener | On the **emulator**, never the owner's phone: the desktop adds it as a peer, presses Exchange, notes and files arrive both ways |
| Discovery | Desktop announces, phone finds it; block mDNS and confirm the remembered address works; then a wrong address and confirm the account check refuses it |
| The S3 wizard | MinIO in a container for the suite, and once by hand against real Amazon from a fresh console account, following only the wizard's screens. A bad key, a bad region and a taken bucket name each give their own sentence |
| QR | Payload round-trip: encoded in Python, decoded in Kotlin, against a shared fixture as `transcription_flags_contract.json` is shared; the code is at most QR version 10. Camera succession with a fake `FrameSource` where cameras 0 and 1 fail. The pasted-text path likewise, and `account join` on a desktop |
| End to end | A clean emulator install: scan, exchange, record, deliver; the note on the desktop and the file in the bucket |

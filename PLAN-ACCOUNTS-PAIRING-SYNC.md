# Plan: accounts, pairing, LAN sync, peer file transfer, and S3 by wizard

Status: **agreed, not started.** Written 2026-09-12 for review.

Scope spans three repositories: `voicecore` (protocol and storage), `Voice`
(desktop and server), `VoiceAndroid` (the phone). Nothing in this plan has been
implemented.

---

## Context

On 2026-09-12 a week of recordings was destroyed: an instrumented test run
replaced the Android application, Android deleted its private and external data
with it, and nothing had left the phone. The sync peer was unreachable, no bucket
was configured, and configuring one meant copying five values out of three web
consoles. The backup that existed was six days old.

The lesson is not "be careful". It is that **getting a recording into a second
place must be easy enough that it always happens**, and that two people sharing
one server must not be able to merge into each other's notes by accident.

The outcome this plan produces: one wizard makes the bucket, one QR code pairs a
phone, the two devices find each other on the LAN by themselves, files move
directly between them, one server hosts several households, and an account
identity makes a wrong-address sync impossible rather than merely unlikely.

---

## What already exists — reuse it, do not rewrite it

| Thing | Where | State |
|---|---|---|
| Peer file transfer over HTTPS | `voicecore/src/sync_client.rs` `download_audio_file` / `upload_audio_file`; routes `/sync/audio/:id/file` in `sync_server.rs` | **Written, wired to nothing.** The bindings expose only the cloud path |
| HTTPS with trust-on-first-use | `sync_client.rs`: `danger_accept_invalid_certs` plus a pinned `certificate_fingerprint` held per peer | Working |
| Certificate generation in Rust | `voicecore/src/tls.rs` (rcgen) | Working — this is what lets the **phone** be a server |
| A peer **list**, already multi-peer | `Config::add_peer` / `peers()`; Android's `configure_sync` writes into it | The core is a list; Kotlin only ever reads `peers[0]` |
| Per-database identity and reset detection | `sync_meta.database_id`, handshake `database_id`, `sync_peers.peer_database_id` | Working — and means the **opposite** of an account id, see Stage 1 |
| Cloud storage with custom endpoints | `file_storage_s3.rs`, `Voice/src/core/cloud_storage.py`, `cli storage configure-s3` | Works for Amazon; DigitalOcean and Backblaze untested |
| Config directory resolution | `Config(config_dir=)` → `RustConfig`; `-d` and `$VOICE_CONFIG_DIR` in `src/main.py` | The seam the account layer hooks into |
| Layman set-up guide | `Voice/CLOUD-STORAGE-SETUP.md` | The wizard replaces most of it for Amazon |

---

## Decisions taken by the owner

1. Both sides may start a sync, **on a button press only, never automatically**.
   The phone therefore needs a listener, running only while asked.
2. The QR code carries **everything inline**: the account key and the S3
   credentials. Accepted risk — a photograph of that screen is a credential until
   the keys are replaced by hand.
3. **One S3 key with `s3:CreateBucket`, kept.** Fewest steps for the user; the key
   can create and use buckets in that account and nothing else.
4. **mDNS discovery**, with the remembered address and a typed address as
   fallbacks.
5. Accounts live in `~/.config/voice/<account-id>/`, indexed by
   `~/.config/voice/accounts.db`. **Nothing existing is moved:** `-d` keeps opening
   `~/.config/voice/` and the six `~/.config/voice-*` test directories.
6. **One account key per account**, used with every peer, carried in the QR.
7. A hosted account must be **added by hand** on the server; an unknown account is
   refused. The REST endpoint for the future sign-up website is **designed here,
   not built**.
8. Android remains **single-account**.

---

## Stage 1 — Account identity

`database_id` already exists and must not be reused: today a *differing* one means
"re-exchange everything", which is exactly the accidental merge to be prevented.

- `sync_meta.account_id`, written when the database is created (`database.rs`,
  beside the `database_id` insert at ~6950). `create_tables` takes an optional
  account id, so the account-creation command can name the directory before the
  database exists.
- `sync_peers.peer_account_id`, added by a migration in the style of
  `migrate_add_sync_sequence`.
- `HandshakeRequest` **and** `HandshakeResponse` carry `account_id`
  (`sync_server.rs` ~47-65), so each side can refuse the other.
- Comparison, in `sync_client.rs::peer_cursors` and in the server's handshake:
  - equal → proceed;
  - the other side has one and this database has none → adopt it;
  - this database has one, has **never synced**, and holds **no notes** → adopt
    (a virgin install that has just been paired);
  - otherwise different → **refuse, exchange nothing**, naming both accounts;
  - a known peer whose account id has **changed** → refuse. This is the
    router-reshuffle case the whole stage exists for.
- `cli sync adopt-account <peer>` for someone who means it.
- Android "switch account" wipes local data knowingly. Nothing adopts silently
  over existing notes.

## Stage 2 — Several accounts on one installation

New `Voice/src/core/accounts.py`, plus resolution in `src/main.py` where `-d` and
`$VOICE_CONFIG_DIR` are handled today.

```
~/.config/voice/
  accounts.db                       index, never synced, mode 0600
  01a0952602bc70808f15a84d31aaa8d2/ notes.db  config.json  audio/  voice.log
  01a09612f4c1718b9e2d71f0c9a4b3e7/ …
```

- `accounts.db`: `accounts(account_id PK, label, directory, is_default, hosted,
  account_key, created_at, last_opened_at)`. The database inside an account
  directory is **authoritative** for its own `account_id`; this table is only an
  index, and a disagreement is reported rather than corrected.
- Flags: `-a|--account-id <id-or-label>` selects from the index;
  `-d|--config-dir` remains an explicit directory; **the two together exit with an
  error**; `$VOICE_ACCOUNT_ID` mirrors `-a` as `$VOICE_CONFIG_DIR` mirrors `-d`.
  The "Using CONFIG_DIR: …" first line gains the account label.
- With no flags: the default account from the index. If the index is absent or has
  no default, one is created and registered, so a first run is never a dead end.
- The **account key** lives in that account's `config.json` (`sync.account_key`),
  because it belongs to the account and is used with every peer.
- Commands: `account list` (marking default and hosted), `account create
  [--label]`, `account default <id|label>`, `account host --id <id> [--label]`
  (registers an account this machine will serve, generating and printing its key),
  `account unhost`, `account remove` (index only; data is deleted only under a
  separate explicit flag), `account key <id> [--rotate]`.
- Audio directories default to `audio/` **inside the account directory**, so two
  accounts never share recordings. The existing absolute `audiofile_directory` is
  left alone for accounts that already have one.

## Stage 3 — One server, several households

`AppState` holds exactly one `Arc<Mutex<Database>>` today (`sync_server.rs:37`).

- `AppState` becomes a map from account id to an opened (database, config), filled
  on demand from `accounts.db` where `hosted = 1`, with a bounded cache.
- **Every request** carries `X-Account-ID` and `X-Account-Key` — routing and
  authentication in the same two headers, which keeps the server stateless; the
  client already sets `X-Device-ID` this way. The handshake's `account_id` field
  stays, so a client can also verify it reached the account it meant to.
- Unknown account → **404**, nothing created. Wrong key → **401**. Both surface as
  sentences: "This server does not host your account", "The account key is wrong —
  pair again with the QR code".
- There is **no authentication today at all**: the server never reads a header, so
  anyone who can reach port 8384 can read and write everything. These two headers
  close that, and they are required on a LAN peer as well as on a public server.
- For the future sign-up website, recorded but **not built**:
  `POST /admin/accounts {account_id, label}` → `{account_key}`,
  `GET /admin/accounts`, `DELETE /admin/accounts/<id>`, with
  `Authorization: Bearer <admin token>` from the server's configuration.
  `account host` is the same code path, so the endpoint becomes a thin wrapper.

## Stage 4 — Peer file transfer over HTTPS

- Expose the existing `download_audio_file` / `upload_audio_file` through both
  binding layers (`android.rs`, `rust/voice-python/src/lib.rs`); only the
  `_from_cloud` variants are exposed now.
- Policy in one place in the core: a missing recording is fetched from a **LAN
  peer first**, then from the bucket; a push offers files to a peer that lacks
  them.
- **Streaming both ways.** An eight-hour recording must not be buffered
  (`TECHNICAL-DECISIONS.md` 3.1). Check the client's write path and the server's
  read path, and fix either if it collects the body in memory.
- `max_sync_file_size_mb` applies to the bucket, not to a LAN transfer.

## Stage 5 — Several sync servers, and the address in plain sight

- Core bindings for the list that already exists: `list_peers`, `add_peer`,
  `remove_peer`, `sync_with_peer(peer_id)`, over UniFFI and PyO3.
- Android (`SyncSettingsScreen.kt`, `SettingsViewModel.kt`): stop keeping
  `server_url` and `server_peer_id` in SharedPreferences and read the core's list.
  **Add additional sync server** at the bottom; with two or more configured, both
  opening the settings and pressing Sync ask which server first.
- Desktop: the same list in the GUI sync dialogue; `cli sync peers` already exists.
- **The About dialogue shows this device's LAN address and port** on both
  platforms (`main_window.py::_show_about`; a new entry in Android's Settings),
  because addresses change and the other device may need it typed.

## Stage 6 — The phone as a listener

- New UniFFI `start_sync_server(port)` / `stop_sync_server()` in `android.rs`,
  wrapping what `start_sync_server` already does for Python.
- Its certificate is generated on the phone by the core's `tls.rs`; the fingerprint
  is shown so the desktop can pin it.
- `SyncListenerService`: a foreground service (type `dataSync`) holding the port,
  with a Stop action, started by a switch on the sync screen. **Never started by
  itself**, so it costs nothing when unused.
- The sync screen shows address, port, peer id and fingerprint as text.

## Stage 7 — Finding each other

1. **mDNS**: the desktop announces `_voicesync._tcp` (Python `zeroconf`, a new
   dependency) with the account id and fingerprint in its TXT record; Android
   browses with `NsdManager`, and announces itself while its listener runs.
2. **Remembered address**: each peer's last known URL, already in the peer config.
3. **Typed by hand**, from the other device's About dialogue.

Every route checks the account id (Stage 1) and the account key (Stage 3), so a
right-looking address belonging to the wrong account is refused, not merged.

## Stage 8 — The S3 wizard

`Voice/src/core/storage_setup.py`, driven by a GUI wizard
(`src/ui/storage_wizard.py`) and an interactive `cli storage setup`:

1. Paste the key id and secret; whitespace and a stray `Access key ID:` prefix are
   trimmed — the commonest failure.
2. A region, defaulting to the nearest by round-trip time.
3. A generated bucket name (`voice-<6 random>`), changeable, created private with
   `s3:CreateBucket`; "name taken" suggests another.
4. Write a small object, read it back, compare, delete it.
5. Save through the existing `storage configure-s3` path — a synced entity, so the
   phone receives it.
6. Failures in words: `403 SignatureDoesNotMatch` → "the secret is wrong, or has a
   space on the end"; `301 PermanentRedirect` → "the bucket is in another region";
   a DNS failure → "check the endpoint".
7. Offer to start the sync server, and to keep it started.

DigitalOcean and Backblaze keep the manual path in `CLOUD-STORAGE-SETUP.md` until
someone has run them in earnest.

## Stage 9 — The QR code

- **Desktop** generates it with `segno` (pure Python, no Pillow, and prints to a
  terminal so the TUI and CLI can show one too). Payload: version, account id,
  **account key**, label, every peer (URL, port, peer id, certificate
  fingerprint), and the storage configuration. Shown only when asked, beside
  "treat this like a password", hidden again after sixty seconds. A **Copy setup
  text** button gives the same payload for a phone with no working camera.
- **Android** reads it with CameraX and ZXing core (pure Java, offline, no Play
  Services — the target market may have neither). New `CAMERA` permission.
- **Every camera in turn, front-facing last**, because a broken camera is common in
  the target market: order `cameraProvider.availableCameraInfos` rear → external →
  front, and move on when one fails to open **or delivers no frame within three
  seconds**. The selection logic sits behind an interface (`CameraChoice` /
  `FrameSource`) so it is testable without hardware
  (`TECHNICAL-DECISIONS.md` 6.7).
- Scanning sets the account id and key, and refuses if the phone already holds
  another account's notes.

## Stage 10 — Proof that it worked

- A line on both platforms: "1,284 recordings · 1,284 in the bucket · last sent 3
  minutes ago", and a warning when anything has been in one place only for more
  than a day — the phone is where that matters.
- The wizard ends by doing it: record on the phone, press Sync, see the note on the
  desktop and the file in the bucket.

---

## Carried into implementation

Raised during planning, agreed as part of the work, listed so they are not lost:

1. **Android sends the key as well as the id**, on every request — not only in the
   handshake, which cannot authenticate `/sync/apply` or a file download.
2. **Key rotation**: `account key --rotate` voids every QR ever generated and
   requires every device to be paired again. Say so where it is offered.
3. **Audio directories per account**, so two people on one machine never share a
   recordings directory.
4. **Keys must never reach the logs.** With the key in a header, request logging
   will print it by default; redact deliberately.
5. **A server needs no account of its own.** `account host` must not make a hosted
   account the default, and a pure server must not be made to create an empty
   default account because `voice` was run with no flags.
6. **Nothing limits disk per account** on a shared server. Not in this work; the
   `account` commands are where it will live.

## Risks and accepted trade-offs

- **The QR holds live credentials** — the S3 keys and the account key. Whoever
  photographs the screen holds them until they are replaced by hand (decision 2).
- **One account key for every peer**: the operator of any server for an account
  holds the key that also opens that account's other peers (decision 6).
- **The S3 key can create buckets**; it can touch nothing else in the account
  (decision 3).
- **A listener on the phone** is a port and a service; off unless switched on.
- `tls.py` and `tls.rs` are two certificate implementations. Not unified here, so
  the fingerprints must be verified to agree.
- `config.json` and `accounts.db` hold secrets in plain text; both at mode 0600.

## Verification

Two rules over all of it: **no test runs against live data** — instrumented
Android tests install as `com.dotancohen.voiceandroid.uitest`
(`TECHNICAL-DECISIONS.md` 7.6) — and **nothing touches the phone before
`VoiceAndroid/tools/voice-phone-backup` has run and verified.**

| What | How |
|---|---|
| Account identity | Rust unit tests: equal, absent-adopts, virgin-adopts, different-refuses, changed-refuses. A mismatched pair in `convergence_tests.rs` asserting nothing is exchanged |
| Accounts layer | `-a` by id and by label; `-a` with `-d` exits non-zero; default selection; a first run with no index; an index whose id disagrees with its database is reported; `-d ~/.config/voice` still opens the 11,429-note database |
| One server, two households | Two accounts hosted on one server, a client each: each sees only its own notes, and `sqlite3` confirms no row crossed. Unknown account → 404; wrong key → 401 |
| Peer file transfer | Two desktops on localhost: a recording on one arrives on the other on demand; a 2 GB file transfers with resident memory flat (measured) |
| Several servers | A LAN peer and a cloud server configured together; selection asked; each syncs independently |
| The phone as listener | On the **emulator**, never the owner's phone: the desktop adds it as a peer, presses Sync, notes arrive |
| Discovery | Desktop announces, phone finds it; block mDNS and confirm the remembered address works; then a wrong address and confirm the account check refuses it |
| The S3 wizard | MinIO in a container for the suite, and once by hand against real Amazon. A bad key, a bad region and a taken bucket name each give their own sentence |
| QR | Payload round-trip: encoded in Python, decoded in Kotlin, against a shared fixture as `transcription_flags_contract.json` is shared. Camera succession with a fake `FrameSource` where cameras 0 and 1 fail. The pasted-text path likewise |
| End to end | A clean emulator install: scan, sync, record, sync; the note on the desktop and the file in the bucket |

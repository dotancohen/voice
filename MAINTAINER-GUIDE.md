# Voice (desktop) — a maintainer's guide

A map of the desktop application `Voice/`: what each part of the code is for,
how the parts call each other, and what is in the database. It is written for
a developer who is new to the project. A term in **bold** at its first use is
defined in the [glossary](#14-glossary) at the end.

Written on 2026-09-13 from the code itself (Voice commit `9086989`, core commit
`987f769`). Checked against the code on 2026-09-14, on branch
`accounts-pairing-sync`: Voice commit `10365ef`, VoiceCore commit `fe788d1`.
Voice's `submodules/voicecore` points at core commit `abedc04`; the three
VoiceCore commits after it change only `CLAUDE.md` and `README.md`. Where a
document says something different from the code, the code was taken as the
truth. The disagreements that remain are listed in
[section 12](#12-where-older-documents-disagree-with-the-code), and defects
found in the code in [section 13](#13-defects-found-in-the-code).

## Contents

1. [The Voice Family in one page](#1-the-voice-family-in-one-page)
2. [The layers of the desktop application](#2-the-layers-of-the-desktop-application)
3. [Directory map](#3-directory-map)
4. [The Python source, file by file](#4-the-python-source-file-by-file)
5. [The Rust core, as the desktop uses it](#5-the-rust-core-as-the-desktop-uses-it)
6. [Files on disk](#6-files-on-disk)
7. [The database](#7-the-database)
8. [How the parts work together](#8-how-the-parts-work-together)
9. [Building, running and testing](#9-building-running-and-testing)
10. [Rules to follow when changing the code](#10-rules-to-follow-when-changing-the-code)
11. [Where to look first](#11-where-to-look-first)
12. [Where older documents disagree with the code](#12-where-older-documents-disagree-with-the-code)
13. [Defects found in the code](#13-defects-found-in-the-code)
14. [Glossary](#14-glossary)

---

## 1. The Voice Family in one page

Four projects live side by side in `VoiceFamily/`:

| Directory | What it is | Language |
|---|---|---|
| `Voice/` | The desktop and server application: a graphical interface, a terminal interface, a command line and a web API | Python 3 |
| `VoiceAndroid/` | The Android application | Kotlin |
| `VoiceCore/` | The shared **core library**: the database, versioning, sync, cloud storage | Rust |
| `VoiceTranscription/` | Speech-to-text (Whisper and online services) | Rust, with Python and Android bindings |

The most important fact for a maintainer: **almost every rule about data is
written once, in Rust, in VoiceCore.** Both applications call the same Rust
code. The Python code draws the screens, reads files, runs transcriptions and
calls the core. When you ask "where is X implemented?", the answer is usually
`Voice/submodules/voicecore/src/`.

```
          Voice (desktop, Python)                    VoiceAndroid (Kotlin)
  GUI (Qt)   TUI (Textual)   CLI   Web API               Compose screens
        \         |          |      /                          |
         src/core/*.py  (Python wrappers)            view models, VoiceRepository
                    |                                          |
    voicecore Python module (PyO3)              uniffi.voicecore (UniFFI, JNA)
    rust/voice-python/src/lib.rs                submodules/voicecore/src/android.rs
                    \                                          /
                     `------------ VoiceCore (Rust) ----------'
                     database.rs  versions.rs  sync_*.rs  file_storage*.rs
                                          |
                          notes.db (SQLite)  +  recording files
```

The core is checked out three times: `Voice/submodules/voicecore`,
`VoiceAndroid/submodules/voicecore` and the standalone `VoiceCore/`. They are
git **submodules** and must point at the same commit
(`TECHNICAL-DECISIONS.md` 7.2; `VoiceFamily/CLAUDE.md`, "One core, three
binding layers").

### Where the rules are written

On 2026-09-14 the documents about more than one project moved from `Voice/` to
`VoiceFamily/`, and `CLAUDE.md` was split into one file for every project and
one per project.

| Document | What it holds |
|---|---|
| `VoiceFamily/TECHNICAL-DECISIONS.md` | Decisions shared by all projects, numbered (for example "3.1a"). Read it before changing any shared behaviour |
| `VoiceFamily/SYNC_SPECIFICATION.md` | Numbered rules of the data model and the sync protocol. An id such as `FILE-22`, `VER-9` or `PURGE-5` in a code comment refers to a rule here. Section 7.1 lists every route of the listener |
| `VoiceFamily/PLAN-ACCOUNTS-PAIRING-SYNC.md` | The plan for accounts, pairing and file transfer, in 16 stages. "Stage 13" in a comment refers to a stage here |
| `VoiceFamily/CLAUDE.md` | Working instructions for every project: tests, naming, the owner's data, the three binding layers, where each document belongs |
| `Voice/CLAUDE.md` | Working instructions for the desktop only: building the Python binding, the interface frameworks, common commands, which document a change belongs in |
| `VoiceCore/CLAUDE.md` | Working instructions for the core: logging, the database, sync, adding a syncable entity type or field, recordings, versioned fields |
| `Voice/USER_MANUAL.md` | How the application is used, interface by interface |
| `Voice/DEVELOPMENT.md`, `Voice/TESTING.md` | Installing, deploying the server, running tests; the test suite |
| `Voice/CONFIGURATION.md`, `Voice/CLOUD-STORAGE-SETUP.md`, `Voice/SECURITY-CONSIDERATIONS.md` | The configuration file; the cloud bucket set up by hand; exposing a server |
| `VoiceFamily/BUGS-THE-TESTS-MISSED.md` | Bugs that shipped although tests existed, and why the tests missed them |
| `VoiceFamily/test-plans/` | Manual test plans for the desktop, the server and the phones together; they drive the phone with voice-adb |

---

## 2. The layers of the desktop application

A call from a button to the database crosses four layers. Using "save a Note"
as the example:

| Layer | File | What happens there |
|---|---|---|
| 1. Interface | `src/ui/note_pane.py` (GUI), `src/tui.py`, `src/cli.py`, `src/web.py` | Reads what the user typed and calls the wrapper |
| 2. Python wrapper | `src/core/database.py`, class `Database` | Converts ids from `bytes` to hex strings and calls the Rust object |
| 3. Binding | `rust/voice-python/src/lib.rs`, `#[pyclass(name = "Database")]` | **PyO3** code that turns Python arguments into Rust values and Rust errors into Python exceptions |
| 4. Core | `submodules/voicecore/src/database.rs` and `versions.rs` | Writes the change to SQLite, records its version, rebuilds the display caches |

### How Python can call Rust

The directory `rust/voice-python/` is a Rust **crate** whose output is a shared
library (`crate-type = ["cdylib"]`, library name `voicecore`). The tool
**maturin** compiles it and installs it into the **virtual environment**
`.venv/`, where Python imports it like any module:

```python
from voicecore import Database as RustDatabase
```

The binding crate depends on the core by path
(`voicecore_lib = { package = "voicecore", path = "../../submodules/voicecore" }`),
so building the binding also compiles the core.

**Consequence:** after any change to Rust code, run `maturin develop --release`
again (see [section 9](#9-building-running-and-testing)). Until then Python
keeps loading the old library and your change does not exist as far as the
application is concerned.

### A module in `src/core/` never imports Qt

Each file in `src/core/` states "This module must have NO Qt/PySide6
dependencies". This is what lets the terminal interface, the command line and
the web API run on a server where PySide6 is not installed. Qt code belongs in
`src/ui/` only.

### Adding a new database function

Three places, in this order (`VoiceFamily/CLAUDE.md`, "One core, three binding
layers"):

1. The function itself: `submodules/voicecore/src/database.rs` (or the module it belongs to). The change is made and committed in `VoiceCore/`; the submodule checkouts are then moved to that commit.
2. The Python binding: a method in `rust/voice-python/src/lib.rs`.
3. The Android binding: a method in `submodules/voicecore/src/android.rs`.

Then, usually, a method on the wrapper class in `src/core/database.py`. A
function that is missing from a binding does not exist on that platform.

---

## 3. Directory map

```
Voice/
├── src/                     the application (section 4)
│   ├── main.py              entry point: chooses the account and the interface
│   ├── cli.py               command-line interface (argparse), 4,724 lines
│   ├── tui.py               terminal interface (Textual), 2,624 lines
│   ├── web.py               web API (Flask), 604 lines
│   ├── ui/                  graphical interface (PySide6 / Qt)
│   └── core/                logic shared by the four interfaces, no Qt
├── rust/
│   ├── Cargo.toml           Rust workspace holding the binding crate
│   └── voice-python/        PyO3 binding: src/lib.rs, 3,487 lines
├── submodules/
│   ├── voicecore/           the Rust core (git submodule)
│   └── voicetranscription/  transcription library; Python binding in bindings/python,
│                            imported as `voice_transcription`
├── tests/                   pytest suite (section 9.4)
├── tools/                   batch_transcribe.py, migrate_from_classic.py
├── bin/voice                shell launcher: runs .venv/bin/python -m src.main
├── requirements.txt         desktop dependencies (Qt, Textual, Flask, zeroconf ...)
├── requirements-server.txt  server dependencies (no Qt)
├── requirements-dev.txt     mypy, black, pytest, pytest-qt, moto[server] ...
├── pyproject.toml           mypy (strict) and black (line length 100) settings
├── pytest.ini               test discovery, markers, coverage options
├── MAINTAINER-GUIDE.md      this file
└── CLAUDE.md, README.md, USER_MANUAL.md, DEVELOPMENT.md, TESTING.md,
    CONFIGURATION.md, CLOUD-STORAGE-SETUP.md, SECURITY-CONSIDERATIONS.md
```

Build output that can be deleted and generated again (`TECHNICAL-DECISIONS.md`
7.5): `htmlcov/`, `.coverage`, `.mypy_cache/`, `.pytest_cache/`. The `.venv/`
directory can also be created again, but then every dependency and the Rust
binding must be installed again.

The older design documents describe earlier stages of the design and are kept
on purpose. Since 2026-09-14 they are in `VoiceFamily/`: `SYNC_PLANNING.md`,
`SYNC_PLANNING-questions.md`, `SYNC_IMPLEMENTATION_PLAN.md`,
`TODO_SYNC_CONFLICTS.md`. `PLAN-ANDROID.md` is in `VoiceAndroid/`. Where they
disagree with `SYNC_SPECIFICATION.md`, the specification is current.

---

## 4. The Python source, file by file

### 4.1 `src/main.py` — what happens at start

1. Parse the arguments. The first positional word chooses the interface:
   `gui`, `tui`, `cli` or `web`. The option `-a/--account` chooses the account.
2. Find the **root** directory: `$VOICE_CONFIG_DIR`, or `~/.config/voice`.
3. Find the account: `-a`, or `$VOICE_ACCOUNT_ID`, or the default account.
   `voicecore.resolve_account(root, selector, create)` returns the account's
   directory, and creates the default account when the root is empty. Two
   kinds of command need no account and never create one: `cli sync serve`,
   and `cli account list|create|default|remove|host`.
4. Start the log file `voice.log` (rotated at 5 MiB, two old files kept).
5. `ensure_own_device_card(...)`: make this installation's device key for the
   account and write its **device card**.
6. Print `Using CONFIG_DIR: ...` as the first line. For `--format json` or
   `csv` this line goes to standard error, so the output stays machine-readable.
   A test that counts output lines must skip this line.
7. With no interface given: the `default_interface` configuration value, else
   the GUI when PySide6 and qdarktheme can be imported, else the TUI. The
   arguments are then parsed a second time with that interface inserted, and
   every value the first parse and step 3 set (the account's directory, the
   root, the label) is copied onto the new result. Without that copy the
   interface started without its account
   (`tests/unit/test_main_without_an_interface.py`).
8. Run the interface: `run_gui` (in `main.py`), `tui.run`, `cli.run` or `web.run`.

`run_gui` opens `Config`, opens `Database(database_file)`, calls
`reconcile_transcription_settings` (section 7.5), creates the `QApplication`,
applies the dark or light theme and shows `MainWindow`.

### 4.2 The graphical interface: `src/ui/` (PySide6 / Qt)

`MainWindow` (`main_window.py`) is three panes side by side in a `QSplitter`:
Tags on the left, the list of Notes in the middle, the open Note on the right.
At start it calls `db.settle_file_names(audio directory)`, which renames
recording files on disk when a sync changed their names (FILE-15).

| File | Purpose |
|---|---|
| `main_window.py` | The window, its menu bar (File → Issues... opens `IssuesDialog`), and the connections between the three panes |
| `tags_pane.py` | The Tag tree; selecting a Tag filters the Note list |
| `notes_list_pane.py` | The Note list and search box; draws rows from `notes.di_cache_note_list_pane_display` |
| `note_pane.py` | One Note: text, Tags, Recordings, Transcriptions, the conflict banner; reads `notes.di_cache_note_pane_display`. Shows where a Recording's copies are (after `check_files_here`, section 8.7) and removes this computer's copy after a Yes/No question |
| `audio_player_widget.py` | Waveform drawing (`WaveformWidget`) and the player. The Recording list has a context menu, "Where are the copies?" and "Remove from this device", which emits `locations_requested` or `remove_local_requested` |
| `transcription_widget.py` | A Transcription's text and its five flags |
| `transcription_dialog.py` | Choosing a transcription service and its options |
| `transcription_queue_dialog.py` | The queue of Recordings waiting to be transcribed |
| `tag_management_dialog.py` | Adding Tags to one Note |
| `tag_hierarchy_dialog.py` | Creating, renaming and moving Tags |
| `trash_dialog.py` | Deleted Notes: recover, or purge for good |
| `version_dialogs.py` | A field's history, and resolving a conflict |
| `issues_dialog.py` | `IssuesDialog`: the Issues list (section 8.8) as a tree, read again by the Refresh button |
| `sync_dialog.py` | Sync, deliver, exchange, send and fetch with a peer, in a `QThread` so the window stays responsive |
| `storage_wizard.py` | Step-by-step creation of the S3 bucket |
| `styles.py` | Shared style sheet fragments |

### 4.3 The terminal interface: `src/tui.py` (Textual)

One file. `VoiceTUI(App)` is the application. Its screens are
`TagManagementScreen`, `HistoryScreen`, `TrashScreen`,
`TranscriptionQueueScreen`, `ResolveConflictScreen` and `IssuesScreen`; its
widgets are `TagsTree`, `NotesList`, `NoteDetail`, `TUIAudioPlayer` and
`TUITranscriptionBox`. `detect_rtl` and `make_rtl_text` lay out Hebrew text
right to left. It runs over SSH on a server.

Keys added on 2026-09-14: **F8** opens `IssuesScreen` (F5 reads the list again,
Escape closes it); **w** shows, as a notification, where the copies of the
Recording the player is on are; **x** removes this computer's copy of that
Recording on the second press.

### 4.4 The command line: `src/cli.py` (argparse)

`add_cli_subparser` (from about line 3530) declares every command; each
command is carried out by a `cmd_...` function earlier in the file. Groups
with subcommands:

| Group | Subcommands |
|---|---|
| `sync` | `status`, `discover`, `check`, `list-peers`, `add-peer`, `remove-peer`, `rename-peer`, `now`, `conflicts`, `resolve`, `serve`, and one command per operation (deliver, exchange, send, fetch) |
| `account` | `show`, `list`, `create`, `default`, `remove`, `show-code`, `hide-code`, `recording-key export/import`, `host`, `grant`, `join`, `snapshots`, `snapshot`, `backup`, `restore`, `move` |
| `storage` | `status`, `setup`, `replace-key`, `check`, `upload-pending`, `download-missing`, `mirror`, `encrypt`, `reupload-encrypted`, `disable`, `upload-limit [megabytes]` (the account's upload limit, section 8.8), and the S3 settings |
| `device` | `list`, `revoke` |
| `config` | `show`, `get`, `set` (the local `config.json`) |
| `settings` | `list`, `get`, `set` (the synced settings) |

There are also single commands for Notes, Tags (`tag-rename`, `tag-move`),
Recordings, transcription, the trash and maintenance. Among them:
`audiofile-show <id>` prints a `Copies:` section (where each copy is),
`audiofile-remove-local <id>` removes this device's copy (exit status 1 when
refused), and `issues` prints the Issues list (`--format json` prints the
core's dictionary). Run `bin/voice cli --help` and
`bin/voice cli <command> --help` for the complete, current list; the help text
is the maintained reference.

### 4.5 The web API: `src/web.py` (Flask)

A JSON API with these routes: `/api/notes` (GET, POST),
`/api/notes/<note_id>` (GET, PUT, DELETE), `/api/notes/<note_id>/attachments`,
`/api/audiofiles/<audio_id>`, `/api/audiofiles/<audio_id>/locations` (GET),
`/api/audiofiles/<audio_id>/remove-local` (POST; 409 when no other place holds
the file), `/api/issues` (GET), `/api/storage/upload-limit` (GET, and PUT with
`{"megabytes": n}`), `/api/tags`, `/api/search`, `/api/trash`,
`/api/trash/<note_id>/recover`, `/api/trash/<note_id>` (DELETE),
`/api/transcription-queue` (GET, POST) with `/next`, `/remove`, `/clear`,
`/api/maintenance/missing-data` (GET, POST), `/api/health`.

This is not the sync server. The sync server is Rust (section 5).

### 4.6 `src/core/` — logic shared by the four interfaces

| File | Purpose |
|---|---|
| `database.py` | Wrapper around `voicecore.Database`. Accepts ids as `bytes` or hex, reports this computer's timezone to the core when a database is opened. Since 2026-09-14 also `file_locations`, `check_files_here`, `remove_local_copy`, `max_upload_bytes`, `set_max_upload_mb`, `issues` |
| `config.py` | Wrapper around `voicecore.Config` (`config.json`) |
| `models.py` | Frozen dataclasses `Note`, `Tag`, `NoteAttachment`, `AudioFile`; `AUDIO_FILE_FORMATS`, read from the core |
| `audiofile_manager.py` | Copies an imported file into the audio directory under its `disk_name`, never overwriting; reads a file's creation date from the filesystem or its name |
| `audio_player.py` | Playback through `mpv` |
| `waveform.py` | Decodes audio with `ffmpeg` into waveform bars in bounded memory; "large recording" limits (60 minutes or 100 MiB) |
| `transcription_service.py` | Runs a transcription in a background thread: `local_whisper`, `speechtext_ai`, `google`; records timing in `service_response` |
| `transcription_queue.py` | The queue file `transcription_queue.json`: one transcription at a time, visible to all four interfaces |
| `transcription_backlog.py` | `cli transcribe-backlog`: long Recordings the phone refused to transcribe |
| `transcription_flags.py` | The five flags (`original`, `verified`, `verbatim`, `cleaned`, `polished`) and their wording |
| `synced_settings.py` | Keeps `config.json` and the synced settings in agreement at start |
| `search.py` | Parses search input (`tag:Work`, `is:marked`, free text) and runs it |
| `conflicts.py` | Python view of conflicts and field versions |
| `note_editor.py` | `NoteEditorMixin`, shared by the GUI and TUI Note views |
| `cloud_storage.py` | Download from the bucket, and the "missing, in cloud" status |
| `storage_setup.py` | The steps of the bucket wizard, shared by the CLI and the GUI. A refused bucket creation suggests another name only when the service's sentence says the name is taken |
| `issues_text.py` | The sentences of the Issues list and of where a Recording's copies are, used by the CLI, the GUI and the TUI: `size_words`, `place_names`, `place_label`, `issue_sections`, `location_lines`. The web API returns the core's dictionaries instead |
| `discovery.py` | Finding peers on the local network with **zeroconf** (`_voicesync._tcp`) |
| `missing_data.py` | Survey and calculation of facts that were never recorded (lengths, dates, caches) |
| `timestamp_utils.py` | Formatting a timestamp at its own offset; this computer's timezone |
| `validation.py` | Id, Tag name and search query checks |

---

## 5. The Rust core, as the desktop uses it

Files in `submodules/voicecore/src/`, largest first (line counts of 2026-09-14):

| File | Lines | Purpose |
|---|---|---|
| `database.rs` | 9,382 | Opening the database, creating and migrating tables, every query, the display caches, the change feed, snapshots, where each copy of a Recording is (`file_locations`), the account's upload limit |
| `sync_server.rs` | 4,879 | The HTTP server peers connect to (`/sync/...`, `/pair/...`), built on **axum** |
| `android.rs` | 2,820 | The Android binding (not used by the desktop) |
| `versions.rs` | 2,615 | Versioned fields: history, heads, merges, conflicts (section 7.4) |
| `sync_client.rs` | 2,286 | The side that connects: sync, deliver, exchange, send, fetch, join |
| `file_storage.rs` | 1,561 | Upload to and download from the bucket; skips files over the upload limit; states the bucket's and this device's copies |
| `config.rs` | 1,335 | `config.json`: device id and name, peers, keys, backup, audio directory |
| `validation.rs` | 806 | Checks on ids, names, timestamps |
| `models.rs` | 781 | Entity structs, attachment types, the audio format list, recording file names |
| `bucket_setup.rs` | 755 | Creating and hardening an S3 bucket; the core's own signed requests (`signed`, `send_signed_watched`, `get_signed_stream`); `explain_error` and `explain_refusal` |
| `file_storage_s3.rs` | 485 | Bucket upload of a small file or of parts, download, and the existence check, each as a signed request of `bucket_setup.rs` |
| `sync_apply.rs` | 419 | Applying one batch of changes from a peer |
| `accounts.rs` | 413 | The index of accounts on one installation (`accounts.db`) |
| `crypto.rs` | 405 | Encryption of Recordings in the bucket (AES-256-GCM) |
| `search.rs` | 394 | Search |
| `issues.rs` | 387 | The Issues list (ISSUE-1), calculated at every call and never stored |
| `merge.rs` | 382 | Merging Notes |
| `pairing.rs` | 342 | Pairing codes and setup texts |
| `sync_protocol.rs` | 309 | Request and response types, error codes |
| `tls.rs` | 296 | Self-signed certificates for the server |
| `auth.rs` | 248 | Device keys and device cards |
| `transfer.rs` | 210 | Streaming a file between peers; `stall_of_upload`, which ends an upload that stops moving (section 8.9) |
| `timezone.rs` | 127 | The local timezone reported by the application |
| `error.rs` | 126 | `VoiceError` |
| `waveform.rs` | 78 | Waveform levels kept with a Recording |
| `conflicts.rs` | 61 | Conflict types |
| `convergence_tests.rs`, `timezone_tests.rs` | — | Tests only |

**Cargo features** (`Cargo.toml`) choose what is compiled: `server`, `desktop`
and `file-storage` are on by default; `uniffi` is added for Android.
`file-storage` also brings in `tokio-util`, for the watched upload bodies.

**Shared build directory.** `VoiceFamily/.cargo/config.toml` makes every Rust
crate in the family build into `VoiceFamily/.cargo-target/`
(`TECHNICAL-DECISIONS.md` 7.4). A built tool is at
`.cargo-target/release/<tool>`, not under the crate's own directory.

---

## 6. Files on disk

### 6.1 The root and its accounts

```
~/.config/voice/                    the root ($VOICE_CONFIG_DIR replaces it)
├── config.json                     machine settings: device id and name, listen port, backup, public URL
├── accounts.db                     index of accounts (SQLite, never synced)
├── certs/                          the server's TLS certificate
├── backups/<account id>/           periodic database backups (default)
└── <account id>/                   one directory per account
    ├── notes.db                    the database (plus notes.db-wal and notes.db-shm while open)
    ├── config.json                 the account's local settings
    ├── audio/                      Recording files
    ├── snapshots/                  up to five copies of notes.db (section 8.6)
    ├── voice.log                   the log
    └── transcription_queue.json    the transcription queue of this machine
```

A root that holds one database and no `accounts.db` is itself the account
(`src/main.py`). The audio directory is the value `audiofile_directory` in the
account's `config.json`.

### 6.2 Three kinds of setting

| Where | Synced? | Examples |
|---|---|---|
| `config.json` (local file) | Never | Paths, Whisper model, port, colours, `sync.mirror_audio_files`, `sync.max_sync_file_size_mb` (the listener's body limit for its JSON routes), the device key |
| Table `synced_settings` (through versions) | Yes | `transcription.preferred_languages`, `transcription.providers.<provider>.api_key`, `tag_color.<name>` |
| Table `file_storage_config` | Yes | The bucket's provider, name, region and credentials, `encrypt`, and `max_upload_mb` (the account's upload limit) |

---

## 7. The database

### 7.1 Basic facts

- **One SQLite file per account**, `notes.db`. SQLite is a database stored in
  one ordinary file, with no server process.
- It is opened by `Database::new` in `database.rs`, which sets **WAL** journal
  mode, sets `busy_timeout` to 10 seconds (a second connection waits instead of
  failing with "database is locked"), and then runs every **migration** in a
  fixed order:

```
init_database                        the original tables, indexes and system Tags
migrate_add_sync_received_at
migrate_timestamps_to_unix           text dates became Unix seconds
migrate_add_storage_columns
migrate_add_file_storage_config_table
migrate_drop_legacy_conflict_tables  the six old conflicts_* tables
create_version_tables                field_versions, field_heads ... (versions.rs)
migrate_create_root_versions
migrate_add_sync_sequence            seq columns, triggers, most newer tables and columns,
                                     including file_locations and audio_files.size_bytes
migrate_add_timezone_columns
```

- **There is no schema version number.** Each migration checks whether its
  table or column already exists and skips that step when it exists. Opening a
  database twice is therefore harmless. To add a column, add a
  "check, then `ALTER TABLE`" step to a migration function.
- **Ids** are **UUID7** values stored as 16-byte **BLOB**s. The applications
  show them as 32 lowercase hexadecimal characters with no hyphens. In the
  version tables, `entity_id` is stored as that text instead.
- **Timestamps** are `INTEGER` seconds since 1970-01-01 UTC (Unix time). Every
  user-visible timestamp `x` has two more columns: `x_offset` (seconds east of
  UTC where it happened) and `x_zone` (the IANA name, such as
  `Asia/Jerusalem`). A Note made at 15:20 in Jerusalem shows 15:20 anywhere.
  Sync bookkeeping (`sync_received_at`, `seq`, `last_sync_at`) and
  `storage_uploaded_at` have no zone columns. `file_locations.changed_at` is in
  milliseconds.
- **Nothing is deleted by an ordinary delete.** Deleting sets `deleted_at` (a
  **soft delete**): the row, its history and its files stay, and the Note waits
  in the trash. Only a **purge**, asked for from the trash, removes rows.
- **Foreign keys** are declared but SQLite does not enforce them unless a
  connection turns them on; the code does not rely on them.

### 7.2 How the user's data relates

```
                       tags ──┐ parent_id (a Tag inside another Tag)
                        ▲     │
                        │ ◄───┘
                   note_tags             (link: one row per Note and Tag)
                        │
notes ──────────────────┘
  │
  └── note_attachments ──(attachment_id, attachment_type = 'audio_file')──► audio_files
                                                                               │
                                                              transcriptions, file_locations
```

- A Note has any number of Tags, through `note_tags`.
- A Note has any number of Attachments. `note_attachments` is a
  **polymorphic association**: `attachment_type` says which table
  `attachment_id` points into. Today the only type in use is `audio_file`
  (`summary` is reserved in `models.rs`). There is no foreign key from
  `attachment_id`, because it may point into different tables.
- A Recording (`audio_files` row) has any number of Transcriptions, and one
  `file_locations` row per place that has stated whether it holds the file
  (section 8.7).
- `notes.primary_attachment_id` names the Attachment that stands for the Note,
  and `audio_files.primary_transcription_id` the Transcription that stands for
  the Recording. Empty means "the oldest one" (PRIMARY-1 to PRIMARY-3).

### 7.3 Tables of the user's data

Every table in this section also has `seq`, `sync_received_at`, and the
`_offset`/`_zone` pair for each of its timestamps.

**`notes`** — one row per Note.

| Column | Meaning |
|---|---|
| `id` | UUID7 |
| `content` | The text. A copy of the head of the versioned field `note.content` |
| `created_at`, `modified_at`, `deleted_at` | When it was created, last changed, moved to the trash |
| `primary_attachment_id` | Section 7.2 |
| `di_cache_note_pane_display` | Cache, JSON: `tags` (id, name, full path), `conflicts` (kinds), `attachments` (with Recordings and Transcriptions), `cached_at` |
| `di_cache_note_list_pane_display` | Cache, JSON: `date`, `marked`, `content_preview`, `duration_seconds`, `tags`, `cached_at` |

**`tags`** — `id`, `name`, `parent_id` (NULL at the top level), the three
timestamps. Two Tags may share a name under different parents.

**`note_tags`** — `note_id`, `tag_id` (together the **primary key**), the
three timestamps. Removing a Tag from a Note sets `deleted_at`; the row stays.

**`note_attachments`** — `id`, `note_id`, `attachment_id`, `attachment_type`,
`device_id` (the device that made the link), the three timestamps.

**`audio_files`** — one row per Recording.

| Column | Meaning |
|---|---|
| `filename` | The name the file had when it was imported or recorded |
| `disk_name` | The file's name in the audio directory, the same on every device (TECHNICAL-DECISIONS 3.1a). **The only way to find the file** |
| `imported_at`, `file_created_at` | When it entered Voice; when the recording was made |
| `duration_seconds` | Length, when known |
| `summary` | Versioned text |
| `device_id` | The device that created the row |
| `content_sha256` | SHA-256 of the file's bytes; also the bucket object's name |
| `size_bytes` | The file's size, written together with the content hash, synced, and never changed once known (FILE-23). NULL until a device has measured the file |
| `storage_provider`, `storage_key`, `storage_uploaded_at` | Set after an upload to the bucket; NULL means not uploaded |
| `storage_encrypted` | 1 when the bucket object is encrypted |
| `waveform_levels` | The levels a waveform is drawn from, kept by the first device that decoded the file (FILE-20) |
| `primary_transcription_id` | Section 7.2 |

**`transcriptions`** — one row per Transcription of a Recording.

| Column | Meaning |
|---|---|
| `audio_file_id` | The Recording |
| `content` | The text. `Pending...` while running; starts with `Error:` when it failed |
| `content_segments` | JSON: pieces of text with their start and end times |
| `service` | For example `local_whisper`, `speechtext_ai`, `google` |
| `service_arguments` | JSON: model, language and other options |
| `service_response` | JSON: what the service returned, plus the cost of the run (clock time, processor time, peak memory) |
| `state` | The five flags, space-separated; `!` in front means "not". Default: `original !verified !verbatim !cleaned !polished`. The column keeps the name `state` because renaming a synced column is expensive (TECHNICAL-DECISIONS 1.4) |
| `device_id` | The device that made it |

**System Tags.** `init_database` creates four Tags whose ids are the same on
every device, so sync never duplicates them:

| Tag | Id | Purpose |
|---|---|---|
| `_system` | `a1b2c3d4-0000-5000-8000-000000000001` | Parent of the hidden Tags |
| `_system/_marked` | `...0002` | The star on a Note |
| `_system/_nonsynced` | `...0003` | Parent of Tags for items that are not synced |
| `_system/_nonsynced/_too-big` | `...0004` | Recordings larger than `max_sync_file_size_mb` |

### 7.4 The version history (`versions.rs`)

**The idea.** The rule of the project is that nothing the user wrote is ever
lost, not even when two devices changed the same thing while offline
(TECHNICAL-DECISIONS 1.1). So every editable value is kept like a small Git
repository: a chain of immutable **versions**, and a **head** that is the
current value. The columns in `notes`, `tags` and so on are copies of the
heads, kept for speed.

| Table | Purpose |
|---|---|
| `field_versions` | Every version ever written, never changed and never deleted. `entity_type`, `entity_id`, `field`, `content` (the value), `parent_id` (the version it was written on top of), `merge_parent_id` (the second parent of a merge), `conflict_kind`, `context` (for a deletion: what the deleting device saw), `device_id`, `device_name`, `created_at`, `published` |
| `field_heads` | One row per field: `head_id`, the version that is the current value |
| `field_conflicts` | One row per merge that needs the user: the base, side A, side B, the merge version, both devices, `resolved_at` |
| `field_deferred` | Fields whose row could not be written yet (for example a Tag link that arrived before its Note); tried again after each batch |
| `synced_settings` | Copies of the heads of `setting.value`: `key`, `value`, `modified_at` |
| `devices` | Copies of the heads of each device card: `device_id`, `name`, `certificate_fingerprint`, `addresses`, `listens`, `key_hash`, `revoked`, `application` |

**Which fields are versioned** (`FIELD_REGISTRY` in `versions.rs`), and how
two concurrent changes are merged:

| Entity | Fields | Merge kind |
|---|---|---|
| `note` | `content` / `primary_attachment` / `deleted` | Text / Scalar / Deleted |
| `transcription` | `content` / `state` / `deleted` | Text / Flags / Deleted |
| `audio_file` | `summary` / `primary_transcription` / `deleted` | Text / Scalar / Deleted |
| `tag` | `name`, `parent` / `deleted` | Scalar / Deleted |
| `note_tag` | `active` (entity id is `<note id>:<tag id>`) | Membership |
| `note_attachment` | `active` | Membership |
| `setting` | `value` (entity id is the setting key) | Scalar |
| `device` | `name`, `certificate_fingerprint`, `addresses`, `listens`, `key_hash`, `application` / `revoked` | Scalar / Membership |

| Merge kind | When both devices changed it differently |
|---|---|
| Text | A **three-way merge** (diff3). Edits to different lines combine silently; edits to the same lines keep both, between `<<<<<<< VERSION A` and `>>>>>>> VERSION B`, and a conflict is recorded |
| Scalar | The later value is shown; a conflict is recorded |
| Flags | Merged flag by flag |
| Membership | The link stays attached; a conflict is recorded |
| Deleted | The item stays alive; a conflict is recorded |

**An example.** The phone and the desktop both edit the same Note while
offline. Each writes a version whose parent is the old head. After a sync
each device holds two **leaves**. Each device merges them against their common
ancestor and gets the same merge version, because merge ids are hashes of
their inputs. The Note shows both texts between conflict markers, and a
`field_conflicts` row appears. When the user edits the text or presses
"Accept merge", a new version descends from the merge and the conflict is
resolved on every device after the next sync.

**The rule that follows for you:** never change an editable value with plain
SQL. Every write goes through `set_field`, `set_deleted` or `init_field`
(SYNC_SPECIFICATION DM-1). A plain `UPDATE notes SET content = ...` changes
the copy but not the history, and the next recomputation of the head puts the
old value back, or sends a wrong row to every peer.

Values that are written by the machine rather than typed by the user
(`filename`, `duration_seconds`, `service_response` and similar) are not
versioned. When a row arrives from a peer they are merged column by column:
the row with the newer `modified_at` wins a column (DM-4). `file_locations`
rows are not versioned either; they have a rule of their own (section 8.7).

### 7.5 Tables for sync

| Table | Purpose |
|---|---|
| `sync_sequence` | One row holding a counter for the whole database |
| `seq` column | On `field_versions`, `notes`, `tags`, `note_tags`, `note_attachments`, `audio_files`, `transcriptions`, `file_storage_config`, `purges`, `file_locations`. **Triggers** set it from the counter when a row is inserted, or when a synced column really changed. Cache columns never change it |
| `sync_meta` | Key/value: `database_id` (a random id; a new one means the database was replaced) and `account_id` |
| `sync_peers` | One row per peer: `peer_id`, `peer_name`, `peer_url`, `certificate_fingerprint`, `last_sync_at`, `last_received_cursor`, `last_sent_seq`, `peer_database_id`, `peer_account_id`, `last_operation`, `peer_entity_types`, and older timestamp columns |
| `sync_failures` | Changes from a peer that could not be applied, kept and tried again at the next batch |
| `purges` | Everything ever purged: `entity_type`, `entity_id`, `purged_at`, `device_id`. Kept for ever, so a peer that has not heard of the purge cannot bring the item back |
| `file_storage_config` | One row (`id = 'default'`): the bucket settings, as JSON in `config` |
| `file_locations` | Where each copy of a Recording is: `audio_id`, `place` (a device id or `cloud`), `present`, `changed_at` (milliseconds), `changed_by`, `sync_received_at`; primary key `(audio_id, place)` (section 8.7) |

**What a sync sends** is every row and version whose `seq` is above what the
peer has already received: the entity types `note`, `tag`, `note_tag`,
`note_attachment`, `audio_file`, `transcription`, `file_storage_config`,
`field_version`, `purge` and `file_location` (`ALL_SYNC_ENTITY_TYPES` in
`sync_apply.rs`; SYNC_SPECIFICATION PROTO-1). A `file_location` change has the
entity id `<audio id>:<place>`. Synced settings and device cards travel as
`field_version` changes.

### 7.6 Tables that never leave this device

| Table | Purpose |
|---|---|
| `pairing_offers` | The hash of a pairing code while it is valid, its expiry, failed attempts |
| `audio_file_copies` | Which peer was known to hold which Recording. Replaced by `file_locations`: nothing writes it any more, and it is read once, by the migration that first creates `file_locations` |
| `upload_parts` | Journal of an upload in parts, so an interrupted upload continues |
| `pending_file_renames` | A Recording whose file must still be renamed on disk |
| `purged_objects` | Bucket objects deleted by a purge |

In the separate file `accounts.db` (the root's index): `accounts`
(`account_id`, `label`, `is_default`, `hosted`, `created_at`,
`last_opened_at`) and `hosting_offers`.

### 7.7 Reading a database safely

The owner's database has no second copy. **Never open the live `notes.db` for
writing, and never write to any database with plain SQL.** To look inside:

1. Make a copy. `bin/voice cli account snapshot` writes one into
   `snapshots/` through SQLite's backup API. Or close every Voice process and
   copy `notes.db`, `notes.db-wal` and `notes.db-shm` together (a copy of
   `notes.db` alone can miss the latest changes, which may still be in the
   `-wal` file).
2. Open the copy read-only: `sqlite3 -readonly copy.db`.

Useful queries:

```sql
-- The 20 newest Notes that are not in the trash
SELECT lower(hex(id)) AS id,
       datetime(created_at, 'unixepoch') AS created_utc,
       substr(content, 1, 60) AS start
FROM notes
WHERE deleted_at IS NULL
ORDER BY created_at DESC
LIMIT 20;

-- The Tags of one Note (paste the id as hexadecimal after X)
SELECT t.name
FROM note_tags nt JOIN tags t ON t.id = nt.tag_id
WHERE nt.note_id = X'0190a1b2c3d47e5f8a9b0c1d2e3f4a5b'
  AND nt.deleted_at IS NULL;

-- The history of a Note's text (entity_id is lowercase hexadecimal text)
SELECT lower(hex(id)), lower(hex(parent_id)), device_name,
       datetime(created_at, 'unixepoch'), substr(content, 1, 40)
FROM field_versions
WHERE entity_type = 'note' AND field = 'content'
  AND entity_id = '0190a1b2c3d47e5f8a9b0c1d2e3f4a5b'
ORDER BY created_at;

-- Open conflicts
SELECT entity_type, entity_id, field, kind, device_a_name, device_b_name
FROM field_conflicts
WHERE resolved_at IS NULL;

-- Where the copies of one Recording are, as last stated
SELECT place, present, datetime(changed_at / 1000, 'unixepoch'), lower(hex(changed_by))
FROM file_locations
WHERE audio_id = X'0190a1b2c3d47e5f8a9b0c1d2e3f4a5b';
```

---

## 8. How the parts work together

### 8.1 Editing a Note

1. The interface calls `Database.update_note(note_id, content)` in `src/core/database.py`.
2. The binding calls `update_note` in `database.rs`.
3. The core writes a `field_versions` row (parent: the current head, device:
   this one), recomputes the head, and copies it into `notes.content` and
   `notes.modified_at`.
4. The display caches of the Note are rebuilt.
5. The update trigger gives the row and the version new `seq` numbers, so they
   are in the feed at the next sync.

### 8.2 Importing a Recording

`cmd_import_audiofiles` in `src/cli.py` (line 417):

1. `db.create_audio_file(name, file_created_at, audio_dir)`: the core creates
   the row and decides `disk_name`. An imported file keeps its own name; a
   name that is already taken gets a suffix from the Recording's id.
2. `AudioFileManager.import_file(path, disk_name)` copies the file into the
   audio directory. It refuses to overwrite a file.
3. `db.store_content_hash(audio_file_id, audio_dir)` stores the SHA-256 and the
   file's size (`size_bytes`).
4. A Note is created, and `db.attach_to_note(note_id, audio_file_id, "audio_file")` links the two.

### 8.3 Transcribing

1. A request adds the Recording to `transcription_queue.json`
   (`transcription_queue.enqueue`). One transcription runs at a time
   (TECHNICAL-DECISIONS 3.5).
2. `TranscriptionService.transcribe_async` creates a Transcription whose text
   is `Pending...`, then runs the service from the `voice_transcription` module
   in a background thread.
3. When it finishes, the row receives the text, the segments and
   `service_response`, including the time and memory the run took. Estimates of
   waiting time are calculated from these measurements, never invented.

### 8.4 Sync, and moving files

The words have exact meanings (TECHNICAL-DECISIONS 4.5), in code and in the
interface:

| Word | Meaning |
|---|---|
| **Sync** | Exchange database changes with a peer, both directions. No file moves |
| **Upload** / **Download** | Copy Recording files to / from the S3 bucket |
| **Send** / **Fetch** | Copy Recording files to / from another Voice installation |
| **Deliver** | Sync, then send |
| **Exchange** | Sync, then send and fetch |
| **Listen** | Accept connections from peers |
| **Host** | Serve an account that is not this device's own |
| **Pair** | Give a fresh device the account's id, a key of its own and one peer |

Every one of these runs only when the user asks. The one automatic action is
the periodic database backup.

**A sync, step by step** (`sync_with_peer` in `sync_client.rs`, SYNC_SPECIFICATION FLOW-1):

1. Compare this device's audio directory with what it has stated about its
   copies (`check_files_here`, section 8.7), so the push carries a file that
   was deleted by hand.
2. `POST /sync/handshake`: identities, protocol version `2.0`, the account, the key.
3. If the peer's `database_id` differs from the stored one, both cursors restart from zero.
4. **Pull:** `GET /sync/changes?cursor=N` page by page (at most about 4 MB each).
   Each page is applied in one transaction (`sync_apply.rs`), then the cursor is saved.
5. **Push:** this device's changes since `last_sent_seq`, page by page, through `POST /sync/apply`.
6. Record the time and the operation in `sync_peers`.

An interrupted sync continues from the last saved cursor. Applying the same
page twice changes nothing (it is **idempotent**).

**The listener** is `bin/voice cli sync serve` (default port 8384) or "Listen
for peers" in the GUI. It starts the Rust server in `sync_server.rs` over
HTTPS with a self-signed certificate, which a peer remembers at its first
connection (**TOFU**). Peers on the same network find each other by zeroconf.

**Files between installations** (FILE-12, FILE-13): `POST /sync/audio/missing`
tells the sender which Recordings the receiver lacks and how many bytes of each
it already holds; `GET` and `POST /sync/audio/:id/file` stream the bytes,
resume after an interruption, and verify the SHA-256. The receiver of a whole
file states that it holds the file and that the sender holds it; a fetcher
states the same (section 8.7).

**Files and the bucket:** the object is named by the content hash, so two
devices that import the same file share one object. Files over 8 MiB
(`PART_SIZE`) are uploaded in parts, journalled in `upload_parts`; a smaller
file is read into memory and sent in one request. Objects may be encrypted
(`crypto.rs`, TECHNICAL-DECISIONS 3.1c). How long each request may take is in
section 8.9.

### 8.5 Pairing

A device shows a code (a QR code or a setup text `voice://pair?...`) that
carries a single-use token valid for ten minutes (`pairing_offers`). The new
device claims it (`/pair/claim`, `/pair/grant`) and receives the account id,
its own device key and one peer. A device keeps its own key in its
`config.json`; every other device knows only the key's hash, from the synced
device card. The setup text carries the listener's certificate fingerprint as
`&f=`, when the offer finds the certificate (see section 13.1, item 1).

### 8.6 Snapshots and backups

- **Snapshot** (SNAP-1 to SNAP-4): a copy of `notes.db` in `snapshots/`,
  named `notes-<UTC time>.db`, taken before applying anything from a peer,
  before moving to another account and before a restore. The newest five are
  kept. Recordings are not included.
- **Backup** (SNAP-5): every `backup.interval_hours` (default 24, 0 turns it
  off) into `backup.directory` (default `<root>/backups/<account id>/`),
  keeping `backup.keep` copies (default 30). It runs inside the listener and
  inside the open desktop application; `account backup` runs it at once.

### 8.7 Where each copy of a Recording is (FILE-22)

Each row of `file_locations` is a statement: "this place holds this
Recording's file" or "no longer holds it". A place is a device of the account
(its id, 32 hexadecimal characters) or `cloud` (`PLACE_CLOUD`, the bucket).

- **Which statement wins.** `apply_sync_file_location` keeps the statement with
  the newer `changed_at`; at equal times the larger `changed_by`; then the one
  that says present. Every device therefore keeps the same rows, whatever order
  they arrive in. Statements about different places never conflict, so a
  device that removes its copy while another uploads the file keeps both facts.
- **Who writes a statement** (`set_file_location(audio_id, place, present)`,
  which writes nothing when the statement repeats the current one):
  - this device, after it receives a file whole (`receive_audio_file` in
    `sync_server.rs`), fetches one, or downloads one from the bucket;
  - the sender or fetcher, about the peer (`record_copy`); the peer's own
    newer statement replaces it;
  - `check_files_here(audio_dir, here)`, which compares the audio directory
    with this device's statements and returns (now here, now gone). It runs
    before each sync, at every Issues list, and when "Where are the copies?"
    is asked for. A directory that does not exist states nothing;
  - the bucket's row: an upload (`update_audio_file_storage`) states present,
    clearing an upload states absent, and a download that finds no object
    states absent.
- **Removing this device's copy**: `remove_local_copy(audio_id, audio_dir, here)`
  deletes the file and states it gone. It is refused when no other place holds
  the file. GUI: the Recording's context menu; TUI: `x` twice; CLI:
  `audiofile-remove-local`; web: `POST /api/audiofiles/<id>/remove-local`.
- **A purge** deletes the Recording's `file_locations` rows.
- **An older database**: when the migration first creates the table, it writes
  `cloud` rows for uploaded Recordings and peer rows from `audio_file_copies`.
  Nothing on disk is read.
- `copies_of(audio_id, here)` and `not_duplicated(audio_dir, here)` read these
  rows. The `here` argument is this device's id; the Python binding takes it
  from the process when it is not given.

### 8.8 The account's upload limit, and Issues (FILE-23, ISSUE-1)

**The upload limit** is `max_upload_mb` inside the synced storage
configuration (`file_storage_config.config`), so it is the same on every device
of the account. `max_upload_bytes` returns 100 MB (`DEFAULT_MAX_UPLOAD_MB`)
when it is not set. `set_max_upload_mb` refuses 0, and refuses when no bucket
is configured. `upload_files_with` in `file_storage.rs` compares each file's
size on disk with the limit, leaves a larger file where it is, and counts it in
`too_large`. The per-device `sync.max_sync_file_size_mb` is only the
listener's body limit for its JSON routes. The limit is shown and set by
`cli storage upload-limit [megabytes]` and `GET`/`PUT /api/storage/upload-limit`;
the GUI and the TUI have no control for it.

**Issues** is `issues::issues(db, audio_dir, here)` in `issues.rs`. It is
calculated at every call and never stored. With an audio directory it first
runs `check_files_here`. It returns:

| Key | What is in it |
|---|---|
| `recordings_not_in_cloud` | Recordings not deleted and not stated present in the bucket, each with `size_bytes`, `held_by` and a `reason`: `no_bucket` (no bucket configured), else `too_large` (size known and over the limit), else `waiting_for_upload` (a device holds the file), else `no_copy_known`. A row with a `storage_key` and no `cloud` statement at all counts as in the bucket |
| `max_upload_bytes` | The limit the reasons were judged by |
| `orphaned_transcriptions` | Transcriptions whose Recording row is not there |
| `orphaned_attachments` | Attachments whose Note or Recording row is not there |
| `orphaned_recordings` | Recordings no Note holds (a Note in the trash still holds its Recordings) |
| `tags_with_whitespace` | Tags whose names contain whitespace, with their paths |

The Python binding adds `count` and gives `reason` as a string.
`src/core/issues_text.py` turns the dictionary into titled sections of
sentences. Opened from: GUI File → Issues...; TUI F8; `cli issues`;
`GET /api/issues`.

### 8.9 Network timeouts (FILE-14)

A link that stops moving must end a request in bounded time; a link that is
only slow must not.

| Request | Limits |
|---|---|
| Any connection to a peer | Connect: 3 seconds to `localhost`, a loopback, private or link-local address; 10 seconds elsewhere (`connect_timeout_for`) |
| Sync requests (`build_client`) | 30 seconds for a read to make progress; 180 seconds in all per request |
| Fetch from a peer | 30 seconds for a read to make progress; no overall limit |
| Send to a peer (`send_client_for`) | No read timeout and no overall limit, because the connection reads nothing while a body goes out. `transfer::stall_of_upload` ends the send when no byte of the body moved for 30 seconds (`SEND_STALL`), or 60 seconds after the last byte without an answer (`ANSWER_AFTER_LAST_BYTE`) |
| Bucket upload of a small file or of a part (`bucket_setup::send_signed_watched`) | The same stall watch, plus a 15-minute deadline (`REQUEST_TIMEOUT`, `PART_TIMEOUT`) |
| Bucket download (`bucket_setup::get_signed_stream`) | Connect 10 seconds; 30 seconds for a read to make progress (`STALL_TIMEOUT`); no overall limit |
| Bucket existence check | A signed `HEAD` with 30 seconds |

A transfer is tried three times, with waits of one, two and four seconds. A try
after a broken send asks the peer (`missing_on_peer`) how many bytes it now
holds and continues from there. A transfer that breaks keeps the bytes that
arrived in its part file on both sides.

### 8.10 The bucket wizard

`src/core/storage_setup.py` calls `bucket_setup.rs` through the binding:

- `create_bucket`: in `us-east-1` behind an endpoint, the bucket is made by a
  signed `PUT` with no body, because the library would send a location
  constraint for a region it does not know by name, and the service refuses it.
- `explain_refusal(key, text)`: when the endpoint is `http://` and the service
  refused without naming a cause (a wrong secret, an unknown key id, no such
  bucket, another region, a taken name), the sentence says that a bucket
  hardened by the wizard accepts only `https://`. Otherwise it returns
  `explain_error(text)`.
- `round_trip`: the test write is the core's own signed `PUT`, which reads the
  service's whole answer, so the error code in it can be explained.

---

## 9. Building, running and testing

### 9.1 First installation

```bash
cd /home/dotancohen/Projects/VoiceFamily/Voice
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cd rust/voice-python
/home/dotancohen/Projects/VoiceFamily/Voice/.venv/bin/maturin develop --release
```

### 9.2 After changing Rust code

```bash
cd /home/dotancohen/Projects/VoiceFamily/Voice/rust/voice-python
/home/dotancohen/Projects/VoiceFamily/Voice/.venv/bin/maturin develop --release
```

Always run maturin from `rust/voice-python/`, never from the repository root.

**Warning when Android is built as well.** The desktop build and the Android
build write the same file, `.cargo-target/release/libvoicecore.so`. maturin
builds it without the `uniffi` feature, and afterwards the Android binding
generator silently generates nothing. Generate the Kotlin bindings before
running maturin, or see `VoiceAndroid/CLAUDE.md`.

### 9.3 Running

Never run these against `~/.config/voice` while working: that is the owner's
live data. Set `VOICE_CONFIG_DIR` to a temporary directory first.

```bash
bin/voice                      # GUI if PySide6 is installed, else TUI
bin/voice tui
bin/voice cli --help
bin/voice web --port 8080
bin/voice cli sync serve --verbose
bin/voice -a <account> gui     # another account
```

### 9.4 Tests

```bash
.venv/bin/python -m pytest                       # everything
.venv/bin/python -m pytest tests/unit            # one directory
.venv/bin/python -m pytest -m cli                # one marker: unit, gui, tui, cli, web, integration, slow
cd submodules/voicecore && cargo test            # the Rust core
cd submodules/voicecore && cargo test convergence   # random multi-device sync fleets
```

| Directory or file | What it tests |
|---|---|
| `tests/unit/` | Database, cache rebuilds, conflicts, search, trash, transcription queue and flags, waveform, validation, where the copies are and the upload limit (`test_file_locations.py`), the Issues sentences (`test_issues_text.py`), start without an interface |
| `tests/sync/` | Sync between real installations: pagination, conflicts, failures, pairing, hosting, file transfer, discovery, the flags agreement with Android, locations between devices (`test_file_locations_sync.py`), sync and transfers over a failing link (`test_sync_over_a_failing_network.py`) |
| `tests/cli/`, `tests/tui/`, `tests/gui/`, `tests/web/` | One interface each; the Issues list and the copies in each (`test_cli_issues.py`, `test_tui_issues.py`, `test_tui_copies.py`, `test_issues_dialog.py`, `test_note_pane_copies.py`, `test_api_issues.py`) |
| `tests/display/` | Where Attachments are placed in the Note view |
| `tests/integration/` | Workflows across interfaces, timezone travel, performance; `test_file_storage.py` against a real S3 server (`TestTheWizardAgainstARealS3`, `TestUploadsAndDownloads`, `TestFailuresOfTheBucket`, `TestTheBucketOverAFailingNetwork`, `TestWhereTheCopiesAre`, `TestStorageBookkeeping`) |
| `tests/local_s3.py` | `LocalS3`: moto's S3 server on this machine, reached over TCP like Amazon, with authentication on (a key made in moto's IAM, signature version 4). The session fixture `local_s3` in `tests/conftest.py` starts one server for the session; each test takes its own bucket. Needs `moto[server]==5.2.3` from `requirements-dev.txt`. The server speaks plain HTTP, so a bucket with the wizard's TLS-only policy refuses every write |
| `tests/faulty_network.py` | `FaultyLink`: a TCP proxy between a client and a server that fails on command: `refuse()`, `cut_after(...)`, `stall()`, `answer(status)`, `drop_replies()`, `throttle(bytes_per_second)`, `freeze_after(...)`, `pass_through()`. Used in front of a listener and in front of moto |
| `tests/fixtures/transcription_flags_contract.json` | Cases both applications must agree on; must stay byte-identical to the Android copy |

The fixtures in `tests/conftest.py` create a fresh configuration directory and
database under pytest's `tmp_path` for each test. Tests never touch
`~/.config/voice` (TECHNICAL-DECISIONS 7.6).

`pytest.ini` turns warnings into errors (`filterwarnings = error`), so a new
warning fails the suite.

### 9.5 Style checks

```bash
.venv/bin/mypy src/      # strict type checking
.venv/bin/black src/     # formatting, line length 100
```

---

## 10. Rules to follow when changing the code

1. **A failing test is never made to pass by changing the test, the fixture or
   the data.** First decide, in writing, whether the code or the test's premise
   is wrong (TECHNICAL-DECISIONS 6.5).
2. **Nothing the user wrote is overwritten.** No "last write wins"; deletes are
   soft; disagreements become conflicts (1.1).
3. **Every editable value is written through the version functions**, never
   with plain SQL (7.4 above).
4. **A new synced field or entity** touches `FIELD_REGISTRY`, the `seq`
   triggers in `migrate_add_sync_sequence`, the feed in `collect_changes` and
   `get_full_dataset`, `ALL_SYNC_ENTITY_TYPES` and `apply_one` in
   `sync_apply.rs`, and both bindings (`VoiceCore/CLAUDE.md`, "Adding a
   syncable entity type or field").
5. **Derived data is never synced** (a cache, a colour calculated from a name) (1.3).
6. **A migration never changes a value that refers to a file** outside the database (3.1a).
7. **Memory never grows with the user's data**: stream or bound anything the
   size of a Recording, a log or a table (3.1).
8. **No ambiguous words** in names or text: not "handle", "process", "manage",
   "fill", "update" as a vague verb; say what happens. A wrong name is renamed
   everywhere in one change (4.4). Use the sync vocabulary of 8.4 exactly.
9. **Entity nouns are capitalised** where a user reads them: Note, Tag,
   Recording, Transcription, Attachment (4.2).
10. **Test data that contains text contains Hebrew** (6.3).
11. **Logs use the `tracing` crate** in Rust, never `println!`.
12. **Documentation follows the change**: `USER_MANUAL.md` for the user,
    `DEVELOPMENT.md` for building, `TESTING.md` for the tests, the `--help`
    text for the CLI (`Voice/CLAUDE.md`, "Documentation requirements").
13. **The core checkouts stay identical**; after a core change, rebuild the
    desktop binding and the Android library and bindings together (7.2).

---

## 11. Where to look first

| Question | Start at |
|---|---|
| Why is this value shown? | The cache JSON in `notes`, then `rebuild_note_cache` in `database.rs` |
| Why did a sync not bring something? | `sync_failures`, `sync_peers` cursors, `SYNC_SPECIFICATION.md` section 7 |
| Why is there a conflict? | `field_conflicts`, `bin/voice cli sync conflicts --details` |
| Where is a Recording's file? | `audio_files.disk_name` in the directory `audiofile_directory` |
| Which devices hold a Recording? | `file_locations`, `bin/voice cli audiofile-show <id>` (section 8.7) |
| Why is a Recording not in the bucket? | `bin/voice cli issues`, then `issues.rs` (section 8.8) |
| Why did a transfer or an upload stop? | The error sentence, section 8.9, `transfer::stall_of_upload` |
| What happens when a command runs? | `add_cli_subparser` in `src/cli.py`, then its `cmd_...` function |
| What does this rule id mean? | `VoiceFamily/SYNC_SPECIFICATION.md` (FILE-22, VER-9 ...) or the plan (Stage N) |

---

## 12. Where older documents disagree with the code

Checked against the code on 2026-09-14. The code is described correctly in this
guide. On 2026-09-14 `Voice/CLAUDE.md`, `SYNC_SPECIFICATION.md` (FILE-6,
section 7.1, FILE-12, PROTO-1) and `DEVELOPMENT.md` were corrected, and every
disagreement with them that this section listed on 2026-09-13 is gone.
`USER_MANUAL.md`, `README.md`, `CONFIGURATION.md`, `CLOUD-STORAGE-SETUP.md`,
`SECURITY-CONSIDERATIONS.md`, `DEVELOPMENT.md` and `TESTING.md` were being
corrected by other people while this was checked; they were searched only for
the subjects of the rows below.

| Text | What it says | What the code does |
|---|---|---|
| `bin/voice`, the comment on line 3 | The launcher honours `-d` | `src/main.py` has no `-d`; the options are `-a/--account` and `$VOICE_CONFIG_DIR` |
| `src/main.py`, the module docstring and the `--help` examples | `cli list-notes`, `cli search --tag Work` | The commands are `notes-list` and `notes-search` |
| The docstrings of `AudioFile` in `src/core/models.py` and of `AudioFileManager` in `src/core/audiofile_manager.py` | A file is stored at `{audiofile_directory}/{id}.{extension}` | The file is named by `audio_files.disk_name` (FILE-15, TECHNICAL-DECISIONS 3.1a); the bucket object by the content hash (3.1b). Only rows older than `disk_name` keep `<id>.<ext>` |

---

## 13. Defects found in the code

Found by reading the code on 2026-09-13 and 2026-09-14; nothing here was
confirmed by running the application. "Verified" means the code path was read
from start to end and the result follows from it. "Suspected" means it was
seen in part and needs a test before it is fixed.

### 13.1 Verified

1. **A setup text made on an indexed root has no `&f=`.** `pairing_offer` in
   `rust/voice-python/src/lib.rs` receives the account's directory (from
   `cli account show-code` and the GUI sync dialog) and opens it with
   `Config::new`, which takes that directory as the root. `pairing::offer` then
   looks for `<account dir>/certs/server.crt` (and `certs_dir()` creates the
   empty directory), while the listener's certificate is
   `<root>/certs/server.crt`. The fingerprint is empty, and
   `SetupText::to_text` leaves `f` out. A device that joins over `https://` to
   the self-signed listener has no fingerprint to pin. The automated pairing
   tests use `--plain-http` on 127.0.0.1 and cannot show this.
   `ensure_own_device_card`, called at every start, opens the account
   directory the same way and writes this device's card with an empty
   certificate fingerprint. `hosting_offer` opens the root and is not affected.
2. **`cli note-purge` reads the live root.** `_remove_audio_files` in
   `src/cli.py` calls `Config()` with no directory, so the core opens
   `dirs::config_dir()/voice` (`~/.config/voice`) whatever `$VOICE_CONFIG_DIR`
   and `-a` say, writes a `config.json` there when there is none, and deletes
   matching files in that configuration's audio directory. Do not run
   `note-purge` on the owner's computer until this is fixed.
3. **Files of purged Recordings stay on disk.** Four functions look for them as
   `<audio id>.*`: `_remove_audio_files` (`src/cli.py`),
   `_remove_purged_audio_files` (`src/web.py`), `purge_audio_files`
   (`src/tui.py`) and `remove_audio_files` (`src/ui/trash_dialog.py`). Files
   are named by `disk_name`; only rows older than that column match.
4. **Calculate missing data finds no file named by `disk_name`.**
   `audio_path` in `src/core/missing_data.py` looks for `<id>.<ext>`.
5. **The bucket wizard's Save and "Replace key" remove `encrypt` and
   `max_upload_mb`.** `save` in `src/core/storage_setup.py` writes a
   configuration of bucket, region, keys, prefix and endpoint only, and
   `set_file_storage_config` replaces the whole JSON. After the next sync every
   device of the account has encryption off and the 100 MB limit.
6. **A TUI session writes nothing to `voice.log`.** `run` in `src/tui.py`
   removes every `logging.StreamHandler` from the root logger;
   `RotatingFileHandler` is a subclass of `StreamHandler`.
7. **`cli storage upload-pending` does not show `too_large`.** The core counts
   the files over the upload limit; `cmd_storage_upload_pending` prints
   uploaded, skipped, failed and deferred only.
8. **`cli sync now` without `--peer` prints the conflict count as
   `Errors: N`** (`print(f"    Errors: {result.conflicts}")`).
9. **The hint `Run: voice config set audiofile_directory ...` lacks `cli`**
   (`src/cli.py`, several places).
10. **The GUI transcription queue shows `2th`, `3th`**
    (`f"{row.position}th"` in `src/ui/transcription_queue_dialog.py`).

### 13.2 Suspected

- `cli account create` without `--label`, a second time, fails with "An
  account is already labelled default" (`accounts.rs`).
- Core exceptions reach the user as a traceback instead of an `Error:` line:
  `account recording-key import` with a bad key, `storage encrypt on` before
  the key was exported, `sync serve --plain-http` on a host that is not a
  loopback address, `sync serve` when the port is taken, `sync discover`
  without zeroconf.
- `cli account grant-host` to a single-directory listener answers
  `TOKEN_INVALID` instead of saying that the listener hosts no other accounts.
- `cli sync check` always reports that the listener on this machine is not
  listening, because that flag belongs to the process.
- On a hosting server, a CLI command other than `sync serve` and
  `account list|create|default|remove|host`, run without `-a`, creates a
  `default` account.
- GUI: the Transcribe button acts on the first Recording of a Note only;
  in-place edits in the Tag hierarchy dialog are never saved; Forget and Rename
  in the sync dialog with no row selected act on the last peer; several sync
  dialog checks run on the GUI thread and freeze the window; the transcription
  queue does not start at launch.
- TUI: Ctrl+F can report `0 gap(s) cannot be calculated`.
- The core's `tracing` lines are not recorded from the GUI or the TUI: a
  subscriber is installed only when the listener starts with `--verbose`.

---

## 14. Glossary

**axum** — A Rust library for writing HTTP servers. The sync server is built on it.

**BLOB** — "Binary large object": an SQLite column type that stores raw bytes. Ids are 16-byte BLOBs.

**Cache (display cache)** — A value calculated from other data and stored so it does not have to be calculated again, such as `di_cache_note_list_pane_display`. It can always be rebuilt and is never synced.

**Cargo feature** — A named option in `Cargo.toml` that includes or leaves out parts of a Rust crate when it is compiled.

**Core library** — Code shared by several applications. Here: VoiceCore, in Rust.

**Crate** — A Rust package: a library or a program, described by a `Cargo.toml`.

**Denormalised copy** — The same value stored in a second place for faster reading. `notes.content` is a denormalised copy of the head in `field_versions`.

**Device card** — The synced record of one device of an account: name, addresses, certificate fingerprint, the hash of its key, whether it was revoked.

**Diff3 / three-way merge** — Combining two edited versions of a text by comparing each with the version they both started from (the base). Git merges files this way.

**Foreign key** — A column declared to refer to a row in another table.

**Head** — The version of a field that is its current value.

**Idempotent** — Running it twice has the same result as running it once.

**Index** — An extra structure SQLite keeps so that searches on a column are fast.

**Leaf** — A version that no other version was written on top of. Two leaves for one field means two devices changed it independently.

**maturin** — A tool that compiles a Rust crate written with PyO3 and installs it as a Python module.

**Migration** — Code that changes an existing database's structure (new tables, new columns) so that it matches what the current code expects.

**moto** — A Python library that imitates Amazon's services. The tests run its S3 server on this machine.

**Peer** — Another Voice installation of the same account that this one syncs with.

**Polymorphic association** — A link whose target table is named in a column (`attachment_type`) instead of being fixed.

**Primary key** — The column, or columns, that identify a row uniquely.

**Proxy (TCP proxy)** — A program that accepts a connection and copies its bytes to another server and back. `FaultyLink` is one that can break the connection on command.

**Purge** — Removing an item for good, with its history, on every device. Only possible from the trash.

**PyO3** — A Rust library for writing Python modules in Rust.

**Root (directory)** — The directory that holds all accounts of an installation: `~/.config/voice` unless `$VOICE_CONFIG_DIR` says otherwise.

**Signed request** — An HTTP request to S3 that carries a signature calculated from the request and the secret key (signature version 4), so the service can check who sent it.

**Soft delete** — Marking a row as deleted (`deleted_at`) instead of removing it.

**SQLite** — A database engine that stores a whole database in one file and runs inside the application.

**Stall** — A connection that stays open but moves no bytes.

**Submodule** — A git repository placed inside another at a fixed commit. `submodules/voicecore` is one.

**TOFU** — "Trust on first use": a certificate is accepted the first time and remembered; a different certificate later is refused.

**Transaction** — A group of database writes that either all take effect or none do.

**Trigger** — SQL that SQLite runs by itself when a row is inserted or changed. Here triggers set `seq`.

**UUID7** — A 128-bit id whose first part is the time it was made, so ids sort by creation time. The last characters are random.

**Version** — One immutable value of a field, with a pointer to the version it replaced.

**Virtual environment (`.venv`)** — A directory holding a private Python interpreter and packages for one project.

**WAL (write-ahead log)** — An SQLite journal mode: changes are written to `notes.db-wal` first and copied into `notes.db` later. Readers and a writer can work at the same time.

**zeroconf (mDNS)** — A way for programs on one local network to announce and find each other without a central server.

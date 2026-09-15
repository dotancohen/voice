# Testing Voice (desktop and server)

This document describes the automated tests of this project: the `pytest`
suite in `tests/`. It says what each part tests, what must be installed, how
to run the whole suite or one part of it, and which helpers the tests share.

Two other suites test the same family of applications:

- the core's Rust tests, in `submodules/voicecore` (section 11 below);
- the phone's tests, described in
  [`../VoiceAndroid/DEVELOPMENT.md`](../VoiceAndroid/DEVELOPMENT.md), section "Tests".

The manual test plans, which cover the desktop, a server and the phones
together, are in [`../test-plans/`](../test-plans/). Start with its `README.md`.

Numbers in this document that change when tests are added are labelled with
the date they were counted. There is no CI configuration in this repository:
the suite runs when someone runs it.

## Contents

1. [Rules for every test](#1-rules-for-every-test)
2. [Before the first run](#2-before-the-first-run)
3. [Running the suite](#3-running-the-suite)
4. [The test tree](#4-the-test-tree)
5. [Test data](#5-test-data)
6. [The S3 servers](#6-the-s3-servers)
7. [The fault proxy](#7-the-fault-proxy)
8. [Two or more devices in one test](#8-two-or-more-devices-in-one-test)
9. [Contract fixtures shared with the Android suite](#9-contract-fixtures-shared-with-the-android-suite)
10. [What happens when a prerequisite is missing](#10-what-happens-when-a-prerequisite-is-missing)
11. [The core's Rust tests](#11-the-cores-rust-tests)

---

## 1. Rules for every test

**A test never runs against live data.** `~/.config/voice` holds the owner's
notes and recordings, and there is no second copy. Every test uses a temporary
directory: the fixtures in `tests/conftest.py` create one under pytest's
`tmp_path`, and a test that starts `python -m src.main` sets `VOICE_CONFIG_DIR`
to a temporary directory in the child's environment. Every new test must also
use a temporary directory.
The rule and the reason for it are in
[`../TECHNICAL-DECISIONS.md`](../TECHNICAL-DECISIONS.md) 7.6 and in
[`../CLAUDE.md`](../CLAUDE.md), "The owner's data".

**A failing test is never negotiated with.** A failing test says either that
the code is wrong or that the test's premise is wrong; find out which and say
so before editing anything. A test is never made to pass by writing values into
the database, a file or a cache, by loosening or deleting its assertion, by
changing the fixture so that the condition under test no longer exists, by
adding a branch to the production code that only the test reaches, or by
marking it skipped, expected to fail or flaky. The full rule is in
[`../TECHNICAL-DECISIONS.md`](../TECHNICAL-DECISIONS.md) 6.5 and in
[`../CLAUDE.md`](../CLAUDE.md), section "Testing".

**A test names the specification rule it covers.** When a test checks a rule of
[`../SYNC_SPECIFICATION.md`](../SYNC_SPECIFICATION.md), its name, docstring or
a comment names the rule id (for example `FILE-22` or `ACCT-2`), and the rule's
row in section 12 of that document ("Test coverage map") names the test.

**Read the bugs that got past the tests.**
[`../BUGS-THE-TESTS-MISSED.md`](../BUGS-THE-TESTS-MISSED.md) lists bugs that
shipped from code that had tests, why each test did not catch its bug, and the
eighteen rules (R1 to R18) that came out of them. Read it before writing tests
for anything that syncs, that crosses a language boundary, or that can be
interrupted. Among the rules:

- The suite passes completely or it is broken; there is no list of known failures (R3).
- Assert what the operation produced, not that it did not crash (R2).
- Fixture text is several Hebrew words, not one ASCII word (R6).
- Compute the expected value independently of the code under test (R9).
- Test the second one: the second transcription, delete, device, sync (R12).
- Test at the size the data really reaches (R18).

---

## 2. Before the first run

Every command in this document runs from the project directory:

```bash
cd /home/dotancohen/Projects/VoiceFamily/Voice
```

### 2.1 The virtual environment

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

`requirements.txt` holds what the application imports. It also names
`PySide6` with the comment "install with --no-deps": the `PySide6` package
without `--no-deps` also installs PySide6-Addons, which nothing in this project
imports.

`requirements-dev.txt` holds pytest, pytest-qt, pytest-cov, pytest-asyncio,
requests, and `moto[server]==5.2.3`, the S3 server of section 6 (moto brings
boto3 with it).

Every test needs PySide6, not only the GUI tests: `tests/conftest.py` imports
`QApplication` at module level.

### 2.2 The core, built into the virtual environment

```bash
cd /home/dotancohen/Projects/VoiceFamily/Voice/rust/voice-python
/home/dotancohen/Projects/VoiceFamily/Voice/.venv/bin/maturin develop --release
```

The tests do not compile or read the Rust source. `src/core/database.py`,
`src/core/config.py` and other modules import the Python module `voicecore`,
and so do many tests; `maturin develop` compiles `submodules/voicecore`
together with the bindings in `rust/voice-python` and installs the result as
that module in `.venv`. Rebuild after every change in `submodules/voicecore/`
or `rust/voice-python/`. Without a rebuild the tests run against the previous
build of the core and report on code that is no longer there.

This build overwrites the shared `VoiceFamily/.cargo-target/release/libvoicecore.so`
with a build that has no `uniffi` feature; [`CLAUDE.md`](CLAUDE.md), "Building
the Python bindings", says what that means for the phone's build.

### 2.3 Other programs

- `ffmpeg` on `PATH`, for
  `tests/cli/test_cli_audiofiles.py::TestAudiofilesWaveforms`.
- The `VoiceAndroid` checkout beside this one
  (`/home/dotancohen/Projects/VoiceFamily/VoiceAndroid`), for the one test that
  compares the two copies of the contract fixture (section 9).
- Nothing in the repository sets `QT_QPA_PLATFORM`. The Qt tests open widgets;
  on a computer without a display, `QT_QPA_PLATFORM=offscreen` is Qt's setting
  for that case, but it has not been tried with this suite.

No test needs an Amazon account, a network connection or a phone. The S3
server, the sync servers and the fault proxy all run on `127.0.0.1`.

---

## 3. Running the suite

### 3.1 The whole suite

```bash
.venv/bin/python -m pytest
```

On 2026-09-14 this collected 1534 tests.

`pytest.ini` applies these settings to every run:

- `testpaths = tests`.
- `addopts` includes `--cov=src --cov-report=html --cov-report=term-missing`:
  every run measures coverage, prints the lines not covered, and rewrites
  `htmlcov/`. Add `--no-cov` to turn coverage off. No minimum coverage is set
  or enforced.
- `--strict-markers`: a marker that is not declared in `pytest.ini` is an error.
- `filterwarnings = error`, with `DeprecationWarning`,
  `PendingDeprecationWarning` and `ResourceWarning` ignored: any other warning
  fails the test that raised it.
- `asyncio_mode = auto` (the Textual tests are `async def`), and
  `qt_api = pyside6`.

### 3.2 One directory

Selecting by directory is the reliable way to run one part of the suite
(section 3.4 explains why markers are not).

```bash
.venv/bin/python -m pytest tests/unit
.venv/bin/python -m pytest tests/sync
.venv/bin/python -m pytest tests/cli
.venv/bin/python -m pytest tests/gui
.venv/bin/python -m pytest tests/tui
.venv/bin/python -m pytest tests/web
.venv/bin/python -m pytest tests/integration
.venv/bin/python -m pytest tests/display
```

| Directory | Tests collected on 2026-09-14 |
|---|---|
| `tests/unit` | 612 |
| `tests/sync` | 484 |
| `tests/cli` | 113 |
| `tests/gui` | 104 |
| `tests/integration` | 90 |
| `tests/web` | 80 |
| `tests/tui` | 43 |
| `tests/display` | 8 |
| **Total** | **1534** |

### 3.3 One file, class or test

```bash
.venv/bin/python -m pytest tests/integration/test_file_storage.py
.venv/bin/python -m pytest tests/integration/test_file_storage.py::TestTheBucketOverAFailingNetwork
.venv/bin/python -m pytest tests/sync/test_transcription_flags_contract.py::test_the_android_copy_is_the_same_file
.venv/bin/python -m pytest -k "hebrew"
```

`-k` selects every test whose name, class or file name contains the expression
(case-insensitive).

### 3.4 Markers

`pytest.ini` declares seven markers. **They are applied to only some of the
files**, so a marker selects fewer tests than the directory of the same name,
and nothing in `tests/sync/` or `tests/display/` carries a marker except one
class. What each marker selected on 2026-09-14:

| Command | Selected | What it selects, and what it leaves out |
|---|---|---|
| `.venv/bin/python -m pytest -m unit` | 155 | 5 of the 25 files in `tests/unit`: `test_cache_rebuild.py`, `test_edge_cases.py`, `test_search.py`, `test_trash.py`, `test_validation.py` |
| `.venv/bin/python -m pytest -m gui` | 101 | every test in `tests/gui` except the 3 tests of the class `TestSentences` in `test_sync_dialog.py` |
| `.venv/bin/python -m pytest -m tui` | 43 | every test in `tests/tui` |
| `.venv/bin/python -m pytest -m cli` | 68 | `tests/cli` except `test_cli_audiofiles.py`, `test_cli_audiofiles_edge_cases.py`, `test_cli_audiofiles_note_creation.py`, `test_cli_issues.py` and `test_cli_storage.py`; plus the class `TestFromTheCommandLine` in `tests/sync/test_storage_setup.py` |
| `.venv/bin/python -m pytest -m web` | 52 | `tests/web` except `test_api_audiofiles.py`, `test_api_audiofiles_edge_cases.py` and `test_api_issues.py` |
| `.venv/bin/python -m pytest -m integration` | 53 | `tests/integration` except `test_file_storage.py`, `test_sync_integration.py` and `test_timezone_travel.py` |
| `.venv/bin/python -m pytest -m slow` | 10 | the classes `TestLargeDatabasePerformance` and `TestScalabilityLimits` in `tests/integration/test_performance.py` |
| `.venv/bin/python -m pytest -m "not slow"` | 1524 | every test except those two classes |

`-m "not slow"` is the one marker selection that means what it says. For every
other part of the suite, select by directory (section 3.2).

---

## 4. The test tree

### 4.1 Directories

| Directory | What it tests |
|---|---|
| `tests/unit/` | The Python layer in `src/core/` and the core through its Python bindings, without servers: the database and search, configuration, validation, edge cases (length limits, Unicode, Hebrew), recordings and their file names, the display caches, conflicts between two databases in one process, the trash, cloud storage decisions without the network, where the copies of a recording are and removing this device's copy (with `FakeS3`), missing data, timestamps shown at their recorded offset, transcription flags, the transcription queue and backlog, waveforms, this device's address in words |
| `tests/sync/` | Sync between installations: the Rust sync server started as a child process, the sync client, the command-line sync commands, accounts, pairing, hosting, discovery on the local network, protocol versions, pagination, validation of what a device sends, conflicts between devices, concurrent syncs, network failures, files between instances, the bucket wizard, the transcription flags contract |
| `tests/cli/` | The command line (`python -m src.main cli ...`), run as a child process with `VOICE_CONFIG_DIR` set to a temporary directory: listing, showing and searching notes, output formats, accounts, devices, devices, recordings, issues, storage, trash, merging notes |
| `tests/gui/` | The Qt interface, with real widgets built on the session's `qapp` and clicked or typed into directly: the tags pane, the notes list, search, the note pane (conflicts, copies of a recording, missing media), the sync, trash and issues dialogs |
| `tests/tui/` | The Textual interface through Textual's `run_test()`: the tags tree, notes list, note detail, keys, search, conflicts, copies, missing media, trash, issues |
| `tests/web/` | The Flask Web API through Flask's test client: notes, tags, search, recordings, issues, trash, health check, CORS, HTTP methods, JSON and UTF-8 |
| `tests/integration/` | Operations across several layers: the same results from the GUI, the CLI and the Web API; multi-step workflows; error cases; timings over 1000 notes; importing recordings; cloud storage against a real S3 server (section 6) and through the fault proxy (section 7); conflict resolution between two databases; a note keeping its clock while its author travels |
| `tests/display/` | That a note's attachments are shown below its content, in the Web API, the TUI and the GUI |

### 4.2 Files outside the test directories

| File | What it is |
|---|---|
| `tests/conftest.py` | Fixtures for every test: `qapp`, `test_config_dir`, `test_config`, `test_db_path`, `empty_db`, `populated_db`, `local_s3` (sections 5 and 6) |
| `tests/helpers.py` | Imports the id helpers of `tests/conftest.py` (`TAG_IDS`, `NOTE_IDS`, `get_tag_uuid_hex`, `get_note_uuid_hex` and others) for test files that import them by module name |
| `tests/sync_support.py` | Reads the sync feed of a database and applies a batch of changes through the core, without a server (section 8) |
| `tests/local_s3.py` | `LocalS3`: moto's S3 server with authentication on (section 6) |
| `tests/fake_s3.py` | `FakeS3`: a small S3 server in a thread for the bucket wizard's tests (section 6) |
| `tests/faulty_network.py` | `FaultyLink`: a TCP proxy that fails on command (section 7) |
| `tests/sync/conftest.py` | Sync nodes, sync servers as child processes, and sync helpers (section 8) |
| `tests/integration/conftest.py` | `large_db`, `cli_runner`, `web_client` (section 5) |
| `tests/web/conftest.py`, `tests/display/conftest.py` | `web_app` and `client`: a Flask app and its test client over `populated_db` |
| `tests/fixtures/transcription_flags_contract.json` | The contract shared with the Android suite (section 9) |
| `tests/audiofile-sync-test.ogg` | The recording that `tests/sync/test_audiofile_binary_sync.py` uploads and downloads |
| `tests/test_config.example.toml` | A template for credentials of a real bucket. No test reads it or `tests/test_config.toml` (which `.gitignore` lists) |

### 4.3 Notable test files

| File | Why it is notable |
|---|---|
| `tests/integration/test_file_storage.py` | Cloud storage against moto: the wizard, uploads and downloads, uploads in parts, encryption, a failing bucket, the bucket through the fault proxy (FILE-14), where the copies of a recording are (FILE-22) |
| `tests/sync/test_sync_over_a_failing_network.py` | Sync and file transfers between two installations through the fault proxy (FILE-14) |
| `tests/sync/test_storage_setup.py` | The bucket wizard against `FakeS3`, including `storage setup` and `storage check` from the command line |
| `tests/sync/test_file_locations_sync.py` | FILE-22 between two installations with moto |
| `tests/unit/test_file_locations.py` | FILE-22, FILE-23 and FILE-26: a copy is removed only when the bucket, asked at that moment, confirms that it holds the file |
| `tests/unit/test_addresses_text.py` | LISTEN-4: the words for this device's address, and the shape of the core's `listen_addresses` on this machine |
| `tests/sync/test_sync_server.py` | The Rust sync server's endpoints, with the server started as a real process |
| `tests/sync/test_sync_concurrent.py` | Concurrent syncs and edits during a sync, using the subprocess helpers of section 8 |
| `tests/sync/test_transcription_flags_contract.py`, `tests/sync/test_transcription_flags_sync.py` | The contract with the phone, and every field shape in it carried through a real sync (section 9) |
| `tests/unit/test_conflicts.py` | Two databases in one process exchanging their feeds without a server |
| `tests/unit/test_apply_changes.py` | The feed and the apply path through the core; a delete never destroys an edit it did not see (HEAD-6, CONF-10, VER-4) |
| `tests/unit/test_main_without_an_interface.py` | `python -m src.main` with no interface named, the start-up path of the crash of 2026-09-13 |
| `tests/integration/test_performance.py` | Timings over `large_db`; the only tests marked `slow` |

---

## 5. Test data

### 5.1 `populated_db`

`populated_db` (in `tests/conftest.py`) creates a database in the test's
temporary directory through the `Database` API, with 21 tags and 9 notes, and
writes a `config.json` beside it for the CLI tests.

```
Work
├── Projects
│   └── Voice
└── Meetings
Personal
├── Family
└── Health
Geography
├── Europe
│   ├── France
│   │   └── Paris
│   └── Germany
├── Asia
│   └── Israel
└── US
    └── Texas
        └── Paris
Foo
└── bar
Boom
└── bar
```

Two tag names are ambiguous on purpose: `Paris` and `bar`.

| Note | Content | Tags |
|---|---|---|
| 1 | Meeting notes from project kickoff | Work, Projects, Meetings |
| 2 | Remember to update documentation | Work, Projects, Voice |
| 3 | Doctor appointment next Tuesday | Personal, Health |
| 4 | Family reunion in Paris | Personal, Family, France, Paris (under France) |
| 5 | Trip to Israel planning | Personal, Asia, Israel |
| 6 | שלום עולם - Hebrew text test | Personal |
| 7 | Testing ambiguous tag with Foo/bar | Foo, bar (under Foo) |
| 8 | Another note with Boom/bar | Boom, bar (under Boom) |
| 9 | Cowboys in Paris, Texas | US, Texas, Paris (under Texas) |

The ids are not fixed numbers: the database generates them when the fixture
runs. A test reads them through `get_tag_uuid_hex(key)` and
`get_note_uuid_hex(number)` (or the dictionaries `TAG_IDS` and `NOTE_IDS`).
Tag keys are the tag names, except `Paris_France`, `Paris_Texas`, `bar_Foo`
and `bar_Boom`.

### 5.2 Other fixtures with data

- `empty_db`: an empty database with the device id `00000000000070008000000000000001`.
- `large_db` (`tests/integration/conftest.py`): 1000 notes of 50 to 550
  characters, 100 tags in 10 branches of 10 levels, 1 to 5 tags on each note,
  written through the core's sync apply functions.
- `cli_runner` (`tests/integration/conftest.py`): runs
  `python -m src.main cli ...` with `VOICE_CONFIG_DIR` set to the test's
  directory, and returns the exit code, stdout and stderr.
- `web_client`, `web_app`, `client`: a Flask test client over `populated_db`.

### 5.3 Hebrew

The application is used in Hebrew, and test text is Hebrew wherever text
matters (rule R6). On 2026-09-14, 64 of the 105 test files contained Hebrew.
The fixtures in `tests/integration/conftest.py`, `tests/sync/conftest.py`,
`tests/web/conftest.py` and the S3 and proxy helpers contain none; a test that
uses them writes its own Hebrew text.

---

## 6. The S3 servers

### 6.1 `LocalS3`: moto, with authentication on

`tests/local_s3.py` starts moto's `ThreadedMotoServer` (Apache 2.0 licence)
inside the pytest process, on `127.0.0.1` at a free port, speaking plain HTTP.
The core reaches it over TCP as it reaches Amazon.

- **One server for the session.** The session fixture `local_s3` in
  `tests/conftest.py` starts it the first time a test asks for it and stops it
  at the end of the session. Nothing needs to be started by hand.
- **One bucket for each test.** `LocalS3.new_bucket_name()` returns
  `voice-t00001`, `voice-t00002`, and so on. The region is `eu-central-1`.
- **Authentication is on.** The module sets `INITIAL_NO_AUTH_ACTION_COUNT=3`
  before it imports moto, and it is the only module in the tests that imports
  moto. The first three requests, which are not signed, create the IAM user
  `voice`, its inline policy `voice-buckets` (`s3:*` on every resource) and an
  access key. Every later request must be signed (signature version 4) with
  that key; a wrong secret or an unknown key id is refused.
- **No TLS.** A bucket given the wizard's "TLS only" policy refuses every
  write, as Amazon would over plain HTTP. Tests that upload use a bucket
  without that policy; the hardening test checks the refusal.
- **For looking into a bucket:** `client()` (a boto3 client with the key),
  `objects(bucket)` (every key and its bytes), `unfinished_uploads(bucket)`.

What must be installed: `moto[server]==5.2.3` from `requirements-dev.txt`.
Section 10 says what happens without it.

Users: `tests/integration/test_file_storage.py` and
`tests/sync/test_file_locations_sync.py`.

### 6.2 `FakeS3`: the wizard's server

`tests/fake_s3.py` is a small S3 server in a thread, used by
`tests/sync/test_storage_setup.py`, `tests/gui/test_storage_wizard.py`,
`tests/unit/test_file_locations.py`, `tests/cli/test_cli_issues.py`,
`tests/web/test_api_issues.py`, `tests/gui/test_note_pane_copies.py` and
`tests/tui/test_tui_copies.py`. It checks that every request is signed
(signature version 4) with its own key id (by default `AKIAIOSFODNN7EXAMPLE`),
answers every DELETE with `403 AccessDenied` and records that one was attempted
(`deleted_anything()`), can refuse every request with a chosen error code
(`refuse_with`), answers `409 BucketAlreadyExists` for names in `taken_names`,
keeps the settings the wizard writes on a bucket, and with `fail_part` answers
`503 SlowDown` once for one part of an upload in parts.

---

## 7. The fault proxy

`tests/faulty_network.py` defines `FaultyLink(target_port, target_host="127.0.0.1")`:
a TCP proxy on `127.0.0.1` between a client (the core's sync client or its
bucket client) and a server (a device's listener or the S3 server). The test
points the client at `link.url` instead of the server, then sets a fault:

| Method | Effect |
|---|---|
| `refuse()` | Closes the proxy's port; the next connections are refused by the operating system |
| `cut_after(bytes_down=..., bytes_up=...)` | Resets the connection (RST) once that many bytes have crossed in that direction |
| `stall()` | Accepts connections, reads what the client sends, and never answers |
| `answer(status, body=b"", request=None)` | Answers with that HTTP status without reaching the server |
| `drop_replies(request=None)` | The request reaches the server and the server acts on it; its reply never reaches the client |
| `throttle(bytes_per_second)` | Every byte gets through, at that rate |
| `freeze_after(bytes_down=..., bytes_up=...)` | After that many bytes in that direction, nothing more is forwarded and nothing is closed |
| `pass_through()` | Removes the fault; after `refuse()` it opens the port again |

- `answer` and `drop_replies` take `request`, the start of a request's first
  line (for example `b"POST /sync/apply"`): the fault then applies from that
  request on, and earlier requests on the connection pass untouched.
- Every fault method takes `connections`: the number of connections, accepted
  after the fault is set, that the fault applies to (all of them when `None`).
- Counters: `bytes_up`, `bytes_down`, `connections`, `faulted_connections`.
- `FaultyLink` is a context manager; `stop()` closes the port and resets every
  open connection.

Users: `tests/sync/test_sync_over_a_failing_network.py` (a proxy in front of a
device's listener) and `tests/integration/test_file_storage.py` (a proxy in front
of moto). Both define `within(seconds, operation)`, which fails the test when
the operation has not ended in time: a dead link must end an operation, not
leave it waiting forever.

The Android suite has a port of this proxy, `network/FaultyLink.kt`, with fewer
fault modes; [`../VoiceAndroid/DEVELOPMENT.md`](../VoiceAndroid/DEVELOPMENT.md)
describes the Android tests.

---

## 8. Two or more devices in one test

### 8.1 Sync nodes with real servers: `tests/sync/conftest.py`

- `SyncNode`: one installation, with its name, device id, configuration
  directory, database path, `Database`, `Config`, port and server process.
  `url` is `http://127.0.0.1:<port>`; `wait_for_server(timeout=10)` polls
  `/sync/status`; `stop_server()` terminates the server; `kill_server()` kills
  it (a crash); `reload_db()` opens the database again, to see what the server
  process wrote.
- `create_sync_node(name, device_id, base_dir, port=None, account_id=ACCOUNT_ID)`:
  a directory of its own under the test's `tmp_path`, `notes.db` in the
  account, `config.json`, the node's own key and device card, and admission of
  the test client and of every other node of the same account created in the
  same test (in both directions), as pairing would admit them. Nodes of
  different accounts refuse each other (ACCT-2); `OTHER_ACCOUNT_ID` makes one.
- `start_sync_server(node)`: runs
  `python -m src.main cli sync serve --host 127.0.0.1 --port <port> --plain-http`
  with `VOICE_CONFIG_DIR` set to the node's directory.
- Fixtures: `sync_node_a`, `sync_node_b`, `sync_node_c`, `running_server_a`,
  `running_server_b`, `two_nodes_with_servers`, `three_nodes_with_servers` (the
  last two with every node configured as a device of every other).
- `AUTH` holds the headers of the test client, for a test that calls a server's
  endpoints directly; `auth_for(node)` gives a node's own headers;
  `admit(server, caller)` and `admit_test_device(server, device_id, name)`
  admit further devices.
- `sync_nodes(source, target)` syncs through `voicecore.SyncClient.sync_with_device`.
  Also `create_note_on_node`, `create_tag_on_node`, `get_note_count`,
  `get_tag_count` (which does not count system tags, whose names start with
  `_`), `wait_for_condition`, and `simulate_network_partition` (stops a server
  and starts it again).
- Subprocess versions (`run_db_operation`, `create_note_subprocess`,
  `update_note_subprocess`, `delete_note_subprocess`, `get_note_subprocess`,
  `get_note_count_subprocess`, `sync_nodes_subprocess`) run each operation in
  a separate Python process. They were written when the core's database object
  could not be used from more than one thread; it can now (its database is
  behind a lock, `tests/unit/test_database_threads.py`), and separate
  processes still make the concurrency real.

### 8.2 Without a server

- `tests/sync_support.py`: `read_feed(db, cursor=0, limit=100000)` reads a
  database's write-order feed after the cursor and returns the changes with the
  cursor to continue from; `apply_sync_changes(db, changes, from_device_id)`
  applies a batch through the core; `get_device_last_sync` and `update_device_last_sync`.
  Used by `tests/unit/test_apply_changes.py` and several files in `tests/sync/`.
- `tests/unit/test_conflicts.py`: two databases in one process exchanging
  their feeds.
- `tests/integration/test_file_storage.py`: `Device` and the `linked_device`
  fixture, installations that share a moto bucket.

---

## 9. Contract fixtures shared with the Android suite

The desktop and the phone read a transcription's flags from the same synced
field with their own code. The agreement is one JSON file, kept in both
repositories:

| This repository | VoiceAndroid |
|---|---|
| `tests/fixtures/transcription_flags_contract.json` | `app/src/test/resources/transcription_flags_contract.json` |

**The two copies must be identical, byte for byte.** Change both in the same
commit. On 2026-09-14 they were identical.

- `tests/sync/test_transcription_flags_contract.py` checks this project's flag
  code against the contract, and its test `test_the_android_copy_is_the_same_file`
  compares the two copies. When `../VoiceAndroid` is not checked out, that test
  is skipped; it is the only test in the suite that can be skipped.
- `tests/sync/test_transcription_flags_sync.py` writes every field shape from
  the contract on one node and reads it on another after a real sync.
- In VoiceAndroid, `TranscriptionFlagsContractTest.kt` reads its copy.

Only the desktop test compares the copies. Other agreements between the two
applications (for example the wording of the Issues window, tested by
`tests/unit/test_issues_text.py`) are kept by expectations written in both
suites, with no shared file.

---

## 10. What happens when a prerequisite is missing

| Missing | What happens |
|---|---|
| The core not built (section 2.2) | `tests/conftest.py` imports `core.config`, which imports `voicecore`; pytest stops with an import error before running any test |
| The core built from older code | The tests run against the older core and their results describe code that is no longer in the source tree |
| PySide6 | `tests/conftest.py` cannot import `QApplication`; pytest stops before running any test |
| moto | `tests/integration/test_file_storage.py` and `tests/sync/test_file_locations_sync.py` import `tests.local_s3` at module level, so collecting them fails. pytest runs no tests at all when collection fails, so a run of the whole suite, or of `tests/integration` or `tests/sync`, ends with collection errors and no results. Other directories are not affected |
| `ffmpeg` on `PATH` | `tests/cli/test_cli_audiofiles.py::TestAudiofilesWaveforms::test_keeps_the_levels_of_every_recording_here_once` fails with "ffmpeg is required to decode recordings". It is not skipped |
| A sync server that does not answer `/sync/status` within 10 seconds | `running_server_a`, `running_server_b`, `two_nodes_with_servers` and `three_nodes_with_servers` fail the test ("Failed to start sync server ...") |
| `../VoiceAndroid` | `test_the_android_copy_is_the_same_file` is skipped (section 9) |
| Not running from the `Voice` directory | `cli_runner` runs `python -m src.main` without setting a working directory, and `src.main` is not found |

---

## 11. The core's Rust tests

The core has its own tests, inline in its source files, plus two whole test
files: `src/convergence_tests.rs` and `src/timezone_tests.rs`.

```bash
cd /home/dotancohen/Projects/VoiceFamily/Voice/submodules/voicecore
cargo test
cargo test convergence
cargo test -- --nocapture
```

`cargo test convergence` runs the property-based convergence tests: 2 to 4
in-memory devices make random edits in Hebrew and exchange them in random order
until no device has anything left to send, and the tests assert that every device holds the same
data. Build output goes to `/home/dotancohen/Projects/VoiceFamily/.cargo-target`
(set in `VoiceFamily/.cargo/config.toml`), not to a `target/` directory in the
checkout.

To trace one seed of the convergence tests:

```bash
cd /home/dotancohen/Projects/VoiceFamily/Voice/submodules/voicecore
FLEET_DEBUG=1 FLEET_SEED=<n> cargo test debug_single_seed -- --nocapture
```

| Variable | Default | Meaning |
|---|---|---|
| `FLEET_SEED` | not set | The seed. Without it, `debug_single_seed` passes without running anything |
| `FLEET_DEBUG` | not set | Any value prints the trace |
| `FLEET_TOPOLOGY` | mesh | `hub` for a hub topology |
| `FLEET_DEVICES` | 3 | Number of devices |
| `FLEET_STEPS` | 80 | Number of random operations |
| `FLEET_PAGE` | 5 | Feed page size |
| `FLEET_DUP` | 0 | Each delivery has a chance of one in N of being delivered twice (0: never) |

Which Rust tests cover which specification rule is listed in section 12 of
[`../SYNC_SPECIFICATION.md`](../SYNC_SPECIFICATION.md).

The phone's tests are described in
[`../VoiceAndroid/DEVELOPMENT.md`](../VoiceAndroid/DEVELOPMENT.md). Before
running any Android task whose name contains `connected` or `install`, read
[`../CLAUDE.md`](../CLAUDE.md), "The owner's data": such a task installs an
application on a device, and on 2026-09-12 one destroyed a week of the owner's
notes.

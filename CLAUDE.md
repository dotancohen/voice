# Claude Code Instructions

## Technical decisions

Decisions that apply to more than one project in the Voice Family — data rules,
time handling, thresholds, naming, interface conventions, testing rules — are in
`../TECHNICAL-DECISIONS.md`. Read it before changing behaviour that the other
projects share, and record new cross-project decisions there rather than in this
file.


## Violation Logging

When you violate user instructions (performing tasks not explicitly requested, making assumptions instead of asking, giving evasive answers, etc.), you MUST document the violation in `CLAUDE-VIOLATIONS.md`. Include:
- Date
- What happened
- Which instruction was violated
- The user's response
- Why it happened

This is mandatory. Do not skip this step.

## Code Patterns

Always read the existing code. Do not make assumptions. Before implementing new functionality, find and read how similar functionality is already implemented in the codebase.

## Testing

### A failing test is never negotiated with

**Read this before touching a failing test.** A failing test says one of two
things: the code is wrong, or the test's premise is wrong. Say which, in plain
words, before editing anything.

It is forbidden to make a test pass by:

- writing values into the database, a file or a cache so that the assertion
  finds what it wants;
- loosening, deleting or rewriting the assertion;
- changing the fixture so that the condition under test no longer exists;
- adding a branch to the production code that only the test reaches;
- marking it skipped, expected-to-fail or flaky.

A test altered to pass reports success while telling nobody anything about
whether the software works. That is worse than having no test.

When a test cannot construct the state it needs — real data reached that state
through history no API reproduces, for example a Note written before the display
caches existed — the code lacks a seam. Separate the logic from the data access
and test the logic with constructed rows; `src/core/missing_data.py` has its
`survey_rows` and `notes_missing_caches` seam for exactly this, and
`VoiceAndroid`'s `data/MissingData.kt` has its `Store` interface. Restructuring the code under
test so it can be tested is legitimate; manufacturing the data is not.

See `../TECHNICAL-DECISIONS.md` 6.5.

### Naming

No ambiguous words, in code or in anything the user reads: no "fill", "handle",
"process", "manage", "do". Say what happens — calculate, read, copy, rebuild,
delete, send. When a name is wrong, rename it everywhere in one change. See
`../TECHNICAL-DECISIONS.md` 4.4.

### What every feature needs

Always add tests for new functionality before declaring a feature complete. Include:
- Happy path tests
- Edge cases
- Hebrew text in test data (this is a Hebrew-focused application)

Run all tests and ensure they pass before considering the feature done.

### Prefer Tests Over Bash Scripts

When tempted to create a bash script to verify or test something, consider creating a pytest test case instead. Before creating either:
1. Ask the user which approach they prefer
2. Explain what the bash script would do
3. Explain what the equivalent test case would do
4. Show code for both options

**Why tests are usually better:**
- Tests are repeatable and run automatically in CI
- Tests document expected behavior
- Tests catch regressions
- Tests live in the codebase permanently

**When bash scripts are appropriate:**
- One-time manual operations
- Build/deploy scripts
- Interactive debugging sessions

## File Reading

When reading files, read the whole file at once rather than searching for individual portions. This avoids requiring multiple authorization prompts.

## Project Structure

### Submodule: voicecore
The `submodules/voicecore` directory is a git submodule containing the core Rust library. It is shared between:
- **Voice** (this repo) - Python desktop app, uses voicecore via PyO3 bindings in `rust/voice-python/`
- **VoiceAndroid** - Android app, uses voicecore via UniFFI bindings in `android.rs`

### Building Python Bindings
Always run maturin from the `rust/voice-python/` directory, NOT from the repo root:
```bash
cd /home/dotancohen/Projects/VoiceFamily/Voice/rust/voice-python
/home/dotancohen/Projects/VoiceFamily/Voice/.venv/bin/maturin develop --release
```

### Running Rust Tests
Run tests from the voicecore submodule directory:
```bash
cd /home/dotancohen/Projects/VoiceFamily/Voice/submodules/voicecore
cargo test
```

## Exposing New Functionality

When adding new database methods or functionality:

1. **Core implementation**: Add to `submodules/voicecore/src/database.rs`

2. **Python bindings**: Expose in `rust/voice-python/src/lib.rs` for CLI/TUI access

3. **Android bindings**: Expose in `submodules/voicecore/src/android.rs` for VoiceAndroid access
   - Requires rebuilding with `cargo ndk` for Android
   - Must copy .so file to VoiceAndroid's jniLibs directory

Missing any binding layer will cause the functionality to be unavailable on that platform.

## Logging and Debugging

Use the `tracing` crate for logging, NOT `eprintln!` or `println!`:
- `tracing::error!()` - Errors that need attention
- `tracing::warn!()` - Warnings
- `tracing::info!()` - Important operational info (shown by default)
- `tracing::debug!()` - Debugging info (shown with --verbose)
- `tracing::trace!()` - Very detailed tracing (rarely shown)

The sync server's `--verbose` flag enables DEBUG level logging via `EnvFilter::new("debug")`.

## Database

### Schema Location
The database schema is defined in `submodules/voicecore/src/database.rs` in the `create_tables()` function.

### Transcription Flags (the `state` field)
The `transcriptions.state` field tracks the verification/editing status of a transcription. It's a space-separated string of flags — the field name is `state` in the database and in the sync protocol and stays that way, but everything above the database calls them flags, because any number of them can be true at once. `src/core/transcription_flags.py` is the one definition (names, wording, `has_flag`, `toggle_flag`), mirrored by `data/TranscriptionFlags.kt` in VoiceAndroid; the agreed cases are in `tests/fixtures/transcription_flags_contract.json`, read by the test suites of both applications, and both copies of that file must be identical. The five:
- `original` - Unmodified transcription from the service
- `verified` - User has verified the transcription is accurate
- `verbatim` - Transcription includes filler words, false starts, etc.
- `cleaned` - Transcription has been cleaned up (remove filler words)
- `polished` - Transcription has been edited for readability

Example: `"original verified"` means the original transcription has been verified as accurate.

### Note Display Cache

The `di_cache_note_pane_display` column on the `notes` table stores pre-computed data for faster Note pane display. The cache JSON contains:
- `tags` - List of tags with `id`, `name`, and `full_path` (hierarchical path)
- `conflicts` - List of conflict type strings (e.g., `["content", "delete"]`)
- `attachments` - List of attachments with nested `audio_file` and `transcriptions` data
- `cached_at` - Timestamp when cache was last built

**When to update the cache schema:**
If you add new fields to the Note pane display that require database queries, consider:
1. Adding the field to the cache JSON in `rebuild_note_cache()` in `database.rs`
2. Updating the cache consumer in `note_pane.py` (`_load_from_cache()`)
3. Adding auto-rebuild triggers to any mutation methods that affect the new field

**Auto-rebuild triggers:**
The cache is automatically rebuilt when these operations affect a note:
- `update_note()` - content changed
- `add_tag_to_note()` / `remove_tag_from_note()` - tags changed
- `create_transcription()` / `update_transcription()` - transcriptions changed
- `accept_conflict()` / `resolve_conflict_with_content()` and any sync that flags or resolves a conflict (`refresh_entity_caches()` in `versions.rs`)

**Manual rebuild:**
```bash
# Rebuild cache for a specific note
python -m src.main cli db-maintenance rebuild-cache <note_id>

# Rebuild cache for all notes (may take time with many notes)
python -m src.main cli db-maintenance rebuild-cache
```

## UI Frameworks

### Desktop TUI
The desktop GUI uses **Textual** (Python TUI framework). Main files:
- `src/tui.py` - Main TUI application and screens
- `src/ui/` - UI components and widgets

### Android
The Android app uses **Jetpack Compose** with the MVVM pattern:
- ViewModels in `viewmodel/` directory
- Composable screens in `ui/screens/`
- Repository pattern in `data/VoiceRepository.kt`

**Times and timezones:** timestamps are Unix seconds; beside each user-visible one the core stores `<stamp>_offset` (seconds east of UTC where it happened) and `<stamp>_zone` (IANA name). A reader renders the instant at that offset, so a note written at 15:20 in Jerusalem still reads 15:20 in New York; rows with no offset fall back to the reader's zone. The platform reports its zone (`Database.__init__` in Python, `VoiceRepository.reportTimeZone` on Android), because the core cannot see Android's framework settings. Locale and the 12/24-hour preference are never stored: each interface formats with its own (`src/core/timestamp_utils.py`, `util/Stamps.kt`). Ordering and merging use the instant alone. See `SYNC_SPECIFICATION.md` 3.3 and the core README.

**Recorder:** `audio/VoiceRecorder.kt` is the single recorder and lives outside any screen, because leaving the app, going home or locking the phone must not stop a recording; `audio/RecordingService.kt` is the foreground service (type `microphone`) that keeps the process alive and shows the elapsed time in a notification. `viewmodel/RecordingViewModel.kt` only exposes its flows, and `ui/screens/RecordingScreen.kt` only presses its buttons, so the screen can come and go. During a telephone call Android hands the microphone to the telephone, so Settings → Recorder chooses between keeping the silence and pausing until the call ends (`RecorderPreferences.duringCall`, watched through `AudioManager.mode` in the recorder's ticker). `RecorderPreferences.kt` also holds the selected microphone and its friendly names, the default action of the New button, the recording format, and whether the recording screen starts recording as it opens. `audio/MicLevelMeter.kt` is the level stream for the microphone test. Save is `importAudioFile` plus a copy into the audio directory, so a recording is a note with an attachment exactly like an imported file. Formats: Opus 128 kb/s 48 kHz in Ogg (`.ogg`, default) and AAC 96 kb/s (`.m4a`) through MediaRecorder; 16 kHz mono 16-bit WAV (`.wav`) through `audio/WavRecorder.kt` (AudioRecord, Whisper's native input). The notes list's `+` button taps the default action and long-presses for the menu.

**Playback speed:** `audio/PlaybackPreferences.kt` (one speed for every player, 0.5×–3×), `ui/components/PlaybackSpeedControl.kt` (a Canvas slider with ½/1/2 marks that snap, under the waveform in both `AudioPlayerWidget` and the list's `CompactAudioPlayer`). The notes list shows one line of the note and one line of the first transcription of any recording on it, and skips whichever is missing rather than leaving an empty row. The New button turns into a red record icon when a tap would start a recording. A selection of notes can be merged (`NotesViewModel.mergeSelected`, oldest survives, `merge_notes` in the core moves tags and attachments and deletes the emptied notes). In the notes list each recording is a small `🔊n` button at the left of the row (`AttachmentChip` in `NotesScreen.kt`) that unfolds the compact player; it carries a small transcribe icon when that recording already has a transcription. The chip's contents are wrapped in `CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr)`: in a right-to-left interface the bidirectional algorithm otherwise renders `🔊1` as `1🔊` (the symbol is a neutral, the digit a European number), which put the symbol on the wrong side. Video attachments get their own symbol next to `AUDIO_SYMBOL`.

**Selecting several notes:** long-press a note in the list (`NotesViewModel.selectedNoteIds`); while a selection exists the star becomes a tick box, a tap toggles selection instead of opening the note, Back leaves the selection, and a bar at the bottom offers Tag (`ui/components/MultiTagDialog.kt`, a tri-state box per tag: filled when every selected note has it, half when only some, and tapping adds to those missing or removes from all), Delete (soft delete of each note) and Transcribe (queues every recording of the selected notes). Transcriptions always run one at a time; `OnDeviceTranscriber` holds the queue and `TranscriptionService` shows "N waiting" in its notification. A bulk transcription skips any recording that already has a finished transcription from the chosen model (`NoteWithAudioFiles.transcribedModels`, filled from each row's `service_arguments`); asking the same model again is deliberate and therefore only possible in a note, where it asks for confirmation first. `Transcription.isFinished` in `data/Note.kt` is what "already transcribed" means: not `Pending...` and not `Error:`.

**Leaving a note:** the list keeps its scroll position (`rememberLazyListState` hoisted in `NotesScreen`, item keys are note ids) and points out the row of the note just left with two dots that travel from the middle of the row to its edges (`ui/components/Spotlight.kt`; bright warm dots in the light theme, barely lighter than the row in the dark one). How long that takes is Settings → Advanced → Spotlight duration (`util/UiPreferences.kt`, 0 to 1 second, 0 turns it off), a device setting that is not synced. `AudioPlayerManager.setPlaybackSpeed` sets ExoPlayer's `PlaybackParameters(speed, pitch = 1)` on the running player, which time-stretches without restarting.

**On-device transcription (`transcription/`):** whisper.cpp through VoiceTranscription's `voice-transcription-android` crate (`jniLibs/arm64-v8a/libvoice_transcription_android.so` + `libc++_shared.so`, Kotlin in `java/uniffi/voice_transcription/`; arm64 only, other ABIs have no library). `WhisperModels.kt` is the model catalogue (ggml files from Hugging Face, stored in `files/whisper-models/`, downloaded with resume), `TranscriptionPreferences.kt` the chosen model/language/beam size, `AudioToWav.kt` decodes any recording with MediaCodec and resamples (windowed sinc) to 16 kHz mono WAV because the phone has no ffmpeg, `OnDeviceTranscriber.kt` the queue and the job itself (creates a "Pending..." transcription row, then stores content, segments JSON and service response exactly like `transcription_service.py`, service name `local_whisper`), `TranscriptionService.kt` the foreground service that runs the queue (type `mediaProcessing` on API 35+, `dataSync` on 34). UI: Settings → Transcription (`TranscriptionSettingsScreen`), and a transcribe icon at the left of every file in the note's player (`AudioFileListItem`), which opens `ui/components/TranscribeDialog.kt` (model + language, Cancel/Settings/Transcribe). The note screen shows only the transcriptions of the file the player is on (`onCurrentFileChanged`); `TranscriptionCard` carries two buttons under the text — copy, and `TranscriptionDetailsDialog`, which holds when/service/model/language, how the transcription ran (elapsed, CPU, cores busy, peak memory, model size, the phone — written by `OnDeviceTranscriber`'s `WorkWatch` into `service_response.performance`), the main-transcription mark, and the five flags of `data/TranscriptionFlags.kt` (the same five, in the same words, as `src/core/transcription_flags.py` here). Features under trial are behind `BuildConfig.DEV_FEATURES` (debug builds only): drag-to-select in the notes list, transcribe-on-save, and editing a transcription's text. Rebuilding the whisper library: see VoiceTranscription/README.md "Build Android Bindings".

**ADB automation (debug builds):** `app/src/debug/.../automation/AdbCommandReceiver.kt` exposes every user action as a broadcast Intent; `tools/voice-adb` wraps it. When adding a user-facing action to the app, add the matching action to the receiver, its intent-filter in `app/src/debug/AndroidManifest.xml`, and a line in `voice-adb`, so the manual test plans can script it.

**UI Guidelines:**
- **Never use Floating Action Buttons (FABs)** - These floating buttons hover over content and block UI elements underneath them (e.g., the last item in a list, dropdown menus). Always place action buttons in the TopAppBar's `actions` slot instead.

### Building VoiceAndroid

When building the Android app after modifying voicecore Rust code:

1. **Regenerate Kotlin bindings** (if you added/changed UniFFI-exposed functions):
```bash
cd /home/dotancohen/Projects/VoiceFamily/VoiceAndroid/submodules/voicecore
cargo build --release --features uniffi
"$CARGO_TARGET/release/uniffi-bindgen" generate --library "$CARGO_TARGET/release/libvoicecore.so" --language kotlin --out-dir /tmp/kotlin-bindings
cp /tmp/kotlin-bindings/uniffi/voicecore/voicecore.kt /home/dotancohen/Projects/VoiceFamily/VoiceAndroid/app/src/main/java/uniffi/voicecore/voicecore.kt
```

2. **Build native library for Android** - CRITICAL: Use absolute path for output:
```bash
cd /home/dotancohen/Projects/VoiceFamily/VoiceAndroid/submodules/voicecore
ANDROID_NDK_HOME=/home/dotancohen/Android/Sdk/ndk/29.0.14206865 cargo ndk -t arm64-v8a -o /home/dotancohen/Projects/VoiceFamily/VoiceAndroid/app/src/main/jniLibs build --release --features uniffi
```

**WARNING**: every Rust crate in the family shares one build directory
(`VoiceFamily/.cargo-target`, see `../TECHNICAL-DECISIONS.md` 7.4), and
`target/release/libvoicecore.so` is one path that several builds write to. A
`maturin develop` for the Python bindings rebuilds voicecore **without** the
`uniffi` feature and replaces that file, after which `uniffi-bindgen` reads no
interface from it and silently generates nothing (it still exits 0). Cargo does
not notice, because its fingerprint says the featured build is current. So:
generate the Kotlin bindings *before* running maturin, or force the build first:

```bash
cd /home/dotancohen/Projects/VoiceFamily/VoiceAndroid/submodules/voicecore
touch src/lib.rs && cargo build --release --features uniffi
```

Always check that the new function is in the generated file before copying it.

**WARNING**: Do NOT use relative paths with `cargo ndk -o`. The relative path is resolved from the Cargo workspace root, not the current directory, which can cause the .so file to be copied to the wrong location. Always use absolute paths.

3. **Build APK**:
```bash
cd /home/dotancohen/Projects/VoiceFamily/VoiceAndroid
JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 ./gradlew assembleDebug
```

Use the system JDK 21, not Android Studio's bundled JBR. As of 2026-09-11 that
JBR is JDK 25, and this Gradle/Kotlin cannot parse its version string: every
task fails immediately with `java.lang.IllegalArgumentException: 25.0.3`.

4. **Install on device**:
```bash
adb install /home/dotancohen/Projects/VoiceFamily/VoiceAndroid/app/build/outputs/apk/debug/app-debug.apk
```

**Common crash: `UnsatisfiedLinkError: undefined symbol`**
This means the Kotlin bindings reference functions that don't exist in the native library. Causes:
- Forgot to rebuild libvoicecore.so after adding new Rust functions
- Library was copied to wrong path (see WARNING above about relative paths)
- Kotlin bindings were regenerated but native library wasn't rebuilt

Fix: Ensure both Kotlin bindings AND native library are rebuilt, and library is in the correct jniLibs path.

**CRITICAL: Always rebuild BOTH bindings AND native library together**
When changing UniFFI-exposed Rust code, you MUST rebuild both:
1. Kotlin bindings (using uniffi-bindgen)
2. Android native library (using cargo ndk)

If you only regenerate bindings without rebuilding the native library, the app will crash with `UnsatisfiedLinkError` because the bindings expect functions that don't exist in the old `.so` file. This is easy to miss because the desktop build/test may work fine while Android crashes.

## Common Commands

`bin/voice` wraps `.venv/bin/python -m src.main`; `VOICE_CONFIG_DIR` replaces `-d`. Every run prints `Using CONFIG_DIR: ...` first (stderr for JSON/CSV output). Tests that count or compare stdout lines must skip that line.

```bash
# Run CLI
.venv/bin/python -m src.main cli <command>

# Run TUI
.venv/bin/python -m src.main gui

# Run sync server
.venv/bin/python -m src.main cli sync serve --verbose

# Sync to a peer
.venv/bin/python -m src.main cli sync now <peer_url>

# Run Python tests
.venv/bin/python -m pytest

# Run Rust tests
cd submodules/voicecore && cargo test
```

## Documentation Requirements

When making changes to any structured API, documentation MUST be updated:

The documentation is three files: `README.md` says what VOICE is and why
(marketing), `USER_MANUAL.md` says how it is used (every interface, every
setting), and `DEVELOPMENT.md` says how to install, build, deploy and test
it. Put a change where its reader is, not where the text used to live.

### CLI Changes
- Add new commands/options to `USER_MANUAL.md` in the appropriate section
- Update the `--help` text in `src/cli.py` (argparse help strings)
- If adding sync-related commands, update both "Syncing between installations" and any troubleshooting sections

### Sync Protocol Changes
- Update `submodules/voicecore/README.md` with new endpoints, request/response formats
- Document any new entity types in the sync protocol section
- Update the Change Format example if fields change

### Web API Changes
- Update `USER_MANUAL.md` Web API Endpoints section
- Update docstring in `src/web.py` with endpoint documentation
- Include example curl commands

### Configuration Changes
- Update `USER_MANUAL.md` Config Options table
- Update `CONFIGURATION.md` if it exists
- Update example config JSON snippets

## Teaching and Corrections

When I make mistakes, point them out and teach me the correct way. This includes:

- Spelling errors
- Grammatical errors
- Incorrect technical terminology
- Misunderstandings about technology or concepts
- Poorly phrased questions or statements

My goal is to learn. When correcting me:
1. Point out the specific mistake
2. Explain the correct term, concept, or phrasing
3. Provide context so I understand *why* it's correct

If I phrase something poorly, suggest a more accurate phrasing.

## Sync Design Decisions

### Partial Batch Failures
When applying a batch of sync changes, if change 5 of 10 fails:
- Changes 1-4 should still be applied (already done)
- Changes 6-10 should still be attempted and applied if valid
- Only the failing change(s) should be reported as errors
- Do NOT wrap all changes in a single transaction that rolls back everything
- Each change is independent - one failure should not prevent others from succeeding

### Datetime Format Enforcement
All datetime strings MUST be in the format "YYYY-MM-DD HH:MM:SS" with zero-padded values.

**Why this matters:**
- Timestamps are compared as strings for LWW (Last Write Wins)
- Non-zero-padded dates break string comparison: "2025-1-1" < "2025-12-01" is lexically wrong
- "2025-01-01" correctly sorts before "2025-12-01"

**Enforcement approach:**
1. **Code validation (Rust)**: `validate_datetime()` in `validation.rs` rejects malformed dates
2. **Sync boundary validation**: All incoming sync changes are validated before applying
3. **Python binding**: `validate_datetime()` is exposed to Python for API-level validation

**Database enforcement options (not currently implemented):**
- SQLite CHECK constraints don't support complex regex patterns natively
- Could add a trigger, but code-level validation is sufficient since:
  - All data enters via the Rust/Python API layer
  - The sync apply functions validate before writing
  - Direct SQL access is not expected in production

### Per-Entity-Type Limits in get_changes_since()

**CRITICAL**: The `get_changes_since()` function in `database.rs` (used by both the sync server's `/sync/changes` handler and the client's push) must use per-entity-type limits, NOT a shared global limit. (An earlier fix went into `sync_server.rs` only and was lost when the query moved into `database.rs`; the fix now lives in `database.rs` as `let remaining = limit;` before each entity-type query.)

**What went wrong (fixed 2026-01-09):**
The original code had a shared `limit` (default 1000) across all entity types. Each entity type query would only run if `remaining > 0`:
```rust
// BAD: This caused tags to be skipped if notes consumed the limit
let remaining = limit - changes.len();
if remaining > 0 {
    // query tags...
}
```

If a client had many notes modified since their last sync (filling the 1000 limit), tags/note_tags/audio_files/transcriptions would be **completely skipped**, causing missing data.

**The fix:**
Each entity type now gets its own `per_type_limit` allocation:
```rust
// GOOD: Each type gets its own limit
let per_type_limit = limit;
// query notes with per_type_limit
// query tags with per_type_limit (no "if remaining > 0" check)
// etc.
```

**Why Full Re-sync worked but incremental didn't:**
- `/sync/full` endpoint uses `get_full_dataset()` which queries each entity type separately with NO limit
- `/sync/changes` endpoint used `get_changes_since()` with the buggy shared limit

### NULL modified_at Causes Entities to Be Invisible in Incremental Sync

**CRITICAL**: When the server applies an incoming sync change (tag, note_tag, audio_file, etc.), it MUST set `modified_at` to a non-NULL timestamp if the incoming data has `modified_at = NULL`.

**What went wrong (fixed 2026-01-09):**
When a device creates an entity (e.g., a tag), it sets `created_at` but leaves `modified_at = NULL`. When this entity is synced to the server, the server stored it with `modified_at = NULL`. The incremental sync query:
```sql
WHERE modified_at > ? OR (modified_at IS NULL AND created_at > ?)
```
only returns entities where EITHER:
- `modified_at` is after the since timestamp, OR
- `modified_at` is NULL AND `created_at` is after the since timestamp

If a client's `last_sync_at` is after the entity's `created_at`, and `modified_at` is NULL, the entity is NEVER returned.

**Example failure scenario:**
1. Desktop creates tag at Dec 30 (`created_at = "2025-12-30"`, `modified_at = NULL`)
2. Desktop syncs to server - server stores tag with `modified_at = NULL`
3. Android syncs at Jan 1, setting `last_sync_at = "2026-01-01"`
4. Desktop creates new tag at Jan 5
5. Android syncs at Jan 6, asking for changes since `"2026-01-01"`
6. Server query: tag has `created_at = "2025-12-30"` < `"2026-01-01"` and `modified_at = NULL`
7. Tag is NOT returned because neither condition matches
8. Full Re-sync works because it doesn't filter by timestamp

**The fix:**
In `sync_server.rs` apply functions (`apply_tag_change`, `apply_note_tag_change`, etc.), use the change's timestamp as a fallback when `modified_at` is NULL:
```rust
let modified_at = data["modified_at"].as_str()
    .or(Some(change.timestamp.as_str()));
```

This ensures entities received via sync always have a `modified_at` timestamp, making them discoverable by subsequent incremental syncs.

**Database migration for existing data:**
If you have an existing database with NULL `modified_at` values, run:
```sql
UPDATE tags SET modified_at = created_at WHERE modified_at IS NULL;
UPDATE note_tags SET modified_at = created_at WHERE modified_at IS NULL;
UPDATE note_attachments SET modified_at = created_at WHERE modified_at IS NULL;
UPDATE audio_files SET modified_at = imported_at WHERE modified_at IS NULL;
```

### Adding New Syncable Entity Types

When adding a new entity type that needs to sync between devices, you MUST update ALL of the following locations (and add the table to `migrate_add_sync_sequence` in `database.rs` so it gets a `seq` column and triggers, or it will never appear in the cursor feed):

1. **`sync_server.rs` - `get_changes_since()`**: Add a query to fetch changes for the new entity type. Without this, the entity will never be sent to clients during sync.

2. **`sync_server.rs` - `apply_sync_changes()`**: Add a match arm to handle applying changes for the new entity type.

3. **`sync_server.rs` - `get_full_dataset()`**: Add a query to include the entity in full sync responses.

4. **`sync_server.rs` - `ALL_SYNC_ENTITY_TYPES` constant**: Add the entity type string to this list.

5. **`sync_server.rs` - `test_get_changes_since_returns_all_entity_types`**: Add test data creation for the new entity type.

6. **`sync_client.rs` - `apply_*_change()`**: Add a function to apply incoming changes for this entity type.

7. **`database.rs`**: Add `apply_sync_<entity>()` method for applying sync changes.

8. **`android.rs`** (if needed for Android): Expose any new methods via UniFFI bindings.

9. **`lib.rs`** (Python bindings): Expose any new methods to Python.

**Why this matters:** We had a bug where transcriptions were missing from `get_changes_since()`, causing transcription changes to never sync to clients. The `test_get_changes_since_returns_all_entity_types` test now catches this - it will fail if any entity type in `ALL_SYNC_ENTITY_TYPES` is not returned by `get_changes_since()`.

### Audio File Binaries: Cloud Storage, On Demand

Audio file *metadata* syncs like every other entity. The *binary* is handled by `file_storage.rs` and never by the sync server:

- The device that imported a file uploads it to cloud storage before every push (`storage_provider IS NULL AND deleted_at IS NULL AND the file is on this device`). Records without a local file are skipped silently: they belong to another device. Upload failures are warnings, not sync errors, and are retried on the next sync.
- Other devices download a binary only when the user asks (CLI `audiofile-download` / `note-audiofiles-download`, TUI `d` / Download button, GUI Download button, Android Download button), unless `sync.mirror_audio_files` is enabled in that installation's `config.json` (desktop/server only, never synced).
- "Cloud storage not configured" is a silent no-op for the automatic paths and a clear error for the on-demand ones.
- Downloads go to `<file>.part`, are size-verified against the object, then renamed. A crash never leaves a truncated file that looks present.
- After the first remote failure in a batch the batch stops (`deferred` count); the rest is retried next sync instead of timing out one by one.
- The on-disk and cloud object name is `{audio_id}.{ext}` where `ext` comes from `audio_file_extension()` (`models.rs`, mirrored by `audio_file_extension()` in `src/core/audiofile_manager.py`): lowercase, last dot wins, `bin` when there is no extension. Every platform must use these helpers; never derive the extension by hand.
- Every incoming `audio_file` row is applied through one upsert that merges per column: the newer row wins a metadata column, an older row only fills in NULLs, the cloud location is never erased by a row without one and only replaced by a newer row that has one, and the versioned columns (summary, deletion) are never written from a row. Do not reintroduce "skip older rows": it left a peer that edited the summary first without the `storage_key`.
- rust-s3 must stay at 0.37 or newer: older versions load TLS roots from the OS certificate directory, which Android does not have.

### Data Loss Prevention - CRITICAL

**NEVER use LWW (Last Writer Wins) or any other data loss strategy.**

**Definition of Data:**
- All note content
- Tag associations (note_tags)
- Tag names
- Tag hierarchies (parent_id relationships)
- Note attachments
- Note attachment fields
- Audio files and their metadata

**Definition of Data Loss:**
1. Any database record of the above data is removed, unless the user explicitly runs a delete operation
2. Any database record of the above data is not copied to another instance (server or client) when syncing

**Required behavior:**
- Conflicts must create conflict records for user resolution, never silently overwrite
- Sync must propagate ALL changes to all peers, never skip changes
- Deletes must be soft-deletes with timestamps, never hard-deletes
- When both sides have changes, merge and flag - do NOT pick a winner
- `versions.rs` is the authoritative implementation (see below)

### Versioned Fields (versions.rs)

Every editable value is a field with a Git-like history in `field_versions` (append-only DAG: `parent_id`, `merge_parent_id`), a head per field in `field_heads`, and conflicts in `field_conflicts`. Entity rows (`notes.content`, `tags.name`, ...) are denormalised copies of the heads, rewritten by `apply_head_to_entity()`.

- **Write path:** every mutation goes through `set_field()` / `set_deleted()` (never `UPDATE notes SET content` directly). A new field is registered in `field_kind()` / `fields_for_entity()` and denormalised in `apply_head_to_entity()`.
- **Sync:** the feed carries `field_version` changes; `sync_apply.rs` applies versions first, rows second, links last, then `recompute_heads()`. Rows without history get a deterministic hash root (`ensure_root_version`), so pre-versioning data merges cleanly.
- **Merge rules:** Text = diff3 (markers `<<<<<<< VERSION A` / `>>>>>>> VERSION B`, symmetric on every device); Scalar = later wins + flag; Flags = per-flag; Membership and Deleted = disagreement keeps the link/entity + flag; delete that did not see a concurrent edit is resurrected (delete conflict).
- **Determinism:** root, merge, accept and resurrect version ids and conflict ids are hashes, so every device computes the same graph and the same conflict ids. `conflict_kind` travels on the merge version so a device that merely receives a merge still records the conflict.
- **Resolution:** any version descending from the merge (an edit, or `accept_conflict()`) resolves it everywhere. Saving a note with an open conflict resolves it. There is no keep-local / keep-remote: both sides are already in the merge.
- **Synced settings:** `synced_settings` is a versioned key/value store (`get_setting` / `set_setting`); `src/core/synced_settings.py` reconciles it with `config.json` on startup.
- **First edit of a field** (e.g. the first tombstone) has no parent but has a `device_id`; only hash roots (no parent, no device) are treated as pre-existing data with timestamp 0.
- **Authored vs derived:** merges and resurrections (parent, no device) are derived and are NOT synced; every device recomputes them. Heads are folded from the *authored* leaves only (`authored_leaves`), so arrival order and page size cannot change the result. An authored version written on top of a derived one publishes it (`publish_derived_ancestors`) so peers can complete the child. Never make a derived version a fold input; never sync one that is not published.
- **Cursor feed:** `get_changes_after_seq(cursor, upto, limit)` is the sync feed. Every syncable table has a `seq` column stamped by triggers (`migrate_add_sync_sequence`): on insert, and on update of a synced column *when the value changed*. Row updates on the apply path must use `NULLIF(MAX(...), 0)` forms so an echo of our own data writes nothing (otherwise rows ping-pong between peers forever). Adding a syncable table means adding it to the trigger list there. `recompute_head` must write the entity row exactly once.
- **Property tests:** `cargo test convergence` runs random multi-device fleets (`src/convergence_tests.rs`): every entity type, pages down to 1, duplicate deliveries, a hub topology, a replaced device. Run them after any change to versions.rs, sync_apply.rs, the row-apply upserts or the feed; they found every regression so far (they must also stay quiescent: a row written with a changed value on every echo shows up as "fleet did not quiesce"). `FLEET_DEBUG=1 FLEET_SEED=<n> [FLEET_TOPOLOGY=hub ...] cargo test debug_single_seed -- --nocapture` traces one seed.
- **Unversioned metadata** (transcription `service_response`/`content_segments`, audio filename/duration, attachment target) merges per column by `modified_at` in the `apply_sync_*` upserts. A local update of such a column must stamp `modified_at` and must treat `None` as "leave alone" (see `update_transcription`).
- **Tag cycles** from concurrent moves are broken deterministically in `recompute_head` (largest id on the cycle loses, derived no-parent head, scalar conflict). Recursive tag queries use `UNION` / a depth limit; keep it that way.
- **Batches and pages:** `sync_apply::apply_changes` runs one batch in one `BEGIN IMMEDIATE` transaction; never open another transaction inside a row-apply path. Feed pages are bounded by `FEED_BYTE_BUDGET` (4 MB) in both directions; keep any new feed content under it rather than raising the server body limit. The client pages initial syncs from cursor zero; `/sync/full` is for tools only.
- **Specification:** `SYNC_SPECIFICATION.md` numbers every rule; name the id in new tests.

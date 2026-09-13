# VOICE — user manual

How the application is used: the four interfaces, what each screen and
command does, and the settings behind them. For what VOICE is, see the
[README](README.md); for installing and building it,
[DEVELOPMENT.md](DEVELOPMENT.md).

## Contents

- [Usage](#usage)
- [What a transcription says about itself](#what-a-transcription-says-about-itself)
- [Long recordings](#long-recordings)
  - [Transcribing what the phone could not](#transcribing-what-the-phone-could-not)
- [The trash bin](#the-trash-bin)
- [Dates of imported recordings](#dates-of-imported-recordings)
- [Calculating missing data](#calculating-missing-data)
- [The transcription queue](#the-transcription-queue)
- [Syncing between installations](#syncing-between-installations)
- [Cloud storage for audio files](#cloud-storage-for-audio-files)
- [Search syntax](#search-syntax)
- [Recording voice notes](#recording-voice-notes)
- [Configuration](#configuration)
- [Database location](#database-location)

## Usage

- For now no packaged executable. All interfaces are accessed through a unified entry point: `python -m src.main`

```bash
python -m src.main          # Auto-detect interface: GUI if available, else TUI
python -m src.main -a sillyberry       # Open another account of this installation
```

The first line every run prints is `Using CONFIG_DIR: <directory>` (on stderr when the output format is JSON or CSV, so that stdout stays parseable). The directory is chosen in this order:

1. the `VOICE_CONFIG_DIR` environment variable, which names the **root**
   (`~/.config/voice` by default): the machine's settings, `accounts.db`, and
   one directory per account
2. `-a <id or label>` on the command line, or `$VOICE_ACCOUNT_ID`, which
   chooses the account under the root; without either, the default account
3. `~/.config/voice/`

The `bin/voice` script runs the entry point through the repository's virtual environment from any directory. Put it on your `PATH` once and use `voice` instead of `.venv/bin/python -m src.main`:

```bash
ln -s ~/Projects/VoiceFamily/Voice/bin/voice ~/.local/bin/voice     # or: alias voice=~/Projects/VoiceFamily/Voice/bin/voice
export VOICE_CONFIG_DIR=~/voice-test                     # optional: a config directory for testing
voice cli sync status
voice tui
```

This device's local configuration (name, audio folder, sync port) is read and written with `voice cli config`:

```bash
voice cli config show
voice cli config get device_name
voice cli config set device_name "Desktop"
voice cli config set audiofile_directory ~/voice-audio   # created if missing
```

### GUI Mode

```bash
python -m src.main gui                        # Force GUI mode
python -m src.main gui --theme light  # Force light theme
python -m src.main gui --theme dark   # Force dark theme
```

### TUI Mode

```bash
python -m src.main tui
```

#### TUI Keybaord Controls

- `Up/Down`: Navigate lists
- `Left/Right`: Collapse/Expand tag hierarchy
- `Enter`: Select item
- `e`: Edit selected note
- `s`: Save changes
- `a`: Show all notes
- `q`: Quit
- `Ctrl+P`: Open command palette

### CLI Mode

- Allow specifying the first few UUID characters only, like Git does

Create notes:
```bash
python -m src.main cli note-create "Hello, world!"
echo "Note from stdin" | python -m src.main cli note-create
```

Show specific note:
```bash
python -m src.main cli note-show <note-uuid>
```
List all notes:
```bash
python -m src.main cli notes-list
```

Search notes:
```bash
python -m src.main cli notes-search --text "meeting"                            # Search by text
python -m src.main cli notes-search --tag Work                                         # Search by tag
python -m src.main cli notes-search --tag Europe/France/Paris         # Search by hierarchical tag path
python -m src.main cli notes-search --tag Work --tag Projects  # Multiple tags (AND logic)
python -m src.main cli notes-search --text "meeting" --tag Work        # Combined text and tags
```

#### Tag management

```bash
python -m src.main cli tags-list                                                          # List tags (hierarchical)
python -m src.main cli tag-create "Foobar"                                      # Add root-level tag
python -m src.main cli tag-create "Foobar" --parent <tag-uuid>       # Add a tag with a parent
python -m src.main cli notes-tag --tags <tag-uuid> <tag-uuid> --notes <note-uuid> <note-uuid>    # Attach tags to notes
```

#### Import files

Import directory of audio files as new notes:
```bash
python -m src.main cli audiofiles-import /path/to/files/
python -m src.main cli audiofiles-import /path/to/files/ --recursive      # Include subdirectories
python -m src.main cli audiofiles-import /path/to/files/ --tags <tag-uuid> # Tag imported notes
python -m src.main cli audiofiles-import /path/to/files/ --tags <uuid1> <uuid2>  # Multiple tags
```

#### Audio files stored in the cloud

Audio binaries are not copied by sync; they are uploaded to cloud storage by the device that imported them and fetched by other devices only when asked (see "Cloud Storage for Audio Files"). To fetch media on this device:
```bash
python -m src.main cli audiofile-download <audiofile-uuid>         # One file
python -m src.main cli note-audiofiles-download <note-uuid>        # All files of a note
python -m src.main cli audiofile-show <audiofile-uuid>             # Shows whether the media is on this device / in the cloud
python -m src.main cli note-audiofiles-list --note-id <note-uuid>  # Same, per note
```

Transcribing a file that is not on this device downloads it first.

#### Transcription

Transcribe audio files attached to notes using local Whisper AI:

```bash
# Transcribe all audio files for a specific note
python -m src.main cli note-audiofiles-transcribe <note-uuid>

# Transcribe a specific audio file
python -m src.main cli audiofile-transcribe <audiofile-uuid>

# Specify model (name or full path)
python -m src.main cli note-audiofiles-transcribe <note-uuid> --model small
python -m src.main cli note-audiofiles-transcribe <note-uuid> --model large-v3
python -m src.main cli audiofile-transcribe <audiofile-uuid> --model /path/to/ggml-model.bin

# Specify language hint (see "Language hints" below)
python -m src.main cli note-audiofiles-transcribe <note-uuid> --language he
python -m src.main cli audiofile-transcribe <audiofile-uuid> --language en

# Specify expected number of speakers
python -m src.main cli note-audiofiles-transcribe <note-uuid> --speaker-count 2
```

**Language hints:**

Providing a language hint improves transcription accuracy, especially for non-English audio. Languages are specified using [ISO 639-1 two-letter codes](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes).

Common language codes:
| Code | Language |
|------|----------|
| `en` | English |
| `he` | Hebrew |
| `ar` | Arabic |
| `es` | Spanish |
| `fr` | French |
| `de` | German |
| `zh` | Chinese |
| `ja` | Japanese |
| `ru` | Russian |

You can set default preferred languages in `config.json`:
```json
{
  "transcription": {
    "preferred_languages": ["he", "en", "ar"]
  }
}
```

When transcribing, the language is determined by (in order of priority):
1. The `--language` CLI argument
2. The first language in `transcription.preferred_languages` config
3. Auto-detection by Whisper (if no hint provided)

**Model selection:**
- The `--model` flag accepts either a model name (e.g., `small`, `large-v3`) or a full path to a GGML model file
- Model names are resolved from `~/.local/share/whisper/ggml-<name>.bin`
- If no model is specified, the largest available model is automatically selected
- When multiple versions of the same size exist (e.g., `large-v2`, `large-v3`), the highest version is preferred

**Available model sizes** (in order of quality/size):
- `tiny` - Fastest, lowest quality (~75 MB)
- `base` - Fast, basic quality (~142 MB)
- `small` - Good balance of speed/quality (~487 MB)
- `medium` - High quality (~1.5 GB)
- `large`, `large-v2`, `large-v3` - Highest quality (~3 GB)

**Downloading models:**

GGML Whisper models can be downloaded from [Hugging Face](https://huggingface.co/ggerganov/whisper.cpp/tree/main):
```bash
mkdir -p ~/.local/share/whisper
cd ~/.local/share/whisper
wget https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin
```

**Transcription providers:**

The following transcription providers are supported. Configure them in `config.json` under `transcription.providers`:

| Provider | Description | Configuration |
|----------|-------------|---------------|
| `whisper` | Local Whisper AI (default) | `model_path`: Path to GGML model file |
| `google` | Google Cloud Speech-to-Text | `credentials_path`, `project_id`, `speech_model`, `speech_location`, `sample_rate`, `batch_timeout` |
| `assemblyai` | AssemblyAI API | `api_key` |
| `huggingface` | HuggingFace (for diarization) | `token` |

Example provider configuration:
```json
{
  "transcription": {
    "preferred_languages": ["en", "he"],
    "providers": {
      "whisper": {
        "model_path": "/home/user/.local/share/whisper/ggml-large-v3.bin"
      }
    }
  }
}
```

#### Database maintenance

**Normalize timestamps:**

- Normalizes timestamps from ISO 8601 format (2025-12-29T23:22:13.462391) to SQLite format (2025-12-29 23:22:13)
- Uses PRAGMA user_version to track migration status (only runs once)
- Is extensible - future normalizations (like unicode normalization) can be added to the normalize_database() method

```
python -m src.main cli db-maintenance database-normalize
```

**Rebuild note display cache:**

The display cache stores pre-computed data for faster Note pane display (tags, conflicts, attachments with transcriptions). The cache is automatically updated when notes, tags, or attachments change.

To manually rebuild:

```bash
# Rebuild cache for a specific note
python -m src.main cli db-maintenance rebuild-cache <note_id>

# Rebuild cache for all notes
python -m src.main cli db-maintenance rebuild-cache
```

#### Output formatting

```bash
python -m src.main cli --format json # JSON output
python -m src.main cli --format csv  # CSV output
```

### Web API Mode

- Server runs on `http://127.0.0.1:5000` by default.
- All endpoints return JSON.
- CORS is enabled for cross-origin requests.
- IDs are UUID7 hex strings (32 characters, no hyphens).

```bash
python -m src.main web
python -m src.main web --host 0.0.0.0 --port 8080 # Custom host or port
python -m src.main web --debug                    # Debug mode
```

#### Web API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/notes` | List all notes |
| POST | `/api/notes` | Create a new note |
| GET | `/api/notes/<id>` | Get specific note |
| PUT | `/api/notes/<id>` | Update a note |
| DELETE | `/api/notes/<id>` | Delete a note (soft delete) |
| GET | `/api/notes/<id>/attachments` | List attachments for a note |
| GET | `/api/audiofiles/<id>` | Get audio file details |
| GET | `/api/tags` | List all tags |
| GET | `/api/search` | Search notes |

#### Example API Usage

**List and retrieve notes:**
```bash
curl http://127.0.0.1:5000/api/health                # Health check
curl http://127.0.0.1:5000/api/notes                 # List all notes
curl http://127.0.0.1:5000/api/notes/<note-uuid>     # Get specific note
curl http://127.0.0.1:5000/api/tags                  # List all tags
```

**Create and update notes:**
```bash
# Create a new note
curl -X POST http://127.0.0.1:5000/api/notes \
  -H "Content-Type: application/json" \
  -d '{"content": "My new note"}'

# Update an existing note
curl -X PUT http://127.0.0.1:5000/api/notes/<note-uuid> \
  -H "Content-Type: application/json" \
  -d '{"content": "Updated content"}'

# Delete a note (soft delete)
curl -X DELETE http://127.0.0.1:5000/api/notes/<note-uuid>
```

**Search notes:**
```bash
curl "http://127.0.0.1:5000/api/search?text=meeting"                # Search by text
curl "http://127.0.0.1:5000/api/search?tag=Work"                    # Search by tag
curl "http://127.0.0.1:5000/api/search?tag=Europe/France/Paris"     # Hierarchical tag
curl "http://127.0.0.1:5000/api/search?tag=Work&tag=Projects"       # Multiple tags (AND logic)
curl "http://127.0.0.1:5000/api/search?text=meeting&tag=Work"       # Combined text and tags
```

**Get attachments and audio files:**
```bash
curl http://127.0.0.1:5000/api/notes/<note-uuid>/attachments  # List note attachments
curl http://127.0.0.1:5000/api/audiofiles/<audio-uuid>        # Get audio file details
```

#### API Response Format

**Success responses** return the requested data directly:
```json
{
  "id": "018d1234abcd5678901234567890abcd",
  "content": "Note content here",
  "created_at": "2024-01-15 10:30:00",
  "modified_at": "2024-01-15 10:35:00"
}
```

**Error responses** include an error message:
```json
{
  "error": "Note 018d1234... not found"
}
```

**HTTP Status Codes:**
- `200` - Success
- `201` - Created (for POST requests)
- `400` - Bad request (validation error)
- `404` - Not found
- `500` - Internal server error

## What a transcription says about itself

A transcription is more than its text: it carries when it was made, by which
service and with which model, and what has been done to it since. Unfold a
transcription in the GUI and its **Flags** are the five lines under the text.
Click one to turn it on or off.

| Flag | Means |
|------|-------|
| Original | Unmodified transcription from the service |
| Verified | User has verified the transcription is accurate |
| Verbatim | Transcription includes filler words, false starts, etc. |
| Cleaned | Transcription has been cleaned up (remove filler words) |
| Polished | Transcription has been edited for readability |

They are flags rather than one state because any number of them can be true
at once: a transcription can be verified *and* cleaned, and a verbatim one
that is later tidied stops being verbatim and becomes cleaned. Nothing sets
them for you except *Original*, which is true of every transcription until
somebody edits it — they are a record of what a person has done, kept for the
person who reads it next.

Every Tag also has a colour of its own, calculated from the first six
characters of the MD5 hash of its name, so the same Tag looks the same here
and on the phone with nothing stored. A colour chosen on either device is
kept in the synced settings under `tag_color.<name>` and travels with
everything else.

The flags are stored in the transcription's `state` field, a space-separated
list of those five words with `!` in front of the ones that are off, so
`original !verified !verbatim !cleaned !polished` is a fresh transcription.
That field name is the one the database and the sync protocol have always
used; only what you read calls them flags. The field syncs with everything
else, and the Android application shows the same five in the same words, so a
transcription verified on a phone reads as verified here.

## Long recordings

A Note holds a recording of any length. An eight-hour recording of somebody
sleeping is kept, played, tagged, searched and synced exactly like a
two-minute voice note; nothing about it is a special case.

One thing is **offered rather than done** for a long recording, because it
means reading the whole of it: the **waveform**. Drawing one decodes the
entire recording — on an ordinary desktop that is a few seconds for an hour of
audio and most of a minute for eight hours, and on a phone many times slower.
For a recording past the limits below, the waveform area reads

> Click to generate waveform
> Resource intensive operation on large file

and the waveform is drawn when you click it. It is then kept with the
recording, so the waiting happens once.

### Transcribing what the phone could not

**Transcription has no length limit here, and this is where the long ones are
done.** The Android application transcribes up to ten minutes and refers
anything longer to the desktop, because Whisper holds the whole recording in
memory as it works — about 230 MB an hour on top of the model — which a phone
does not have. A recording of many hours will still exhaust a small machine;
for those, use the machine with the most memory.

Those Recordings do not transcribe themselves. To find them:

```bash
python -m src.main cli transcribe-backlog --dry-run
```

which lists every Recording over ten minutes with no Transcription, and its
length. To transcribe them, this machine has to be told that it can:

```bash
python -m src.main cli transcribe-backlog --enable     # once, on this machine
python -m src.main cli transcribe-backlog              # then, whenever you like
```

**The setting belongs to the machine, and is never synced**, because whether a
computer can transcribe a two-hour meeting is a fact about that computer. A
laptop without the hardware leaves it off and nothing changes for it; the
machine that has the hardware turns it on. `--force` transcribes them for one
run without changing the setting, and `--disable` turns it off again.

Options: `--min-minutes N` to pick up Recordings over some other length (the
default is ten minutes, the phone's own limit), `--limit N` to do only so many
in one run, and `--language`, `--model` and `--backend` as for any other
transcription.

A Recording whose length was never recorded is left alone: its length is
exactly what this decision needs, and a wrong guess means spending an hour on
something the phone would have done in a minute.


### What counts as a large recording

| Measure | Limit |
|---------|-------|
| Length | 60 minutes |
| Size | 100 MiB |

Either one is enough. The length is the measure that matters, because the work
tracks the length of the audio; the size catches a recording whose length is
not known yet, or whose header is wrong. For reference, 100 MiB is about 52
minutes of 16 kHz WAV, 1.8 hours of Opus at 128 kb/s, or 2.4 hours of AAC at
96 kb/s.

Both numbers are in `src/core/waveform.py` as `LONG_RECORDING_SECONDS` and
`LARGE_RECORDING_BYTES`, and the Android application uses the same two.

## The trash bin

Deleting a note has always been reversible: the note keeps its history and
its recordings, and every device is told that it was deleted rather than
being told to forget it. The trash bin is where those notes are seen and
dealt with.

- **GUI**: File → Trash. Recover puts a note back in the list; *Delete for
  good* asks once and then removes it.
- **TUI**: `Ctrl+T`. The same two buttons; *Delete for good* asks by making
  you press it twice, so one keystroke can never destroy a note.
- **CLI**: `trash-list`, `note-recover <id>`, `note-purge <id>`. The purge
  asks you to type the word `delete` unless `--yes` is given.
- **Web API**: `GET /api/trash`, `POST /api/trash/<id>/recover`,
  `DELETE /api/trash/<id>`.
- **Android**: Settings → Trash.

Removing a note for good takes its history, its tag links, its attachments
and the recordings that hung on that note alone, on this device and on every
device it syncs with. It cannot be undone, and a device that has not synced
yet cannot bring the note back: the removal is written down and travels, and
anything that arrives about a removed note is dropped. A recording that
another note still holds is never taken. A copy already uploaded to cloud
storage is not deleted from the bucket.

## Dates of imported recordings

The date of an imported recording is taken from the filesystem, which is right
whenever the file was copied with its dates intact. A date in the file name is
used only when it is more than 48 hours older than the filesystem date, which
is what a copy made without preserving dates looks like (`rsync` without `-a`,
a download, a restore from a phone). A file name date close to the filesystem
date, or newer than it, is ignored.

These file name shapes are recognised, each of which carries a time as well as
a date: `Recording 2026-09-08 14-53-14`, `2026-09-08 14-53-14`,
`2026-09-08T14:53:14`, `20260908_145314` and `REC_20260908_145314`, wherever
they appear in the name. A name holding only a date is not enough.

## The transcription queue

Transcribing locally takes the whole machine: the model wants about a gigabyte of
memory and every core, so two transcriptions at once are slower than the same two
in turn. So a recording sent to be transcribed goes into a queue and is worked on
one at a time.

There is **one queue for the whole installation**, not one per interface. It is a
small file, `transcription_queue.json`, in your configuration directory, so the
GUI, the TUI, the CLI and the Web API all show the same queue and can all reorder
it. The file is local to this computer and is never synced: what this machine is
busy with is not a fact about your notes.

The queue is shown in three groups, read downwards as time runs forwards:

| Group | What it is |
|---|---|
| Waiting | Recordings that have not started. Newest first, with the place each one will really be reached in, and how long until it is done |
| Processing | The recording being transcribed now |
| Completed | What is finished, newest first, with what the work cost |

A finished recording carries the numbers the screen exists for: how much text
came out, how long the recording was, and the **clock time**, **processor time**
and **peak memory** the work took. Those are what tell you whether a larger model
is worth its wait, and they are what every waiting estimate is calculated from —
the estimate is the median of what this machine has actually done with that
model, not a specification. Until something has finished here, no estimate is
offered, because a made-up number is worse than none.

**Moving one recording to the front.** When you need one transcription before the
rest, "transcribe this one next" puts it at the head of the queue. The recording
being worked on is never interrupted: it is minutes into work that would have to
start again, which would cost more than the wait. "Next" means next after that
one.

**GUI:** File → Transcription queue... A table, one row per recording, with the
note it belongs to. Select a waiting row to move it to the front or take it out.

**TUI:** Ctrl+K. `n` moves the selected recording to the front, `r` takes it out,
F5 reads the queue again.

**CLI:**

```bash
# What is waiting, what is running, and what the finished ones cost
.venv/bin/python -m src.main cli transcription-queue

# The same as JSON, the shape the Web API returns
.venv/bin/python -m src.main cli transcription-queue --format json

# Transcribe this one next, or take it out (ids may be given as prefixes)
.venv/bin/python -m src.main cli transcription-queue --next 01a0938f
.venv/bin/python -m src.main cli transcription-queue --remove 01a0938f

# Forget everything waiting; what is being worked on is not stopped
.venv/bin/python -m src.main cli transcription-queue --clear

# Do the waiting work here and now, one recording at a time
.venv/bin/python -m src.main cli transcription-queue --run --limit 3
```

**Web API:**

```bash
# The queue
curl http://localhost:5000/api/transcription-queue

# Put a recording in it
curl -X POST http://localhost:5000/api/transcription-queue \
    -H 'Content-Type: application/json' \
    -d '{"audio_file_id": "01a0...", "provider": {"provider_id": "local_whisper"}}'

# Move one to the front, take one out, forget everything waiting
curl -X POST http://localhost:5000/api/transcription-queue/next \
    -H 'Content-Type: application/json' -d '{"audio_file_id": "01a0..."}'
curl -X POST http://localhost:5000/api/transcription-queue/remove \
    -H 'Content-Type: application/json' -d '{"audio_file_id": "01a0..."}'
curl -X POST http://localhost:5000/api/transcription-queue/clear
```

The Web API does not transcribe: it queues. The GUI works through the queue while
it is open, and `transcription-queue --run` does it from a terminal.

The phone has the same queue for its own work; see VoiceAndroid's user manual.

## Calculating missing data

Some facts about a recording are not known when it arrives, and some were
never calculated: a file imported before lengths were recorded has no length, a
recording copied without its filesystem dates has no creation date, and a note
written before the display caches existed has no cache. None of that is lost
data — it can be read back off the file, or computed again — but until it is, the
application shows less than it knows, and the decisions that depend on a
length (whether a waveform is drawn without asking, whether the phone will
transcribe a recording) have nothing to go on.

The repair is one operation with one report, on every interface. It runs in two
steps: it says what is missing, and it calculates only when asked, because
reading the length of every recording is work and you should see what it is for
before it starts.

What it calculates:

| What | Where it comes from |
|---|---|
| Recordings with no length recorded | read off the file's header (`ffprobe`); the audio is not decoded, so an eight-hour recording costs the same as a one-minute one |
| Recordings with no creation date | the filesystem date, or the date in the name the file arrived under, by the rule in [Dates of imported recordings](#dates-of-imported-recordings) |
| Notes with no display cache | recomputed from the note, its tags and its attachments |

What it never calculates, and says so instead:

| What | Why not |
|---|---|
| Recordings whose file is not on this computer | there is nothing here to read. Download them first, or run the repair on the device that has them |
| Recordings with no timezone recorded | a timezone cannot be derived from a file, and writing this computer's offset would state something false about where the recording was made |

Running it twice is harmless: the second run finds nothing to do. Nothing it
writes is an edit by you, so none of it touches a note's history; the values
reach the other devices as ordinary metadata on the next sync.

**GUI:** File → Calculate &missing data... It shows what is missing, asks, then
reports what it calculated.

**TUI:** Ctrl+F.

**CLI:**

```bash
# Say what is missing, change nothing
.venv/bin/python -m src.main cli calculate-missing-data --dry-run

# Calculate it
.venv/bin/python -m src.main cli calculate-missing-data

# Only the lengths, and only the first fifty recordings
.venv/bin/python -m src.main cli calculate-missing-data --no-dates --no-caches --limit 50
```

| Option | What it does |
|---|---|
| `--dry-run` | Report what is missing and stop |
| `--limit N` | At most N recordings, for a run that should not take all night |
| `--no-durations` | Leave the lengths alone |
| `--no-dates` | Leave the creation dates alone |
| `--no-caches` | Leave the display caches alone |

**Web API:**

```bash
# What is missing
curl http://localhost:5000/api/maintenance/missing-data

# Calculate it (the same options, as JSON)
curl -X POST http://localhost:5000/api/maintenance/missing-data \
    -H 'Content-Type: application/json' \
    -d '{"durations": true, "file_dates": true, "caches": true, "limit": 50}'
```

On the phone the same repair is Settings → Calculate missing data; see
VoiceAndroid's user manual.

## Syncing between installations

- The other devices of the account are the **peers**. After a device is
  paired (its code read, or its grant text used) every device of the account
  appears in the peer list by itself, with its name and where it listens;
  nothing is typed twice. A peer can also be added by hand from its id and
  address (`sync add-peer`, "Add by address…").
- Every device can listen and every device can call. Choose one instance to
  listen (the desktop's "Listen for peers", the phone's switch, or
  `sync serve`), and press the button on another. The result is the same
  whichever side listened.
- **One button**: the desktop's File → Sync… dialogue and the phone's sync
  screen show "Exchange with Desk", where Desk is the peer used last. The
  arrow beside it chooses another peer or another operation (sync, deliver,
  exchange, send, fetch). Every result is one sentence and ends with the
  request id, which is in both devices' logs.
- A peer can be **renamed** on this device (`sync rename-peer`, "Rename…") and
  **forgotten** (`sync remove-peer`, "Forget"): a forgotten peer's card does
  not bring it back until it is added again or paired again.
- **Finding each other**: a listening device announces itself on the local
  network with a hash of the account id, never the id. An operation tries
  the address it remembers first; if nothing answers there, it asks the
  network where the peer is and remembers the answer. `sync discover` and
  the dialogue's "Find on this network" list the devices of the account
  nearby. A listener without a configured `public_url` serves its own
  network only; a phone on hotel wifi is not a server for the hotel.
- **While an operation runs** the dialogue (and the phone's notification)
  says what it is doing and how far it is, and has a Cancel button: a
  transfer stopped continues from where it stopped next time.
- **The listener can stop itself** after one, four or eight hours of
  silence, chosen beside the switch; by default it keeps listening.
- Instances can be run as a systemd service to run in the background.

On the instance designated as the server:
```bash
# Get device ID
python -m src.main cli sync status

# Start the sync server, if it is not running as a systemd service
python -m src.main cli sync serve
```

On the instance designated as the client:
```bash
# Add server as a peer, with the fingerprint its 'sync serve' printed
python -m src.main cli sync add-peer <peer-device-id> "PeerName" https://<peer-ip>:8384 --fingerprint SHA256:...

# Trigger sync
python -m src.main cli sync now                                              # Sync with all configured peers
python -m src.main cli sync now --peer <peer-device-id> # Sync with a specific peer only
```

### Conflicts

Every editable value (note content, tag name and parent, transcription text and state, tag links, attachments, deletions, synced settings) is versioned like a Git history. When two devices change the same value before syncing, the sync merges the two versions three-way:

- Text is merged line by line. Edits to different lines combine silently. Edits to the same lines are both kept in the text between `<<<<<<< VERSION A` / `=======` / `>>>>>>> VERSION B` markers.
- A deletion never wins over a concurrent edit: the item stays alive with the edit.
- A tag link removed on one device but kept on the other stays attached.
- A tag renamed or moved on both devices keeps the later value.

In every case that needed a decision, a conflict record is created on every device (same id everywhere) naming the two devices. The GUI, TUI and Android show a banner on the note with an **Accept merge** button. Resolving happens in one of two ways, and either way the resolution reaches every peer:

- **Edit and save** the note (clean up the markers). A save while a conflict is open resolves it.
- **Accept the merge** as it stands.

The **Resolve…** button (GUI, TUI, Android) opens the two versions and their common ancestor side by side next to an editable result. **History** (GUI, TUI, Android) lists every earlier version of the note and restores any of them; a restore is a normal edit, so nothing is lost.

```bash
# Delete a note (soft), rename or move a tag; all of these sync and merge like any edit
python -m src.main cli note-delete <note-id>
python -m src.main cli tag-rename <tag-id> "שם חדש"
python -m src.main cli tag-move <tag-id> <parent-tag-id>
python -m src.main cli tag-move <tag-id> --root

# Every version of a note, oldest first; show one; restore one
python -m src.main cli note-history <note-id>
python -m src.main cli note-history <note-id> --show <version-id>
python -m src.main cli note-restore <note-id> <version-id>

# List conflicts (add --details for the base, both sides and the merged value)
python -m src.main cli sync conflicts
python -m src.main cli sync conflicts --note <note-id>
python -m src.main cli sync conflicts --all           # include resolved

# Accept the merged value as it is
python -m src.main cli sync resolve <conflict-id>

# Replace the value with corrected text
python -m src.main cli sync resolve <conflict-id> --content-file fixed.txt
python -m src.main cli sync resolve <conflict-id> --content "טקסט מתוקן"
```

### Where "later wins"

Text is never decided by time: both edits are kept. Time decides only where there is no way to keep both, and each such decision is recorded so nothing is hidden:

| Decision | What is compared | Recorded? |
|----------|------------------|-----------|
| A tag renamed or moved on two devices; a synced setting changed on two devices | the version's `created_at`; the later one is shown | yes, a scalar conflict listing both values and both devices |
| The same transcription flag (verified, cleaned, ...) switched both ways on two devices | the version's `created_at` | yes, a flags conflict |
| Unversioned metadata: an audio file's filename, duration and creation time; a transcription's service name, arguments, response and segments; which note an attachment belongs to | the row's `modified_at`; the newer row wins each column, an older row only fills gaps | no (machine-written fields) |
| The cloud location of an audio file after a re-upload | `modified_at`; a row without a location never erases one | no |
| The cloud storage configuration | `modified_at` | no |

A device whose clock is badly wrong therefore wins those decisions; it never loses or gains data. Merges, deletions, links and convergence between devices do not depend on clocks at all (see `SYNC_SPECIFICATION.md`, LIM-13).

### Synced settings

A few settings are about the user rather than the machine and follow the user to every device through the database: `transcription.preferred_languages` and the API key of each cloud transcription provider (`transcription.providers.<provider>.api_key`). Paths, ports and models stay local. On startup the synced value overrides `config.json`; a value present only in `config.json` seeds the other devices. To change one:

```bash
python -m src.main cli settings list
python -m src.main cli settings get transcription.preferred_languages
python -m src.main cli settings set transcription.preferred_languages '["he", "en"]'
python -m src.main cli settings set transcription.providers.assemblyai.api_key <key>
```

### The account, and snapshots

Every database belongs to one **account**, a 32-character id minted with it. Two
devices exchange changes only when they hold the same account; a device of
another account is refused with a sentence naming both, and nothing crosses.
That is what keeps two people's notes apart when both reach the same server or
the same address.

```bash
python -m src.main cli account show          # the account id, the database id, the note count
python -m src.main cli account snapshots     # the copies kept beside the database, newest first
python -m src.main cli account snapshot      # take a copy now
python -m src.main cli account restore <name>   # replace the database with a copy (asks first)
```

A **snapshot** is a copy of the whole notes database, taken before every sync
and before anything else that rewrites the database in one step. The newest
five are kept in `snapshots/` beside the database. Restoring one brings the
notes back as they were; the state being replaced is kept as the newest
snapshot, so a restore can itself be undone. Recordings are files and are never
part of a snapshot.

Moving a database to another account is the one way two accounts are merged,
and it is deliberate: `account move --to <id> --current <id>` proceeds only when
the full id of the account being given up is typed by hand. A snapshot is taken
first, and every peer is forgotten so the next sync exchanges everything.

### Listening for peers

A device is reachable only while it **listens**: File → Listen for peers in
the desktop, the switch on the phone's sync screen, or `sync serve` on a
server. About shows the account, the device id, the addresses and the
certificate fingerprint of this device, which another device may need typed.

### Moving recordings between devices

A sync moves notes, tags and the list of recordings, never a recording's
bytes. The bytes move with these, each with one peer:

```bash
python -m src.main cli sync deliver <peer>    # sync, then send the recordings the peer lacks
python -m src.main cli sync exchange <peer>   # sync, then send and fetch
python -m src.main cli sync send <peer>       # send only, no sync
python -m src.main cli sync fetch <peer>      # fetch only, no sync
```

A recording travels streamed, so an eight-hour file needs no memory to speak
of, and a transfer that stops continues from where it stopped the next time.
The receiver checks the file's hash before it accepts it, and refuses a file
that would fill its disk.

### The periodic backup

Every 24 hours (`backup.interval_hours` in the root's `config.json`; 0 turns
it off) the listener and the open desktop copy each account's database to
`<root>/backups/<account id>/`, keeping the newest 30. It is separate from
the snapshots taken before every sync. `account backup` does it now.

### Merging two accounts

For a phone and a desktop that ended up with different accounts:
`account move --to "<the other account's code>" --current <this account's full id, typed by hand>`
(on the phone, Advanced Settings → Move this device to another account).
A snapshot is taken, the device joins the other account keeping its notes,
tags with one path become one, and everything is exchanged. Nothing is
deleted.

### Where recordings are, and what they are called

A recording's file is named after its start and the end of its id:
`2026_09_21_14_30_59-abcdefgh.ogg`. On the phone the files are in the
shared `Recordings/Voice` folder (reachable from any file manager and over a
cable, and left alone when the application is replaced); on the desktop in
the account's `audio` folder. The folder holds recordings and nothing else.

### The bucket, set up by the wizard

File → Set up the bucket… (or `storage setup`) takes a person who has never
seen the Amazon console from nothing to a tested bucket: where to click, the
policy text to paste (it lets the key make and use buckets named `voice-…`
and nothing else; it cannot delete a recording), the pasted key cleaned of
spaces, the nearest region proposed, a generated bucket name, the bucket
made private and hardened (public access blocked, encrypted, TLS only), its
lifecycle rules set (cheaper storage after thirty days), a small object
written and read back, and the whole saved as part of the account so every
device receives it at its next sync. A purged recording's object is tagged
and removed by the bucket a day later. "Replace the bucket's key…" tests a
new key the same way and saves it for every device. "Test everything" in
the sync dialogue, or `sync check --all`, checks every peer and the bucket
as one table; `storage check` the bucket alone.

### Is everything somewhere else too?

`sync status` says, in one line, what exists on this device only: "3 notes
and 2 recordings are not duplicated off this device", or "Everything is
duplicated off this device." A note counts as duplicated once a sync has
sent it to any peer; a recording once it is in the bucket or a peer is
known to hold it. Below the line, every peer with when it was last reached
and what the last operation was. The phone shows the same line at the top
of its sync screen, and nowhere else: no notification, no badge. A
recording's details (`note-audiofiles-list`) name where its copies are:
this device, the bucket, and each peer.

### Pairing a new device

The device that holds the account shows a **code**; the new device reads it.
Nothing lasting is in the code: a token that is valid for ten minutes and for
one device, the account id, and where the showing device listens.

```bash
python -m src.main cli sync serve                  # the showing device must be listening
python -m src.main cli account show-code           # a QR code and the setup text (add --url if the address is wrong)
python -m src.main cli account hide-code           # withdraw the code before it expires
python -m src.main cli account join "voice://pair?..."   # on the new device: paste the setup text
```

The new device takes the account, receives a key of its own, and adds the
showing device as a peer with its certificate pinned. On the phone that key
is kept wrapped by the Android Keystore, so a copy of the app's files does not
carry it; on the desktop `config.json` is readable by its owner only. A device that already
holds notes of another account refuses the code and says to show its own code
to the other device instead.

On the phone, Settings → Sync has **Show my code** (the code stays on screen
for a minute, with Copy and Share beside it) and **Read a code**, which opens
the camera with a paste field under it for a phone whose camera cannot read
it. A setup text sent through any messaging app is a link: tapping it opens
Voice at the sync screen and pairs. A phone with no notes yet offers "Pair
with another device" and "Start on my own" on its first screen, and after
pairing shows the new peer with one Exchange button.

### A server that hosts accounts

A server on the internet holds no account of its own; it **hosts** the
accounts its users give it, one directory each under its root, and serves
them all from one listener. The holder of an account cannot be reached by
the server, so the direction is reversed: the server shows a **grant text**
and the holder gives the account to it.

```bash
# On the server, in an empty root (VOICE_CONFIG_DIR): no account is created
python -m src.main cli sync serve                               # serves every account of the root
python -m src.main cli account host --label meirav              # a grant text: valid ten minutes, once

# On the device that holds the account (a phone pastes the text into its setup-text field)
python -m src.main cli account grant-host "voice://pair?v=1&g=1&..."
python -m src.main cli sync deliver <server-device-id>          # notes and recordings to the server

# Back on the server
python -m src.main cli account list                             # the hosted account, never the default
python -m src.main -a meirav cli account show-code              # a code for the account's next device
```

The server receives a key made for it, the holder's card, and the notes on
the first delivery; a further device of the account joins through the
server's code as through any device. Every request to a hosted account is
one line in `audit.log` beside its database: time, device, route, bytes and
outcome, never a key or content. A desktop with several accounts in its root
serves them the same way: `sync serve` there listens for every account.

### Devices, keys and certificates

Every device of an account has a **key** of its own, made when it created the
account or given to it when it was paired. Every request to a peer carries it,
and every peer holds only a hash of it, on the device's **card**, which travels
with the notes. A device nobody has let in, or one that was revoked, is
refused with a sentence and a code.

```bash
python -m src.main cli device list                # every device of the account, with its state
python -m src.main cli device revoke <device-id>  # refuse a device everywhere, once the revocation has travelled
```

A listener serves **HTTPS** with its own certificate. A peer that was paired
knows the certificate's fingerprint and accepts no other; a peer without a
fingerprint is checked against the system's root certificates, as a public
server behind a real certificate needs. Plain `http://` is accepted only to
this machine itself. `sync serve --plain-http` serves plain http for a reverse
proxy in front, and only on a loopback address.

### Sync Troubleshooting

When sync issues occur (e.g., missing attachments, transcriptions, or data inconsistencies), use these commands:

```bash
# Reset sync timestamps - forces next sync to exchange all data
# Useful when incremental sync missed some changes
python -m src.main cli sync reset-timestamps

# Full resync - performs initial sync (full dataset transfer) with peers
# Fetches all data regardless of last_sync timestamps
python -m src.main cli sync full-resync                       # Resync with all peers
python -m src.main cli sync full-resync --peer <peer-id>      # Resync with specific peer
```

**When to use each:**
- `reset-timestamps`: Clears the "last synced" timestamps locally. The next regular `sync now` will exchange all data. Use when you suspect sync state is stale.
- `full-resync`: Immediately performs a complete sync, pulling and pushing all data. Use when you need to recover missing data now.

### Managing Peers

```bash
# List all configured peers
python -m src.main cli sync list-peers

# Remove a peer
python -m src.main cli sync remove-peer <peer-device-id>
```

### Firewall Configuration

Open the sync server port (default 8384) in your firewall.

UFW (Ubuntu/Debian):
```bash
sudo ufw allow 8384/tcp comment "Voice Sync"
sudo ufw reload
    sudo ufw status
```

firewalld (RHEL/CentOS/Fedora):
```bash
sudo firewall-cmd --permanent --add-port=8384/tcp
sudo firewall-cmd --reload
sudo firewall-cmd --list-ports
```

iptables:
```bash
sudo iptables -A INPUT -p tcp --dport 8384 -j ACCEPT
sudo iptables-save | sudo tee /etc/iptables/rules.v4
```
    
### Reverse Proxy with SSL (Recommended)

For production deployments, use a reverse proxy with SSL termination. The sync protocol transmits data in plain text, so HTTPS is strongly recommended.

#### Nginx configuration

- Place this in the file `/etc/nginx/sites-available/voice`

```nginx
server {
    listen 443 ssl http2;
    server_name sync.example.com;

    ssl_certificate /etc/letsencrypt/live/sync.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sync.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8384;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name sync.example.com;
    return 301 https://$server_name$request_uri;
}
```

Enable and test:
```bash
sudo ln -s /etc/nginx/sites-available/voice /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Obtain SSL certificate with Let's Encrypt:
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d sync.example.com
```

When using a reverse proxy, use HTTPS in the peer URL:
```bash
python -m src.main cli sync add-peer <server-device-id> "Server" https://sync.example.com
```

## Cloud Storage for Audio Files

> **Setting it up for the first time?** `CLOUD-STORAGE-SETUP.md` walks through
> creating the storage and collecting the five values it needs, click by click,
> for Amazon S3, DigitalOcean Spaces and Backblaze B2. It assumes no technical
> experience. This section is the reference; that one is the walkthrough.

Audio files can be stored in cloud storage (AWS S3 or S3-compatible services) instead of being synced through the sync server. This is recommended for large audio collections to reduce sync server load.

### Configuration

Storage configuration is stored in the database and syncs between devices automatically.

```bash
# Check current storage configuration
python -m src.main cli storage status

# Configure AWS S3 storage
python -m src.main cli storage configure-s3 \
    --bucket my-voice-audio \
    --region us-east-1 \
    --access-key-id AKIAIOSFODNN7EXAMPLE \
    --secret-access-key wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY \
    --prefix audio/

# Configure S3-compatible storage (DigitalOcean Spaces, MinIO, etc.)
python -m src.main cli storage configure-s3 \
    --bucket my-voice-audio \
    --region us-east-1 \
    --access-key-id <access-key> \
    --secret-access-key <secret-key> \
    --endpoint https://nyc3.digitaloceanspaces.com

# Disable cloud storage (keep files local only)
python -m src.main cli storage disable
```

### AWS S3 Setup

1. Create an S3 bucket
   - S3 -> Create bucket
   - Leave defaults (block public access ON)

2. Create an IAM policy
  - IAM -> Policies -> Create policy.
  - Policy editor: JSON
  - Paste the following JSON, adjusting the `Resource` names for your bucket:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::my-voice-audio",
                "arn:aws:s3:::my-voice-audio/*"
            ]
        }
    ]
}
```
  - Policy name: VoiceFileSync

3. Create an IAM user
  - IAM -> Users -> Create user.
  - User name: `voicefilesync`. Do NOT check "Provide user access to the AWS Management Console".
  - Select "Attach policies directly" then select "VoiceFileSync".

4. Create access key
  - IAM -> Users -> select `voicefilesync` user.
  - Security Credentials -> Access Keys -> Create access key
  - Select "Application running outside AWS"
  - Description tag value: `Voice-File-Sync`
  - Copy your `Access key` and `Secret access key`. This information will be configured in Voice in the next step. If you loose this value, AWS can not show it to you again.

5. Configure Voice with the bucket details and IAM credentials
  - Use the `cli storage configure-s3` command. See previous section for details.

### How It Works

- Metadata (notes, tags, audio file records, transcriptions) syncs through the sync server as before. Audio binaries never do.
- A sync never moves a recording. The device that imported a recording uploads it when you ask: `cli storage upload-pending` here, the Upload button on the phone. Records that were imported on another device are left for that device to upload.
- Other devices download a file **only on demand**: the GUI and TUI show a "Media missing" notice with a Download button (the TUI also uses the `d` key), the CLI has `audiofile-download` and `note-audiofiles-download`, and the Android app shows a Download button on the note. Transcribing a missing file downloads it first.
- Until the importing device has uploaded a file, other devices show it as "not uploaded by its device yet" and cannot fetch it.
- The storage configuration (including the credentials) syncs to all connected devices. Configure it once, on any installation.
- Sync keeps working while cloud storage is unreachable, because it never touches it. An upload that fails is reported and tried again at the next upload, and after the first failure the remaining uploads are deferred instead of each waiting for a timeout.
- Downloads are written to a temporary `.part` file, checked against the object size and only then renamed into place, so an interrupted download never leaves a broken file behind.
- Every recording carries the hash of its bytes. The bucket object is named by it, so the same file imported on two devices is stored once; a download whose bytes do not match the hash is removed and reported instead of being kept as the recording.
- A file larger than 8 MiB goes up in parts. If the connection drops, the parts already in the bucket stay there and the next `upload-pending` (or the phone's next Upload) sends only the rest; the object appears only when every part is there. Parts of an upload never finished are removed by the bucket's own rule after two days.

### Encrypting recordings in the bucket

Off by default. When on, nobody without the account's **recording key** can
listen to a recording in the bucket, Amazon included. The price is a key that,
if lost, makes those recordings unreadable for ever, so:

1. Export the key first: `cli account recording-key export` (a QR code and 43
   characters), "Export the recording key…" in File → Sync…, or "Export the
   key" under Advanced Settings on the phone. Keep it on paper. The switch
   stays off until the key was exported from that device.
2. Turn it on: `cli storage encrypt on`, the "Encrypt recordings in the bucket"
   box, or the switch on the phone. The setting is synced, so every device of
   the account encrypts from then on. Every device receives the key when it is
   paired; a device that lost everything imports it (`cli account recording-key
   import <text>`, "Import…", "Import a key").
3. Recordings already in the bucket stay plain until you press "Re-upload
   existing recordings encrypted" (`cli storage reupload-encrypted`); it goes
   one file at a time and continues where it stopped.

A device with the key keeps its own copies plain: downloads and fetches are
opened on arrival. A device without the key (a server that mirrors the bucket)
keeps the objects as they are and serves them as they are; the device that
fetches from it opens them. Turning encryption off makes new uploads plain and
leaves the encrypted objects readable by any device with the key.

### Manual Upload and Download

```bash
# Upload all audio files on this device that haven't been uploaded to cloud storage yet
python -m src.main cli storage upload-pending

# Download every audio file that is in cloud storage but not on this device
python -m src.main cli storage download-missing
```

`upload-pending` is useful for the initial migration of existing audio files, for troubleshooting, and for uploading when the sync server is not available.

### Keeping a Complete Local Copy (Mirror)

A desktop or server installation can opt in to holding every audio file, as a local backup of the bucket. Every sync then also downloads all missing files. This is a local setting (`sync.mirror_audio_files` in `config.json`); it is never synced and other installations are not aware of it. Do not enable it on Android.

```bash
python -m src.main cli storage mirror enable    # Also run "storage download-missing" to fetch everything now
python -m src.main cli storage mirror disable
python -m src.main cli storage status           # Shows the current mirror setting
```

## Search Syntax

### Free-text Search

- Searches note content (case-insensitive)

```
meeting
hello world
```

### Tag Search

- Hierarchical paths supported. Parent tag searchess include children.

```
tag:Paris               # Matches both Europe/France/Paris and US/Texas/Paris
tag:Europe/France/Paris
```

### Combined Search (AND logic)

```
tag:Work meeting
tag:Personal tag:Family reunion
```
Multiple terms are combined with AND logic:
- `tag:A tag:B` - notes must have (A or descendants) AND (B or descendants)
- `tag:A hello` - notes must have (A or descendants) AND contain the text "hello"

## Recording voice notes

- On Android I use and recommend [Axet Audio Recorder](https://f-droid.org/en/packages/com.github.axet.audiorecorder/), which can set filenames as timestamps.
- Another good Android app is [ASR Voice Recorder - Apps on Google Play](https://play.google.com/store/apps/details?id=com.nll.asr&hl=en)
- [Wearable device that records your voice for legal defense | Hacker News](https://news.ycombinator.com/item?id=36457266)

### Tips

- Take care to enunciate clearly at first. It will make listening easier, and help with AI transcription.
- If recording after midnight, mention in the recording that the content relates to the previous day.

### Concerns

- Who is being recorded?
- Do they know they are being recorded?

- What devices are used to record?
- Using internal device mics, or higher quality external mics?
- Does the mic have a wind muff? This reduces wind noise but severely muffles voice quality.

- For what purpose is the recording?
- Who is going to listen to it? When?

- Transcription?
- Does the transcription need timestamps?
- Multiple people speaking simultaneously? Do you need per-speaker seperation?
- Do you need to identify people by their voice?
- Identify sounds in the background?
- Identify yelling?
- Identify emotions via voice clues?

- Are there multiple languages in the recordings?
- Are there many proper nouns?
- Many non-dictionary terms?
- Is the speech typically confined to a specific subject?
- Are there nonstandard accents?
- Unusually fast or slow speech?
- Wordplay or puns?

- Is there background noise?
- Consistent background noise or intermittent?
- Is there wind noise?
- Is there background music?
- Are there background voices?

- In what formats are the existing recordings?
- Are you flexible in choosing a different recording format?
- What are the consequences of an inaccurate transcription?
- How fast must the transcription run?
- Does it need to be local?
- On what hardware?
- Are there storage constraints?
- What is the transcription budget?
- Does it need to be open source?

## Configuration

- Configuration is stored in `<config-dir>/config.json`. The default location is `~/.config/voice/config.json`, or can be set with the `-d` flag.
- Tho configuration file can be edited manually. The application reads the config file on startup.
- For detailed documentation, see [CONFIGURATION.md](CONFIGURATION.md).

### Config Schema

```json
{
  "database_file": "/path/to/notes.db",
  "default_interface": null,
  "window_geometry": null,
  "implementations": {},
  "themes": {
    "colours": {
      "warnings": "#FFFF00",
      "warnings_dark": "#FFFF00",
      "warnings_light": "#FF8C00",
      "tui_border_focused": "green",
      "tui_border_unfocused": "blue"
    }
  },
  "transcription": {
    "preferred_languages": ["en"],
    "providers": {
      "whisper": {
        "model_path": "/home/user/.local/share/whisper/ggml-large-v3.bin"
      }
    }
  }
}
```

### Config Options

| Key                                 | Type        | Default             | Description                                                          |
|-------------------------------------|-------------|---------------------|----------------------------------------------------------------------|
| database_file                       | string      | CONFIG_DIR/notes.db | Path to SQLite database file                                         |
| default_interface                   | string/null | null                | Default interface. If null, auto-detects: GUI if available, else TUI |
| window_geometry                     | object/null | null                | Saved window size/position (set automatically)                       |
| implementations                     | object      | {}                  | Reserved for future component selection                              |
| themes.colours.warnings             | string      | #FFFF00             | Warning highlight color (backward compatible)                        |
| themes.colours.warnings_dark        | string      | #FFFF00             | Warning color for dark theme (yellow)                                |
| themes.colours.warnings_light       | string      | #FF8C00             | Warning color for light theme (dark orange)                          |
| themes.colours.tui_border_focused   | string      | green               | TUI border color for focused pane                                    |
| themes.colours.tui_border_unfocused | string      | blue                | TUI border color for unfocused panes                                 |
| sync                                                                        | object/null | null          | Sync settings                                                                                    |
| sync.enabled                                                                | object/null | null          | Sync settings                                                                                    |
| sync.server_port                                                     | number |                 | Port that this instance listens on when running as a sync server  |
| sync.peers                                                                | object/null | null          | Servers that this instance is configured to connect to as a client  |
| sync.peers.peer_id                                                 | string |           | ID of server. Printed to stdout when server started, and when using cli option `cli sync status`  |
| sync.peers.peer_name                                                 | string |           | Human readable name of the server. |
| sync.peers.peer_url                                                 | string |           | URL of the server. |
| sync.peers.peer_certificate_fingerprint         | string/null | null      | Stored after Trust On First Use TLS certificate verification  |
| sync.max_sync_file_size_mb                      | number      | 100       | Files larger than this are tagged `_system/_nonsynced/_too-big` |
| sync.mirror_audio_files                         | boolean     | false     | Download every cloud audio file on each sync (local backup of the bucket). Local-only, never synced; desktop/server only |
| transcription.preferred_languages               | array       | []        | List of [ISO 639-1](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) language codes for transcription hints (e.g., ["en", "he"]) |
| transcription.providers.whisper.model_path      | string/null | null      | Path to GGML Whisper model file. If not set, auto-selects from ~/.local/share/whisper/ |

### Sync configuration

- Sync settings are stored in the config file.

### Color Values

Colors are specified as hex strings (e.g., `#FFFF00`). The warning color is used to highlight ambiguous tags in search results.

Theme-specific colors take precedence:
- Dark theme: Uses `warnings_dark`, falls back to `warnings`, then `#FFFF00`
- Light theme: Uses `warnings_light`, falls back to `warnings`, then `#FF8C00`

### Example Custom Config

```json
{
  "database_file": "/home/user/documents/notes.db",
  "themes": {
    "colours": {
      "warnings_dark": "#FFD700",
      "warnings_light": "#FF6600"
    }
  },
  "device_id": "019b552595fd7413a3eaffd04ea82f8b",
  "device_name": "Foo on desktop",
  "sync": {
    "enabled": false,
    "server_port": 8384,
    "peers": [
      {
        "peer_id": "018e5874b8357f489eb72834083c05b7",
        "peer_name": "Bar on server",
        "peer_url": "http://1.2.3.4:8384",
        "certificate_fingerprint": null
      }
    ]
  },
  "transcription": {
    "preferred_languages": ["en", "he"],
    "providers": {
      "whisper": {
        "model_path": "/home/user/.local/share/whisper/ggml-large-v3.bin"
      }
    }
  }
}
```

## Database Location

- Default: `~/.config/voice/notes.db`
- Custom: `<config-dir>/notes.db` when using `-d` flag

# VOICE — user manual

How the application is used: the four interfaces, what each screen and
command is for, and the settings behind them. For what VOICE is, see the
[README](README.md); for installing and building it,
[DEVELOPMENT.md](DEVELOPMENT.md).

## Contents

- [Usage](#usage)
  - [The configuration root and the account](#the-configuration-root-and-the-account)
  - [Accounts on this installation](#accounts-on-this-installation)
  - [GUI Mode](#gui-mode)
  - [TUI Mode](#tui-mode)
  - [CLI Mode](#cli-mode)
  - [Web API Mode](#web-api-mode)
- [What a transcription says about itself](#what-a-transcription-says-about-itself)
- [Long recordings](#long-recordings)
  - [Transcribing what the phone could not](#transcribing-what-the-phone-could-not)
- [The trash bin](#the-trash-bin)
- [Dates of imported recordings](#dates-of-imported-recordings)
- [The transcription queue](#the-transcription-queue)
- [Calculating missing data](#calculating-missing-data)
- [Syncing between installations](#syncing-between-installations)
  - [Pairing a new device](#pairing-a-new-device)
  - [Listening for peers](#listening-for-peers)
  - [Peers](#peers)
  - [The five operations](#the-five-operations)
  - [Conflicts](#conflicts)
  - [Where "later wins"](#where-later-wins)
  - [Synced settings](#synced-settings)
  - [The account, and snapshots](#the-account-and-snapshots)
  - [Backups](#backups)
  - [Merging two accounts](#merging-two-accounts)
  - [Where the copies are](#where-the-copies-are)
  - [Is everything somewhere else too?](#is-everything-somewhere-else-too)
  - [Issues](#issues)
  - [Devices, keys and certificates](#devices-keys-and-certificates)
  - [A server that hosts accounts](#a-server-that-hosts-accounts)
  - [Sync troubleshooting](#sync-troubleshooting)
  - [Firewall configuration](#firewall-configuration)
  - [Reverse proxy](#reverse-proxy)
- [Cloud storage for audio files](#cloud-storage-for-audio-files)
  - [The bucket, set up by the wizard](#the-bucket-set-up-by-the-wizard)
  - [The upload limit](#the-upload-limit)
  - [Encrypting recordings in the bucket](#encrypting-recordings-in-the-bucket)
- [Search syntax](#search-syntax)
- [Recording voice notes](#recording-voice-notes)
- [Configuration](#configuration)
- [Database location](#database-location)

## Usage

- There is no packaged executable yet. All interfaces are started through one entry point: `python -m src.main`

```bash
python -m src.main                     # No interface named: default_interface from config.json, else GUI if PySide6 is installed, else TUI
python -m src.main -a sillyberry gui   # Open another account of this installation
```

The `bin/voice` script runs the entry point through the repository's virtual environment from any directory. Put it on your `PATH` once and use `voice` instead of `.venv/bin/python -m src.main`:

```bash
ln -s ~/Projects/VoiceFamily/Voice/bin/voice ~/.local/bin/voice     # or: alias voice=~/Projects/VoiceFamily/Voice/bin/voice
export VOICE_CONFIG_DIR=~/voice-test                     # optional: a configuration root for testing
voice cli sync status
voice tui
```

The options `-a` and `--theme` go before the interface; `--format` goes after `cli` and before the command (`voice -a work cli --format json sync status`).

This device's local configuration (name, audio folder, sync port) is read and written with `voice cli config`:

```bash
voice cli config show
voice cli config get device_name
voice cli config set device_name "Desktop"
voice cli config set audiofile_directory ~/voice-audio   # created if missing
```

The keys `config` knows are `device_name`, `audiofile_directory`, `default_interface`, `sync.server_port`, `sync.enabled` and `sync.mirror_audio_files`. Other settings are changed by editing the JSON file ([Configuration](#configuration)).

### The configuration root and the account

The **root** is the directory named by the `VOICE_CONFIG_DIR` environment variable, or `~/.config/voice` when it is not set. A root has one of two shapes:

- **A one-account directory**: `config.json`, `notes.db` and `certs/` in the root itself, and no `accounts.db`. The root is the account.
- **An indexed root**: `config.json` (the machine's settings: device id and name, listen port, backup, public address), `accounts.db` (the index of accounts) and `certs/` in the root, and one directory per account, named by the account id, holding that account's `config.json`, `notes.db`, `audio/`, `snapshots/` and logs. An empty root becomes an indexed root at the first run.

The account is chosen at start and cannot be changed while the application runs:

1. `-a <id, unique prefix of the id, or label>` on the command line;
2. else the `VOICE_ACCOUNT_ID` environment variable;
3. else the default account of the index. When the index has no default account, one labelled `default` is created and made the default. `cli sync serve` and `cli account list|create|default|remove|host` never create an account.

On a one-account directory `-a` is refused: `Error: account: <root> holds one account and no index, so -a <x> cannot select one`. There is no `-d` option.

The first line every run prints says which directory is in use (on stderr when the output format is JSON or CSV, so that stdout stays parseable):

- `Using CONFIG_DIR: <root>/<account id> (account <label>)` for an account of an indexed root
- `Using CONFIG_DIR: <root>` for a one-account directory
- `Using CONFIG_DIR: <root> (no account of its own)` for a command that runs without an account

Log lines are written to `voice.log` in the account's directory (in the root for a command with no account), rotated at 5 MB with two old files kept. In the GUI, Help → Application Log shows the end of that file.

### Accounts on this installation

```bash
voice cli account list                    # every account of the root, the default first, marked (default) or (hosted)
voice cli account create --label work     # a new account; the first one that is not hosted becomes the default
voice cli account default work            # the account opened when no -a is given
voice cli account remove work             # forget it in the index; its directory is not touched
voice cli account show                    # this account's id, database id, directory and Note count
```

These commands need an indexed root; on a one-account directory `account list` says so and the others refuse. The GUI and the TUI have no control for accounts: choose one with `-a` at start.

### GUI Mode

```bash
python -m src.main gui                        # Force GUI mode
python -m src.main gui --theme light  # Force light theme
python -m src.main gui --theme dark   # Force dark theme
```

The window has three panes (Tags, the Notes list, the Note) and three menus:

- **File**: `New Note` (Ctrl+N), `Sync…` (Ctrl+Shift+S), `Set up the bucket…`, `Replace the bucket's key…`, `Listen for peers` (a switch), `Manage Tags...`, `Trash...`, `Issues...`, `Calculate missing data...`, `Transcription queue...`, `Quit` (Ctrl+Q)
- **Note**: `Delete Note` (the Delete key); the Note goes to the trash
- **Help**: `Message Log` (this session's messages from the main window), `Application Log` (the end of `voice.log`), `About` (the version, and this device's account, device id, addresses and certificate fingerprint)

A click on a Tag adds `tag:<name>` to the search field and searches; Shift+click adds the Tag to the selected Note. A click on the star at the start of a row in the Notes list stars or unstars that Note.

### TUI Mode

```bash
python -m src.main tui
```

#### TUI Keyboard Controls

| Key | Effect |
|-----|--------|
| `Up`/`Down` | Move in a list; `Up` at the top of the Notes list moves to the search field, `Down` moves back |
| `Left`/`Right` | Collapse/expand the Tag hierarchy |
| `Enter` | Select the item, or run the search |
| `Tab` | Move to the next pane or control |
| `n` | New Note |
| `s` | Save the Note |
| `r` | Read the list again with the current search |
| `a` | Clear the search and show all Notes |
| `t` | The Tags of the selected Note |
| `m` | Star or unstar the selected Note |
| `d` | Download the Note's missing Recordings from cloud storage |
| `w` | Where are the copies of the Recording |
| `x` | Remove this computer's copy of the Recording (press twice) |
| `Ctrl+T` | Trash |
| `Ctrl+F` | Calculate missing data |
| `Ctrl+K` | Transcription queue |
| `F8` | Issues |
| `Ctrl+P` | Command palette |
| `q` | Quit |

Editing a Note starts with the `Edit` button; there is no key for it. The text interface has no controls for sync, listening, pairing, the bucket, encryption, Transcribe, creating or moving Tags, or deleting a Note: use the GUI or the CLI for those.

### CLI Mode

Most commands that take an id accept a unique prefix of it, as Git commands accept a prefix of a commit id; the `--help` of each command says whether it accepts one (`voice cli <command> --help`).

Create, edit and merge Notes:
```bash
python -m src.main cli note-create "Hello, world!"
echo "Note from stdin" | python -m src.main cli note-create
python -m src.main cli note-edit <note-id> "New text"
python -m src.main cli notes-merge <note-id-1> <note-id-2>
```

Show a specific Note:
```bash
python -m src.main cli note-show <note-id>
```
List all Notes:
```bash
python -m src.main cli notes-list
```

Search Notes:
```bash
python -m src.main cli notes-search --text "meeting"                   # Search by text
python -m src.main cli notes-search --tag Work                         # Search by Tag
python -m src.main cli notes-search --tag Europe/France/Paris          # Search by hierarchical Tag path
python -m src.main cli notes-search --tag Work --tag Projects          # Multiple Tags (AND logic)
python -m src.main cli notes-search --text "meeting" --tag Work        # Combined text and Tags
```

#### Tags

```bash
python -m src.main cli tags-list                                   # List Tags (hierarchical)
python -m src.main cli tag-create "Foobar"                         # Create a top-level Tag
python -m src.main cli tag-create "Foobar" --parent <tag-id>       # Create a Tag under another
python -m src.main cli notes-tag --tags <tag-id> <tag-id> --notes <note-id> <note-id>    # Add Tags to Notes
```

`tag-rename` and `tag-move` are in [Conflicts](#conflicts). In the GUI, File → Manage Tags... creates, renames, moves (`Move To...`, or drag and drop) and deletes Tags.

#### Import files

Import a directory of audio files as new Notes (the CLI only):
```bash
python -m src.main cli audiofiles-import /path/to/files/
python -m src.main cli audiofiles-import /path/to/files/ --recursive      # Include subdirectories
python -m src.main cli audiofiles-import /path/to/files/ --tags <tag-id>  # Add a Tag to the imported Notes
python -m src.main cli audiofiles-import /path/to/files/ --tags <id1> <id2>  # Several Tags
```

#### Recordings on this device and in the cloud

A sync never moves a Recording's file. A file reaches the bucket by upload (`storage upload-pending`) and comes back from it by download; it reaches a peer by send, fetch, deliver or exchange ([The five operations](#the-five-operations)). To download on this device, and to see where the copies are:
```bash
python -m src.main cli audiofile-download <audiofile-id>         # One file
python -m src.main cli note-audiofiles-download <note-id>        # All files of a Note
python -m src.main cli audiofile-show <audiofile-id>             # Where the copies are: the bucket and each device
python -m src.main cli audiofile-remove-local <audiofile-id>     # Remove this device's copy (refused when it is the only one)
python -m src.main cli issues                                    # What needs attention (add --format json for a program)
python -m src.main cli note-audiofiles-list --note-id <note-id>  # The Recordings of a Note, with their copies
python -m src.main cli audiofiles-waveforms                      # Decode and keep the waveform levels of every Recording on this device that has none
```

`audiofile-transcribe` and `note-audiofiles-transcribe` download a file that is not on this device from the bucket first.

#### Transcription

Transcribe the Recordings of a Note, or one Recording, from the command line:

```bash
# Transcribe all Recordings of a Note
python -m src.main cli note-audiofiles-transcribe <note-id>

# Transcribe one Recording
python -m src.main cli audiofile-transcribe <audiofile-id>

# Specify model (name or full path)
python -m src.main cli note-audiofiles-transcribe <note-id> --model small
python -m src.main cli note-audiofiles-transcribe <note-id> --model large-v3
python -m src.main cli audiofile-transcribe <audiofile-id> --model /path/to/ggml-model.bin

# Specify language hint (see "Language hints" below)
python -m src.main cli note-audiofiles-transcribe <note-id> --language he
python -m src.main cli audiofile-transcribe <audiofile-id> --language en

# Specify expected number of speakers
python -m src.main cli note-audiofiles-transcribe <note-id> --speaker-count 2

# Another service
python -m src.main cli audiofile-transcribe <audiofile-id> --backend assemblyai --api-key <key>
```

The `--backend` values are `local_whisper` (the default), `assemblyai`, `google_cloud` and `speechtext_ai`.

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

The preferred languages are a synced setting (see [Synced settings](#synced-settings)):
```bash
python -m src.main cli settings set transcription.preferred_languages '["he", "en", "ar"]'
```

At every start the synced value is written over `transcription.preferred_languages` in `config.json`.

When the CLI transcribes, the language is chosen in this order:
1. The `--language` argument
2. The first language in `transcription.preferred_languages`
3. Detection by the service (no hint)

The GUI's Transcribe dialog has its own `Language:` choice, `Auto-detect` unless another is chosen.

**Model selection (CLI, `local_whisper`):**
- The `--model` flag accepts either a model name (e.g., `small`, `large-v3`) or a full path to a GGML model file
- A model name is looked for as `~/.local/share/whisper/ggml-<name>.bin`, then `~/.local/share/whisper/<name>.bin`
- Without `--model`, `transcription.providers.whisper.model_path` from `config.json` is used
- Without either, the largest `ggml-*.bin` in `~/.local/share/whisper` is selected; of several versions of one size (e.g., `large-v2`, `large-v3`), the highest version

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

**Where each interface reads a service's settings:**

The CLI reads `transcription.providers.<name>` in `config.json`:

| `--backend` | Read from |
|-------------|-----------|
| `local_whisper` | `--model`, else `providers.whisper.model_path` |
| `assemblyai` | `--api-key`, else `$ASSEMBLYAI_API_KEY`, else `providers.assemblyai.api_key` |
| `google_cloud` | an access token from `--api-key` or `gcloud auth print-access-token`; the project from `--project-id`, else `$GOOGLE_CLOUD_PROJECT`, else `providers.google.project_id` (or `providers.google_cloud.project_id`) |
| `speechtext_ai` | `--api-key`, else `$SPEECHTEXT_AI_API_KEY`, else `providers.speechtext_ai.api_key` |

The GUI's Transcribe dialog and the transcription queue use the services `local_whisper`, `speechtext_ai` and `google`, and read `transcription.<service>` in `config.json`: for example `transcription.local_whisper.model_path`, `transcription.speechtext_ai.api_key`, and `transcription.google.credentials_path`, `project_id`, `speech_model`, `speech_location`. Without a `model_path`, `local_whisper` looks for `ggml-<model>.bin` (model `base` unless the dialog names another) in `~/.local/share/whisper`, `~/.cache/whisper`, `/usr/share/whisper` and `/usr/local/share/whisper`.

Example configuration for the CLI:
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

- Rewrites timestamps stored in ISO 8601 form (2025-12-29T23:22:13.462391) in SQLite form (2025-12-29 23:22:13)
- Changes only the rows that are still in ISO 8601 form, so running it again changes nothing

```bash
python -m src.main cli db-maintenance database-normalize
```

**Rebuild the display caches:**

The display cache stores data calculated in advance for the Note pane and the Notes list (Tags, conflicts, attachments with Transcriptions). It is rebuilt when Notes, Tags or attachments change.

To rebuild it by hand:

```bash
# Rebuild the caches of one Note
python -m src.main cli db-maintenance note-rebuild-caches <note_id>

# Rebuild the caches of every Note
python -m src.main cli db-maintenance note-rebuild-caches

# Rebuild every cache field in the database (--verbose lists the caches first)
python -m src.main cli db-maintenance rebuild-all-caches

# Read the length of Recordings that have none from their files (--dry-run: only list them)
python -m src.main cli db-maintenance audio-rebuild-durations --dry-run
```

#### Output formatting

```bash
python -m src.main cli --format json sync status   # JSON output
python -m src.main cli --format csv sync list-peers  # CSV output
```

### Web API Mode

- The server runs on `http://127.0.0.1:5000` by default (Flask's development server).
- All endpoints return JSON.
- CORS is enabled for all routes.
- IDs are UUID7 hex strings (32 characters, no hyphens). The Web API accepts only full ids, never a prefix.

```bash
python -m src.main web
python -m src.main web --host 0.0.0.0 --port 8080 # Custom host or port
python -m src.main web --debug                    # Debug mode
```

#### Web API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/notes` | List all Notes |
| POST | `/api/notes` | Create a Note: `{"content": "..."}` |
| GET | `/api/notes/<id>` | Get one Note, with `has_conflicts` and `conflict_types` |
| PUT | `/api/notes/<id>` | Change a Note's content: `{"content": "..."}` |
| DELETE | `/api/notes/<id>` | Delete a Note (it goes to the trash) |
| GET | `/api/notes/<id>/attachments` | List the attachments of a Note |
| GET | `/api/audiofiles/<id>` | Get a Recording's details |
| GET | `/api/audiofiles/<id>/locations` | Where the Recording's copies are: the bucket and each device, as last stated |
| POST | `/api/audiofiles/<id>/remove-local` | Remove this device's copy to save space; 409 when no other place holds it, or when it is not on this device |
| GET | `/api/issues` | What needs your attention: Recordings not in cloud storage and why, orphaned Transcriptions, attachments and Recordings, Tags whose names contain spaces |
| GET | `/api/storage/upload-limit` | The account's upload limit in MB |
| PUT | `/api/storage/upload-limit` | Set the account's upload limit: `{"megabytes": 250}` |
| GET | `/api/tags` | List all Tags |
| GET | `/api/search` | Search Notes: `text`, and `tag` (may repeat) |
| GET | `/api/trash` | The Notes in the trash |
| POST | `/api/trash/<id>/recover` | Take a Note out of the trash |
| DELETE | `/api/trash/<id>` | Remove a Note in the trash for good |
| GET | `/api/maintenance/missing-data` | What is missing ([Calculating missing data](#calculating-missing-data)) |
| POST | `/api/maintenance/missing-data` | Calculate it |
| GET | `/api/transcription-queue` | The transcription queue (`service` narrows the finished work to one service) |
| POST | `/api/transcription-queue` | Put a Recording in the queue |
| POST | `/api/transcription-queue/next` | Transcribe this Recording next |
| POST | `/api/transcription-queue/remove` | Take a Recording out of the queue |
| POST | `/api/transcription-queue/clear` | Forget everything waiting |

#### Example API Usage

**List and retrieve Notes:**
```bash
curl http://127.0.0.1:5000/api/health                # Health check
curl http://127.0.0.1:5000/api/notes                 # List all Notes
curl http://127.0.0.1:5000/api/notes/<note-id>       # Get one Note
curl http://127.0.0.1:5000/api/tags                  # List all Tags
```

**Create and change Notes:**
```bash
# Create a Note
curl -X POST http://127.0.0.1:5000/api/notes \
  -H "Content-Type: application/json" \
  -d '{"content": "My new note"}'

# Change the content of a Note
curl -X PUT http://127.0.0.1:5000/api/notes/<note-id> \
  -H "Content-Type: application/json" \
  -d '{"content": "Updated content"}'

# Delete a Note (it goes to the trash)
curl -X DELETE http://127.0.0.1:5000/api/notes/<note-id>
```

**Search Notes:**
```bash
curl "http://127.0.0.1:5000/api/search?text=meeting"                # Search by text
curl "http://127.0.0.1:5000/api/search?tag=Work"                    # Search by Tag
curl "http://127.0.0.1:5000/api/search?tag=Europe/France/Paris"     # Hierarchical Tag
curl "http://127.0.0.1:5000/api/search?tag=Work&tag=Projects"       # Multiple Tags (AND logic)
curl "http://127.0.0.1:5000/api/search?text=meeting&tag=Work"       # Combined text and Tags
```

**Get attachments and Recordings:**
```bash
curl http://127.0.0.1:5000/api/notes/<note-id>/attachments  # List a Note's attachments
curl http://127.0.0.1:5000/api/audiofiles/<audio-id>        # Get a Recording's details
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
- `400` - Bad request (validation error, or an id that is not 32 hex characters)
- `404` - Not found
- `409` - Refused: `remove-local` when no other place holds the file, or the file is not on this device
- `500` - Internal server error

## What a transcription says about itself

A Transcription is more than its text: it carries when it was made, by which
service and with which model, and what has been done to it since. Unfold a
Transcription in the GUI and its **Flags** are the five checkboxes under the
text. Click one to turn it on or off, then `Save`.

| Flag | Means |
|------|-------|
| Original | Unmodified transcription from the service |
| Verified | User has verified the transcription is accurate |
| Verbatim | Transcription includes filler words, false starts, etc. |
| Cleaned | Transcription has been cleaned up (remove filler words) |
| Polished | Transcription has been edited for readability |

They are flags rather than one state because any number of them can be true
at once: a Transcription can be verified *and* cleaned, and a verbatim one
that is later tidied stops being verbatim and becomes cleaned. Nothing sets
them for you except *Original*, which is true of every Transcription until
somebody edits it — they are a record of what a person has changed, kept for
the person who reads it next.

The flags are stored in the Transcription's `state` field, a space-separated
list of those five words with `!` in front of the ones that are off, so
`original !verified !verbatim !cleaned !polished` is a fresh Transcription.
That field name is the one the database and the sync protocol have always
used; only what you read calls them flags. The text interface shows the field
as it is stored (`State: ...`), and its `Edit` button lets you type the words.
The field syncs with everything else, and the Android application shows the
same five in the same words, so a Transcription verified on a phone reads as
verified here.

## Long recordings

A Note holds a Recording of any length. An eight-hour Recording of somebody
sleeping is kept, played, tagged, searched and synced exactly like a
two-minute voice note; nothing about it is a special case.

One thing is **offered, not started without asking**, for a long Recording in the GUI,
because it means reading the whole of it: the **waveform**. Drawing one decodes
the entire Recording — on an ordinary desktop that is a few seconds for an hour
of audio and most of a minute for eight hours, and on a phone many times
slower. For a Recording past the limits below, with no waveform levels kept by
any device, the GUI's waveform area reads

> Click to generate waveform
> Resource intensive operation on large file

and the waveform is drawn when you click it. The levels are then kept with the
Recording and synced, so the waiting happens once.

The text interface makes no such offer: when a Note opens, it decodes the
waveform of every Recording of the Note whose levels are not kept yet.
`cli audiofiles-waveforms` decodes and keeps the levels of every Recording on
this device that has none.

### Transcribing what the phone could not

**Transcription has no length limit here, and this is where the long ones are
transcribed.** The Android application transcribes up to ten minutes and refers
anything longer to the desktop, because Whisper holds the whole Recording in
memory as it works — about 230 MB an hour on top of the model — which a phone
does not have. A Recording of many hours will still exhaust a small machine;
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

Options: `--min-minutes N` to include Recordings over some other length (the
default is ten minutes, the phone's own limit), `--limit N` to transcribe only
so many in one run, and `--language`, `--model` and `--backend` as for any other
transcription.

A Recording whose length was never recorded is left alone: its length is
exactly what this decision needs, and a wrong guess means spending an hour on
something the phone would have transcribed in a minute.


### What counts as a large recording

| Measure | Limit |
|---------|-------|
| Length | 60 minutes |
| Size | 100 MiB |

Either one is enough. The length is the measure that matters, because the work
follows the length of the audio; the size catches a Recording whose length is
not known yet, or whose header is wrong. For reference, 100 MiB is about 52
minutes of 16 kHz WAV, 1.8 hours of Opus at 128 kb/s, or 2.4 hours of AAC at
96 kb/s.

Both numbers are in `src/core/waveform.py` as `LONG_RECORDING_SECONDS` and
`LARGE_RECORDING_BYTES`, and the Android application uses the same two.

## The trash bin

Deleting a Note is reversible: the Note keeps its history and its Recordings,
and every device is told that it was deleted rather than being told to forget
it. The trash bin is where those Notes are seen, recovered, or removed for
good.

- **GUI**: File → Trash... `Recover` puts a Note back in the list; `Delete for
  good` asks once and then removes it.
- **TUI**: `Ctrl+T`. The same two buttons; `Delete for good` asks by making
  you press it twice, so one keystroke can never destroy a Note.
- **CLI**: `trash-list`, `note-recover <id>`, `note-purge <id>`. The purge
  asks you to type the word `delete` unless `--yes` is given.
- **Web API**: `GET /api/trash`, `POST /api/trash/<id>/recover`,
  `DELETE /api/trash/<id>`.
- **Android**: Settings → Trash.

Removing a Note for good removes, from the database of this device and of every
device it syncs with, the Note, its history, its Tag links, its attachments and
the Recordings that belonged to that Note alone. It cannot be undone, and a
device that has not synced yet cannot bring the Note back: the removal is
written down and travels, and anything that arrives about a removed Note is
dropped. A Recording that another Note still holds is never removed. A copy
already uploaded to cloud storage is not deleted from the bucket. No snapshot
is taken before a removal.

## Dates of imported recordings

The date of an imported Recording is taken from the filesystem, which is right
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
in turn. So a Recording sent to be transcribed goes into a queue and is
transcribed one at a time.

There is **one queue for each account directory**, shared by the interfaces. It is
a small file, `transcription_queue.json`, in the account's directory, so the
GUI, the TUI, the CLI and the Web API opened on the same account all show the same
queue and can all reorder it. The file is local to this computer and is never
synced: what this machine is busy with is not a fact about your Notes.

The queue is shown in three groups, read downwards as time runs forwards:

| Group | What it is |
|---|---|
| Waiting | Recordings that have not started. Newest first, with the place each one will really be reached in, and how long until it is done |
| Being worked on (`processing` in JSON) | The Recording being transcribed now |
| Done (`completed` in JSON) | What is finished, newest first, with what the work cost |

A finished Recording carries the numbers the screen exists for: how much text
came out, how long the Recording was, and the **clock time**, **processor time**
and **peak memory** the work took. Those are what tell you whether a larger model
is worth its wait, and they are what every waiting estimate is calculated from —
the estimate is the median of what this machine has actually measured, not a
specification. Until something has finished here, no estimate is offered,
because a made-up number is worse than none.

**Moving one Recording to the front.** When you need one Transcription before the
rest, "transcribe this one next" puts it at the head of the queue. The Recording
being worked on is never interrupted: it is minutes into work that would have to
start again, which would cost more than the wait. "Next" means next after that
one.

**GUI:** File → Transcription queue... A table, one row per Recording, with the
Note it belongs to. Select a waiting row and press `Transcribe this one next` or
`Take out of the queue`; `Reload` reads the queue again.

**TUI:** Ctrl+K. `n` moves the selected Recording to the front, `r` takes it out,
F5 reads the queue again. The text interface does not transcribe.

**CLI:**

```bash
# What is waiting, what is being worked on, and what the finished ones cost
.venv/bin/python -m src.main cli transcription-queue

# The same as JSON, the shape the Web API returns
.venv/bin/python -m src.main cli transcription-queue --format json

# Transcribe this one next, or take it out (ids may be given as prefixes)
.venv/bin/python -m src.main cli transcription-queue --next 01a0938f
.venv/bin/python -m src.main cli transcription-queue --remove 01a0938f

# Forget everything waiting; what is being worked on is not stopped
.venv/bin/python -m src.main cli transcription-queue --clear

# Transcribe what is waiting, here and now, one Recording at a time
.venv/bin/python -m src.main cli transcription-queue --run --limit 3
```

**Web API:**

```bash
# The queue
curl http://localhost:5000/api/transcription-queue

# Put a Recording in it
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

The Web API does not transcribe: it queues. The GUI transcribes, one at a time,
the Recordings sent from its Transcribe dialog, and works through the queue
after its queue window has changed it; `transcription-queue --run` transcribes
from a terminal.

The phone has the same queue for its own work; see VoiceAndroid's user manual.

## Calculating missing data

Some facts about a Recording are not known when it arrives, and some were
never calculated: a file imported before lengths were recorded has no length, a
Recording copied without its filesystem dates has no creation date, and a Note
written before the display caches existed has no cache. None of that is lost
data — it can be read back from the file, or calculated again — but until it is,
the application shows less than it knows, and the decisions that depend on a
length (whether a waveform is drawn without asking, whether the phone will
transcribe a Recording) have nothing to go on.

The repair is one operation with one report. In the GUI, the CLI and the Web API
it runs in two steps: it says what is missing, and it calculates only when
asked, because reading the length of every Recording is work and you should see
what it is for before it starts.

What it calculates:

| What | Where it comes from |
|---|---|
| Recordings with no length recorded | read from the file's header (`ffprobe`); the audio is not decoded, so an eight-hour Recording costs the same as a one-minute one |
| Recordings with no creation date | the filesystem date, or the date in the name the file arrived under, by the rule in [Dates of imported recordings](#dates-of-imported-recordings) |
| Notes with no display cache | calculated again from the Note, its Tags and its attachments |

The lengths and dates are calculated only for Recordings whose file it finds in
the audio folder.

What it never calculates, and says so instead:

| What | Why not |
|---|---|
| Recordings whose file is not on this computer | there is nothing here to read. Download them first, or run the repair on the device that has them |
| Recordings with no timezone recorded | a timezone cannot be derived from a file, and writing this computer's offset would state something false about where the Recording was made |

Running it twice is harmless: the second run finds nothing to calculate. Nothing
it writes is an edit by you, so none of it touches a Note's history; the values
reach the other devices as ordinary metadata on the next sync.

**GUI:** File → Calculate missing data... It shows what is missing, asks, then
reports what it calculated.

**TUI:** Ctrl+F. It calculates at once, without the report and the question.

**CLI:**

```bash
# Say what is missing, change nothing
.venv/bin/python -m src.main cli calculate-missing-data --dry-run

# Calculate it
.venv/bin/python -m src.main cli calculate-missing-data

# Only the lengths, and only the first fifty Recordings
.venv/bin/python -m src.main cli calculate-missing-data --no-dates --no-caches --limit 50
```

| Option | Effect |
|---|---|
| `--dry-run` | Report what is missing and stop |
| `--limit N` | Read at most N Recordings in one run |
| `--no-durations` | Leave Recording lengths alone |
| `--no-dates` | Leave creation dates alone |
| `--no-caches` | Leave display caches alone |

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

The words below have one meaning each, in this manual and on screen:

| Word | Meaning |
|------|---------|
| **Sync** | Exchange database changes (Notes, Tags, Transcriptions, the list of Recordings, settings) with a peer, both directions. A sync never moves a file |
| **Upload** / **Download** | Copy Recording files from this device to the bucket / from the bucket to this device |
| **Send** / **Fetch** | Copy Recording files from this device to a peer / from a peer to this device |
| **Deliver** | Sync, then send |
| **Exchange** | Sync, then send and fetch |
| **Listen** | Accept connections from peers |
| **Host** | Serve an account that is not this device's own |
| **Pair** | Give a new device the account's id, a key of its own and one peer |

- The other devices of the account are the **peers**. A device is let in only
  by **pairing**: it reads a code another device of the account shows
  (`account show-code` and `account join`), or a server is given the account
  with a grant text (`account host` and `account grant-host`). After that,
  every device of the account appears in the peer list by itself, with its
  name and where it listens, as the device cards travel with sync.
- Every device can listen and every device can call. One device listens (the
  desktop's File → Listen for peers, the phone's switch, or `sync serve`), and
  the other starts the operation. The result is the same whichever side
  listened.
- **One button**: the desktop's File → Sync… dialogue and the phone's sync
  screen show "Exchange with Desk", where Desk is the peer of the last
  operation. The arrow beside it chooses another peer or another of the five
  operations.
- **Finding each other**: a listening device announces itself on the local
  network with a hash of the account id, never the id. An operation tries
  the address it remembers first; if nothing answers there, it asks the
  network where the peer is for three seconds and remembers the answer.
  `sync discover` and the dialogue's "Find on this network" list the devices of
  the account nearby. A listener without a configured `public_url` serves its
  own network only; a phone on hotel wifi is not a server for the hotel.
- **While an operation runs** the dialogue (and the phone's notification)
  says what it is doing and how far it is, and has a `Cancel` button: a
  transfer stopped continues from where it stopped next time.
- Instances can be run as a systemd service; see [DEVELOPMENT.md](DEVELOPMENT.md).

### Pairing a new device

The device that holds the account shows a **code**; the new device reads it.
Nothing lasting is in the code: a token that is valid for ten minutes and for
one device, the account id, the showing device's id, where it listens, and,
when the listener's certificate is found, the certificate's fingerprint
(`voice://pair?v=1&a=…&t=…&d=…&u=…&f=…`).

```bash
python -m src.main cli sync serve                  # the showing device must be listening
python -m src.main cli account show-code           # a QR code and the setup text (add --url if the address is wrong; --text-only for no QR code)
python -m src.main cli account hide-code           # withdraw the code before it expires
python -m src.main cli account join "voice://pair?..."   # on the new device: paste the setup text
```

In the GUI, File → Sync… → `Show my code` shows the QR code and the setup text in
a window titled `My code`. If the listener is off, it is switched on for the
code and off again when the window closes. **Closing the window withdraws the
code**, so the other device must read it while the window is open. The desktop
reads another device's code only with `account join`; the GUI and the TUI have
no control for it.

A code is used once. A new `show-code` replaces the previous one, and five wrong
tokens withdraw it.

The new device takes the account, receives a key of its own, and adds the
showing device as a peer with the certificate fingerprint from the code pinned.
It also receives the recording key, if the account has one, and `sync.enabled`
is set to true. On the phone that key is kept wrapped by the Android Keystore,
so a copy of the app's files does not carry it; on the desktop it is in the
account's `config.json`. A device that already holds Notes of another account
refuses the code (`DEVICE_HOLDS_NOTES`) and says to show its own code to the
other device instead, or to use `account move`.

After joining, `sync exchange <peer>` (or `sync now`) brings the account's Notes
here.

On the phone, Settings → Sync Settings has **Show my code** (the code stays on
screen for a minute, with Copy and Share beside it) and **Read a code**, which
opens the camera with a paste field under it for a phone whose camera cannot
read it. A setup text sent through any messaging app is a link: tapping it opens
Voice at the sync screen and pairs. A phone with no Notes yet offers "Pair
with another device" and "Start on my own" on its first screen, and after
pairing offers "Exchange now".

### Listening for peers

A device is reachable only while it **listens**:

- **GUI**: File → Listen for peers, or the `Listen for peers` box in File →
  Sync…. The GUI's listener serves the open account only. Beside the box, the
  listener can be set to stop itself: `keep listening` (the default),
  `stop after 1 hour of silence`, `stop after 4 hours of silence`,
  `stop after 8 hours of silence`. `sync serve` has no such setting.
- **CLI**: `sync serve`. On a one-account directory it serves that account; on
  an indexed root it serves every account of the index.

```bash
python -m src.main cli sync serve                         # https on 0.0.0.0, port sync.server_port (8384)
python -m src.main cli sync serve --port 9000 --verbose   # log every request to stdout
python -m src.main cli sync serve --no-announce           # do not announce on the local network
python -m src.main cli sync serve --host 127.0.0.1 --plain-http   # plain http, for a reverse proxy on this machine
```

`--no-color` removes the colour codes from the `--verbose` log. Ctrl-C stops the
listener.

The listener serves **HTTPS** with its own self-signed certificate, made the
first time it listens and kept in `certs/` in the root. Its fingerprint
(`SHA256:` followed by 32 hex bytes) is shown in Help → About, at the bottom of
File → Sync…, in `device list`, and in the log line `Certificate fingerprint`
of `sync serve --verbose`; `sync serve` does not print it otherwise.

There is **no trust on first use**. A peer with a pinned fingerprint is accepted
only if its certificate matches the pin; a peer without one is checked against
the system's root certificates, which a self-signed listener does not pass. A
pin comes from pairing or granting, from `sync add-peer --fingerprint`, or
from an address found on the local network. Plain `http://` is accepted only
to this machine itself (`localhost`, `127.*`, `::1`); `sync serve --plain-http`
is allowed only on a loopback address.

Rules the listener applies:

- A caller that is not on a private, loopback or link-local address is refused
  (`NOT_ON_LAN`) unless `public_url` is set in the root's `config.json`.
- After three refused requests from one address, each further answer to it
  waits 2, then 4, then 8 seconds; the count is forgotten after ten minutes.
- The JSON sync requests are limited to `sync.max_sync_file_size_mb` (100 MB
  by default). Recordings sent to the listener are streamed and are not held
  to that limit.
- A snapshot of the account's database is taken before each handshake it
  accepts.

### Peers

```bash
python -m src.main cli sync status                         # this device, the peers, and what is on this device only
python -m src.main cli sync list-peers                     # every peer, with its address, fingerprint and last operation
python -m src.main cli sync discover                       # the devices of this account announcing on this network
python -m src.main cli sync check <peer-id>                # reachable, certificate, protocol, account, key, clock, free space
python -m src.main cli sync check --all                    # every peer and the bucket, as one table
python -m src.main cli sync rename-peer <peer-id> "Desk"   # a name shown on this device only
python -m src.main cli sync remove-peer <full-peer-id>     # forget a peer on this device (the full id)
python -m src.main cli sync add-peer <peer-id> "Desk" https://<address>:8384 --fingerprint SHA256:...
```

`sync add-peer` alone **does not let a device in**. It only writes the peer into
this device's list; the listener still refuses a device that was not paired
into its account (`This device is not paired with this account; pair again
(DEVICE_UNKNOWN)`, or `ACCOUNT_UNKNOWN` for another account). Pair instead. A
forgotten peer's card does not bring it back until it is added again or paired
again.

In File → Sync…, the peers table shows each peer's address, when it was last
reached and its last operation. The buttons below it: `Rename…`, `Forget`,
`Add by address…`, `Find on this network`, `Check connection` and `Test
everything` (every peer and the bucket). `Rename…` and `Forget` act on the
selected row.

### The five operations

A sync moves Notes, Tags, Transcriptions and the list of Recordings, never a
Recording's file. Files move between two devices with these, each with one peer:

```bash
python -m src.main cli sync exchange <peer>   # sync, then send the Recordings the peer lacks and fetch the ones this device lacks
python -m src.main cli sync deliver <peer>    # sync, then send the Recordings the peer lacks
python -m src.main cli sync send <peer>       # send only, no sync
python -m src.main cli sync fetch <peer>      # fetch only, no sync
python -m src.main cli sync now --peer <peer> # sync only: no file moves
python -m src.main cli sync now               # sync only, with every peer in turn
```

`<peer>` is the peer's device id or a unique prefix of it.

In File → Sync…, the button reads `Exchange with <peer>`. Its arrow opens one
submenu per peer, each with:

- `Exchange — sync, then send and fetch recordings`
- `Deliver — sync, then send recordings`
- `Sync — notes only`
- `Send — recordings the peer lacks, no sync`
- `Fetch — recordings this device lacks, no sync`

A result reads, for example, `Exchange with Desk: received 3 changes and sent 1,
fetched 2 recordings, 41.0 MB moved. Request 0a1b….` The request id is in both
devices' logs. When the peer refuses, the dialogue offers the button that
addresses the refusal (`Show my code` or `Check connection`). After every
operation the Notes list and the open Note are read again.

A Recording travels streamed, so an eight-hour file needs no memory to speak
of, and a transfer that stops continues from where it stopped the next time.
The receiver checks the file's hash before it accepts it, and refuses a file
that would not fit on its disk.

### Conflicts

Every editable value (Note content, Tag name and parent, Transcription text and state, Tag links, attachments, deletions, synced settings) is versioned like a Git history. When two devices change the same value before syncing, the sync merges the two versions three-way:

- Text is merged line by line. Edits to different lines combine silently. Edits to the same lines are both kept in the text between `<<<<<<< VERSION A` / `=======` / `>>>>>>> VERSION B` markers.
- A deletion never wins over a concurrent edit: the item stays alive with the edit.
- A Tag link removed on one device but kept on the other stays attached.
- A Tag renamed or moved on both devices keeps the later value.

In every case that needed a decision, a conflict record is created on every device (same id everywhere) naming the two devices. The GUI, TUI and Android show a banner on the Note with an **Accept merge** button. Resolving happens in one of two ways, and either way the resolution reaches every peer:

- **Edit and save** the Note (clean up the markers). A save while a conflict is open resolves it.
- **Accept the merge** as it stands.

The **Resolve…** button opens the two versions and their common ancestor side by side next to an editable result. In the GUI it is on every conflict banner and answers that a conflict that is not a text conflict is resolved with Accept merge or an edit; the TUI shows it only for a text conflict. **History** (`History…` in the GUI, `History` in the TUI, and on Android) lists every earlier version of the Note and restores any of them; a restore is a normal edit, so nothing is lost.

```bash
# Delete a Note (it goes to the trash), rename or move a Tag; all of these sync and merge like any edit
python -m src.main cli note-delete <note-id>
python -m src.main cli tag-rename <tag-id> "שם חדש"
python -m src.main cli tag-move <tag-id> <parent-tag-id>
python -m src.main cli tag-move <tag-id> --root

# Every version of a Note, oldest first; show one; restore one
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
| A Tag renamed or moved on two devices; a synced setting changed on two devices | the version's `created_at`; the later one is shown | yes, a scalar conflict listing both values and both devices |
| The same transcription flag (verified, cleaned, ...) switched both ways on two devices | the version's `created_at` | yes, a flags conflict |
| Unversioned metadata: a Recording's filename, duration and creation time; a Transcription's service name, arguments, response and segments; which Note an attachment belongs to | the row's `modified_at`; the newer row wins each column, and an older row supplies only the columns the newer row lacks | no (machine-written fields) |
| The cloud location of a Recording after a re-upload | `modified_at`; a row without a location never erases one | no |
| The cloud storage configuration | `modified_at` | no |

A device whose clock is badly wrong therefore wins those decisions; it never loses or gains data. Merges, deletions, links and convergence between devices do not depend on clocks at all (see `SYNC_SPECIFICATION.md`, LIM-13).

### Synced settings

A few settings are about the user rather than the machine and follow the user to every device through the database: `transcription.preferred_languages` and the API key of each cloud transcription provider (`transcription.providers.<provider>.api_key`). Paths, ports and models stay local. On startup the synced value overrides `config.json`; a value present only in `config.json` is written to the database and so reaches the other devices. To change one:

```bash
python -m src.main cli settings list
python -m src.main cli settings get transcription.preferred_languages
python -m src.main cli settings set transcription.preferred_languages '["he", "en"]'
python -m src.main cli settings set transcription.providers.assemblyai.api_key <key>
```

### The account, and snapshots

Every database belongs to one **account**, a 32-character id minted with it. Two
devices exchange changes only when they hold the same account; a device of
another account is refused with a sentence naming both (`ACCOUNT_MISMATCH`), and
nothing crosses. That is what keeps two people's Notes apart when both reach the
same server or the same address.

```bash
python -m src.main cli account show          # the account id, the database id, the directory, the Note count
python -m src.main cli account snapshots     # the copies kept beside the database, newest first
python -m src.main cli account snapshot      # take a copy now
python -m src.main cli account restore <name>   # replace the database with a copy (asks first; --yes does not ask)
```

A **snapshot** is a copy of the whole Notes database. One is taken before every
sync, before each handshake a listener accepts, and before `account move`,
`account restore` and a join that changes the account id. The newest five are
kept in `snapshots/` beside the database. Restoring one brings the Notes back as
they were; the state being replaced is kept as the newest snapshot, so a restore
can itself be undone. Recordings are files and are never part of a snapshot. The
GUI and the TUI have no view of the snapshots.

Moving a database to another account is the one way two accounts are merged,
and it is deliberate: `account move --to <id> --current <id>` proceeds only when
the full id of the account being given up is typed by hand. A snapshot is taken
first, and the record of what was exchanged with each peer is deleted, so the
next sync exchanges everything; the peers stay in the list.

### Backups

A **backup** is a copy of an account's database in
`<root>/backups/<account id>/` (or in `backup.directory/<account id>/` when that
is set), separate from the snapshots. The newest `backup.keep` (30) are kept.
`backup.interval_hours` in the root's `config.json` sets the interval (24 hours;
0 turns the periodic backup off).

- **`account backup`** copies every account of the root now.
- **`sync serve`** copies, every interval, the accounts that a request has opened
  since it started; the first copy is made one interval after the start.
- **The GUI** checks every 15 minutes while it is open, and copies the open
  account when its interval has passed.
- The TUI makes no backup.

### Merging two accounts

For a phone and a desktop that ended up with different accounts:
`account move --to "<the other account's code>" --current <this account's full id, typed by hand>`
(on the phone, Settings → Advanced → Move this device to another account).
A snapshot is taken, the device joins the other account keeping its Notes,
Tags with one path become one, and everything is exchanged. Nothing is
deleted.

### Where the copies are

A Recording made by the application is named after its start and the last eight
characters of its id: `2026_09_21_14_30_59-abcdefgh.ogg`. An imported file keeps
its own name. On the phone the files are in the shared `Recordings/Voice` folder
(reachable from any file manager and over a cable, and left alone when the
application is replaced); on the desktop in the account's `audio` folder (or
`audiofile_directory`). The folder holds Recordings and nothing else.

Every device knows where each Recording's copies are: the bucket, and each
device that holds the file, as that device last said.

- **Where are the copies?** In the GUI, right-click a Recording in a Note's
  `Recordings` list → `Where are the copies?`. In the TUI, `w`. On the command
  line, `audiofile-show <id>`; in the Web API,
  `GET /api/audiofiles/<id>/locations`; on the phone, the ⋮ menu of a Recording.
- **Remove from this device** deletes this device's file to save space; the
  Recording, its Transcriptions and every other copy stay, and it can be
  fetched or downloaded again. In the GUI, right-click → `Remove from this
  device` (asks first). In the TUI, `x` twice (`Remove from this computer`). On
  the command line, `audiofile-remove-local <id>`; in the Web API,
  `POST /api/audiofiles/<id>/remove-local`; on the phone, "Remove from this
  phone". It is refused while this device holds the only known copy: `<file> is
  on this device only; it can be removed from here once the bucket or another
  device holds it`.

In the TUI, `w` and `x` act on the Recording that is playing, else on the first
Recording of the Note.

This device compares its folder with what it last said before every sync,
before `Where are the copies?` in the GUI, and when Issues are read, so a file
deleted from the folder by hand becomes known to every device.

### Is everything somewhere else too?

`sync status` says, in one line, what exists on this device only: "3 notes and
2 recordings are not duplicated off this device.", or "Everything is duplicated
off this device." A Note counts as duplicated once a sync has sent it to any
peer; a Recording once it is in the bucket or a peer is known to hold it. Below
the line, every peer with when it was last reached and what the last operation
was. File → Sync… shows the same line, and a checklist: `Paired devices`,
`Bucket`, `Listener`, `Not duplicated`, `Last exchange`; a row that is not yet
in place has a button beside it (`Show my code`, `Set up the bucket`, `Listen
for peers`, `Exchange`). The phone shows the same line at the top of its
sync screen, and nowhere else: no notification, no badge. A Recording's details
(`note-audiofiles-list`, `audiofile-show`) name where its copies are: this
device, the bucket, and each peer.

### Issues

File → Issues... (F8 in the text interface, `cli issues`, `GET /api/issues`,
Settings → Issues on the phone) lists what needs attention, read afresh each
time and never pushed:

- Recordings that are not in the bucket, and why: no bucket is set up for the
  account, the file is larger than the account's upload limit, it is waiting
  for the named devices that hold it to upload it, or no device and no bucket is
  known to hold it;
- Transcriptions whose Recording is not there, and attachments whose Note or
  Recording is not there;
- Recordings that no Note holds (a Note in the trash still holds its own);
- Tags whose names contain spaces.

The list offers no actions: a line goes away when what it names has changed.
The GUI window has `Refresh`; the TUI screen reads the list again with F5.

### Devices, keys and certificates

Every device of an account has a **key** of its own, made when it created the
account or given to it when it was paired. Every request to a peer carries it,
and every peer holds only a hash of it, on the device's **card**, which travels
with the Notes. A device nobody has let in, or one that was revoked, is
refused with a sentence and a code.

```bash
python -m src.main cli device list                # every device of the account, with its certificate and state
python -m src.main cli device revoke <device-id>  # every peer refuses the device once the revocation has reached it
```

A revoked device still holds the bucket key, if one was configured; replace the
key (`storage replace-key`, or File → Replace the bucket's key…) if that matters.
The GUI and the TUI have no device list.

The listener's certificate and the rules for trusting it are in
[Listening for peers](#listening-for-peers).

### A server that hosts accounts

A server on the internet holds no account of its own; it **hosts** the
accounts its users give it, one directory each under its root, and serves
them all from one listener. The holder of an account cannot be reached by
the server, so the direction is reversed: the server shows a **grant text**
and the holder gives the account to it.

```bash
# On the server, in an empty root (VOICE_CONFIG_DIR)
python -m src.main cli sync serve                               # serves every account of the root; the first run makes the certificate
python -m src.main cli account host --label meirav              # a grant text: valid ten minutes, once

# On the device that holds the account (a phone pastes the text into its setup-text field)
python -m src.main cli account grant-host "voice://pair?v=1&g=1&..."
python -m src.main cli sync deliver <server-device-id>          # Notes and Recordings to the server

# Back on the server
python -m src.main cli account list                             # the hosted account, marked (hosted), never the default
python -m src.main -a meirav cli account show-code              # a code for the account's next device
```

`sync serve` and `account list|create|default|remove|host` create no account.
Run every other command on the server with `-a <label>`: without `-a` it opens
the default account, and on a root with no default account it creates one
labelled `default`.

The grant text carries the certificate fingerprint only when the certificate
exists, and the certificate is made the first time `sync serve` runs; run the
listener first.
For callers from the internet, set `public_url` in the root's `config.json`
(for example `"public_url": "https://sync.example.com"`).

The server receives a key made for it, the holder's card, and the Notes on
the first delivery; a further device of the account joins through the
server's code as through any device. Every account served from an indexed root
has an `audit.log` beside its database, hosted or not: one line for each request
that carries a device key (time, request id, device, route, bytes and status),
never a key or content, rotated at 5 MB. Pairing requests and `/sync/status` are
not in it, and a one-account directory writes no audit log. A desktop with
several accounts in its root serves them the same way: `sync serve` there
listens for every account.

### Sync troubleshooting

When sync issues occur (e.g., missing attachments, Transcriptions, or data inconsistencies), use these commands:

```bash
# Check the connection to a peer, step by step, with a code for each failure
python -m src.main cli sync check <peer-id>

# Reset sync timestamps - the next sync exchanges all data
python -m src.main cli sync reset-timestamps

# Full resync - exchanges the whole dataset with peers now,
# whatever the last sync timestamps say
python -m src.main cli sync full-resync                       # Resync with all peers
python -m src.main cli sync full-resync --peer <peer-id>      # Resync with one peer
```

**When to use each:**
- `reset-timestamps`: Clears the "last synced" timestamps locally. The next `sync now` exchanges all data. Use when you suspect the sync state is stale.
- `full-resync`: Runs a complete sync now, pulling and pushing all data. Use when you need to recover missing data now.

### Firewall configuration

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

### Reverse proxy

The listener serves HTTPS by itself, so a reverse proxy is not required. A
server that should present a certificate from a public authority (so that
devices accept it without a pinned fingerprint) can put a reverse proxy in front
of a listener that serves plain http on the loopback address:

```bash
python -m src.main cli sync serve --host 127.0.0.1 --port 8384 --plain-http
```

Behind a proxy on the same machine, every caller reaches the listener from
127.0.0.1.

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

Obtain an SSL certificate with Let's Encrypt:
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d sync.example.com
```

Behind the proxy, give the public address in the codes and grant texts, so that
devices call it:
```bash
python -m src.main cli account host --url https://sync.example.com --label meirav
python -m src.main -a meirav cli account show-code --url https://sync.example.com
```

## Cloud storage for audio files

> **Setting it up by hand?** `CLOUD-STORAGE-SETUP.md` walks through
> creating the storage and collecting the values it needs, click by click,
> for Amazon S3, DigitalOcean Spaces and Backblaze B2. The wizard below
> (File → Set up the bucket…, or `storage setup`) sets up Amazon S3 for you.

Recording files can be kept in cloud storage (AWS S3 or S3-compatible services),
the **bucket**. The bucket holds Recordings only. Notes, Tags and Transcriptions
travel between your devices by sync, never through the bucket.

### The bucket, set up by the wizard

File → Set up the bucket… (or `storage setup`) takes a person who has never
seen the Amazon console from nothing to a tested bucket: where to click, the
policy text to paste (it lets the key make and use buckets named `voice-…`
and nothing else; it cannot delete a Recording), the pasted key cleaned of
spaces, the nearest region proposed, a generated bucket name, the bucket
made private and hardened (public access blocked, encrypted at rest, TLS only),
its lifecycle rules set (cheaper storage after thirty days, purged objects
deleted a day later, abandoned uploads after two), a small object written and
read back, and the whole saved as part of the account so every device receives
it at its next sync. In the GUI, `Next` stays disabled until the round trip
has passed.

```bash
python -m src.main cli storage setup                          # asks each question
python -m src.main cli storage setup --access-key-id AKIA... --secret-access-key ... --yes   # takes the flags and the defaults, asks nothing
python -m src.main cli storage replace-key <new-access-key-id>  # a new key for the bucket, tested, then saved for every device
python -m src.main cli storage check                          # the bucket as it is: key, round trip, public access, encryption, TLS, lifecycle
```

"Replace the bucket's key…" (File menu) tests a new key the same way and saves
it for every device. `Test everything` in the Sync dialogue, or
`sync check --all`, checks every peer and the bucket as one table;
`storage check` checks the bucket alone.

### Configuration

The storage configuration is stored in the database and syncs between devices.

```bash
# Check current storage configuration
python -m src.main cli storage status

# Configure AWS S3 storage without the wizard (the key is not tested)
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

`configure-s3` replaces the whole stored configuration, so the upload limit
returns to its default of 100 MB. To change only the key, use
`storage replace-key`.

### AWS S3 Setup by hand

The wizard makes the bucket and gives the policy text itself. These steps are
the alternative by hand; `storage check` and `sync check --all` read the
bucket's settings that the wizard's policy allows, and may report failures with
a narrower policy.

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
   - Copy your `Access key` and `Secret access key`. This information will be configured in Voice in the next step. If you lose this value, AWS cannot show it to you again.

5. Configure Voice with the bucket details and IAM credentials
   - Use the `cli storage configure-s3` command. See previous section for details.

### How it works

- A sync never moves a Recording's file. The bucket is reached only by upload and download.
- The desktop uploads when you ask: `cli storage upload-pending` (the GUI and the TUI have no upload control); the phone uploads with the Upload button. Recordings whose file is not on this device are skipped; the device that holds them uploads them.
- Other devices download a file **only on demand**: the GUI and TUI show a "Media missing" notice with a Download button (the TUI also uses the `d` key), the CLI has `audiofile-download`, `note-audiofiles-download` and `storage download-missing`, and the Android app shows a Download button on the Note. The CLI's transcribe commands download a missing file first.
- Until a device that holds a file has uploaded it, other devices show it as "not uploaded by their device yet" and cannot download it; a peer that holds it can still send it (`sync deliver`, `sync exchange`, `sync send`, or `sync fetch` from the other side).
- The storage configuration (including the credentials) syncs to all connected devices. Configure it once, on any installation.
- Sync keeps working while cloud storage is unreachable, because it never touches it. An upload that fails is reported and tried again at the next upload, and after the first failure the remaining uploads are deferred instead of each waiting for a timeout.
- Downloads are written to a temporary `.part` file, checked against the object size and only then renamed into place, so an interrupted download never leaves a broken file behind.
- Every Recording carries the hash of its bytes. The bucket object is named by it (`<hash>.<extension>`, with `.enc` added when encrypted), so the same file imported on two devices is stored once; a download whose bytes do not match the hash is removed and reported instead of being kept as the Recording.
- A file larger than 8 MiB goes up in parts. If the connection drops, the parts already in the bucket stay there and the next `upload-pending` (or the phone's next Upload) sends only the rest; the object appears only when every part is there. Parts of an upload never finished are removed by the bucket's own rule after two days.

### The upload limit

The account has one upload limit, the same on every device (it is part of the
synced storage configuration): a Recording larger than that is not uploaded to
the bucket and stays on the devices that hold it. Issues names it: `larger than
the account's upload limit of <size>`. The default is 100 MB, and the limit is
at least 1 MB. It can be set only once a bucket is configured
(`No bucket is configured yet`).

```bash
python -m src.main cli storage upload-limit       # Upload limit: 100 MB for every device of the account
python -m src.main cli storage upload-limit 250   # set it for every device
curl -X PUT http://127.0.0.1:5000/api/storage/upload-limit \
    -H 'Content-Type: application/json' -d '{"megabytes": 250}'
```

On the phone it is Settings → Sync Settings → Upload limit (MB). The GUI and
the TUI have no control for it.

### Encrypting recordings in the bucket

Off by default. When on, nobody without the account's **recording key** can
listen to a Recording in the bucket, Amazon included. The price is a key that,
if lost, makes those Recordings unreadable for ever, so:

1. Export the key first: `cli account recording-key export` (a QR code and 43
   characters), `Export the recording key…` in File → Sync…, or "Export the
   key" in Settings → Advanced on the phone. Keep it on paper. The switch
   stays off until the key was exported from that device. Exporting makes the
   key if the account has none.
2. Turn it on: `cli storage encrypt on`, the `Encrypt recordings in the bucket`
   box in File → Sync…, or the switch on the phone. The setting is synced, so
   every device of the account encrypts from then on. A device receives the key
   when it is paired; a device that lost everything imports it
   (`cli account recording-key import <text>`, `Import…`, "Import a key").
   `cli storage encrypt` with no argument prints the state.
3. Recordings already in the bucket stay plain until you press `Re-upload
   existing recordings encrypted` (`cli storage reupload-encrypted`); it goes
   one file at a time and continues where it stopped.

A device with the key keeps its own copies plain: downloads and fetches are
decrypted on arrival. A device without the key (a server that holds encrypted
objects) keeps them as they are and serves them as they are; the device that
fetches from it decrypts them. Turning encryption off makes new uploads plain and
leaves the encrypted objects readable by any device with the key.

### Manual upload and download

```bash
# Upload every Recording on this device that is not in cloud storage yet
python -m src.main cli storage upload-pending

# Download every Recording that is in cloud storage but not on this device
python -m src.main cli storage download-missing
```

`upload-pending` is how the desktop uploads: for the first upload of existing
Recordings, and after every import.

### Keeping a complete local copy (mirror)

A desktop or server installation can record that it should hold every Recording,
as a local backup of the bucket. This is a local setting
(`sync.mirror_audio_files` in `config.json`); it is never synced and other
installations are not aware of it. Do not enable it on Android. A sync never
moves a file, so the files are downloaded with `storage download-missing`.

```bash
python -m src.main cli storage mirror enable
python -m src.main cli storage download-missing   # download everything the bucket has and this device lacks
python -m src.main cli storage mirror disable
python -m src.main cli storage status             # Shows the current mirror setting
```

## Search syntax

### Free-text Search

- Searches Note content (case-insensitive)

```
meeting
hello world
```

### Tag Search

- Hierarchical paths supported. A search for a parent Tag includes its children.

```
tag:Paris               # Matches both Europe/France/Paris and US/Texas/Paris
tag:Europe/France/Paris
```

### Starred Notes

- `is:marked` finds the starred Notes. In the GUI the star button beside the
  search field adds or removes it.

### Combined Search (AND logic)

```
tag:Work meeting
tag:Personal tag:Family reunion
tag:Work is:marked
```
Multiple terms are combined with AND logic:
- `tag:A tag:B` - Notes must have (A or descendants) AND (B or descendants)
- `tag:A hello` - Notes must have (A or descendants) AND contain the text "hello"

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
- Multiple people speaking simultaneously? Do you need per-speaker separation?
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

- On an indexed root, the machine's configuration (device id and name, listen port, backup, public address) is `<root>/config.json`, and an account's configuration is `<root>/<account id>/config.json`. On a one-account directory both are in `<root>/config.json`. The root is `~/.config/voice` unless `VOICE_CONFIG_DIR` names another; `-a` (or `VOICE_ACCOUNT_ID`) chooses the account.
- The configuration file can be edited by hand. The application reads it at start.
- For detailed documentation, see [CONFIGURATION.md](CONFIGURATION.md).

### Config Schema

```json
{
  "database_file": "/path/to/notes.db",
  "default_interface": null,
  "window_geometry": null,
  "implementations": {},
  "audiofile_directory": "/home/user/.config/voice/<account id>/audio",
  "themes": {
    "colours": {
      "warnings": "#FFFF00",
      "warnings_dark": null,
      "warnings_light": null,
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

The machine's settings (in the root's `config.json` on an indexed root):

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| device_id | string | generated | This installation's id, 32 hex characters |
| device_name | string | the host name | The name other devices show for this one |
| sync.server_port | number | 8384 | Port the listener listens on |
| public_url | string | "" | Where this machine is reachable from the internet. Empty: the listener serves its own network only |
| backup.interval_hours | number | 24 | Hours between periodic backups; 0 turns them off |
| backup.directory | string | "" | Where backups go; empty means `<root>/backups/<account id>/` |
| backup.keep | number | 30 | How many backups are kept per account |

The account's settings (in `<root>/<account id>/config.json`):

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| database_file | string | `<account directory>/notes.db` | Path to the SQLite database file |
| default_interface | string/null | null | `gui`, `tui`, `cli` or `web`. If null: GUI if PySide6 is installed, else TUI |
| audiofile_directory | string/null | `<account directory>/audio` | The folder of Recording files. Set when the account is created |
| window_geometry | string/null | null | Not read or written by the desktop code |
| implementations | object | {} | Reserved; not read |
| themes.colours.warnings | string | #FFFF00 | Colour of ambiguous Tags in the GUI's search field |
| themes.colours.warnings_dark | string/null | null | The same colour for the dark theme; when unset, `warnings` is used |
| themes.colours.warnings_light | string/null | null | The same colour for the light theme; when unset, `warnings` is used |
| themes.colours.tui_border_focused | string | green | TUI border colour of the focused pane |
| themes.colours.tui_border_unfocused | string | blue | TUI border colour of the other panes |
| sync.enabled | boolean | false | Shown by `sync status`; `account join` and `account grant-host` set it to true |
| sync.peers | array | [] | The peers of this device |
| sync.peers[].peer_id | string | | The peer's device id |
| sync.peers[].peer_name | string | | The name shown for the peer |
| sync.peers[].peer_url | string | | Where the peer listens (`https://…`) |
| sync.peers[].certificate_fingerprint | string/null | null | The pinned fingerprint of the peer's certificate (`SHA256:…`), from pairing, `add-peer --fingerprint` or discovery on the local network |
| sync.last_peer_id | string | "" | The peer of the last operation, named on the one button |
| sync.forgotten_peers | array | [] | Peers forgotten on this device; their cards do not bring them back |
| sync.listener_idle_stop_hours | number | 0 | Hours of silence after which the GUI's listener stops; 0 means never |
| sync.max_sync_file_size_mb | number | 100 | The listener's size limit for JSON sync requests; Recordings are streamed and not held to it |
| sync.mirror_audio_files | boolean | false | Records that this installation keeps a copy of every Recording in the bucket. Local-only, never synced; desktop/server only |
| sync.device_key | string | | This device's key for the account (made at creation or given by pairing) |
| sync.recording_key | string | | The account's recording key, when encryption was set up |
| sync.recording_key_exported | boolean | false | Whether this device exported the recording key |
| transcription.preferred_languages | array | [] | [ISO 639-1](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) language codes for transcription hints (e.g., ["en", "he"]); overwritten at start by the synced setting |
| transcription.providers.whisper.model_path | string/null | null | Path to a GGML Whisper model file for the CLI. If not set, the CLI selects one from ~/.local/share/whisper/ |

### Sync configuration

- The peers, the device key and the recording key are in the account's `config.json`; the listen port and `public_url` in the machine's.

### Color Values

Colors are specified as hex strings (e.g., `#FFFF00`). The warning color is used to highlight ambiguous Tags in the GUI's search field.

Theme-specific colors take precedence:
- Dark theme: Uses `warnings_dark`, falls back to `warnings`
- Light theme: Uses `warnings_light`, falls back to `warnings`

### Example Custom Config

A one-account directory's `config.json`, which holds the machine's and the account's settings together:

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
    "enabled": true,
    "server_port": 8384,
    "peers": [
      {
        "peer_id": "018e5874b8357f489eb72834083c05b7",
        "peer_name": "Bar on server",
        "peer_url": "https://192.168.1.20:8384",
        "certificate_fingerprint": "SHA256:3a:9f:…"
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

## Database location

- On an indexed root, each account's database is `<root>/<account id>/notes.db`;
  the root is `~/.config/voice` unless `VOICE_CONFIG_DIR` names another, and
  `-a` (or `VOICE_ACCOUNT_ID`) chooses the account.
- A root that holds one database and no `accounts.db` is the account itself:
  `<root>/notes.db`.

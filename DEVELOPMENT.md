# Building and hacking on VOICE

Everything needed to install VOICE from source, run its tests, and deploy the
sync server. For what VOICE is, see the [README](README.md); for how it is
used, the [user manual](USER_MANUAL.md).

## Contents

- [Architecture](#architecture)
- [Installation](#installation)
- [Updating](#updating)
- [Server deployment](#server-deployment)
- [Testing](#testing)
- [Development](#development)


## Technical decisions

Decisions that apply to more than one project in the Voice Family — data rules,
time handling, thresholds, naming, interface conventions, testing rules — are in
`../TECHNICAL-DECISIONS.md`. Read it before changing behaviour the other
projects share, and record new cross-project decisions there.

## Architecture

- Primary application written in fully typed Python 3.
- Core functionality in Rust module for seamless compatibility with mobile applications.
- GUI written in Qt, other modes remain available if Qt (PySide) is not installed.
- TUI written in Textual, other modes remain available if Textual is not installed.
- REST API written in Flask, other modes remain available if Flask is not installed.
- The CLI is always available.
- SQLite database.
- Comprehensive test suite.

## Installation

### Clone and create Virtual Environment

```bash
git clone --recurse-submodules https://github.com/dotancohen/voice.git
cd voice
python3 -m venv .venv
source .venv/bin/activate  # On Linux/Mac
# or
.venv\Scripts\activate  # On Windows
```

### Clone submodules

- If the repo had been cloned without submodules, add them.

```bash
git submodule update --init --recursive
```

### Install Dependencies

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt     # Only for development
pip install -r requirements-server.txt  # For deployment to a server, useful for centralized syncing and TUI/CLI access.
```

### Build Rust Extension

The Rust core library must be built and installed into the virtual environment:

```bash
cd rust/voice-python
maturin develop --release
cd ../..
```

This compiles the Rust code and installs it as a Python module. Rebuild after any changes to Rust code in `submodules/voicecore/` or `rust/voice-python/`.

## Updating

```bash
git pull
git submodule update              # Checkout the submodule commit that Voice points to
cd rust/voice-python
maturin develop --release         # Rebuild if Rust code changed
cd ../..
```

## Server Deployment

- For deploying Voice on a server (sync server + TUI for SSH access), use the server requirements file.

### Pre-Installation

Ensure that tooling is installed:
```bash
sudo apt update && sudo apt install build-essential  # Debian family
sudo apt install pkg-config libssl-dev                              # Debian family

sudo dnf groupinstall "Development Tools"                # Redhat family
sudo dnf install pkg-config openssl-devel                    # Redhat family

which rustc
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y  # Only if rustc is not installed.
```
Then log out and log back in to ensure that environment is set properly.

### Installation

```bash
mkdir -p /var/www/voice
cd /var/www/voice
git clone --recurse-submodules https://github.com/dotancohen/voice.git .
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-server.txt # Provides centralized syncing and TUI/CLI access.
cd rust/voice-python && maturin develop --release && cd ../..
```

### Updating

```bash
cd /var/www/voice
git pull
git submodule update --init --recursive
cd rust/voice-python && ../../.venv/bin/maturin develop --release && cd ../..
```

### Starting the Sync Server

- The database is created automatically on first start
- The default root is `~/.config/voice/`, with one directory per account under it; set `VOICE_CONFIG_DIR` for another root and `-a` for another account.

```bash
python -m src.main cli sync serve                              # Start with defaults (0.0.0.0:8384)
python -m src.main cli sync serve --host 0.0.0.0 --port 8384   # Custom host/port
python -m src.main cli sync serve --verbose                    # Enable logging to stdout
python -m src.main cli sync serve --verbose --no-color         # Logging without ANSI colors
VOICE_CONFIG_DIR=/path/to/root python -m src.main cli sync serve   # With another root
```

#### Sync Server Options

| Option | Short | Description |
|--------|-------|-------------|
| `--host` | | Host to bind to (default: 0.0.0.0) |
| `--port` | | Port to bind to (default: 8384 or from config) |
| `--verbose` | `-v` | Enable verbose logging to stdout (shows sync requests and operations) |
| `--no-color` | | Disable ANSI color codes in log output (useful for log files or non-terminal output) |

### Using the TUI via SSH

- Users can SSH into the server and use the TUI to manage notes.
- On servers without GUI dependencies, simply running `python -m src.main` will launch the TUI.

```bash
ssh user@server
cd /opt/voice
source .venv/bin/activate
python -m src.main       # Will launch TUI if GUI is not available
python -m src.main tui # Force TUI even if GUI is available
```

### Running as a Service

Create user:
```bash
sudo useradd --system --create-home --home-dir /var/www/voice --shell /bin/bash voicesync
sudo chown -R voicesync:voicesync /var/www/voice
```

Create a systemd service file at `/etc/systemd/system/voicesync.service`:
```ini
[Unit]
Description=Voice Sync Server
After=network.target

[Service]
Type=simple
User=voicesync
WorkingDirectory=/var/www/voice
ExecStart=/var/www/voice/.venv/bin/python -m src.main cli sync serve --host 0.0.0.0 --port 8384 --verbose --no-color
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

The `--verbose --no-color` flags are optional but recommended for production:
- `--verbose` logs sync requests and operations to stdout, which systemd captures to journald
- `--no-color` disables ANSI codes that would clutter the journal
- View logs with `journalctl -u voicesync -f` to monitor sync activity or debug issues
- Omit both flags if you don't need to monitor sync operations

Enable and start:
```bash
sudo systemctl enable voicesync
sudo systemctl start voicesync
```

Manage the service:
```bash
sudo systemctl start voicesync # Start the service
sudo systemctl stop voicesync # Stop the service
sudo systemctl restart voicesync # Restart systemd service, e.g. after updating
sudo systemctl status voicesync # Check status
journalctl -u voicesync -f  # Follow logs
```

Access Voice data with sudo. The root holds the machine's `config.json`,
`accounts.db` and `certs/`; each account is a directory named by its id,
`<account id>/`, with its `notes.db`, `config.json`, `audio/` and `snapshots/`
(`voice cli account list` shows the ids):
```bash
sudo -u voicesync vim /var/www/voice/.config/voice/config.json
sudo -u voicesync sqlite3 /var/www/voice/.config/voice/<account id>/notes.db
```

Access Voice data as the logged-in user without sudo:
```bash
sudo usermod -aG voicesync $USER
sudo chmod -R g+rw /var/www/voice/.config/voice/
vim /var/www/voice/.config/voice/config.json
sqlite3 /var/www/voice/.config/voice/<account id>/notes.db
```

## Testing

### Driving the Android app from a computer (ADB)

The debug build of VoiceAndroid accepts every user action as an Android *Intent* (an explicit broadcast to `com.dotancohen.voiceandroid/.automation.AdbCommandReceiver`), so a manual test plan can script the phone. The helper `~/Projects/VoiceFamily/VoiceAndroid/tools/voice-adb` sends the intent and prints the app's reply, which starts with `OK` or `ERROR`:

```bash
voice-adb ping
voice-adb set-sync http://192.168.1.20:8384 <server-peer-id> Android
voice-adb sync-now                      # OK success received=12 sent=3
voice-adb create-note "פתק מהטלפון"     # OK id=01a0...
voice-adb list-notes                    # one NOTE {...} JSON line per note, with media state and conflicts
voice-adb import-audio /sdcard/VoiceTestStorage
voice-adb open settings                 # opens the app on a screen for steps done by hand
voice-adb set-recording-format opus     # opus (default), aac or wav16
voice-adb set-recorder start_immediately=true during_call=pause
voice-adb merge-notes <note>,<note>     # merge them into the oldest one
voice-adb download-model large-v3-q5_0  # a Whisper model for transcription on the phone
voice-adb transcribe <note> he all      # transcribe every recording of the note, one at a time (2 = only the 2nd)
voice-adb list-transcriptions <note>    # one TRANSCRIPTION {...} line per transcription: text, language, model
voice-adb help                          # the full list
```

Release builds do not contain the receiver. See `../test-plans/` (in the VoiceFamily directory) for the manual test plans that use it.

### Run All Tests

```bash
pytest
cargo test --manifest-path submodules/voicecore/Cargo.toml
```

### Run Tests by Type

```bash
pytest tests/unit  # Unit tests only (fast, no dependencies)
pytest tests/gui    # GUI tests only (requires Qt/PySide6)
pytest tests/cli      # CLI tests only
pytest tests/web  # Web API tests only (Flask)
pytest -m unit        # Unit tests
pytest -m gui         # GUI tests
pytest -m cli           # CLI tests
pytest -m web      # Web API tests
```

### Run with Coverage Report

```bash
pytest --cov=src --cov-report=html
```

### Run Specific Test File

```bash
pytest tests/unit/test_database.py
pytest tests/cli/test_cli_search.py
```

### Run Specific Test Class or Function

```bash
pytest tests/unit/test_database.py::TestSearchNotes
pytest tests/cli/test_cli_search.py::TestSearchText::test_search_by_text
```

### Test Data

The test suite uses a pre-populated database with:
- 14 tags in hierarchical structure
- 6 notes with various tag combinations
- Hebrew text support testing
- Multiple notes per tag for comprehensive testing

See [TESTING.md](TESTING.md) for detailed test documentation.

## Development

### Type Checking

```bash
mypy src/
```

### Code Formatting

```bash
black src/
```

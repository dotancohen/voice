# VOICE: The Very Organized Information Capture Engine

- The Problem: Voice notes are a fast, effective way to _temporarily_ record information on the go, but are near impossible to actually work with in their raw format.
- The Solution: VOICE provides the tools to transform data stuck in voice notes into plain text that can be used in Actionable Items, Calendars, Data Stores, or just Archived.

## Features

- Note-taking application with hierarchical tags.
- Sync notes between instances - fully decentralized self-hosted service.
- GUI, TUI, CLI, and Web API interfaces.
- Voice note transcription using local Whisper AI models.

### GUI

- Designed for finding information quickly, via tags and search.
- Full keyboard control and mouse control.
- RTL text support.
- Dark and light themes.

### TUI

- Designed for finding information quickly, via tags and search.
- Full keyboard control and mouse control.
- RTL text support.

### CLI

- Fully scriptable with JSON or CSV output.

### Web API

- RESTful HTTP API with JSON responses.

## Roadmap

- Add UI for Tag management (create, rename, delete).
- Add UI for sync conflict management.
- Web UI that uses Web API.
- Multiple user accounts per server.
- Automatic content summary of voice notes, using AI installed locally.
- Detect file timestamps from filesystem metadata or filenames, import as new notes.

## Requirements

- Python 3.10 or higher
- Rust toolchain (for building the core library)
- maturin (for building Python bindings)
- PySide6 + pyqtdarktheme (for GUI mode)
- Flask + Flask-CORS (for Web API mode)
- Whisper GGML model files (for transcription) - see [Transcription](#transcription) section

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

## Usage

- For now no packaged executable. All interfaces are accessed through a unified entry point: `python -m src.main`

```bash
python -m src.main          # Auto-detect interface: GUI if available, else TUI
python -m src.main -d /path/to/config  # Custom configuration directory
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

- Normalizes timestamps from ISO 8601 format (2025-12-29T23:22:13.462391) to SQLite format (2025-12-29 23:22:13)
- Uses PRAGMA user_version to track migration status (only runs once)
- Is extensible - future normalizations (like unicode normalization) can be added to the normalize_database() method

```
python -m src.main cli db-maintenance database-normalize
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
- The default config directory is at `~/.config/voice/notes.db`, use the -d flag to set a custom directory.

```bash
python -m src.main cli sync serve                              # Start with defaults (0.0.0.0:8384)
python -m src.main cli sync serve --host 0.0.0.0 --port 8384   # Custom host/port
python -m src.main cli sync serve --verbose                    # Enable logging to stdout
python -m src.main cli sync serve --verbose --no-color         # Logging without ANSI colors
python -m src.main -d /path/to/config cli sync serve           # With custom config directory
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

Access Voice data with sudo:
```bash
sudo -u voicesync vim /var/www/voice/.config/voice/config.json
sudo -u voicesync sqlite3 /var/www/voice/.config/voice/voice.db
```

Access Voice data as the logged-in user without sudo:
```bash
sudo usermod -aG voicesync $USER
sudo chmod -R g+rw /var/www/voice/.config/voice/
vim /var/www/voice/.config/voice/config.json
sqlite3 /var/www/voice/.config/voice/voice.db
```

## Syncing between installations

- Sync peers are defined in the Config file.
- All sync peers can function equally as both servers and clients. Choose one instance to listen as a server, and another instance to contact it as a client. The sync result is the same no matter which instance is the client and which instance is the server.
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
# Add server as a peer
python -m src.main cli sync add-peer <peer-device-id> "PeerName" http://<peer-ip>:8384

# Trigger sync
python -m src.main cli sync now                                              # Sync with all configured peers
python -m src.main cli sync now --peer <peer-device-id> # Sync with a specific peer only
```

Resolve edit conflicts from multiple devices:
```bash
# Check for conflicts
python -m src.main cli sync conflicts

# Resolve a conflict by keeping local, remote, or merging
python -m src.main cli sync resolve <conflict-id> local       # Or:
python -m src.main cli sync resolve <conflict-id> remote   # Or:
python -m src.main cli sync resolve <conflict-id> merge
```

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

## Testing

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

## Database Location

- Default: `~/.config/voice/notes.db`
- Custom: `<config-dir>/notes.db` when using `-d` flag

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

## Authorship

- Written by [Dotan Cohen](https://dotancohen.com).
- Extensive help, especially with writing the test suite and Rust components, attributed to Anthropic Claude via Claude Code.

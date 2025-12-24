# VOICE: The Very Organized Information Capture Engine

- The Problem: Voice notes are a fast, effective way to _temporarily_ record information on the go, but are near impossible to actually work with in their raw format.
- The Solution: VOICE provides the tools to transform data stuck in voice notes into plain text that can be used in Actionable Items, Calendars, Data Stores, or just Archived.

## Features

- Note-taking application with hierarchical tags.
- Sync notes between instances - fully decentralized self-hosted service.
- GUI, TUI, CLI, and Web API interfaces.

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

- Features for working with voice notes specifically - the original inspiration for this project.
- Add UI for Tag management (create, rename, delete).
- Add UI for sync conflict management.
- Web UI that uses Web API.
- Multiple user accounts per server.
- Text-To-Speech transcription of voice notes, using either local Whisper AI or Google Cloud Speech.
- Automatic content summary of voice notes, using AI installed locally.
- Detect file timestamps from filesystem metadata or filenames, import as new notes.

## Requirements

- Python 3.10 or higher
- PySide6 + pyqtdarktheme (for GUI mode)
- Flask + Flask-CORS (for Web API mode)

## Architecture

- Core functionallity written in Rust.
- Primary application written in fully typed Python 3.
- GUI writted in Qt, other modes remain available if Qt (PySide) is not installed.
- TUI writted in Textual, other modes remain available if if Textual is not installed.
- REST API writted in Flask, other modes remain available if if Flask is not installed.
- The CLI is always available.
- SQLite database.
- Comprehensive test suite.

## Installation

### Create Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Linux/Mac
# or
.venv\Scripts\activate  # On Windows
```

### Install Dependencies

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt     # Only for development
pip install -r requirements-server.txt # For deployment to a server, useful for centralized syncing and TUI/CLI access.
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

Create notes:
```bash
python -m src.main cli new-note "Hello, world!"
echo "Note from stdin" | python -m src.main cli new-note
```

Show specific note:
```bash
python -m src.main cli show-note <note-uuid>
```

List tags (hierarchical):
```bash
python -m src.main cli list-tags
```

List all notes:
```bash
python -m src.main cli list-notes
```

Search notes:
```bash
python -m src.main cli search --text "meeting"                            # Search by text
python -m src.main cli search --tag Work                                         # Search by tag
python -m src.main cli search --tag Europe/France/Paris         # Search by hierarchical tag path
python -m src.main cli search --tag Work --tag Projects  # Multiple tags (AND logic)
python -m src.main cli search --text "meeting" --tag Work        # Combined text and tags
```

#### Output formatting

```bash
python -m src.main cli --format json # JSON output
python -m src.main cli --format csv  # CSV output
```

### Web API Mode

- Server runs on `http://127.0.0.1:5000` by default.

```bash
python -m src.main web
python -m src.main web --host 0.0.0.0 --port 8080 # Custom host or port
python -m src.main web --debug                      # Debug mode
```

#### Web API Endpoints

- All endpoints return JSON.
- CORS is enabled for cross-origin requests.

```bash
curl http://127.0.0.1:5000/api/health                            # Health check
curl http://127.0.0.1:5000/api/notes                             # List all notes
curl http://127.0.0.1:5000/api/notes/<note-uuid>  # Get specific note
curl http://127.0.0.1:5000/api/tags                                 # List all tags
curl "http://127.0.0.1:5000/api/search?text=meeting"                     # Search notes by text
curl "http://127.0.0.1:5000/api/search?tag=Work"                              # Search notes by tag
curl "http://127.0.0.1:5000/api/search?tag=Europe/France/Paris" # Search notes by hierarchical tag
curl "http://127.0.0.1:5000/api/search?tag=Work&tag=Projects"   # Search notes by specifying multiple tags (AND logic)
curl "http://127.0.0.1:5000/api/search?text=meeting&tag=Work" # Combined text and tags
```

## Server Deployment

- For deploying Voice on a server (sync server + TUI for SSH access), use the server requirements file.

### Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-server.txt # Provides centralized syncing and TUI/CLI access.
```

### Starting the Sync Server

- The database is created automatically on first start
- The default config directory is at `~/.config/voice/notes.db`, use the -d flag to set a custom directory.

```bash
python -m src.main cli sync serve                                                     # Start with defaults (0.0.0.0:8384)
python -m src.main cli sync serve --host 0.0.0.0 --port 8384  # Custom host/port
python -m src.main -d /path/to/config cli sync serve               # With custom config directory
```

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

Create a systemd service file at `/etc/systemd/system/voice-sync.service`:

```ini
[Unit]
Description=Voice Sync Server
After=network.target

[Service]
Type=simple
User=voice
WorkingDirectory=/opt/voice
ExecStart=/opt/voice/.venv/bin/python -m src.main cli sync serve --host 0.0.0.0 --port 8384
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable voice-sync
sudo systemctl start voice-sync
```

## Syncing between installations

**Step 1: Get device IDs** (on each device):
```bash
python -m src.main cli sync status
# Output includes: Device ID: <32-character-hex-id>
```

**Step 2: Start the sync server** (on devices you want to sync from):
```bash
python -m src.main cli sync serve
# Or run as a systemd service (see below)
```

**Step 3: Add peers** (on each device, add the other devices):
```bash
python -m src.main cli sync add-peer <peer-device-id> "PeerName" http://<peer-ip>:8384
```

Example:
```bash
python -m src.main cli sync add-peer a1b2c3d4e5f6789012345678abcdef01 "HomeServer" https://sync.example.com
```

**Step 4: Trigger sync**:
```bash
# Sync with all configured peers
python -m src.main cli sync now

# Sync with a specific peer only
python -m src.main cli sync now --peer <peer-device-id>
```

**Step 5: Check for conflicts** (if any):
```bash
python -m src.main cli sync conflicts
```

**Step 6: Resolve conflicts** (if needed):
```bash
# Resolve a conflict by keeping local, remote, or merging
python -m src.main cli sync resolve <conflict-id> local
python -m src.main cli sync resolve <conflict-id> remote
python -m src.main cli sync resolve <conflict-id> merge
```

### Managing Peers

```bash
# List all configured peers
python -m src.main cli sync list-peers

# Remove a peer
python -m src.main cli sync remove-peer <peer-device-id>
```

### Firewall Configuration

Open the sync server port (default 8384) in your firewall.

**UFW (Ubuntu/Debian):**
```bash
sudo ufw allow 8384/tcp comment "Voice Sync"
sudo ufw reload
sudo ufw status
```

**firewalld (RHEL/CentOS/Fedora):**
```bash
sudo firewall-cmd --permanent --add-port=8384/tcp
sudo firewall-cmd --reload
sudo firewall-cmd --list-ports
```

**iptables:**
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
cargo test --manifest-path rust/voice-core/Cargo.toml
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

Configuration is stored in `<config-dir>/config.json`. The default location is `~/.config/voice/config.json`.

For detailed documentation, see [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

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

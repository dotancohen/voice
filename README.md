# Voice Rewrite

Note-taking application with hierarchical tags, available as GUI, TUI, CLI, and Web API.

## Features
- Hierarchical tag system with unlimited nesting
- **GUI Mode**: Three-pane PySide6 interface with dark/light theme support
- **TUI Mode**: Three-pane Textual terminal interface with RTL support
- **CLI Mode**: Command-line interface with JSON/CSV export
- **Web API Mode**: RESTful HTTP API with JSON responses
- SQLite database backend
- Fully typed Python code
- Clean architecture with complete core/UI separation
- Search with tag: syntax and free-text
- Hierarchical tag filtering (parent includes children)
- AND logic for multiple search terms
- Comprehensive test suite (unit + GUI + CLI + web tests)

## Requirements
- Python 3.10 or higher
- PySide6 + pyqtdarktheme (for GUI mode)
- Flask + Flask-CORS (for Web API mode)

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
```

### For Development
```bash
pip install -r requirements-dev.txt
```

## Usage

All interfaces are accessed through a unified entry point: `python -m src.main`

### GUI Mode

Launch the graphical interface:
```bash
python -m src.main              # Auto-detect: GUI if available, else TUI
python -m src.main gui          # Explicit GUI mode with dark theme
python -m src.main gui --theme light   # Light theme
python -m src.main gui --theme dark    # Dark theme (explicit)
```

With custom configuration directory:
```bash
python -m src.main -d /path/to/config gui --theme light
```

### TUI Mode

Launch the terminal user interface (requires Textual):
```bash
python -m src.main tui
```

**Controls:**
- **Up/Down**: Navigate lists
- **Left/Right**: Collapse/Expand tag hierarchy
- **Enter**: Select item
- **e**: Edit selected note
- **s**: Save changes
- **a**: Show all notes
- **q**: Quit
- **Ctrl+P**: Open command palette

The TUI provides a three-pane layout (Tags, Notes List, Note Detail) with support for Hebrew/Arabic text display.

### CLI Mode

List all notes:
```bash
python -m src.main cli list-notes
python -m src.main cli --format json list-notes  # JSON output
python -m src.main cli --format csv list-notes   # CSV output
```

Show specific note:
```bash
python -m src.main cli show-note <note-uuid>
python -m src.main cli --format json show-note a1b2c3d4e5f6789012345678abcdef01
```

List tags (hierarchical):
```bash
python -m src.main cli list-tags
```

Search notes:
```bash
# Search by text
python -m src.main cli search --text "meeting"

# Search by tag
python -m src.main cli search --tag Work

# Search by hierarchical tag path
python -m src.main cli search --tag Geography/Europe/France/Paris

# Multiple tags (AND logic)
python -m src.main cli search --tag Work --tag Work/Projects

# Combined text and tags
python -m src.main cli search --text "meeting" --tag Work

# JSON output
python -m src.main cli --format json search --tag Personal
```

Custom configuration directory (all commands):
```bash
python -m src.main -d /path/to/config cli list-notes
```

### Web API Mode

Start the Flask web server:
```bash
python -m src.main web
```

Server runs on `http://127.0.0.1:5000` by default.

Custom host/port:
```bash
python -m src.main web --host 0.0.0.0 --port 8080
```

Enable debug mode:
```bash
python -m src.main web --debug
```

**API Endpoints:**

List all notes:
```bash
curl http://127.0.0.1:5000/api/notes
```

Get specific note:
```bash
curl http://127.0.0.1:5000/api/notes/<note-uuid>
```

List all tags:
```bash
curl http://127.0.0.1:5000/api/tags
```

Search notes:
```bash
# Search by text
curl "http://127.0.0.1:5000/api/search?text=meeting"

# Search by tag
curl "http://127.0.0.1:5000/api/search?tag=Work"

# Search by hierarchical tag
curl "http://127.0.0.1:5000/api/search?tag=Geography/Europe/France/Paris"

# Multiple tags (AND logic)
curl "http://127.0.0.1:5000/api/search?tag=Work&tag=Work/Projects"

# Combined text and tags
curl "http://127.0.0.1:5000/api/search?text=meeting&tag=Work"
```

Health check:
```bash
curl http://127.0.0.1:5000/api/health
```

All endpoints return JSON. CORS is enabled for cross-origin requests.

## Server Deployment

For deploying VoiceRewrite on a server (sync server + TUI for SSH access), use the server requirements file:

### Installation

```bash
# Clone the repository
git clone https://github.com/your-repo/voicerewrite.git
cd voicerewrite

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install server dependencies (includes TUI, no GUI)
pip install -r requirements-server.txt
```

### Starting the Sync Server

```bash
# Start with defaults (0.0.0.0:8384)
python -m src.main cli sync serve

# Custom host/port
python -m src.main cli sync serve --host 0.0.0.0 --port 8384

# With custom config directory
python -m src.main -d /path/to/config cli sync serve
```

The database is created automatically on first start at `~/.config/voicerewrite/notes.db` (or in the custom config directory).

### Using the TUI via SSH

Users can SSH into the server and use the TUI to manage notes:
```bash
ssh user@server
cd /opt/voicerewrite
source .venv/bin/activate
python -m src.main tui
```

On servers without GUI dependencies, simply running `python -m src.main` will launch the TUI.

### Running as a Service

Create a systemd service file at `/etc/systemd/system/voicerewrite-sync.service`:

```ini
[Unit]
Description=VoiceRewrite Sync Server
After=network.target

[Service]
Type=simple
User=voicerewrite
WorkingDirectory=/opt/voicerewrite
ExecStart=/opt/voicerewrite/.venv/bin/python -m src.main cli sync serve --host 0.0.0.0 --port 8384
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable voicerewrite-sync
sudo systemctl start voicerewrite-sync
```

### Sync Endpoints

The sync server exposes these endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/sync/status` | GET | Get sync server status |
| `/sync/handshake` | POST | Exchange device info |
| `/sync/changes` | GET | Request changes since timestamp |
| `/sync/apply` | POST | Apply changes from peer |
| `/sync/full` | GET | Get full dataset for initial sync |

### Sync Workflow

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
sudo ufw allow 8384/tcp comment "VoiceRewrite Sync"
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

**Nginx configuration** (`/etc/nginx/sites-available/voicerewrite`):
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
sudo ln -s /etc/nginx/sites-available/voicerewrite /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

**Obtain SSL certificate with Let's Encrypt:**
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d sync.example.com
```

When using a reverse proxy, use HTTPS in the peer URL:
```bash
python -m src.main cli sync add-peer <server-device-id> "Server" https://sync.example.com
```

### Security Considerations

1. **Use HTTPS**: The sync protocol does not encrypt data. Always use a reverse proxy with SSL for production.

2. **Restrict access**: Consider limiting access by IP if your devices have static IPs:
   ```nginx
   location / {
       allow 192.168.1.0/24;
       allow 203.0.113.50;
       deny all;
       proxy_pass http://127.0.0.1:8384;
   }
   ```

3. **Firewall defaults**: Block all incoming traffic except SSH and your sync port:
   ```bash
   sudo ufw default deny incoming
   sudo ufw default allow outgoing
   sudo ufw allow ssh
   sudo ufw allow 443/tcp
   sudo ufw enable
   ```

4. **Bind to localhost**: When using a reverse proxy, bind the sync server to localhost only:
   ```bash
   python -m src.main cli sync serve --host 127.0.0.1 --port 8384
   ```

5. **No CDN needed**: The sync server handles small JSON payloads between trusted devices. CDNs are not applicable.

## Testing

The test suite is organized by interface type for clean separation:
- **Unit tests** (`tests/unit/`) - Core functionality, no dependencies
- **GUI tests** (`tests/gui/`) - GUI components, requires Qt/PySide6
- **CLI tests** (`tests/cli/`) - Command-line interface
- **Web tests** (`tests/web/`) - Flask REST API endpoints

### Run All Tests
```bash
pytest
```

### Run Tests by Type
```bash
# Unit tests only (fast, no dependencies)
pytest tests/unit

# GUI tests only (requires Qt/PySide6)
pytest tests/gui

# CLI tests only
pytest tests/cli

# Web API tests only (Flask)
pytest tests/web

# By marker
pytest -m unit   # Unit tests
pytest -m gui    # GUI tests
pytest -m cli    # CLI tests
pytest -m web    # Web API tests
```

### Run with Coverage Report
```bash
pytest --cov=src --cov-report=html
# Open htmlcov/index.html in browser to view coverage
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
- 14 tags in hierarchical structure (Work/Projects/VoiceRewrite, Geography/Europe/France/Paris, etc.)
- 6 notes with various tag combinations
- Hebrew text support testing
- Multiple notes per tag for comprehensive testing

See `TESTING.md` for detailed test documentation.

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
- Default: `~/.config/voicerewrite/notes.db`
- Custom: `<config-dir>/notes.db` when using `-d` flag

## Configuration

Configuration is stored in `<config-dir>/config.json`. The default location is `~/.config/voicerewrite/config.json`.

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

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `database_file` | string | `<config_dir>/notes.db` | Path to SQLite database file |
| `default_interface` | string\|null | `null` | Default interface (`gui`, `tui`, `cli`, `web`). If null, auto-detects: GUI if available, else TUI |
| `window_geometry` | object\|null | `null` | Saved window size/position (set automatically) |
| `implementations` | object | `{}` | Reserved for future component selection |
| `themes.colours.warnings` | string | `#FFFF00` | Warning highlight color (backward compatible) |
| `themes.colours.warnings_dark` | string | `#FFFF00` | Warning color for dark theme (yellow) |
| `themes.colours.warnings_light` | string | `#FF8C00` | Warning color for light theme (dark orange) |
| `themes.colours.tui_border_focused` | string | `green` | TUI border color for focused pane |
| `themes.colours.tui_border_unfocused` | string | `blue` | TUI border color for unfocused panes |

### Color Values

Colors are specified as hex strings (e.g., `#FFFF00`). The warning color is used to highlight ambiguous tags in search results.

TUI border colors accept Textual color names (e.g., `green`, `blue`, `red`) or hex colors (e.g., `#00FF00`).

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

## Adding Sample Data

Use the CLI to create notes:
```bash
python -m src.main cli new-note "This is my first note!"
echo "Note from stdin" | python -m src.main cli new-note
```

Or use the TUI/GUI to create and edit notes interactively.

## Search Syntax

### Free-text Search
```
meeting
hello world
```
Searches note content (case-insensitive)

### Tag Search
```
tag:Work
tag:Europe/France/Paris
```
Searches by tag. Hierarchical paths supported. Parent tags include children.

### Combined Search (AND logic)
```
tag:Work meeting
tag:Personal tag:Family reunion
```
Multiple terms are combined with AND logic:
- `tag:A tag:B` - notes must have (A or descendants) AND (B or descendants)
- `tag:A hello` - notes must have (A or descendants) AND contain "hello"

## Current Limitations
- No audio recording functionality (coming in future iterations)
- Tag management (create, rename, delete) not yet in UI

## Project Structure
- `src/main.py` - Unified entry point (dispatches to GUI, TUI, CLI, or Web)
- `src/core/` - Business logic and data access (zero Qt dependencies)
- `src/ui/` - GUI components (PySide6)
- `src/tui.py` - Terminal UI module (Textual)
- `src/cli.py` - Command-line interface module
- `src/web.py` - Flask REST API module
- `tests/unit/` - Core functionality tests
- `tests/gui/` - GUI integration tests
- `tests/cli/` - CLI tests
- `tests/web/` - Web API tests
- `docs/` - Documentation including RTL support and configuration
- All code is fully typed and documented

## Architecture

### Critical Design Principle
The application has four modes:
1. **GUI mode** - PySide6 interface (three-pane layout)
2. **TUI mode** - Textual terminal interface (three-pane layout)
3. **CLI mode** - Command-line interface with JSON/CSV/text output
4. **Web API mode** - Flask REST API with JSON responses

Therefore, `src/core/` has **zero Qt dependencies** and can be imported by all interface modes.

### Test Organization
Tests are separated by interface type for complete independence:
- `tests/unit/` - Core functionality (database, config) - 55 tests
- `tests/gui/` - GUI components (requires Qt) - 49 tests
- `tests/cli/` - CLI commands (subprocess) - 38 tests
- `tests/web/` - Web API endpoints (Flask test client) - 38 tests

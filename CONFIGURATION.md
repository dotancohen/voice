# Configuration Reference

Voice stores its configuration under `~/.config/voice/`: the machine's `config.json` and `accounts.db`, and one directory per account with its own `config.json`, `notes.db` and `audio/`. The root can be changed with the `VOICE_CONFIG_DIR` environment variable; the account with `-a`.

See also: Quick reference in [USER_MANUAL.md](../USER_MANUAL.md#configuration)

## Configuration File Location

- **Default**: `~/.config/voice/config.json`
- **Custom**: Set `VOICE_CONFIG_DIR=/path/to/root` before launching the application, and `-a <label>` for an account other than the default

If the configuration file doesn't exist, it will be created with default values on first run.

## Configuration Options

### database_file

**Type**: `string` (file path)
**Default**: `~/.config/voice/notes.db`

Path to the SQLite database file that stores notes and tags.

```json
{
  "database_file": "/home/user/.config/voice/notes.db"
}
```

### default_interface

**Type**: `string` or `null`
**Default**: `null` (auto-detect)
**Options**: `"gui"`, `"tui"`, `"cli"`, `"web"`, or `null`

The default interface to launch when no subcommand is specified.

When set to `null` (the default), the application auto-detects the best interface:
- **GUI** if PySide6 and qdarktheme are installed
- **TUI** otherwise

```json
{
  "default_interface": null
}
```

### window_geometry

**Type**: `object` or `null`
**Default**: `null`

Stores the GUI window position and size for session persistence. Automatically updated when the GUI window is moved or resized.

```json
{
  "window_geometry": {
    "x": 100,
    "y": 100,
    "width": 1200,
    "height": 800
  }
}
```

### implementations

**Type**: `object`
**Default**: `{}`

Reserved for future use. Will store component implementation selections for pluggable architecture.

```json
{
  "implementations": {}
}
```

### themes

**Type**: `object`
**Default**: See below

Contains theming configuration for the application interfaces.

```json
{
  "themes": {
    "colours": {
      "warnings": "#FFFF00",
      "tui_border_focused": "green",
      "tui_border_unfocused": "blue"
    }
  }
}
```

#### themes.colours.warnings

**Type**: `string` (CSS color)
**Default**: `"#FFFF00"` (yellow)

Color used to highlight ambiguous tags in the GUI and TUI. Ambiguous tags are those with the same name but different parent hierarchies (e.g., `France/Paris` and `Texas/Paris`).

For light themes, consider using `"#FF8C00"` (dark orange) for better visibility.

#### themes.colours.tui_border_focused

**Type**: `string` (Textual color name or hex)
**Default**: `"green"`

Border color for the currently focused pane in the TUI (Terminal User Interface).

Accepts Textual color names (e.g., `"green"`, `"blue"`, `"red"`) or hex colors (e.g., `"#00FF00"`).

#### themes.colours.tui_border_unfocused

**Type**: `string` (Textual color name or hex)
**Default**: `"blue"`

Border color for unfocused panes in the TUI.

Accepts Textual color names or hex colors.

### device_id

**Type**: `string` (32 hex characters)
**Default**: Auto-generated on first run

A unique identifier for this device, used for sync. This is a UUIDv7 generated automatically when the config is first created. Do not modify this value manually.

```json
{
  "device_id": "019b552595fd7413a3eaffd04ea82f8b"
}
```

### device_name

**Type**: `string`
**Default**: `"Voice on <hostname>"`

A human-readable name for this device, displayed to peers during sync.

```json
{
  "device_name": "My Desktop"
}
```

### sync

**Type**: `object`
**Default**: See below

Configuration for the sync feature. Sync allows multiple devices to synchronize notes and tags.

```json
{
  "sync": {
    "enabled": false,
    "server_port": 8384,
    "peers": []
  }
}
```

#### sync.enabled

**Type**: `boolean`
**Default**: `false`

Whether sync is enabled for this device.

#### sync.server_port

**Type**: `integer`
**Default**: `8384`

The port this device listens on when running as a sync server (`python -m src.main cli sync serve`). Other peers connect to this port to sync with this device.

#### sync.mirror_audio_files

**Type**: `boolean`
**Default**: `false`

When `true`, every sync also downloads every audio file that is in cloud storage but missing from this installation's `audiofile_directory`, so the installation holds a complete copy of all media (a backup of the cloud bucket). This is a local-only setting: it is never synced to other devices, and other devices are not aware of it. Intended for desktop and server installations; leave it off on phones. Change it with `python -m src.main cli storage mirror enable|disable`.

When `false` (the default), audio files are downloaded only when the user asks for them (Download button in the GUI, TUI and Android app; `audiofile-download` / `note-audiofiles-download` on the CLI).

#### sync.peers

**Type**: `array` of peer objects
**Default**: `[]`

List of peer devices to sync with. Each peer object has the following properties:

| Property | Type | Description |
|----------|------|-------------|
| `peer_id` | string | The peer's device ID (32 hex characters) |
| `peer_name` | string | Human-readable name for the peer |
| `peer_url` | string | URL of the peer's sync server (e.g., `http://192.168.1.100:8384`) |
| `certificate_fingerprint` | string or null | TLS certificate fingerprint for TOFU verification |

```json
{
  "sync": {
    "peers": [
      {
        "peer_id": "019b5574d6357f409ee72734053c05a7",
        "peer_name": "My Server",
        "peer_url": "http://192.168.1.100:8384",
        "certificate_fingerprint": null
      }
    ]
  }
}
```

##### Certificate Fingerprint (TOFU)

The `certificate_fingerprint` field implements Trust On First Use (TOFU) for TLS connections, similar to SSH host key verification:

1. When first connecting to a peer over HTTPS with `certificate_fingerprint: null`, the peer's TLS certificate fingerprint is automatically recorded
2. On subsequent connections, the certificate is verified against the stored fingerprint
3. If the fingerprint doesn't match (e.g., man-in-the-middle attack or server certificate changed), the connection is rejected

**Format**: `SHA256:xx:xx:xx:xx:...` (SHA-256 hash, colon-separated hex)

You can pre-set a fingerprint when adding a peer via CLI:
```bash
python -m src.main cli sync add-peer <id> "<name>" "<url>" --fingerprint "SHA256:aa:bb:..."
```

### server_certificate_fingerprint

**Type**: `string` or `null`
**Default**: `null`

The fingerprint of this device's own TLS certificate, automatically set when the certificate is generated. This is informational and used internally.

### Synced settings (stored in the database, not in config.json)

A few settings are about the user rather than the machine and are shared with every device through sync:

| Key | Value |
|-----|-------|
| `transcription.preferred_languages` | JSON list of ISO 639-1 codes, e.g. `["he", "en"]` |
| `transcription.providers.<provider>.api_key` | API key of a cloud transcription provider |

On startup the synced value overrides the matching entry under `transcription` in `config.json`; a value present only in `config.json` seeds the other devices. Paths, models, ports and colours never sync. Change a synced value with:

```bash
python -m src.main cli settings set transcription.preferred_languages '["he", "en"]'
```

When two devices change the same setting before syncing, the later value is kept and a conflict is recorded (`sync conflicts`).

## Example Complete Configuration

```json
{
  "database_file": "/home/user/.config/voice/notes.db",
  "default_interface": null,
  "window_geometry": null,
  "implementations": {},
  "themes": {
    "colours": {
      "warnings": "#FFFF00",
      "tui_border_focused": "green",
      "tui_border_unfocused": "blue"
    }
  },
  "device_id": "019b552595fd7413a3eaffd04ea82f8b",
  "device_name": "My Desktop",
  "sync": {
    "enabled": false,
    "server_port": 8384,
    "peers": []
  },
  "server_certificate_fingerprint": null
}
```

## Warning Color Priority

The warning color is resolved with this priority (highest to lowest):

1. **Theme-specific key** (`warnings_dark` or `warnings_light`) - if present, used for that theme
2. **Generic key** (`warnings`) - fallback if theme-specific key not present
3. **Built-in default** - `#FFFF00` (yellow) for dark theme, `#FF8C00` (dark orange) for light theme

This allows you to:
- Set a single color for both themes using `warnings`
- Override specific themes using `warnings_dark` or `warnings_light`

### Example: Different colors per theme

```json
{
  "themes": {
    "colours": {
      "warnings": "#FFFF00",
      "warnings_dark": "#FFD700",
      "warnings_light": "#FF6600"
    }
  }
}
```

In this example, dark theme uses `#FFD700` (overrides `warnings`) and light theme uses `#FF6600` (overrides `warnings`).

## Managing Sync Peers

Peers are best managed via CLI commands rather than editing the config file directly:

```bash
# Add a peer
python -m src.main cli sync add-peer <peer_id> "<peer_name>" "<peer_url>"

# List all peers
python -m src.main cli sync list-peers

# Remove a peer
python -m src.main cli sync remove-peer <peer_id>

# Sync with all peers
python -m src.main cli sync now

# Start the sync server
python -m src.main cli sync serve
```

## File Locations

All Voice data is stored in the configuration directory:

| File/Directory | Description |
|----------------|-------------|
| `config.json` | Configuration file (settings, sync peers) |
| `notes.db` | SQLite database (notes, tags, sync state) |
| `certs/` | TLS certificates for sync |
| `certs/server.crt` | This device's TLS certificate |
| `certs/server.key` | This device's TLS private key |

Default location: `~/.config/voice/`

Use `VOICE_CONFIG_DIR` to specify a custom root:
```bash
VOICE_CONFIG_DIR=/path/to/root python -m src.main cli sync list-peers
```

## Modifying Configuration

Configuration can be modified by:

1. **Editing the JSON file directly** - Changes take effect on next application launch
2. **Using the application** - Some settings (like `window_geometry`) are automatically updated
3. **Using CLI commands** - For sync peer management (recommended)

The application validates configuration on load. If the JSON is malformed, default values will be used and a warning will be logged.

## Transcribing long recordings (this machine only)

Inside the `transcription` section of `config.json`, and never synced:

| Key | Meaning |
|-----|---------|
| `transcribe_long_recordings` | Whether this machine transcribes Recordings the phone passed over. Default `false`. |
| `long_recording_minutes` | The length past which a Recording is this machine's work. Default `10`, the phone's own limit. |

Set them with `cli transcribe-backlog --enable` / `--disable`, or by editing
`config.json`. They are deliberately local: whether a computer can transcribe a
two-hour meeting is a fact about that computer. See
`VoiceFamily/TECHNICAL-DECISIONS.md` §3.4.

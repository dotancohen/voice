# Configuration Reference

Voice stores its configuration in a JSON file located at `~/.config/voice/config.json`. The configuration directory can be customized via the `--config-dir` CLI argument.

See also: Quick reference in [README.md](../README.md#configuration)

## Configuration File Location

- **Default**: `~/.config/voice/config.json`
- **Custom**: Use `--config-dir /path/to/dir` when launching the application

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

Use `--config-dir` to specify a custom location:
```bash
python -m src.main --config-dir /path/to/config cli sync list-peers
```

## Modifying Configuration

Configuration can be modified by:

1. **Editing the JSON file directly** - Changes take effect on next application launch
2. **Using the application** - Some settings (like `window_geometry`) are automatically updated
3. **Using CLI commands** - For sync peer management (recommended)

The application validates configuration on load. If the JSON is malformed, default values will be used and a warning will be logged.

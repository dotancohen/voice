# Configuration Reference

Every field of Voice's `config.json` files, where the files are, and which
settings are kept in the database instead. A shorter overview is the
Configuration section of the [user manual](USER_MANUAL.md).

## Contents

- [Where the files are](#where-the-files-are)
- [Machine settings and account settings](#machine-settings-and-account-settings)
- [Configuration options](#configuration-options)
- [Synced settings (stored in the database, not in config.json)](#synced-settings-stored-in-the-database-not-in-configjson)
- [Transcribing long recordings (this machine only)](#transcribing-long-recordings-this-machine-only)
- [Example account configuration](#example-account-configuration)
- [Warning color priority](#warning-color-priority)
- [Sync devices](#sync-devices)
- [Changing the configuration](#changing-the-configuration)

## Where the files are

**The root** is `$VOICE_CONFIG_DIR` (with `~` expanded) when that variable is
set and not empty, otherwise `~/.config/voice`. **The account** is the one
given with `-a <label or id>`, otherwise the one named by `$VOICE_ACCOUNT_ID`,
otherwise the root's default account. There is no option that names a
configuration directory directly.

A root has one of two layouts.

**An indexed root** (what an empty root becomes at the first start of any
command other than `sync serve` and `account list|create|default|remove|host`):

| File or directory | Contents |
|---|---|
| `<root>/config.json` | The machine's settings: device id and name, listen port, backup, `public_url` |
| `<root>/accounts.db` | The index of accounts (mode 0600) |
| `<root>/certs/server.crt`, `<root>/certs/server.key` | The listener's certificate and its key (0600), made at the first start of the listener |
| `<root>/backups/<account id>/` | Periodic backups of the account's database |
| `<root>/<account id>/config.json` | The account's settings on this device |
| `<root>/<account id>/notes.db` | The account's database: notes, tags, recordings' records, sync state, the bucket configuration, synced settings |
| `<root>/<account id>/audio/` | The account's recordings (the default `audiofile_directory`) |
| `<root>/<account id>/snapshots/` | The newest 5 copies of `notes.db`, taken before every sync, move and restore |
| `<root>/<account id>/voice.log` | The application's log, rotated at 5 MB (`voice.log.1`, `voice.log.2`) |
| `<root>/<account id>/audit.log` | One line per authenticated request the listener served, rotated at 5 MB |
| `<root>/<account id>/transcription_queue.json` | The account's transcription queue |

`python -m src.main cli account list` shows the account ids and labels.

**A one-account directory**: a root that holds `config.json` or `notes.db` and
no `accounts.db` is the account itself. `config.json`, `notes.db`, `certs/`,
`snapshots/`, `backups/<account id>/`, `voice.log` and
`transcription_queue.json` are all directly in it, and `audiofile_directory` is
whatever it was set to. `-a` cannot select anything in such a directory, and it
cannot host other accounts.

If a `config.json` does not exist, it is written with default values when the
directory is first opened.

## Machine settings and account settings

On an indexed root, five settings belong to the machine and are read from
`<root>/config.json`: `device_id`, `device_name`, `sync.server_port`, `backup`
and `public_url`. When an account is opened, these values replace what the
account's own `config.json` says, and changing one of them writes it to both
files. Every other field is read from the account's file.

In a one-account directory the single `config.json` holds all of them.

## Configuration Options

### database_file

**Type**: `string` (file path)
**Default**: `notes.db` in the directory of this `config.json`

Path to the SQLite database file. An empty value is replaced with the default
when the file is loaded.

### default_interface

**Type**: `string` or `null`
**Default**: `null`
**Options**: `"gui"`, `"tui"`, `"cli"`, `"web"`, or `null`

The interface to start when none is given on the command line. Read from the
account's `config.json`.

When it is `null`:
- **GUI** if PySide6 and qdarktheme can be imported
- **TUI** otherwise

Set it with `python -m src.main cli config set default_interface tui`.

### window_geometry

**Type**: `string` or `null`
**Default**: `null`

Present in the file, but nothing in the application reads or writes it.

### implementations

**Type**: `object` of strings
**Default**: `{}`

Present in the file, but nothing in the application reads or writes it.

### themes

**Type**: `object`

```json
{
  "themes": {
    "colours": {
      "warnings": "#FFFF00",
      "tui_border_focused": "green",
      "tui_border_unfocused": "blue",
      "warnings_dark": null,
      "warnings_light": null
    }
  }
}
```

#### themes.colours.warnings

**Type**: `string` (CSS color)
**Default**: `"#FFFF00"` (yellow)

The GUI colours ambiguous tag terms in the search field with this colour.
Ambiguous tags are those with the same name but different parent hierarchies
(e.g., `France/Paris` and `Texas/Paris`). See
[Warning color priority](#warning-color-priority).

#### themes.colours.warnings_dark, themes.colours.warnings_light

**Type**: `string` or `null`
**Default**: `null`

The warning colour for the dark or the light theme; `null` means `warnings`.

#### themes.colours.tui_border_focused

**Type**: `string` (Textual color name or hex)
**Default**: `"green"`

Border colour of the focused pane in the TUI. Accepts Textual colour names
(e.g., `"green"`) or hex colours (e.g., `"#00FF00"`).

#### themes.colours.tui_border_unfocused

**Type**: `string` (Textual color name or hex)
**Default**: `"blue"`

Border colour of the panes without focus in the TUI.

### this_device_id

**Type**: `string` (32 hex characters)
**Default**: a UUIDv7, generated when the file is first written
**Machine setting**

This device's identifier for sync. Do not change it.

### this_device_name

**Type**: `string`
**Default**: the first of (1) the name the user gave the computer: the name
set in its system settings (the pretty hostname on Linux, the Computer Name on
macOS), then its host name, such as `"teva-2025"`; (2) its type, such as
`"Ubuntu desktop"`; (3) an animal with the ends of its IPv6 and IPv4 addresses,
such as `"Wombat 81:4c 7.21"`. A name that is empty or starts with `localhost`
counts as none (SYNC_SPECIFICATION UI-11)
**Machine setting**

The name other devices of the account show for this device. Set it with
`python -m src.main cli config set this_device_name "My Desktop"`.

### sync

**Type**: `object`

```json
{
  "sync": {
    "enabled": false,
    "server_port": 8384,
    "devices": [],
    "max_sync_file_size_mb": 100,
    "mirror_audio_files": false,
    "device_key": "",
    "recording_key_exported": false,
    "last_device_id": "",
    "forgotten_devices": [],
    "listener_idle_stop_hours": 0
  }
}
```

#### sync.enabled

**Type**: `boolean`
**Default**: `false`

Whether sync is enabled for this account on this device. `account join` and
`account grant-host` set it to `true`; `cli config set sync.enabled` changes it.

#### sync.server_port

**Type**: `integer`
**Default**: `8384`
**Machine setting**

The port the listener uses (`python -m src.main cli sync serve`, or File →
Listen for devices in the GUI) when `--port` is not given, and the port that
`account show-code` and `account host` put into the addresses they offer.

#### sync.devices

**Type**: `array` of device objects
**Default**: `[]`

The devices this device syncs with. Pairing adds them, and so do the device
cards that sync brings. Each device object has these properties:

| Property | Type | Description |
|----------|------|-------------|
| `device_id` | string | The other device's id (32 hex characters) |
| `device_name` | string | The name this device shows for the other device |
| `device_url` | string | The device's listener, e.g. `https://192.168.1.100:8384` |
| `certificate_fingerprint` | string or null | The pinned fingerprint of the device's TLS certificate |

```json
{
  "sync": {
    "devices": [
      {
        "device_id": "019b5574d6357f409ee72734053c05a7",
        "device_name": "My Server",
        "device_url": "https://192.168.1.100:8384",
        "certificate_fingerprint": "SHA256:aa:bb:cc:..."
      }
    ]
  }
}
```

A `device_url` beginning with `http://` is refused unless its host is
`localhost`, `127.*` or `::1`:
`… is plain http; a device key must not cross a network in clear (TLS_REQUIRED)`.

When a device does not answer at its `device_url` (a network error, not a
refusal), a sync (also the sync that starts a deliver or an exchange), a pull, a
push and an initial sync first try each address on the other device's card, with
the device's pinned certificate, and write the one that answers to `device_url`
(LISTEN-4). When none answers, the operations `sync deliver`, `exchange`,
`send`, `fetch` and `sync now --device` look for it on the local network for 3
seconds. An address found there is written to `device_url`, with
the announced fingerprint.

##### Certificate fingerprint

**Format**: `SHA256:xx:xx:…` (32 bytes of the SHA-256 hash of the certificate,
lowercase hex, separated by colons)

- When `certificate_fingerprint` is set, the device's certificate is accepted
  only if its fingerprint is this one. A different certificate is refused with
  `CERTIFICATE_MISMATCH`.
- When it is `null`, the certificate is checked against the system's root
  certificates. A listener's own self-signed certificate is then refused.
- **There is no trust on first use**: a fingerprint is never recorded by
  connecting. It is set by pairing (`account join`, `account grant-host`), by
  LAN discovery, or by hand:

```bash
python -m src.main cli sync add-device <id> "<name>" "https://192.168.1.100:8384" --fingerprint "SHA256:aa:bb:..."
```

A listener logs its fingerprint when started with `-v`
(`Certificate fingerprint SHA256:…`).

#### sync.max_sync_file_size_mb

**Type**: `integer`
**Default**: `100`

On the desktop: the largest body, in MB, that the listener accepts on its JSON
routes. Recordings sent to the listener are not limited by it. The upload limit
for the bucket is a different setting: `storage upload-limit`.

#### sync.mirror_audio_files

**Type**: `boolean`
**Default**: `false`

Set with `python -m src.main cli storage mirror enable|disable` or
`cli config set sync.mirror_audio_files true`. Never synced. The commands and
`storage status` describe it as "every sync downloads all cloud audio files to
this device", but no sync on the desktop reads this setting today: setting it
downloads nothing. `python -m src.main cli storage download-missing` downloads
every recording that is in the bucket and not on this device.

#### sync.device_key

**Type**: `string` (43 base64url characters)

This device's key for the account, made at the first start or issued at
pairing. Every other device holds only its hash. It is stored in clear on the
desktop; treat the file as a password.

#### sync.recording_key, sync.recording_key_exported

`recording_key` is the account's key for encrypted recordings in the bucket
(43 base64url characters), absent from the file until one exists. It is
received at pairing, or made by `account recording-key export`, which also sets
`recording_key_exported` to `true`. Encryption of new uploads can be switched
on only after the key was exported.

#### sync.last_device_id, sync.forgotten_devices

`last_device_id` is the device of the last operation. `forgotten_devices` lists the
devices removed with `sync forget-device`: their device cards do not add them back
until they are added again by hand or by pairing.

#### sync.listener_idle_stop_hours

**Type**: `integer`
**Default**: `0` (never)

Read only by the GUI: its listener (File → Listen for devices) stops after this
many hours without a request. `sync serve` never stops by itself.

### server_certificate_fingerprint

**Type**: `string` or `null`
**Default**: `null`

No code sets it. The listener's fingerprint is calculated from
`certs/server.crt` whenever it is needed.

### audiofile_directory

**Type**: `string` or `null`
**Default**: `<root>/<account id>/audio` for an account of an indexed root;
`null` in a one-account directory

Where the account's recordings are on this device. Set it with
`python -m src.main cli config set audiofile_directory /path/to/audio`.

### transcription

**Type**: `object`
**Default**: `{"preferred_languages": [], "providers": {}}`

Transcription settings. `preferred_languages` and each
`providers.<provider>.api_key` are copies of synced settings (see below). The
keys for long recordings are described in
[Transcribing long recordings](#transcribing-long-recordings-this-machine-only).

### backup

**Type**: `object`
**Default**: `{"interval_hours": 24, "directory": "", "keep": 30}`
**Machine setting**

The periodic backup of the databases while the listener runs.

| Key | Meaning |
|---|---|
| `interval_hours` | Hours between copies; `0` turns the periodic backup off. The first copy is made one interval after the listener starts |
| `directory` | Where the copies go, in `<directory>/<account id>/`; empty means `<root>/backups/<account id>/` |
| `keep` | How many copies are kept per account |

The listener copies only the accounts that a request opened since it started.
`python -m src.main cli account backup` copies every account of the root at
once.

### public_url

**Type**: `string`
**Default**: `""`
**Machine setting**

When it is empty, the listener refuses every caller whose address is not
private, link-local or loopback:
`This device serves its own network only; it has no public address (NOT_ON_LAN)`.
When it is not empty, callers from every address are served. There is no
command for it: edit `<root>/config.json`, then restart the listener.

## Synced settings (stored in the database, not in config.json)

A few settings are about the user rather than the machine and are shared with every device through sync:

| Key | Value |
|-----|-------|
| `transcription.preferred_languages` | JSON list of ISO 639-1 codes, e.g. `["he", "en"]` |
| `transcription.providers.<provider>.api_key` | API key of a cloud transcription provider |

On startup the synced value replaces the matching entry under `transcription` in `config.json`; a value present only in `config.json` is copied into the database, and from there to the other devices. Paths, models, ports and colours never sync. Change a synced value with:

```bash
python -m src.main cli settings set transcription.preferred_languages '["he", "en"]'
```

When two devices change the same setting before syncing, the later value is kept and a conflict is recorded (`sync conflicts`).

The bucket configuration and its upload limit are also kept in the database and
synced, and only there: `config.json` has no bucket settings. They are changed
with the `storage` commands; see [CLOUD-STORAGE-SETUP.md](CLOUD-STORAGE-SETUP.md)
and `cli storage status`.

## Transcribing long recordings (this machine only)

Inside the `transcription` section of the account's `config.json`, and never synced:

| Key | Meaning |
|-----|---------|
| `transcribe_long_recordings` | Whether this machine transcribes Recordings the phone passed over. Default `false`. |
| `long_recording_minutes` | The length past which a Recording is this machine's work. Default `10`, the phone's own limit. |

Set them with `cli transcribe-backlog --enable` / `--disable`, or by editing
`config.json`. They are deliberately local: whether a computer can transcribe a
two-hour meeting is a fact about that computer. See
`../TECHNICAL-DECISIONS.md` §3.4.

## Example account configuration

`<root>/<account id>/config.json` of a paired desktop:

```json
{
  "database_file": "/home/user/.config/voice/019b5525aa0b7c1e9f3d2c4b5a697887/notes.db",
  "default_interface": null,
  "window_geometry": null,
  "implementations": {},
  "themes": {
    "colours": {
      "warnings": "#FFFF00",
      "tui_border_focused": "green",
      "tui_border_unfocused": "blue",
      "warnings_dark": null,
      "warnings_light": null
    }
  },
  "device_id": "019b552595fd7413a3eaffd04ea82f8b",
  "device_name": "desk",
  "sync": {
    "enabled": true,
    "server_port": 8384,
    "devices": [
      {
        "device_id": "019b5574d6357f409ee72734053c05a7",
        "device_name": "My Server",
        "device_url": "https://192.168.1.100:8384",
        "certificate_fingerprint": "SHA256:aa:bb:cc:..."
      }
    ],
    "max_sync_file_size_mb": 100,
    "mirror_audio_files": false,
    "device_key": "<43 characters>",
    "recording_key_exported": false,
    "last_device_id": "019b5574d6357f409ee72734053c05a7",
    "forgotten_devices": [],
    "listener_idle_stop_hours": 0
  },
  "server_certificate_fingerprint": null,
  "audiofile_directory": "/home/user/.config/voice/019b5525aa0b7c1e9f3d2c4b5a697887/audio",
  "transcription": {
    "preferred_languages": ["he", "en"],
    "providers": {}
  },
  "backup": {
    "interval_hours": 24,
    "directory": "",
    "keep": 30
  },
  "public_url": ""
}
```

## Warning Color Priority

The warning colour is chosen in this order:

1. **Theme-specific key** (`warnings_dark` or `warnings_light`), when it is set, for that theme
2. **Generic key** (`warnings`), whose own default is `#FFFF00` for both themes

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

## Sync devices

A device becomes a device by pairing, not by editing the file. Adding a device by
hand does not let this device into the other device's listener: the listener refuses a
device that was not paired (`DEVICE_UNKNOWN`, or `ACCOUNT_UNKNOWN` for an
account it does not serve).

```bash
# On the device that holds the account, with its listener running: show a code
python -m src.main cli account show-code

# On the new device: join with that code
python -m src.main cli account join "voice://pair?..."

# List, rename and remove devices
python -m src.main cli sync list-devices
python -m src.main cli sync rename-device <device id or prefix> "<name>"
python -m src.main cli sync forget-device <full device id>

# Exchange notes with every device
python -m src.main cli sync now

# Start the listener
python -m src.main cli sync serve
```

Pairing and hosting are described in the user manual. A setup text shown on an
indexed root currently carries no certificate fingerprint (a defect), so a join
over HTTPS to that listener fails certificate verification.

Use `VOICE_CONFIG_DIR` for another root and `-a` for another account:

```bash
VOICE_CONFIG_DIR=/path/to/root python -m src.main -a <label> cli sync list-devices
```

## Changing the Configuration

1. **Commands**: `cli config show|get|set` for `device_name`,
   `audiofile_directory`, `default_interface`, `sync.server_port`,
   `sync.enabled` and `sync.mirror_audio_files`; `cli settings` for synced
   settings; `cli storage`, `cli sync` and `cli account` for the rest.
2. **Editing the JSON file** while no Voice program uses the directory. Changes
   take effect at the next start. `public_url`, `backup`,
   `sync.max_sync_file_size_mb` and `sync.listener_idle_stop_hours` have no
   command.

**If the JSON is malformed**, the default values are used and nothing is
logged. The next time any setting is saved, the defaults are written over the
file: a new `device_id`, and no devices or device key. Keep a copy of the file
before editing it by hand.

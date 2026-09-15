# Building and hacking on VOICE

Everything needed to install VOICE from source, run its tests, and deploy the
sync server. For what VOICE is, see the [README](README.md); for how it is
used, the [user manual](USER_MANUAL.md).

## Contents

- [Technical decisions](#technical-decisions)
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
projects share, and record new cross-project decisions there. The sync rules
are in `../SYNC_SPECIFICATION.md`.

## Architecture

- The application is written in fully typed Python 3 (`src/`).
- The core — database, sync client and listener, pairing, cloud storage — is
  the Rust crate `submodules/voicecore`, which the Android application shares.
  `rust/voice-python` builds its Python module, `voicecore`, with maturin.
- GUI written in Qt (PySide6). Without PySide6 and pyqtdarktheme, the TUI, CLI
  and Web API still start.
- TUI written in Textual, Web API written in Flask. **Both are needed by every
  interface, the CLI included**: `src/main.py` imports `src.tui` and `src.web`
  to build its argument parser, and those modules import Textual and Flask when
  they are loaded.
- The listener announces itself on the local network with `zeroconf`. Without
  it, `sync serve` prints `Not announced on the network: No module named 'zeroconf'`
  and serves anyway, and `cli sync discover` ends in a traceback.
- `segno` draws the QR codes of pairing; without it the setup text is printed
  alone.
- SQLite database.
- Comprehensive test suite.
- `bin/voice` runs `.venv/bin/python -m src.main` from the repository's
  directory. Link it into a directory in your `PATH`, and `voice cli sync status`
  works from anywhere.

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
pip install -r requirements-server.txt  # On a server without the GUI, instead of requirements.txt
```

- `requirements.txt` lists `PySide6` beside `PySide6-Essentials` because
  pytest-qt reads `PySide6.__version__`. Installed through `-r`, it also brings
  `PySide6-Addons` (428 MB), which nothing imports. The file's own advice is to
  install it with `pip install --no-deps PySide6`.
- `requirements-server.txt` has no `zeroconf`. Add `pip install zeroconf` for
  the listener to announce itself on the local network.

### Build Rust Extension

The Rust core library must be built and installed into the virtual environment:

```bash
cd rust/voice-python
maturin develop --release
cd ../..
```

This compiles the Rust code and installs it as a Python module. Rebuild after any changes to Rust code in `submodules/voicecore/` or `rust/voice-python/`.

The Android build writes a library of the same name into the same shared build
directory. If `import voicecore` then fails with
`dynamic module does not define module export function (PyInit_voicecore)`,
maturin installed the phone's library: `touch rust/voice-python/src/lib.rs` and
run `maturin develop --release` again from `rust/voice-python/`
(`CLAUDE.md`, "Building the Python bindings").

## Updating

```bash
git pull
git submodule update              # Checkout the submodule commit that Voice points to
cd rust/voice-python
maturin develop --release         # Rebuild if Rust code changed
cd ../..
```

## Server Deployment

A server runs the listener for one account or for the accounts of several
people, and the TUI or CLI over SSH. The security side (reverse proxy,
firewall, what is encrypted) is in
[SECURITY-CONSIDERATIONS.md](SECURITY-CONSIDERATIONS.md).

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
pip install zeroconf                   # Optional: announce the listener on the local network
cd rust/voice-python && maturin develop --release && cd ../..
```

### Updating

```bash
cd /var/www/voice
git pull
git submodule update --init --recursive
cd rust/voice-python && ../../.venv/bin/maturin develop --release && cd ../..
sudo systemctl restart voicesync
```

### Starting the Sync Server

- The root is `$VOICE_CONFIG_DIR`, else `~/.config/voice` of the user who runs
  the listener.
- **On an empty root**, `sync serve` creates `accounts.db`, `config.json` and
  `certs/server.crt` with `certs/server.key`, and **no account**. It serves
  every account listed in `accounts.db`, including accounts added while it
  runs.
- On a root that holds one account in its own directory (`config.json` or
  `notes.db`, and no `accounts.db`), it serves that account only. Such a root
  cannot host other accounts.
- The listener serves HTTPS with its own self-signed certificate. With `-v` it
  logs the certificate's fingerprint (`Certificate fingerprint SHA256:…`); its
  start text does not show it.
- It refuses callers outside private networks (`NOT_ON_LAN`) unless
  `public_url` is set in `<root>/config.json`, for example
  `"public_url": "https://sync.example.com:8384"`. There is no command for it;
  edit the file, then restart the listener.

```bash
python -m src.main cli sync serve                                # 0.0.0.0, port from config (8384)
python -m src.main cli sync serve --host 0.0.0.0 --port 8384     # Custom host/port
python -m src.main cli sync serve --verbose                      # Enable logging to stdout
python -m src.main cli sync serve --verbose --no-color           # Logging without ANSI colors
python -m src.main cli sync serve --host 127.0.0.1 --plain-http  # Behind a reverse proxy on this machine
VOICE_CONFIG_DIR=/path/to/root python -m src.main cli sync serve # With another root
```

#### Sync Server Options

| Option | Short | Description |
|--------|-------|-------------|
| `--host` | | Host to bind to (default: 0.0.0.0) |
| `--port` | | Port to bind to (default: 8384 or from config) |
| `--verbose` | `-v` | Enable verbose logging to stdout (shows sync requests and operations) |
| `--no-color` | | Disable ANSI color codes in log output |
| `--no-announce` | | Do not announce this listener on the local network |
| `--plain-http` | | Serve plain http instead of https. Allowed only on a loopback address: for a reverse proxy in front, or a test |

Without `--verbose` the Rust core writes no log lines. The Python log lines go
to standard error and to `voice.log`.

### Hosting an account

1. Start the listener on the server once, so that `<root>/certs/server.crt`
   exists. Then, as the same user and with the same `VOICE_CONFIG_DIR`, make a
   grant text:

```bash
python -m src.main cli account host --label dotan --url https://sync.example.com:8384
```

It is valid for ten minutes and for one account, and carries the
certificate's fingerprint. Without `--url` it offers
`https://<each private address>:<port>` and `https://<host name>:<port>`.
2. On the device that holds the account, with the server's listener running:

```bash
voice cli account grant-host "<grant text>"
voice cli sync deliver <server id>
```

3. `python -m src.main cli account list` on the server shows the account,
marked `(hosted)`.

Further devices of the account pair with a device that holds it (`account
show-code` there, `account join` on the new device). A setup text shown on the
server itself (`-a <label> cli account show-code`) currently carries no
certificate fingerprint, because the code looks for the certificate in the
account's directory instead of the root; a join to the server over HTTPS then
fails certificate verification. This is a defect.

**On a hosting server, give `-a` to every command.** Every command other than
`sync serve` and `account list|create|default|remove|host`, run without `-a`
(or `VOICE_ACCOUNT_ID`) on a root that has no default account, creates an
account labelled `default` and makes it the default.

### Using the TUI via SSH

- Run the TUI as the user that runs the listener, so that it opens the same
  root, and name the account.
- Without an interface, `python -m src.main` starts the `default_interface` of
  the account's configuration, else the GUI if PySide6 is installed, else the
  TUI.

```bash
ssh user@server
cd /var/www/voice
sudo -u voicesync -H .venv/bin/python -m src.main -a <label> tui
```

### Running as a Service

Create user:
```bash
sudo useradd --system --create-home --home-dir /var/www/voice --shell /bin/bash voicesync
sudo chown -R voicesync:voicesync /var/www/voice
```

The root is then `/var/www/voice/.config/voice`.

Create a systemd service file at `/etc/systemd/system/voicesync.service` (the
repository contains no unit file):
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

Open the port devices connect to in the firewall (8384/tcp, or 443 for a
reverse proxy); see [SECURITY-CONSIDERATIONS.md](SECURITY-CONSIDERATIONS.md#firewall).

Access Voice data with sudo. The root holds the machine's `config.json`,
`accounts.db`, `certs/` and `backups/`; each account is a directory named by
its id, `<account id>/`, with its `notes.db`, `config.json`, `audio/`,
`snapshots/`, `voice.log` and `audit.log` (`voice cli account list` shows the
ids):
```bash
sudo -u voicesync vim /var/www/voice/.config/voice/config.json
sudo -u voicesync sqlite3 /var/www/voice/.config/voice/<account id>/notes.db
```

Access Voice data as the logged-in user without sudo. This gives the
`voicesync` group every account's device key (in `<account id>/config.json`)
and the certificate's private key:
```bash
sudo usermod -aG voicesync $USER
sudo chmod -R g+rw /var/www/voice/.config/voice/
vim /var/www/voice/.config/voice/config.json
sqlite3 /var/www/voice/.config/voice/<account id>/notes.db
```

## Testing

The test suite, how to run each part, what it needs (the core's Python module
built with `maturin develop --release`, moto for the S3 tests) and the rules
every test follows are in [TESTING.md](TESTING.md). In short:

```bash
cd ~/Projects/VoiceFamily/Voice
.venv/bin/python -m pytest                      # the whole desktop suite
.venv/bin/python -m pytest tests/sync           # one directory
cd submodules/voicecore && cargo test           # the core
```

A test never runs against live data: every test works in a temporary
configuration root, never in `~/.config/voice` (`../TECHNICAL-DECISIONS.md` 7.6).

### Driving the Android app from a computer (ADB)

The debug build of VoiceAndroid accepts user actions as explicit broadcasts to
`com.dotancohen.voiceandroid/.automation.AdbCommandReceiver`, so a manual test
plan can script the phone. `~/Projects/VoiceFamily/VoiceAndroid/tools/voice-adb`
sends the broadcast and prints the app's reply, which contains `OK` or `ERROR`:

```bash
voice-adb ping                          # PING OK pong device=<name> id=<id>
voice-adb use-code 'voice://pair?...'   # pair with the device that showed the code
voice-adb exchange                      # sync, then send and fetch recordings, with the last device
voice-adb sync <device id>                # Notes only, with that device
voice-adb create-note "פתק מהטלפון"     # CREATE_NOTE OK id=01a0...
voice-adb list-notes                    # one NOTE {...} JSON line per note, with media state and conflicts
voice-adb import-audio /storage/emulated/0/voice-testing/VoiceTestStorage
voice-adb open settings                 # opens the app on a screen for steps done by hand
voice-adb set-recording-format opus     # opus (default), opus32, aac or wav16
voice-adb merge-notes <note>,<note>     # merge them into the oldest one
voice-adb transcribe <note> he all      # transcribe every recording of the note, one at a time
voice-adb help                          # the full list
```

`voice-adb` acts on whichever phone `adb` reaches; with two phones connected it
fails, which is intended. Release builds and the `.uitest` build do not contain
the receiver. The manual test plans that use it are in `../test-plans/`; read
their `README.md` first, because the owner's own phone must never be driven by
them.

## Development

### Type Checking

```bash
mypy src/
```

### Code Formatting

```bash
black src/
```

# Claude Code instructions for Voice (desktop and server)

Read `../CLAUDE.md` first: the rules there (tests, naming, the owner's data,
violation logging, data loss, the three checkouts of the core, documentation)
apply here too. The core's own instructions are in `../VoiceCore/CLAUDE.md`,
and `MAINTAINER-GUIDE.md` in this directory is a map of this project's code.

## Project structure

- `src/main.py` — the entry point; `src/cli.py` the command line; `src/web.py`
  the Web API; `src/tui.py` the text interface; `src/ui/` the GUI; `src/core/`
  logic shared by the four interfaces.
- `rust/voice-python/` — the PyO3 bindings of the core, built as the Python
  module `voicecore`.
- `submodules/voicecore` — the core, a submodule checkout of `VoiceCore`
  (`../CLAUDE.md`, "One core, three binding layers").
- `tests/` — the test suite (`TESTING.md`).

### Building the Python bindings

Always run maturin from `rust/voice-python/`, not from the repository root:

```bash
cd /home/dotancohen/Projects/VoiceFamily/Voice/rust/voice-python
/home/dotancohen/Projects/VoiceFamily/Voice/.venv/bin/maturin develop --release
```

This rebuilds the core **without** the `uniffi` feature into the shared
`VoiceFamily/.cargo-target/release/libvoicecore.so`; generate the phone's Kotlin
bindings before running it, or force the featured build first
(`../VoiceAndroid/CLAUDE.md`).

**The collision works the other way too.** The core crate and this crate both
name their library `voicecore`, so cargo writes both to that one
`release/libvoicecore.so` (cargo warns: "has the same output filename"). After
a phone build, `maturin develop` has copied the phone's library into the
virtual environment and still printed `Installed voice-python`; every desktop
interface and every test then fails at import with
`dynamic module does not define module export function (PyInit_voicecore)`.
After maturin, check the installed file before anything else:

```bash
cd /home/dotancohen/Projects/VoiceFamily/Voice
nm -D --defined-only .venv/lib/python3.12/site-packages/voicecore/voicecore.cpython-312-x86_64-linux-gnu.so | grep -c PyInit_voicecore
```

It must print 1. If it prints 0, `touch rust/voice-python/src/lib.rs` and run
maturin again from `rust/voice-python/`.

### Running the core's tests

```bash
cd /home/dotancohen/Projects/VoiceFamily/Voice/submodules/voicecore
cargo test
```

## UI frameworks

### Desktop GUI

The desktop GUI uses **Qt** through PySide6:

- `src/ui/main_window.py` — the main window, its menus and its three panes
- `src/ui/` — the panes, dialogs and widgets

### Desktop TUI

The text interface uses **Textual**:

- `src/tui.py` — the TUI application, its screens and widgets

## Common commands

`bin/voice` wraps `.venv/bin/python -m src.main`. `VOICE_CONFIG_DIR` names the
configuration root (default `~/.config/voice`) and `-a <id or label>` (or
`VOICE_ACCOUNT_ID`) the account under it. Every run prints
`Using CONFIG_DIR: ...` first (to stderr for JSON and CSV output). Tests that
count or compare stdout lines must skip that line.

**Never run these against `~/.config/voice` while working**: that is the
owner's live data. Point `VOICE_CONFIG_DIR` at a temporary directory.

```bash
# Run the CLI
.venv/bin/python -m src.main cli <command>

# Run the GUI
.venv/bin/python -m src.main gui

# Run the TUI
.venv/bin/python -m src.main tui

# Run the sync server
.venv/bin/python -m src.main cli sync serve --verbose

# Sync with every peer, or with one
.venv/bin/python -m src.main cli sync now [--peer <peer id>]

# Run the Python tests
.venv/bin/python -m pytest
```

## Documentation requirements

When changing any structured interface, the documentation changes in the same
change. This project's documents: `README.md` says what VOICE is and why,
`USER_MANUAL.md` how it is used (every interface, every setting),
`DEVELOPMENT.md` how to install, build, deploy and test it, `TESTING.md` the
test suite, `CONFIGURATION.md` the configuration files,
`CLOUD-STORAGE-SETUP.md` the bucket by hand, `SECURITY-CONSIDERATIONS.md`
exposing a server. Put a change where its reader is, not where the text used to
live. Documents about more than this project are in `..` (`../CLAUDE.md`).

### CLI changes

- Add new commands and options to `USER_MANUAL.md` in the right section.
- Update the `--help` text in `src/cli.py` (argparse help strings).
- For sync commands, update "Syncing between installations" and any
  troubleshooting section.
- Check whether a manual test plan in `../test-plans/` uses the command.

### Sync protocol changes

- Update `submodules/voicecore/README.md` (in `VoiceCore`) with new endpoints and
  request and response formats.
- Document new entity types in its sync protocol section, and the rule in
  `../SYNC_SPECIFICATION.md`.
- Update the change format example if fields change.

### Web API changes

- Update the Web API section of `USER_MANUAL.md`.
- Update the docstring in `src/web.py`.
- Include example `curl` commands.

### Configuration changes

- Update the configuration table of `USER_MANUAL.md`.
- Update `CONFIGURATION.md`.
- Update the example JSON snippets.

# VOICE: The Very Organized Information Capture Engine

- The Problem: Voice notes are a fast, effective way to _temporarily_ record information on the go, but are near impossible to actually work with in their raw format.
- The Solution: VOICE provides the tools to transform data stuck in voice notes into plain text that can be used in Actionable Items, Calendars, Data Stores, or just Archived.

**How to use it is in the [user manual](USER_MANUAL.md); how to install and
build it is in [DEVELOPMENT.md](DEVELOPMENT.md).**

## Everything runs on your own machines

There is no company between you and your notes, and no part of VOICE needs an
account or an internet connection:

- **Transcription runs locally.** Whisper models on your own machine, with no
  API key, no per-minute charge, and no recording uploaded to anybody's
  service. Online services are supported for those who want them, and are
  never the only way to get text out of a recording.
- **The database is a SQLite file** in your own directory, and the recordings
  are ordinary audio files beside it. Nothing is locked in an application's
  private store.
- **Syncing is between your own installations**, over a server you run — a
  laptop, a phone and a home server keeping each other up to date, with no
  third party in the middle and no central account.
- **Nothing is lost quietly.** Deleted notes wait in a trash bin, every edit
  keeps its history, and two installations that changed the same note both
  keep what they wrote rather than the later one winning.
- **Cloud storage for the audio is optional**, off by default, and your own
  bucket when it is on.

## Major Features

- Note-taking application with hierarchical tags.
- Sync notes between instances - fully decentralized self-hosted service.
- GUI, TUI, CLI, and Web API interfaces.
- Voice note transcription using local Whisper AI models and many online services.
- An [Android application](https://github.com/dotancohen/VoiceAndroid) that
  records, transcribes and syncs the same notes.

### GUI

- Designed for finding information quickly, via tags and search.
- Full keyboard control and mouse control.
- RTL text support.
- Dark and light themes.

### TUI

- Designed for finding information quickly, via tags and search.
- Full keyboard control and mouse control.
- RTL text support.
- Usable over SSH, so a server's notes are reachable from anywhere.

### CLI

- Fully scriptable with JSON or CSV output.

### Web API

- RESTful HTTP API with JSON responses.

## Additional Features

- Merge Notes
- Compare transcriptions across providers
- Trash bin: deleted notes are recoverable, and can be removed for good
- Transcriptions carry their own state: original, verified, verbatim, cleaned
  or polished, so it is always clear what has been done to a piece of text
- Compare what different services made of the same recording, side by side
- Times are shown as the clock read where they happened, so a note made at
  15:20 in Jerusalem still reads 15:20 from anywhere

## Roadmap

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
- Whisper GGML model files (for transcription) — see [Transcription](USER_MANUAL.md#transcription) in the user manual

## More

- **[User manual](USER_MANUAL.md)** — the four interfaces, screen by screen
  and command by command.
- **[Building and hacking](DEVELOPMENT.md)** — installing from source, the
  architecture, the sync server, and the tests.

## Authorship

- Written by [Dotan Cohen](https://dotancohen.com).
- Extensive help, especially with writing the test suite and Rust components, attributed to Anthropic Claude via Claude Code.

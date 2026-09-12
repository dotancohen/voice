# Manual test plans

Step-by-step plans for a tester who has:

- **Desktop**: a Linux machine with the Voice repository, used for the GUI, the TUI and the CLI.
- **Server**: a Linux machine reachable by SSH, used to run the shared sync server and the TUI.
- **Android**: a phone with the VoiceAndroid debug build installed.
- **iPhone**: not available yet. Steps marked *(iPhone)* are placeholders for when a client exists.

Plans:

| File | What it covers |
|------|----------------|
| `01-syncing.md` | Syncing notes, tags, settings and audio files between all devices; conflicts; outages; large data; clocks; history |

## Conventions used in every plan

- Each step has an **Expected** line. Tick the step only if it matched. If it did not, copy the exact text on screen, the command output, and the relevant part of the log into the results sheet at the end of the plan.
- `Desktop$`, `Server$` and `Android:` show where a step happens. `Desktop$` and `Server$` lines are shell commands, run from the Voice repository directory. `Android:` lines describe taps in the app.
- `<note-id>`, `<peer-id>` and similar placeholders stand for the 32-character hex ids printed by earlier steps. The CLI accepts a unique prefix (the first 8 characters are enough).
- Hebrew text is used on purpose: the application is Hebrew-first. Type the Hebrew exactly as written (copy and paste is fine).
- Logs: on Desktop and Server the application writes `~/.config/voice/voice.log`; the sync server prints requests when started with `--verbose`; on Android use **Settings → View Log**.

## Before every session

```bash
# Desktop and Server: make sure the build is current
cd ~/Projects/VoiceFamily/Voice
git status                 # note the commit you are testing
.venv/bin/python -m src.main cli --help | head -3
```

Write the commit hash, the date, and your name at the top of the results sheet.

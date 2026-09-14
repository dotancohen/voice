# Voice Tools

Stand-alone scripts beside the application. Run them from the repository's
root directory, with the virtual environment active.

## Overview

| Tool | What it does | State |
|------|--------------|-------|
| `batch_transcribe.py` | Runs a transcription for every recording that has none | Does not work with the current CLI |
| `migrate_from_classic.py` | Writes SQL that copies a Voice Classic database into a Voice database | The SQL does not fit the current database |

For transcribing many recordings, the CLI itself has `transcribe-backlog` and
`transcription-queue`; see the [user manual](../USER_MANUAL.md).

## batch_transcribe.py

```bash
python -m tools.batch_transcribe [--dry-run] [--language LANG] [--model MODEL] [--speaker-count N] <database file or directory>
```

It opens the database file, or `database.sqlite` inside the directory given,
lists the recordings without a transcription, and for each one runs
`python -m src.main -d <directory> cli transcribe-audiofile <id>`. `--dry-run`
lists them and runs nothing.

The current program has neither of those: there is no `-d` option (the account
is chosen with `-a`, the root with `VOICE_CONFIG_DIR`), the command is named
`audiofile-transcribe`, and the database file is `notes.db`. Every transcription
that the script starts therefore fails.

## migrate_from_classic.py

```bash
python -m tools.migrate_from_classic <classic database> [-o migration.sql] [-v]
```

It reads a Voice Classic SQLite database and writes SQL statements to standard
output, or to the file given with `-o`. `-v` prints progress to standard error.
Each Classic recording becomes a note, an audio file, the attachment between
them and, when it had text, a transcription; tags, the recordings' tags, and
stars (as the `_marked` tag) are copied as well.

The SQL was written for an earlier database. Checked against the current one:

- the `audio_files` rows it inserts have no `device_id`, a column that may not
  be empty;
- its ids for the `_system` and `_marked` tags are 33 hexadecimal characters,
  not the 32 of `a1b2c3d4-0000-5000-8000-000000000001` and `…0002` in voicecore;
- its help tells you to copy recordings as `<audio file id>.<ext>`, while
  Voice names them `<YYYY_MM_DD_HH_MM_SS>-<end of the id>.<ext>`.

Do not run its output against a database you need. If you try it, run
`python -m src.main cli account snapshot` first.

## Hebrew transcription training

Fine-tuning Whisper models is not part of this repository. These pages explain
it:

- [Fine Tune Whisper the Right Way - ivrit.ai](https://www.ivrit.ai/en/2025/02/13/training-whisper/)
- [Fine-Tune Whisper For Multilingual ASR - Hugging Face](https://huggingface.co/blog/fine-tune-whisper)
- [ivrit.ai Models on HuggingFace](https://huggingface.co/ivrit-ai)

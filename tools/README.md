# Voice Tools

Command-line utilities for the Voice application.

## Overview

| Tool | Description |
|------|-------------|
| `batch_transcribe.py` | Batch transcribe multiple audio files |
| `migrate_from_classic.py` | Migrate data from Voice Classic database |

## Hebrew Transcription Training

For fine-tuning Hebrew transcription models on your Voice notes, see the `train_hebrew.py` tool in the [VoiceTranscription](https://github.com/dotancohen/VoiceTranscription) project. That tool can read from your Voice database and train on notes filtered by tag.

## batch_transcribe.py

Batch transcribe multiple audio files at once.

```bash
python -m tools.batch_transcribe --help
```

## migrate_from_classic.py

Migrate data from Voice Classic SQLite database to the new format.

```bash
python -m tools.migrate_from_classic --source voice-classic.db --target ~/.config/voice/notes.db
```

## References

- [Fine Tune Whisper the Right Way - ivrit.ai](https://www.ivrit.ai/en/2025/02/13/training-whisper/)
- [Fine-Tune Whisper For Multilingual ASR - Hugging Face](https://huggingface.co/blog/fine-tune-whisper)
- [ivrit.ai Models on HuggingFace](https://huggingface.co/ivrit-ai)

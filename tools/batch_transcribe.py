#!/usr/bin/env python3
"""Batch transcribe all audio files without transcriptions.

This script finds all audio files in the database that don't have any
transcriptions and runs the `cli transcribe-audiofile` command on each one.

Usage:
    python tools/batch_transcribe.py /path/to/database.sqlite
    python tools/batch_transcribe.py /path/to/data_dir  # Uses data_dir/database.sqlite

Options:
    --dry-run       Show what would be transcribed without actually running
    --language      Language hint (ISO 639-1 code, e.g., 'en', 'he')
    --model         Model name (e.g., 'small', 'large-v3')
    --speaker-count Expected number of speakers
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any

# Length of short UUID display (same as src.core.models.UUID_SHORT_LEN)
UUID_SHORT_LEN = 12


def find_audio_files_without_transcriptions(db_path: Path) -> List[Dict[str, Any]]:
    """Find all audio files that don't have any transcriptions.

    Args:
        db_path: Path to the SQLite database file

    Returns:
        List of audio file dicts without transcriptions
    """
    # Import here to avoid requiring the module at the top level
    # Add the Voice project root to the path
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from src.core.database import Database

    db = Database(db_path)
    try:
        all_audio_files = db.get_all_audio_files()
        result = []

        for audio_file in all_audio_files:
            audio_id = audio_file.get("id", "")
            transcriptions = db.get_transcriptions_for_audio_file(audio_id)
            if not transcriptions:
                result.append(audio_file)

        return result
    finally:
        db.close()


def transcribe_audio_file(
    data_dir: Path,
    audio_id: str,
    language: str | None = None,
    model: str | None = None,
    speaker_count: int | None = None,
) -> subprocess.CompletedProcess:
    """Run the transcribe-audiofile CLI command.

    Args:
        data_dir: Path to the data directory (parent of database.sqlite)
        audio_id: Audio file UUID hex string
        language: Optional language hint
        model: Optional model name
        speaker_count: Optional expected number of speakers

    Returns:
        CompletedProcess result from subprocess.run
    """
    cmd = [
        sys.executable, "-m", "src.main",
        "-d", str(data_dir),
        "cli", "transcribe-audiofile", audio_id
    ]

    if language:
        cmd.extend(["--language", language])
    if model:
        cmd.extend(["--model", model])
    if speaker_count is not None:
        cmd.extend(["--speaker-count", str(speaker_count)])

    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Batch transcribe audio files without transcriptions"
    )
    parser.add_argument(
        "database_path",
        type=Path,
        help="Path to database.sqlite or data directory containing it"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be transcribed without actually running"
    )
    parser.add_argument(
        "--language",
        type=str,
        help="Language hint (ISO 639-1 code, e.g., 'en', 'he')"
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Model name (e.g., 'small', 'large-v3')"
    )
    parser.add_argument(
        "--speaker-count",
        type=int,
        help="Expected number of speakers"
    )

    args = parser.parse_args()

    # Resolve database path
    db_path = args.database_path.resolve()
    if db_path.is_dir():
        db_path = db_path / "database.sqlite"

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        return 1

    data_dir = db_path.parent

    # Find audio files without transcriptions
    print(f"Scanning database: {db_path}")
    audio_files = find_audio_files_without_transcriptions(db_path)

    if not audio_files:
        print("No audio files found without transcriptions.")
        return 0

    print(f"Found {len(audio_files)} audio file(s) without transcriptions:")
    for af in audio_files:
        audio_id = af.get("id", "unknown")
        filename = af.get("filename", "unknown")
        print(f"  {audio_id[:UUID_SHORT_LEN]}... | {filename}")

    if args.dry_run:
        print("\nDry run - no transcriptions performed.")
        return 0

    print(f"\nTranscribing {len(audio_files)} audio file(s)...")

    success_count = 0
    error_count = 0

    for i, af in enumerate(audio_files, 1):
        audio_id = af.get("id", "")
        filename = af.get("filename", "unknown")
        print(f"\n[{i}/{len(audio_files)}] Transcribing {filename}...")

        result = transcribe_audio_file(
            data_dir=data_dir,
            audio_id=audio_id,
            language=args.language,
            model=args.model,
            speaker_count=args.speaker_count,
        )

        if result.returncode == 0:
            print(f"  Success!")
            if result.stdout.strip():
                # Print first few lines of output
                lines = result.stdout.strip().split("\n")
                for line in lines[:3]:
                    print(f"    {line}")
                if len(lines) > 3:
                    print(f"    ... ({len(lines) - 3} more lines)")
            success_count += 1
        else:
            print(f"  Error (exit code {result.returncode})")
            if result.stderr.strip():
                for line in result.stderr.strip().split("\n")[:5]:
                    print(f"    {line}")
            error_count += 1

    print(f"\nCompleted: {success_count} succeeded, {error_count} failed")
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

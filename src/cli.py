#!/usr/bin/env python3
"""Command-line interface for Voice.

This module provides CLI commands for interacting with notes and tags.
Uses only core/ modules - no Qt/PySide6 dependencies.

Commands:
    notes-list              List all notes
    note-show <id>          Show details of a specific note
    note-create [content]   Create a new note
    note-edit <id> [content] Edit an existing note
    notes-merge <id1> <id2> Merge two notes into one
    tags-list               List all tags in hierarchy
    notes-search            Search notes by text and/or tags
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.audiofile_manager import AudioFileManager, is_supported_audio_format
from src.core.config import Config
from src.core.conflicts import ConflictManager, ResolutionChoice
from src.core.database import Database
from src.core.models import AUDIO_FILE_FORMATS
from src.core.search import resolve_tag_term
from voicecore import SyncClient, sync_all_peers, start_sync_server
from src.core.validation import ValidationError


def format_tag_hierarchy(tags: List[Dict[str, Any]], indent: int = 0) -> str:
    """Format tags as indented hierarchy.

    Args:
        tags: List of tag dictionaries
        indent: Current indentation level

    Returns:
        Formatted string representation of tag hierarchy
    """
    lines: List[str] = []

    # Group tags by parent_id
    tags_by_parent: Dict[Optional[int], List[Dict[str, Any]]] = {}
    for tag in tags:
        parent_id = tag.get("parent_id")
        if parent_id not in tags_by_parent:
            tags_by_parent[parent_id] = []
        tags_by_parent[parent_id].append(tag)

    def add_tag_and_children(tag_id: Optional[int], current_indent: int) -> None:
        """Recursively add tag and its children."""
        if tag_id not in tags_by_parent:
            return

        for tag in sorted(tags_by_parent[tag_id], key=lambda t: t["name"]):
            prefix = "  " * current_indent
            lines.append(f"{prefix}{tag['name']} (ID: {tag['id']})")
            # Add children
            add_tag_and_children(tag["id"], current_indent + 1)

    # Start with root tags (parent_id is None)
    add_tag_and_children(None, indent)

    return "\n".join(lines)


def format_note(note: Dict[str, Any], format_type: str = "text") -> str:
    """Format a single note for display.

    Args:
        note: Note dictionary from database
        format_type: Output format (text, json, csv)

    Returns:
        Formatted note string
    """
    if format_type == "json":
        return json.dumps(note, indent=2, ensure_ascii=False)
    elif format_type == "csv":
        # Simple CSV format: id,created_at,content,tags
        content = note["content"].replace('"', '""')  # Escape quotes
        tags = note.get("tag_names", "")
        return f'{note["id"]},"{note["created_at"]}","{content}","{tags}"'
    else:  # text
        lines = [
            f"ID: {note['id']}",
            f"Created: {note['created_at']}",
        ]
        if note.get("modified_at"):
            lines.append(f"Modified: {note['modified_at']}")
        if note.get("tag_names"):
            lines.append(f"Tags: {note['tag_names']}")
        lines.append(f"\n{note['content']}")
        return "\n".join(lines)


def cmd_list_notes(db: Database, args: argparse.Namespace) -> int:
    """List all notes.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success)
    """
    notes = db.get_all_notes()

    if args.format == "json":
        print(json.dumps(notes, indent=2, ensure_ascii=False))
    elif args.format == "csv":
        print("id,created_at,content,tags")
        for note in notes:
            print(format_note(note, "csv"))
    else:  # text
        if not notes:
            print("No notes found.")
            return 0

        for note in notes:
            # Get first non-blank line of content, up to 100 chars
            content = note["content"]
            # Remove blank lines and get first line
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            first_line = lines[0] if lines else ""
            if len(first_line) > 100:
                first_line = first_line[:100] + "..."

            # Format: ID | Created | Content
            print(f"{note['id']} | {note['created_at']} | {first_line}")

    return 0


def cmd_show_note(db: Database, args: argparse.Namespace) -> int:
    """Show details of a specific note.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for not found)
    """
    note_id = args.note_id

    # VoiceCore handles UUID prefix resolution internally
    try:
        note = db.get_note(note_id)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not note:
        print(f"Error: Note with ID {note_id} not found.", file=sys.stderr)
        return 1

    print(format_note(note, args.format))
    return 0


def cmd_new_note(db: Database, args: argparse.Namespace) -> int:
    """Create a new note.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success)
    """
    # Get content from argument or stdin
    if args.content:
        content = args.content
    elif not sys.stdin.isatty():
        # Read from stdin if piped
        content = sys.stdin.read().strip()
    else:
        # No content provided - create empty note
        content = ""

    try:
        note_id = db.create_note(content)
        if args.format == "json":
            print(json.dumps({"id": note_id, "content": content}))
        else:
            print(f"Created note #{note_id}")
        return 0
    except ValidationError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1


def cmd_edit_note(db: Database, args: argparse.Namespace) -> int:
    """Edit an existing note.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    # Check if note exists
    note = db.get_note(args.note_id)
    if not note:
        print(f"Error: Note with ID {args.note_id} not found.", file=sys.stderr)
        return 1

    # Get new content from argument or stdin
    if args.content:
        content = args.content
    elif not sys.stdin.isatty():
        # Read from stdin if piped
        content = sys.stdin.read().strip()
    else:
        print("Error: No content provided. Use --content or pipe content to stdin.", file=sys.stderr)
        return 1

    if not content:
        print("Error: Content cannot be empty.", file=sys.stderr)
        return 1

    try:
        db.update_note(args.note_id, content)
        if args.format == "json":
            print(json.dumps({"id": args.note_id, "content": content, "updated": True}))
        else:
            print(f"Updated note #{args.note_id}")
        return 0
    except ValidationError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1


def cmd_merge_notes(db: Database, args: argparse.Namespace) -> int:
    """Merge two notes into one.

    The note with the earlier created_at timestamp survives.
    Content is concatenated with a separator line.
    Tags and attachments are moved from the deleted note.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        survivor_id = db.merge_notes(args.note_id_1, args.note_id_2)

        # Get the merged note to display
        merged_note = db.get_note(survivor_id)
        if not merged_note:
            print(f"Error: Could not retrieve merged note.", file=sys.stderr)
            return 1

        if args.format == "json":
            print(json.dumps({
                "survivor_id": survivor_id,
                "deleted_id": args.note_id_2 if survivor_id == args.note_id_1 else args.note_id_1,
                "content": merged_note.get("content", ""),
                "tags": merged_note.get("tag_names", ""),
            }))
        else:
            deleted_id = args.note_id_2 if survivor_id == args.note_id_1 else args.note_id_1
            print(f"Merged notes into #{survivor_id[:8]}...")
            print(f"Deleted note #{deleted_id[:8]}...")
            print()
            content = merged_note.get("content", "")
            if content:
                print("Content:")
                print(content[:500] + ("..." if len(content) > 500 else ""))
        return 0
    except ValidationError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1


def cmd_list_tags(db: Database, args: argparse.Namespace) -> int:
    """List all tags in hierarchy.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success)
    """
    tags = db.get_all_tags()

    if args.format == "json":
        print(json.dumps(tags, indent=2, ensure_ascii=False))
    elif args.format == "csv":
        print("id,name,parent_id")
        for tag in tags:
            parent_id = tag.get("parent_id", "")
            print(f'{tag["id"]},{tag["name"]},{parent_id}')
    else:  # text
        if not tags:
            print("No tags found.")
            return 0
        print(format_tag_hierarchy(tags))

    return 0


def cmd_search(db: Database, args: argparse.Namespace) -> int:
    """Search notes by text and/or tags.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success)
    """
    # Build tag_id_groups from tag paths using the search module
    tag_id_groups: List[List[int]] = []
    any_tag_not_found = False

    if args.tags:
        for tag_path in args.tags:
            tag_ids, is_ambiguous, not_found = resolve_tag_term(db, tag_path)

            if not_found:
                print(f"Warning: Tag '{tag_path}' not found.", file=sys.stderr)
                any_tag_not_found = True
            else:
                tag_id_groups.append(tag_ids)
                if is_ambiguous:
                    print(f"Warning: Tag '{tag_path}' is ambiguous - matching multiple tags (using OR logic)", file=sys.stderr)

    # If any requested tag was not found, return empty results
    if any_tag_not_found:
        notes: List[Dict[str, Any]] = []
    else:
        # Perform search
        notes = db.search_notes(
            text_query=args.text if args.text else None,
            tag_id_groups=tag_id_groups if tag_id_groups else None
        )

    if args.format == "json":
        print(json.dumps(notes, indent=2, ensure_ascii=False))
    elif args.format == "csv":
        print("id,created_at,content,tags")
        for note in notes:
            print(format_note(note, "csv"))
    else:  # text
        if not notes:
            print("No notes found matching search criteria.")
            return 0

        print(f"Found {len(notes)} note(s):\n")
        for i, note in enumerate(notes):
            if i > 0:
                print("\n" + "=" * 60 + "\n")
            print(format_note(note, "text"))

    return 0


def cmd_import_audiofiles(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Import audio files from a directory.

    For each valid audio file:
    1. Validate format (mp3, wav, flac, ogg, opus, m4a)
    2. Get file_created_at from filesystem metadata
    3. Create Note with content="Audio: {filename}", created_at=file_created_at
    4. Create AudioFile record
    5. Copy file to {audiofile_directory}/{uuid}.{ext}

    Args:
        db: Database instance
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    # Check audiofile_directory is configured
    audiofile_dir = config.get_audiofile_directory()
    if not audiofile_dir:
        print("Error: audiofile_directory not configured.")
        print("Run: voice config set audiofile_directory /path/to/audio/files")
        return 1

    source_dir = Path(args.directory)
    if not source_dir.exists():
        print(f"Error: Directory not found: {source_dir}")
        return 1

    if not source_dir.is_dir():
        print(f"Error: Not a directory: {source_dir}")
        return 1

    manager = AudioFileManager(audiofile_dir)

    # Find audio files
    if args.recursive:
        files = list(source_dir.rglob("*"))
    else:
        files = list(source_dir.iterdir())

    audio_files = [f for f in files if f.is_file() and is_supported_audio_format(f.name)]

    if not audio_files:
        print(f"No supported audio files found in {source_dir}")
        print(f"Supported formats: {', '.join(sorted(AUDIO_FILE_FORMATS))}")
        return 0

    imported = 0
    errors = 0

    for audio_path in audio_files:
        try:
            # Get file extension
            ext = manager.get_extension_from_filename(audio_path.name)
            if not ext:
                print(f"  Skipping (no valid extension): {audio_path.name}")
                continue

            # Get file creation time
            file_created_at = manager.get_file_created_at(audio_path)
            file_created_at_str = file_created_at.strftime("%Y-%m-%d %H:%M:%S") if file_created_at else None

            # Create AudioFile record in database
            audio_file_id = db.create_audio_file(audio_path.name, file_created_at_str)

            # Copy file to audiofile_directory
            manager.import_file(audio_path, audio_file_id, ext)

            # Create Note with audio reference
            # Use file_created_at for note's created_at for chronological sorting
            note_content = f"Audio: {audio_path.name}"

            if file_created_at_str:
                # Use apply_sync_note to create note with the correct created_at
                # Generate a new UUID7 for the note
                from uuid6 import uuid7
                note_uuid = uuid7()
                note_id = note_uuid.hex
                db.apply_sync_note(note_id, file_created_at_str, note_content, None, None)
            else:
                # No file timestamp, use current time
                note_id = db.create_note(note_content)

            # Attach audio file to note
            db.attach_to_note(note_id, audio_file_id, "audio_file")

            # Attach tags if specified
            if args.tags:
                for tag_id in args.tags:
                    try:
                        db.add_tag_to_note(note_id, tag_id)
                    except Exception as tag_error:
                        print(f"  Warning: Could not attach tag {tag_id}: {tag_error}")

            print(f"  Imported: {audio_path.name} -> {audio_file_id[:8]}...")
            imported += 1

        except Exception as e:
            print(f"  Error importing {audio_path.name}: {e}")
            errors += 1

    print(f"\nImported {imported} file(s), {errors} error(s)")
    return 0 if errors == 0 else 1


def cmd_list_audiofiles(db: Database, config: Config, args: argparse.Namespace) -> int:
    """List audio files.

    Args:
        db: Database instance
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success)
    """
    if args.note_id:
        # List audio files for a specific note
        audio_files = db.get_audio_files_for_note(args.note_id)
        if not audio_files:
            print(f"No audio files attached to note {args.note_id}")
            return 0

        print(f"Audio files for note {args.note_id}:\n")
    else:
        # List all audio files - we need to query all notes and their attachments
        # For now, we'll just say this is not fully implemented
        print("Listing all audio files requires --note-id parameter.")
        print("Use: voice cli note-audiofiles-list --note-id <note_id>")
        return 0

    for af in audio_files:
        print(f"ID: {af['id'][:8]}...")
        print(f"  Filename: {af['filename']}")
        print(f"  Imported: {af['imported_at']}")
        if af.get('file_created_at'):
            print(f"  File created: {af['file_created_at']}")
        if af.get('summary'):
            print(f"  Summary: {af['summary']}")
        print()

    return 0


def cmd_show_audiofile(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Show details of an audio file.

    Args:
        db: Database instance
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for not found)
    """
    audio_file = db.get_audio_file(args.audio_id)
    if not audio_file:
        print(f"Audio file not found: {args.audio_id}")
        return 1

    print(f"ID: {audio_file['id']}")
    print(f"Filename: {audio_file['filename']}")
    print(f"Imported: {audio_file['imported_at']}")
    if audio_file.get('file_created_at'):
        print(f"File created: {audio_file['file_created_at']}")
    if audio_file.get('summary'):
        print(f"Summary: {audio_file['summary']}")
    if audio_file.get('modified_at'):
        print(f"Modified: {audio_file['modified_at']}")
    if audio_file.get('deleted_at'):
        print(f"Deleted: {audio_file['deleted_at']}")

    # Show file location
    audiofile_dir = config.get_audiofile_directory()
    if audiofile_dir:
        manager = AudioFileManager(audiofile_dir)
        ext = manager.get_extension_from_filename(audio_file['filename'])
        if ext:
            file_path = manager.get_file_path(audio_file['id'], ext)
            if file_path:
                print(f"File path: {file_path}")
            else:
                print("File path: (file not found on disk)")

    return 0


def _transcribe_audio_file(
    db: Database,
    config: Config,
    audio_file_id: str,
    language: Optional[str] = None,
    speaker_count: Optional[int] = None,
    model: Optional[str] = None,
    backend: str = "local_whisper",
    api_key: Optional[str] = None,
    project_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Transcribe a single audio file.

    Args:
        db: Database instance
        config: Config instance
        audio_file_id: Audio file ID to transcribe
        language: Language hint (ISO 639-1 code)
        speaker_count: Expected number of speakers
        model: Model name (e.g., "small", "large-v3") or full path to model file
        backend: Transcription backend (local_whisper, assemblyai, google_cloud)
        api_key: API key for cloud backends
        project_id: Project ID for Google Cloud backend

    Returns:
        Transcription result dict or None on failure
    """
    try:
        from voice_transcription import TranscriptionClient, TranscriptionConfig
    except ImportError:
        print("Error: voice_transcription module not installed.", file=sys.stderr)
        print("Build it with: cd submodules/voicetranscription/bindings/python && maturin develop --features all_backends", file=sys.stderr)
        return None

    # Get audio file from database
    audio_file = db.get_audio_file(audio_file_id)
    if not audio_file:
        print(f"Audio file not found: {audio_file_id}", file=sys.stderr)
        return None

    # Get audio file path
    audiofile_dir = config.get_audiofile_directory()
    if not audiofile_dir:
        print("Error: audiofile_directory not configured.", file=sys.stderr)
        return None

    manager = AudioFileManager(audiofile_dir)
    ext = manager.get_extension_from_filename(audio_file['filename'])
    if not ext:
        print(f"Error: Cannot determine extension for {audio_file['filename']}", file=sys.stderr)
        return None

    file_path = manager.get_file_path(audio_file_id, ext)
    if not file_path:
        print(f"Error: Audio file not found on disk: {audio_file_id}", file=sys.stderr)
        return None

    # Get transcription config
    transcription_cfg = config.get_transcription_config()

    # Determine language
    if not language:
        preferred_langs = transcription_cfg.get("preferred_languages", [])
        if preferred_langs:
            language = preferred_langs[0]

    # Determine model path
    # Priority: 1) --model argument, 2) config, 3) auto-select
    model_path = None
    if model:
        # Check if it's a path or a model name
        if '/' in model or model.endswith('.bin'):
            model_path = model
        else:
            # It's a model name like "small" or "large-v3"
            # Look for it in the whisper directory
            from pathlib import Path
            whisper_dir = Path.home() / ".local" / "share" / "whisper"
            # Try with and without ggml- prefix
            candidates = [
                whisper_dir / f"ggml-{model}.bin",
                whisper_dir / f"{model}.bin",
            ]
            for candidate in candidates:
                if candidate.exists():
                    model_path = str(candidate)
                    break
            if not model_path:
                print(f"Error: Model '{model}' not found in {whisper_dir}", file=sys.stderr)
                print(f"Available models: {[f.name for f in whisper_dir.glob('ggml-*.bin')]}", file=sys.stderr)
                return None

    if not model_path:
        # Try config
        whisper_cfg = transcription_cfg.get("providers", {}).get("whisper", {})
        model_path = whisper_cfg.get("model_path")

    if not model_path:
        # Try to find a model in the default location
        from pathlib import Path
        import re
        whisper_dir = Path.home() / ".local" / "share" / "whisper"
        if whisper_dir.exists():
            # Model size priority (larger = better for multilingual)
            SIZE_PRIORITY = {
                'large': 5,
                'medium': 4,
                'small': 3,
                'base': 2,
                'tiny': 1,
            }

            def parse_model_name(path: Path) -> tuple:
                """Parse model name into (size_priority, version) for sorting.

                Examples:
                    ggml-large-v3.bin -> (5, 3)
                    ggml-large.bin -> (5, 0)
                    ggml-small.bin -> (3, 0)
                """
                name = path.stem.replace('ggml-', '')
                # Extract version if present (e.g., "large-v3" -> "large", 3)
                version_match = re.search(r'-v(\d+)$', name)
                if version_match:
                    version = int(version_match.group(1))
                    size = name[:version_match.start()]
                else:
                    version = 0
                    size = name
                size_priority = SIZE_PRIORITY.get(size, 0)
                return (size_priority, version)

            models = sorted(whisper_dir.glob("ggml-*.bin"), key=parse_model_name, reverse=True)
            if models:
                model_path = str(models[0])
            else:
                print("Error: No Whisper model found. Download one with:", file=sys.stderr)
                print("  wget -P ~/.local/share/whisper/ https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin", file=sys.stderr)
                return None
        else:
            print("Error: No Whisper model configured and no models found.", file=sys.stderr)
            return None

    # Create transcription client based on backend
    try:
        if backend == "local_whisper":
            # Expand ~ in model path
            model_path = str(Path(model_path).expanduser())
            client = TranscriptionClient.with_local_whisper(model_path)
            service = "local_whisper"

        elif backend == "assemblyai":
            # Get API key from argument, environment, or config
            key = api_key or os.environ.get("ASSEMBLYAI_API_KEY")
            if not key:
                transcription_cfg = config.get_transcription_config()
                key = transcription_cfg.get("providers", {}).get("assemblyai", {}).get("api_key")
            if not key:
                print("Error: AssemblyAI API key required. Use --api-key or set ASSEMBLYAI_API_KEY.", file=sys.stderr)
                return None
            client = TranscriptionClient.with_assemblyai(key)
            service = "assemblyai"
            model_path = None

        elif backend == "google_cloud":
            # Get access token from argument, gcloud, or config
            token = api_key
            if not token:
                # Try to get from gcloud
                import subprocess
                try:
                    result = subprocess.run(
                        ["gcloud", "auth", "print-access-token"],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    token = result.stdout.strip()
                except (subprocess.CalledProcessError, FileNotFoundError):
                    pass
            if not token:
                print("Error: Google Cloud access token required. Run 'gcloud auth login' or use --api-key.", file=sys.stderr)
                return None

            # Get project ID
            proj_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT")
            if not proj_id:
                transcription_cfg = config.get_transcription_config()
                proj_id = transcription_cfg.get("providers", {}).get("google_cloud", {}).get("project_id")
            if not proj_id:
                print("Error: Google Cloud project ID required. Use --project-id or set GOOGLE_CLOUD_PROJECT.", file=sys.stderr)
                return None

            client = TranscriptionClient.with_google_cloud(token, proj_id)
            service = "google_cloud"
            model_path = None

        else:
            print(f"Error: Unknown backend '{backend}'", file=sys.stderr)
            print("Available backends: local_whisper, assemblyai, google_cloud", file=sys.stderr)
            return None

    except Exception as e:
        print(f"Error creating transcription client: {e}", file=sys.stderr)
        return None

    # Create transcription config
    transcribe_config = TranscriptionConfig(
        language=language,
        speaker_count=speaker_count or 1,
        word_timestamps=False,
    )

    # Transcribe
    start_time = time.time()
    try:
        result = client.transcribe(str(file_path), transcribe_config)
    except Exception as e:
        print(f"Error transcribing {audio_file['filename']}: {e}", file=sys.stderr)
        return None
    elapsed_time = time.time() - start_time

    # Build service arguments JSON
    service_arguments = json.dumps({
        "language": language,
        "speaker_count": speaker_count or 1,
        "model_path": model_path,
    })

    # Build service response JSON
    service_response = json.dumps({
        "elapsed_time": round(elapsed_time, 3),
        "duration_seconds": result.duration_seconds,
        "confidence": result.confidence,
        "languages": result.languages,
        "speaker_count": result.speaker_count,
    })

    # Build content segments JSON
    content_segments = json.dumps([
        {
            "text": seg.text,
            "start_seconds": seg.start_seconds,
            "end_seconds": seg.end_seconds,
            "speaker": seg.speaker,
            "confidence": seg.confidence,
        }
        for seg in result.segments
    ])

    # Save to database
    transcription_id = db.create_transcription(
        audio_file_id=audio_file_id,
        content=result.content,
        service=service,
        content_segments=content_segments,
        service_arguments=service_arguments,
        service_response=service_response,
    )

    return {
        "transcription_id": transcription_id,
        "audio_file_id": audio_file_id,
        "content": result.content,
        "duration_seconds": result.duration_seconds,
        "languages": result.languages,
    }


def cmd_transcribe_audiofile(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Transcribe a single audio file.

    Args:
        db: Database instance
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    audio_file_id = args.audio_id
    language = getattr(args, 'language', None)
    speaker_count = getattr(args, 'speaker_count', None)
    model = getattr(args, 'model', None)
    backend = getattr(args, 'backend', 'local_whisper')
    api_key = getattr(args, 'api_key', None)
    project_id = getattr(args, 'project_id', None)

    result = _transcribe_audio_file(
        db, config, audio_file_id,
        language=language,
        speaker_count=speaker_count,
        model=model,
        backend=backend,
        api_key=api_key,
        project_id=project_id,
    )

    if not result:
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"Transcription ID: {result['transcription_id']}")
        print(f"Audio File: {audio_file_id[:8]}...")
        if result.get('duration_seconds'):
            print(f"Duration: {result['duration_seconds']:.1f}s")
        if result.get('languages'):
            print(f"Languages: {', '.join(result['languages'])}")
        print(f"\n{result['content']}")

    return 0


def cmd_transcribe_note(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Transcribe all audio files for a note.

    Args:
        db: Database instance
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    note_id = args.note_id
    language = getattr(args, 'language', None)
    speaker_count = getattr(args, 'speaker_count', None)
    model = getattr(args, 'model', None)
    backend = getattr(args, 'backend', 'local_whisper')
    api_key = getattr(args, 'api_key', None)
    project_id = getattr(args, 'project_id', None)

    # Get note to verify it exists
    note = db.get_note(note_id)
    if not note:
        print(f"Note not found: {note_id}", file=sys.stderr)
        return 1

    # Get audio files for note
    audio_files = db.get_audio_files_for_note(note_id)
    if not audio_files:
        print(f"No audio files attached to note {note_id}")
        return 0

    results = []
    errors = 0

    for audio_file in audio_files:
        print(f"Transcribing: {audio_file['filename']}...")
        result = _transcribe_audio_file(
            db, config, audio_file['id'],
            language=language,
            speaker_count=speaker_count,
            model=model,
            backend=backend,
            api_key=api_key,
            project_id=project_id,
        )

        if result:
            results.append(result)
        else:
            errors += 1

    if args.format == "json":
        print(json.dumps({
            "note_id": note_id,
            "transcriptions": results,
            "errors": errors,
        }, indent=2))
    else:
        print(f"\nTranscribed {len(results)} of {len(audio_files)} audio file(s)")
        if errors > 0:
            print(f"Errors: {errors}")

        for result in results:
            print(f"\n--- {result['audio_file_id'][:8]}... ---")
            print(result['content'])

    return 0 if errors == 0 else 1


def cmd_sync_status(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Show sync status and device information.

    Args:
        db: Database instance
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success)
    """
    device_id = config.get_device_id_hex()
    device_name = config.get_device_name()
    sync_config = config.get_sync_config()

    if args.format == "json":
        status = {
            "device_id": device_id,
            "device_name": device_name,
            "sync_enabled": sync_config.get("enabled", False),
            "server_port": sync_config.get("server_port", 8384),
            "peer_count": len(sync_config.get("peers", [])),
        }
        # Get conflict counts
        conflict_mgr = ConflictManager(db)
        status["conflicts"] = conflict_mgr.get_unresolved_count()
        print(json.dumps(status, indent=2))
    else:
        print(f"Device ID: {device_id}")
        print(f"Device Name: {device_name}")
        print(f"Sync Enabled: {sync_config.get('enabled', False)}")
        print(f"Server Port: {sync_config.get('server_port', 8384)}")
        print(f"Configured Peers: {len(sync_config.get('peers', []))}")

        # Show conflict counts
        conflict_mgr = ConflictManager(db)
        counts = conflict_mgr.get_unresolved_count()
        if counts["total"] > 0:
            print(f"\nUnresolved Conflicts: {counts['total']}")
            if counts["note_content"] > 0:
                print(f"  - Note content conflicts: {counts['note_content']}")
            if counts["note_delete"] > 0:
                print(f"  - Note delete conflicts: {counts['note_delete']}")
            if counts["tag_rename"] > 0:
                print(f"  - Tag rename conflicts: {counts['tag_rename']}")

    return 0


def cmd_sync_list_peers(config: Config, args: argparse.Namespace) -> int:
    """List configured sync peers.

    Args:
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success)
    """
    peers = config.get_peers()

    if args.format == "json":
        print(json.dumps(peers, indent=2))
    elif args.format == "csv":
        print("peer_id,peer_name,peer_url,fingerprint")
        for peer in peers:
            fp = peer.get("certificate_fingerprint", "")
            print(f'{peer["peer_id"]},{peer["peer_name"]},{peer.get("peer_url", "")},{fp}')
    else:
        if not peers:
            print("No sync peers configured.")
            return 0

        print(f"Configured Peers ({len(peers)}):\n")
        for peer in peers:
            print(f"  ID: {peer['peer_id']}")
            print(f"  Name: {peer['peer_name']}")
            if peer.get("peer_url"):
                print(f"  URL: {peer['peer_url']}")
            if peer.get("certificate_fingerprint"):
                fp = peer["certificate_fingerprint"]
                # Truncate fingerprint for display
                print(f"  Fingerprint: {fp[:20]}...")
            print()

    return 0


def cmd_sync_add_peer(config: Config, args: argparse.Namespace) -> int:
    """Add a new sync peer.

    Args:
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    peer_id = args.peer_id
    peer_name = args.peer_name
    peer_url = args.peer_url
    fingerprint = getattr(args, 'fingerprint', None)

    try:
        config.add_peer(
            peer_id=peer_id,
            peer_name=peer_name,
            peer_url=peer_url,
            certificate_fingerprint=fingerprint,
            allow_update=False,  # Reject if peer already exists
        )
    except ValidationError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"added": True, "peer_id": peer_id, "peer_name": peer_name}))
    else:
        print(f"Added peer: {peer_name} ({peer_id})")

    return 0


def cmd_sync_remove_peer(config: Config, args: argparse.Namespace) -> int:
    """Remove a sync peer.

    Args:
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    peer_id = args.peer_id

    # Check if peer exists
    existing = config.get_peer(peer_id)
    if not existing:
        print(f"Error: Peer with ID {peer_id} not found", file=sys.stderr)
        return 1

    peer_name = existing.get("peer_name", "Unknown")
    config.remove_peer(peer_id)

    if args.format == "json":
        print(json.dumps({"removed": True, "peer_id": peer_id}))
    else:
        print(f"Removed peer: {peer_name} ({peer_id})")

    return 0


def cmd_sync_now(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Perform sync with peers.

    Args:
        db: Database instance
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for any failures)
    """
    peer_id = getattr(args, 'peer_id', None)

    if peer_id:
        # Sync with specific peer
        client = SyncClient(str(config.get_config_dir()))
        result = client.sync_with_peer(peer_id)

        if args.format == "json":
            print(json.dumps({
                "peer_id": peer_id,
                "success": result.success,
                "pulled": result.pulled,
                "pushed": result.pushed,
                "conflicts": result.conflicts,
                "errors": result.errors,
            }, indent=2))
        else:
            if result.success:
                print(f"Sync with {peer_id} completed:")
                print(f"  Pulled: {result.pulled} changes")
                print(f"  Pushed: {result.pushed} changes")
                if result.conflicts > 0:
                    print(f"  Errors: {result.conflicts}")
                    for error in result.errors:
                        print(f"    - {error}")
            else:
                print(f"Sync with {peer_id} failed:")
                for error in result.errors:
                    print(f"  - {error}")
                return 1
    else:
        # Sync with all peers
        results = sync_all_peers(str(config.get_config_dir()))

        if not results:
            if args.format == "json":
                print(json.dumps({"message": "No peers configured"}))
            else:
                print("No peers configured for sync.")
            return 0

        all_success = all(r.success for r in results.values())

        if args.format == "json":
            output = {}
            for pid, result in results.items():
                output[pid] = {
                    "success": result.success,
                    "pulled": result.pulled,
                    "pushed": result.pushed,
                    "conflicts": result.conflicts,
                    "errors": result.errors,
                }
            print(json.dumps(output, indent=2))
        else:
            print(f"Sync completed with {len(results)} peer(s):\n")
            for pid, result in results.items():
                peer = config.get_peer(pid)
                peer_name = peer.get("peer_name", pid) if peer else pid

                if result.success:
                    print(f"  {peer_name}: OK (↓{result.pulled} ↑{result.pushed})")
                    if result.conflicts > 0:
                        print(f"    Errors: {result.conflicts}")
                        for error in result.errors:
                            print(f"      - {error}")
                else:
                    print(f"  {peer_name}: FAILED")
                    for error in result.errors:
                        print(f"    - {error}")

        return 0 if all_success else 1

    return 0


def cmd_sync_conflicts(db: Database, args: argparse.Namespace) -> int:
    """List unresolved sync conflicts.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success)
    """
    conflict_mgr = ConflictManager(db)

    # Get all conflicts
    note_content = conflict_mgr.get_note_content_conflicts()
    note_delete = conflict_mgr.get_note_delete_conflicts()
    tag_rename = conflict_mgr.get_tag_rename_conflicts()

    if args.format == "json":
        output = {
            "note_content": [
                {
                    "id": c.id,
                    "note_id": c.note_id,
                    "local_device": c.local_device_name or c.local_device_id,
                    "remote_device": c.remote_device_name or c.remote_device_id,
                    "created_at": c.created_at,
                }
                for c in note_content
            ],
            "note_delete": [
                {
                    "id": c.id,
                    "note_id": c.note_id,
                    "surviving_device": c.surviving_device_name or c.surviving_device_id,
                    "deleting_device": c.deleting_device_name or c.deleting_device_id,
                    "created_at": c.created_at,
                }
                for c in note_delete
            ],
            "tag_rename": [
                {
                    "id": c.id,
                    "tag_id": c.tag_id,
                    "local_name": c.local_name,
                    "remote_name": c.remote_name,
                    "created_at": c.created_at,
                }
                for c in tag_rename
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        total = len(note_content) + len(note_delete) + len(tag_rename)
        if total == 0:
            print("No unresolved conflicts.")
            return 0

        print(f"Unresolved Conflicts ({total}):\n")

        if note_content:
            print("Note Content Conflicts:")
            for c in note_content:
                local = c.local_device_name or c.local_device_id[:8]
                remote = c.remote_device_name or c.remote_device_id[:8]
                print(f"  [{c.id[:8]}] Note {c.note_id[:8]} - {local} vs {remote}")

        if note_delete:
            print("\nNote Delete Conflicts:")
            for c in note_delete:
                surviving = c.surviving_device_name or c.surviving_device_id[:8]
                deleting = c.deleting_device_name or c.deleting_device_id[:8]
                print(f"  [{c.id[:8]}] Note {c.note_id[:8]} - edited by {surviving}, deleted by {deleting}")

        if tag_rename:
            print("\nTag Rename Conflicts:")
            for c in tag_rename:
                print(f"  [{c.id[:8]}] Tag {c.tag_id[:8]} - '{c.local_name}' vs '{c.remote_name}'")

    return 0


def cmd_sync_resolve(db: Database, args: argparse.Namespace) -> int:
    """Resolve a sync conflict.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    conflict_id = args.conflict_id
    choice_str = args.choice
    conflict_mgr = ConflictManager(db)

    # Map choice string to enum
    choice_map = {
        "local": ResolutionChoice.KEEP_LOCAL,
        "remote": ResolutionChoice.KEEP_REMOTE,
        "merge": ResolutionChoice.MERGE,
        "both": ResolutionChoice.KEEP_BOTH,
    }

    if choice_str not in choice_map:
        print(f"Error: Invalid choice '{choice_str}'. Use: local, remote, merge, or both", file=sys.stderr)
        return 1

    choice = choice_map[choice_str]

    # Use core method to find and resolve conflict
    success, conflict_type, error = conflict_mgr.find_and_resolve_conflict(
        conflict_id, choice
    )

    if success:
        print(f"Resolved {conflict_type} conflict with {choice_str}")
        return 0
    else:
        print(f"Error: {error}", file=sys.stderr)
        return 1


def cmd_sync_reset_timestamps(db: Database, args: argparse.Namespace) -> int:
    """Reset sync timestamps to force re-fetching all data.

    This clears the 'last synced' timestamps, causing the next regular sync
    to exchange all data with peers. Server configuration is preserved.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        db.reset_sync_timestamps()
        if args.format == "json":
            print(json.dumps({"success": True, "message": "Sync timestamps reset"}))
        else:
            print("Sync timestamps reset successfully.")
            print("The next sync will exchange all data with peers.")
        return 0
    except Exception as e:
        if args.format == "json":
            print(json.dumps({"success": False, "error": str(e)}))
        else:
            print(f"Error resetting sync timestamps: {e}", file=sys.stderr)
        return 1


def cmd_sync_full_resync(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Perform full re-sync with peers (fetches all data).

    This performs an initial sync (full dataset transfer) with each peer,
    fetching all data regardless of last_sync timestamps. Useful when
    attachments or transcriptions are missing.

    Args:
        db: Database instance
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for any failures)
    """
    peer_id = getattr(args, 'peer_id', None)

    if peer_id:
        # Full resync with specific peer
        client = SyncClient(str(config.get_config_dir()))
        result = client.initial_sync(peer_id)

        if args.format == "json":
            print(json.dumps({
                "peer_id": peer_id,
                "success": result.success,
                "pulled": result.pulled,
                "pushed": result.pushed,
                "conflicts": result.conflicts,
                "errors": result.errors,
            }, indent=2))
        else:
            if result.success:
                print(f"Full re-sync with {peer_id} completed:")
                print(f"  Pulled: {result.pulled} changes")
                print(f"  Pushed: {result.pushed} changes")
                if result.conflicts > 0:
                    print(f"  Conflicts: {result.conflicts}")
                    for error in result.errors:
                        print(f"    - {error}")
            else:
                print(f"Full re-sync with {peer_id} failed:")
                for error in result.errors:
                    print(f"  - {error}")
                return 1
    else:
        # Full resync with all peers
        peers = config.get_peers()
        if not peers:
            if args.format == "json":
                print(json.dumps({"message": "No peers configured"}))
            else:
                print("No peers configured for sync.")
            return 0

        client = SyncClient(str(config.get_config_dir()))
        results = {}
        all_success = True

        for peer in peers:
            pid = peer["peer_id"]
            result = client.initial_sync(pid)
            results[pid] = result
            if not result.success:
                all_success = False

        if args.format == "json":
            output = {}
            for pid, result in results.items():
                output[pid] = {
                    "success": result.success,
                    "pulled": result.pulled,
                    "pushed": result.pushed,
                    "conflicts": result.conflicts,
                    "errors": result.errors,
                }
            print(json.dumps(output, indent=2))
        else:
            print(f"Full re-sync completed with {len(results)} peer(s):\n")
            for pid, result in results.items():
                peer = config.get_peer(pid)
                peer_name = peer.get("peer_name", pid) if peer else pid

                if result.success:
                    print(f"  {peer_name}: OK (↓{result.pulled} ↑{result.pushed})")
                    if result.conflicts > 0:
                        print(f"    Conflicts: {result.conflicts}")
                        for error in result.errors:
                            print(f"      - {error}")
                else:
                    print(f"  {peer_name}: FAILED")
                    for error in result.errors:
                        print(f"    - {error}")

        return 0 if all_success else 1

    return 0


def cmd_sync_serve(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Start the sync server.

    Args:
        db: Database instance
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success)
    """
    port = getattr(args, 'port', None) or config.get_sync_server_port()
    verbose = getattr(args, 'verbose', False)
    no_color = getattr(args, 'no_color', False)

    # Use Rust sync server via voicecore bindings
    # The server handles its own startup message and Ctrl-C
    try:
        start_sync_server(
            config_dir=str(config.get_config_dir()),
            port=port,
            verbose=verbose,
            ansi_colors=not no_color
        )
    except KeyboardInterrupt:
        # Rust already handled the shutdown, just exit cleanly
        pass

    return 0


def cmd_maintenance_database_normalize(db: Database, args: argparse.Namespace) -> int:
    """Normalize database data for consistency.

    This includes:
    - Timestamp normalization (ISO 8601 to SQLite format)
    - Future: Unicode normalization

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        print("Normalizing database...")
        db.normalize_database()
        print("Database normalization complete.")
        return 0
    except Exception as e:
        print(f"Error normalizing database: {e}", file=sys.stderr)
        return 1


def cmd_new_tag(db: Database, args: argparse.Namespace) -> int:
    """Create a new tag.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    name = args.name
    parent_prefix = getattr(args, 'parent', None)

    try:
        # VoiceCore handles UUID prefix resolution internally
        tag_id = db.create_tag(name, parent_prefix)

        if args.format == "json":
            result = {"id": tag_id, "name": name}
            if parent_prefix:
                result["parent_id"] = parent_prefix
            print(json.dumps(result))
        else:
            if parent_prefix:
                parent_tag = db.get_tag(parent_prefix)
                parent_name = parent_tag["name"] if parent_tag else parent_prefix
                print(f"Created tag '{name}' (ID: {tag_id}) under '{parent_name}'")
            else:
                print(f"Created tag '{name}' (ID: {tag_id})")
        return 0
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error creating tag: {e}", file=sys.stderr)
        return 1


def cmd_tag_notes(db: Database, args: argparse.Namespace) -> int:
    """Attach tags to notes.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    tag_prefixes = args.tags
    note_prefixes = args.notes

    if not tag_prefixes:
        print("Error: At least one tag is required (--tags)", file=sys.stderr)
        return 1

    if not note_prefixes:
        print("Error: At least one note is required (--notes)", file=sys.stderr)
        return 1

    try:
        # VoiceCore handles UUID prefix resolution internally
        # Attach each tag to each note
        attached = 0
        for note_prefix in note_prefixes:
            for tag_prefix in tag_prefixes:
                if db.add_tag_to_note(note_prefix, tag_prefix):
                    attached += 1

        if args.format == "json":
            print(json.dumps({
                "attached": attached,
                "tags": len(tag_prefixes),
                "notes": len(note_prefixes),
            }))
        else:
            print(f"Attached {len(tag_prefixes)} tag(s) to {len(note_prefixes)} note(s) ({attached} new associations)")
        return 0
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error tagging notes: {e}", file=sys.stderr)
        return 1


def add_cli_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add CLI subparser and its nested subcommands.

    Args:
        subparsers: Parent subparsers object to add CLI parser to
    """
    cli_parser = subparsers.add_parser(
        "cli",
        help="Command-line interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    cli_parser.add_argument(
        "--format",
        choices=["text", "json", "csv"],
        default="text",
        help="Output format (default: text)"
    )

    # Nested subcommands for CLI
    cli_subparsers = cli_parser.add_subparsers(dest="cli_command", help="CLI commands")

    # notes-list command
    cli_subparsers.add_parser(
        "notes-list",
        help="List all notes"
    )

    # note-show command
    show_parser = cli_subparsers.add_parser(
        "note-show",
        help="Show details of a specific note"
    )
    show_parser.add_argument(
        "note_id",
        type=str,
        help="ID of the note to show (UUID hex string)"
    )

    # note-create command
    new_note_parser = cli_subparsers.add_parser(
        "note-create",
        help="Create a new note"
    )
    new_note_parser.add_argument(
        "content",
        nargs="?",
        type=str,
        help="Note content (reads from stdin if not provided)"
    )

    # note-edit command
    edit_note_parser = cli_subparsers.add_parser(
        "note-edit",
        help="Edit an existing note"
    )
    edit_note_parser.add_argument(
        "note_id",
        type=str,
        help="ID of the note to edit (UUID hex string)"
    )
    edit_note_parser.add_argument(
        "content",
        nargs="?",
        type=str,
        help="New content (reads from stdin if not provided)"
    )

    # notes-merge command
    merge_notes_parser = cli_subparsers.add_parser(
        "notes-merge",
        help="Merge two notes into one"
    )
    merge_notes_parser.add_argument(
        "note_id_1",
        type=str,
        help="ID of the first note (UUID hex string)"
    )
    merge_notes_parser.add_argument(
        "note_id_2",
        type=str,
        help="ID of the second note (UUID hex string)"
    )

    # tags-list command
    cli_subparsers.add_parser(
        "tags-list",
        help="List all tags in hierarchy"
    )

    # tag-create command
    new_tag_parser = cli_subparsers.add_parser(
        "tag-create",
        help="Create a new tag"
    )
    new_tag_parser.add_argument(
        "name",
        type=str,
        help="Name of the tag to create"
    )
    new_tag_parser.add_argument(
        "--parent",
        type=str,
        help="Parent tag ID or prefix (e.g., '57c28')"
    )

    # notes-tag command
    tag_notes_parser = cli_subparsers.add_parser(
        "notes-tag",
        help="Attach tags to notes"
    )
    tag_notes_parser.add_argument(
        "--tags",
        nargs="+",
        required=True,
        help="Tag ID(s) or prefix(es) to attach"
    )
    tag_notes_parser.add_argument(
        "--notes",
        nargs="+",
        required=True,
        help="Note ID(s) or prefix(es) to tag"
    )

    # notes-search command
    search_parser = cli_subparsers.add_parser(
        "notes-search",
        help="Search notes by text and/or tags"
    )
    search_parser.add_argument(
        "--text",
        type=str,
        help="Text to search for in note content"
    )
    search_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        help="Tag path to filter by (can be specified multiple times for AND logic)"
    )

    # audiofiles-import command
    import_audio_parser = cli_subparsers.add_parser(
        "audiofiles-import",
        help="Import audio files from a directory"
    )
    import_audio_parser.add_argument(
        "directory",
        type=str,
        help="Directory containing audio files to import"
    )
    import_audio_parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="Recursively search subdirectories"
    )
    import_audio_parser.add_argument(
        "--tags",
        nargs="+",
        metavar="TAG_UUID",
        help="Tag UUID(s) to attach to imported notes (can specify multiple)"
    )

    # note-audiofiles-list command
    list_audio_parser = cli_subparsers.add_parser(
        "note-audiofiles-list",
        help="List audio files attached to a note"
    )
    list_audio_parser.add_argument(
        "--note-id",
        type=str,
        help="List audio files attached to a specific note"
    )

    # audiofile-show command
    show_audio_parser = cli_subparsers.add_parser(
        "audiofile-show",
        help="Show details of an audio file"
    )
    show_audio_parser.add_argument(
        "audio_id",
        type=str,
        help="Audio file ID to show"
    )

    # audiofile-transcribe command
    transcribe_audio_parser = cli_subparsers.add_parser(
        "audiofile-transcribe",
        help="Transcribe a single audio file"
    )
    transcribe_audio_parser.add_argument(
        "audio_id",
        type=str,
        help="Audio file ID to transcribe"
    )
    transcribe_audio_parser.add_argument(
        "--language",
        type=str,
        help="Language hint (ISO 639-1 code, e.g., 'en', 'he')"
    )
    transcribe_audio_parser.add_argument(
        "--speaker-count",
        dest="speaker_count",
        type=int,
        help="Expected number of speakers (for diarization)"
    )
    transcribe_audio_parser.add_argument(
        "--model",
        type=str,
        help="Model name (e.g., 'small', 'large-v3') or path to model file"
    )
    transcribe_audio_parser.add_argument(
        "--backend",
        type=str,
        choices=["local_whisper", "assemblyai", "google_cloud"],
        default="local_whisper",
        help="Transcription backend (default: local_whisper)"
    )
    transcribe_audio_parser.add_argument(
        "--api-key",
        dest="api_key",
        type=str,
        help="API key for cloud backends (AssemblyAI, Google Cloud)"
    )
    transcribe_audio_parser.add_argument(
        "--project-id",
        dest="project_id",
        type=str,
        help="Google Cloud project ID (for google_cloud backend)"
    )

    # note-audiofiles-transcribe command
    transcribe_note_parser = cli_subparsers.add_parser(
        "note-audiofiles-transcribe",
        help="Transcribe all audio files attached to a note"
    )
    transcribe_note_parser.add_argument(
        "note_id",
        type=str,
        help="Note ID to transcribe audio files for"
    )
    transcribe_note_parser.add_argument(
        "--language",
        type=str,
        help="Language hint (ISO 639-1 code, e.g., 'en', 'he')"
    )
    transcribe_note_parser.add_argument(
        "--speaker-count",
        dest="speaker_count",
        type=int,
        help="Expected number of speakers (for diarization)"
    )
    transcribe_note_parser.add_argument(
        "--model",
        type=str,
        help="Model name (e.g., 'small', 'large-v3') or path to model file"
    )
    transcribe_note_parser.add_argument(
        "--backend",
        type=str,
        choices=["local_whisper", "assemblyai", "google_cloud"],
        default="local_whisper",
        help="Transcription backend (default: local_whisper)"
    )
    transcribe_note_parser.add_argument(
        "--api-key",
        dest="api_key",
        type=str,
        help="API key for cloud backends (AssemblyAI, Google Cloud)"
    )
    transcribe_note_parser.add_argument(
        "--project-id",
        dest="project_id",
        type=str,
        help="Google Cloud project ID (for google_cloud backend)"
    )

    # sync command with subcommands
    sync_parser = cli_subparsers.add_parser(
        "sync",
        help="Sync operations (status, peers, conflicts)"
    )
    sync_subparsers = sync_parser.add_subparsers(dest="sync_command", help="Sync commands")

    # sync status
    sync_subparsers.add_parser("status", help="Show sync status and device info")

    # sync list-peers
    sync_subparsers.add_parser("list-peers", help="List configured sync peers")

    # sync add-peer
    add_peer_parser = sync_subparsers.add_parser("add-peer", help="Add a new sync peer")
    add_peer_parser.add_argument("peer_id", type=str, help="Peer device ID (32 hex characters)")
    add_peer_parser.add_argument("peer_name", type=str, help="Peer display name")
    add_peer_parser.add_argument("peer_url", type=str, help="Peer URL (e.g., https://host:8384)")
    add_peer_parser.add_argument(
        "--fingerprint",
        type=str,
        help="Certificate fingerprint (optional, for pre-trusted peers)"
    )

    # sync remove-peer
    remove_peer_parser = sync_subparsers.add_parser("remove-peer", help="Remove a sync peer")
    remove_peer_parser.add_argument("peer_id", type=str, help="Peer device ID to remove")

    # sync now
    sync_now_parser = sync_subparsers.add_parser("now", help="Perform sync with peers")
    sync_now_parser.add_argument(
        "--peer",
        dest="peer_id",
        type=str,
        help="Sync with specific peer ID (default: all peers)"
    )

    # sync conflicts
    sync_subparsers.add_parser("conflicts", help="List unresolved sync conflicts")

    # sync resolve
    resolve_parser = sync_subparsers.add_parser("resolve", help="Resolve a sync conflict")
    resolve_parser.add_argument(
        "conflict_id",
        type=str,
        help="Conflict ID (or prefix) to resolve"
    )
    resolve_parser.add_argument(
        "choice",
        type=str,
        choices=["local", "remote", "merge", "both"],
        help="Resolution choice: local, remote, merge (content), or both (delete)"
    )

    # sync serve
    serve_parser = sync_subparsers.add_parser("serve", help="Start the sync server")
    serve_parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)"
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind to (default: 8384 or from config)"
    )
    serve_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging to stdout (shows sync requests and operations)"
    )
    serve_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color codes in log output"
    )

    # sync reset-timestamps
    sync_subparsers.add_parser(
        "reset-timestamps",
        help="Reset sync timestamps to force re-fetching all data from peers"
    )

    # sync full-resync
    full_resync_parser = sync_subparsers.add_parser(
        "full-resync",
        help="Perform full re-sync (fetches all data regardless of timestamps)"
    )
    full_resync_parser.add_argument(
        "--peer",
        dest="peer_id",
        type=str,
        help="Full re-sync with specific peer ID (default: all peers)"
    )

    # db-maintenance command with subcommands
    maintenance_parser = cli_subparsers.add_parser(
        "db-maintenance",
        help="Database maintenance operations"
    )
    maintenance_subparsers = maintenance_parser.add_subparsers(
        dest="maintenance_command", help="Maintenance commands"
    )

    # maintenance database-normalize
    maintenance_subparsers.add_parser(
        "database-normalize",
        help="Normalize database data (timestamps, unicode, etc.)"
    )


def run(config_dir: Optional[Path], args: argparse.Namespace) -> int:
    """Run CLI with given arguments.

    Args:
        config_dir: Custom configuration directory or None for default
        args: Parsed command-line arguments (should have cli_command attribute)

    Returns:
        Exit code (0 for success, 1 for error)
    """
    # Check if CLI command was provided
    if not hasattr(args, 'cli_command') or not args.cli_command:
        print("Error: No CLI command specified. Use --help for available commands.", file=sys.stderr)
        return 1

    # Initialize config and database
    config = Config(config_dir=config_dir)
    db_path_str = config.get("database_file")
    db_path = Path(db_path_str)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)

    # Execute command
    try:
        if args.cli_command == "notes-list":
            return cmd_list_notes(db, args)
        elif args.cli_command == "note-show":
            return cmd_show_note(db, args)
        elif args.cli_command == "note-create":
            return cmd_new_note(db, args)
        elif args.cli_command == "note-edit":
            return cmd_edit_note(db, args)
        elif args.cli_command == "notes-merge":
            return cmd_merge_notes(db, args)
        elif args.cli_command == "tags-list":
            return cmd_list_tags(db, args)
        elif args.cli_command == "tag-create":
            return cmd_new_tag(db, args)
        elif args.cli_command == "notes-tag":
            return cmd_tag_notes(db, args)
        elif args.cli_command == "notes-search":
            return cmd_search(db, args)
        elif args.cli_command == "audiofiles-import":
            return cmd_import_audiofiles(db, config, args)
        elif args.cli_command == "note-audiofiles-list":
            return cmd_list_audiofiles(db, config, args)
        elif args.cli_command == "audiofile-show":
            return cmd_show_audiofile(db, config, args)
        elif args.cli_command == "audiofile-transcribe":
            return cmd_transcribe_audiofile(db, config, args)
        elif args.cli_command == "note-audiofiles-transcribe":
            return cmd_transcribe_note(db, config, args)
        elif args.cli_command == "sync":
            # Handle sync subcommands
            sync_cmd = getattr(args, 'sync_command', None)
            if not sync_cmd:
                print("Error: No sync command specified. Use 'sync --help'.", file=sys.stderr)
                return 1
            if sync_cmd == "status":
                return cmd_sync_status(db, config, args)
            elif sync_cmd == "list-peers":
                return cmd_sync_list_peers(config, args)
            elif sync_cmd == "add-peer":
                return cmd_sync_add_peer(config, args)
            elif sync_cmd == "remove-peer":
                return cmd_sync_remove_peer(config, args)
            elif sync_cmd == "now":
                return cmd_sync_now(db, config, args)
            elif sync_cmd == "conflicts":
                return cmd_sync_conflicts(db, args)
            elif sync_cmd == "resolve":
                return cmd_sync_resolve(db, args)
            elif sync_cmd == "serve":
                return cmd_sync_serve(db, config, args)
            elif sync_cmd == "reset-timestamps":
                return cmd_sync_reset_timestamps(db, args)
            elif sync_cmd == "full-resync":
                return cmd_sync_full_resync(db, config, args)
            else:
                print(f"Error: Unknown sync command '{sync_cmd}'", file=sys.stderr)
                return 1
        elif args.cli_command == "db-maintenance":
            # Handle maintenance subcommands
            maint_cmd = getattr(args, 'maintenance_command', None)
            if not maint_cmd:
                print("Error: No maintenance command specified. Use 'db-maintenance --help'.", file=sys.stderr)
                return 1
            if maint_cmd == "database-normalize":
                return cmd_maintenance_database_normalize(db, args)
            else:
                print(f"Error: Unknown maintenance command '{maint_cmd}'", file=sys.stderr)
                return 1
        else:
            print(f"Error: Unknown command '{args.cli_command}'", file=sys.stderr)
            return 1
    except ValidationError as e:
        print(f"Error: Invalid {e.field} - {e.message}", file=sys.stderr)
        return 1
    finally:
        db.close()

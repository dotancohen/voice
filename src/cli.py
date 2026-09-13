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
    trash-list              List the notes in the trash
    note-recover <id>       Take a note out of the trash
    note-purge <id>         Remove a trashed note for good, on every device
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
from src.core.cloud_storage import (
    STATUS_IN_CLOUD,
    STATUS_LOCAL,
    STATUS_PENDING,
    audio_file_status,
    describe_download_result,
    download_audio_file,
    download_audio_files_for_note,
    download_missing_audio_files,
)
from src.core.config import Config
from src.core.conflicts import ConflictManager
from src.core.database import Database
from src.core.synced_settings import reconcile_transcription_settings, set_synced_setting
from src.core.models import AUDIO_FILE_FORMATS, UUID_SHORT_LEN
from src.core.search import resolve_tag_term
from src.core.timestamp_utils import format_timestamp, datetime_to_timestamp
from voicecore import SyncClient, sync_all_peers, start_sync_server
from src.core.validation import ValidationError


def format_duration(seconds: int) -> str:
    """Format duration in seconds as [h:]mm:ss.

    Args:
        seconds: Duration in seconds (integer)

    Returns:
        Formatted string like "00:03", "1:07:00", etc.
    """
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"


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
        created_at = format_timestamp(note.get("created_at"), note.get("created_at_offset"))
        return f'{note["id"]},"{created_at}","{content}","{tags}"'
    else:  # text
        lines = [
            f"ID: {note['id']}",
            f"Created: {format_timestamp(note.get('created_at'), note.get('created_at_offset'))}",
        ]
        if note.get("modified_at"):
            lines.append(f"Modified: {format_timestamp(note['modified_at'], note.get('modified_at_offset'))}")
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
            print(f"{note['id']} | {format_timestamp(note.get('created_at'), note.get('created_at_offset'))} | {first_line}")

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

    # Check for conflicts
    conflict_mgr = ConflictManager(db)
    conflict_types = conflict_mgr.get_note_conflict_types(note["id"])
    if conflict_types:
        types_str = ", ".join(conflict_types)
        print(f"WARNING: This note has unresolved {types_str} conflict(s)", file=sys.stderr)
        for c in conflict_mgr.get_note_conflicts(note["id"]):
            print(f"  [{c.id[:UUID_SHORT_LEN]}] {c.describe()}", file=sys.stderr)
        print("  Resolve with: sync resolve <id> (accept) or sync resolve <id> --content-file FILE", file=sys.stderr)

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
            print(f"Merged notes into #{survivor_id[:UUID_SHORT_LEN]}...")
            print(f"Deleted note #{deleted_id[:UUID_SHORT_LEN]}...")
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

            # Get file creation time as Unix timestamp
            file_created_at = manager.get_file_created_at(audio_path)
            file_created_at_ts = datetime_to_timestamp(file_created_at)

            # Create AudioFile record in database; its row names the file
            audio_file_id = db.create_audio_file(audio_path.name, file_created_at_ts)
            row = db.get_audio_file(audio_file_id)

            # Copy file to audiofile_directory
            manager.import_file(audio_path, row["local_name"])
            db.store_content_hash(audio_file_id, manager.audiofile_directory)

            # Create Note with audio reference
            # Use file_created_at for note's created_at for chronological sorting
            note_content = f"Audio: {audio_path.name}"

            if file_created_at_ts:
                # Use apply_sync_note to create note with the correct created_at
                # Generate a new UUID7 for the note
                from uuid6 import uuid7
                note_uuid = uuid7()
                note_id = note_uuid.hex
                db.apply_sync_note(note_id, file_created_at_ts, note_content, None, None)
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

            print(f"  Imported: {audio_path.name} -> {audio_file_id[:UUID_SHORT_LEN]}...")
            imported += 1

        except Exception as e:
            print(f"  Error importing {audio_path.name}: {e}")
            errors += 1

    print(f"\nImported {imported} file(s), {errors} error(s)")
    return 0 if errors == 0 else 1


def _describe_copies(db: Database, config: Config, af: Dict[str, Any], audiofile_dir: Optional[Path]) -> str:
    """Where the copies of a recording are (Stage 10): this device, the bucket, and each peer."""
    places = []
    if audiofile_dir is not None and af.get("filename"):
        from src.core.cloud_storage import audio_file_status, STATUS_LOCAL
        if audio_file_status(af, audiofile_dir) == STATUS_LOCAL:
            places.append("this device")
    if af.get("storage_key"):
        places.append("the bucket")
    names = {p["peer_id"]: p["peer_name"] for p in config.get_peers()}
    for card in db.list_devices():
        names.setdefault(card["device_id"], card["name"] or card["device_id"][:UUID_SHORT_LEN])
    for copy in db.copies_of(af["id"]):
        places.append(names.get(copy["peer_id"], copy["peer_id"][:UUID_SHORT_LEN]))
    return ", ".join(places) if places else "nowhere known"


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

    audiofile_dir = config.get_audiofile_directory()
    for af in audio_files:
        print(f"ID: {af['id'][:UUID_SHORT_LEN]}...")
        print(f"  Filename: {af['filename']}")
        print(f"  Imported: {format_timestamp(af.get('imported_at'), af.get('imported_at_offset'))}")
        if af.get('file_created_at'):
            print(f"  File created: {format_timestamp(af['file_created_at'], af.get('file_created_at_offset'))}")
        if af.get('summary'):
            print(f"  Summary: {af['summary']}")
        if audiofile_dir:
            print(f"  Media: {_describe_media_status(af, audiofile_dir)}")
        print(f"  Copies: {_describe_copies(db, config, af, audiofile_dir)}")
        print()

    return 0


def _describe_media_status(audio_file: Dict[str, Any], audiofile_dir: str) -> str:
    """Human description of where an audio file's binary is."""
    status = audio_file_status(audio_file, audiofile_dir)
    if status == STATUS_LOCAL:
        return "on this device"
    if status == STATUS_IN_CLOUD:
        return "not on this device, in cloud storage (use audiofile-download)"
    return "not on this device, not uploaded by its device yet"


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
    print(f"Imported: {format_timestamp(audio_file.get('imported_at'), audio_file.get('imported_at_offset'))}")
    if audio_file.get('file_created_at'):
        print(f"File created: {format_timestamp(audio_file['file_created_at'], audio_file.get('file_created_at_offset'))}")
    if audio_file.get('summary'):
        print(f"Summary: {audio_file['summary']}")
    if audio_file.get('modified_at'):
        print(f"Modified: {format_timestamp(audio_file['modified_at'], audio_file.get('modified_at_offset'))}")
    if audio_file.get('deleted_at'):
        print(f"Deleted: {format_timestamp(audio_file['deleted_at'], audio_file.get('deleted_at_offset'))}")

    # Cloud storage location
    if audio_file.get('storage_key'):
        print(f"Cloud storage: {audio_file.get('storage_provider')} {audio_file['storage_key']}")
        if audio_file.get('storage_uploaded_at'):
            print(f"Uploaded: {format_timestamp(audio_file['storage_uploaded_at'])}")
    else:
        print("Cloud storage: not uploaded yet")

    # Show file location
    audiofile_dir = config.get_audiofile_directory()
    if audiofile_dir:
        manager = AudioFileManager(audiofile_dir)
        file_path = manager.get_record_path(audio_file)
        if file_path.is_file():
            print(f"File path: {file_path}")
        else:
            print(f"File path: (not on this device, would be {file_path})")
            print(f"Media: {_describe_media_status(audio_file, audiofile_dir)}")

    return 0


def cmd_download_audiofile(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Download one audio file from cloud storage on demand.

    Returns:
        Exit code (0 for success or nothing to do, 1 for failure)
    """
    audio_file = db.get_audio_file(args.audio_id)
    if not audio_file:
        print(f"Audio file not found: {args.audio_id}", file=sys.stderr)
        return 1

    if not config.get_audiofile_directory():
        print("Error: audiofile_directory not configured.", file=sys.stderr)
        print("Run: voice config set audiofile_directory /path/to/audio/files", file=sys.stderr)
        return 1

    try:
        result = download_audio_file(audio_file['id'], config.get_config_dir())
    except RuntimeError as e:
        print(f"Download failed: {e}", file=sys.stderr)
        return 1

    status = result.get("status")
    if status == "downloaded":
        print(f"Downloaded {audio_file['filename']} ({result.get('bytes', 0)} bytes)")
    elif status == "already_local":
        print(f"{audio_file['filename']} is already on this device")
    else:
        print(f"{audio_file['filename']} has not been uploaded to cloud storage by its device yet")
    return 0


def cmd_download_note_audiofiles(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Download every missing audio file attached to a note.

    Returns:
        Exit code (0 for success or nothing to do, 1 for failure)
    """
    note = db.get_note(args.note_id)
    if not note:
        print(f"Note not found: {args.note_id}", file=sys.stderr)
        return 1

    if not config.get_audiofile_directory():
        print("Error: audiofile_directory not configured.", file=sys.stderr)
        print("Run: voice config set audiofile_directory /path/to/audio/files", file=sys.stderr)
        return 1

    try:
        result = download_audio_files_for_note(note['id'], config.get_config_dir())
    except RuntimeError as e:
        print(f"Download failed: {e}", file=sys.stderr)
        return 1

    print(f"Audio files for note {note['id'][:UUID_SHORT_LEN]}...: {describe_download_result(result)}")
    for error in result.errors:
        print(f"  - {error}", file=sys.stderr)
    return 0 if result.failed == 0 else 1


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

    file_path = manager.get_record_path(audio_file)
    if not file_path.is_file():
        # Transcribing is an explicit request for the media, so fetch it on demand.
        status = audio_file_status(audio_file, audiofile_dir)
        if status == STATUS_IN_CLOUD:
            print(f"Audio file not on this device, downloading {audio_file['filename']} from cloud storage...")
            try:
                download_audio_file(audio_file['id'], config.get_config_dir())
            except RuntimeError as e:
                print(f"Error: Download failed: {e}", file=sys.stderr)
                return None
            file_path = manager.get_record_path(audio_file)
            if not file_path.is_file():
                file_path = None
        elif status == STATUS_PENDING:
            print(
                f"Error: Audio file {audio_file['id'][:UUID_SHORT_LEN]}... is not on this device "
                "and has not been uploaded to cloud storage by its device yet",
                file=sys.stderr,
            )
            return None
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
                # Try "google" first (config format), then "google_cloud"
                google_cfg = transcription_cfg.get("providers", {}).get("google", {})
                if not google_cfg:
                    google_cfg = transcription_cfg.get("providers", {}).get("google_cloud", {})
                proj_id = google_cfg.get("project_id")
            if not proj_id:
                print("Error: Google Cloud project ID required. Use --project-id or set GOOGLE_CLOUD_PROJECT.", file=sys.stderr)
                return None

            client = TranscriptionClient.with_google_cloud(token, proj_id)
            service = "google_cloud"
            model_path = None

        elif backend == "speechtext_ai":
            # Get config for API key and options
            transcription_cfg = config.get_transcription_config()
            provider_cfg = transcription_cfg.get("providers", {}).get("speechtext_ai", {})

            # Get API key from argument, environment, or config
            key = api_key or os.environ.get("SPEECHTEXT_AI_API_KEY") or provider_cfg.get("api_key")
            if not key:
                print("Error: SpeechText.AI API key required. Use --api-key or set SPEECHTEXT_AI_API_KEY.", file=sys.stderr)
                return None

            # Get provider-specific options from config (defaults for Hebrew accuracy)
            punctuation = provider_cfg.get("punctuation", True)
            summary = provider_cfg.get("summary", False)
            highlights = provider_cfg.get("highlights", False)

            client = TranscriptionClient.with_speechtext_ai(
                api_key=key,
                punctuation=punctuation,
                summary=summary,
                highlights=highlights,
            )
            service = "speechtext_ai"
            model_path = None

        else:
            print(f"Error: Unknown backend '{backend}'", file=sys.stderr)
            print("Available backends: local_whisper, assemblyai, google_cloud, speechtext_ai", file=sys.stderr)
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
    # Enable debug logging if requested
    if getattr(args, 'debug', False):
        from voice_transcription import enable_debug_logging
        enable_debug_logging()

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
        print(f"Audio File: {audio_file_id[:UUID_SHORT_LEN]}...")
        if result.get('duration_seconds'):
            print(f"Duration: {result['duration_seconds']:.1f}s")
        if result.get('languages'):
            print(f"Languages: {', '.join(result['languages'])}")
        print(f"\n{result['content']}")

    return 0


def cmd_transcribe_backlog(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Transcribe the recordings the phone was too small for.

    The Android application transcribes up to ten minutes and refers anything
    longer here. This finds those recordings — long, and with no finished
    transcription — and transcribes them.

    Doing the work is a choice made per machine: unless
    `transcription.transcribe_long_recordings` is true in this machine's
    config.json, the command reports what is waiting and does nothing, because
    not every desktop has the hardware for it. `--force` overrides that for one
    run.

    Args:
        db: Database instance
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    from src.core import transcription_backlog as backlog

    min_minutes = getattr(args, "min_minutes", None) or backlog.minimum_minutes(config)
    limit = getattr(args, "limit", None)
    dry_run = getattr(args, "dry_run", False)
    force = getattr(args, "force", False)

    waiting = backlog.find_untranscribed(db, min_minutes * 60, limit)

    if not waiting:
        print(f"Nothing waiting: no Recording over {min_minutes} minutes is without a Transcription.")
        return 0

    total_seconds = sum(a.get("duration_seconds") or 0 for a in waiting)
    print(f"{len(waiting)} Recording(s) over {min_minutes} minutes have no Transcription "
          f"({total_seconds // 60} minutes of audio in all):")
    for audio_file in waiting:
        minutes = (audio_file.get("duration_seconds") or 0) // 60
        print(f"  {audio_file['id'][:8]}  {minutes:>4} min  {audio_file.get('filename', '')}")

    if dry_run:
        return 0

    if not backlog.is_enabled(config) and not force:
        print()
        print("This machine is not set to transcribe them. Whether it can is a fact about")
        print("the hardware, so it is asked for explicitly:")
        print()
        print("    python -m src.main cli transcribe-backlog --enable")
        print()
        print("or, for this run only, --force.")
        return 0

    language = getattr(args, "language", None)
    model = getattr(args, "model", None)
    backend = getattr(args, "backend", "local_whisper")
    done = 0
    failed = 0
    for audio_file in waiting:
        minutes = (audio_file.get("duration_seconds") or 0) // 60
        print(f"\nTranscribing {audio_file.get('filename', audio_file['id'][:8])} ({minutes} min)…")
        result = _transcribe_audio_file(
            db, config, audio_file["id"],
            language=language,
            model=model,
            backend=backend,
        )
        if result:
            done += 1
        else:
            failed += 1
            print(f"  failed: {audio_file['id'][:8]}", file=sys.stderr)

    print(f"\nTranscribed {done} Recording(s)" + (f", {failed} failed" if failed else ""))
    return 0 if failed == 0 else 1


def cmd_transcription_queue(db: Database, config: Config, args: argparse.Namespace) -> int:
    """What is waiting to be transcribed here, what is running, and what it cost.

    One queue for the whole installation, so this shows the same thing the GUI,
    the TUI and the Web API show, and can reorder what they queued. See
    `core.transcription_queue`.

    Args:
        db: Database instance
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    from src.core import transcription_queue as queue_module

    queue = queue_module.Queue(config.config_dir)

    # The actions first: each says what it did and then shows the queue.
    promote = getattr(args, "next", None)
    drop = getattr(args, "remove", None)
    if promote:
        full = _resolve_audio_file_id(db, promote)
        if queue.do_next(full or promote):
            print("It will be transcribed next.")
        else:
            print("That Recording is not waiting, or is already next.", file=sys.stderr)
            return 1
    if drop:
        full = _resolve_audio_file_id(db, drop)
        if queue.remove(full or drop):
            print("Taken out of the queue.")
        else:
            print("That Recording is not waiting.", file=sys.stderr)
            return 1
    if getattr(args, "clear", False):
        print(f"Forgot {queue.clear()} waiting Recording(s).")

    if getattr(args, "run", False):
        from src.core.transcription_service import TranscriptionService

        service = TranscriptionService(
            db, Path(config.get_audiofile_directory() or "."), config
        )
        ran = queue_module.drain(
            db, config, service,
            limit=getattr(args, "limit", None),
            progress=lambda line: print(f"  {line}"),
        )
        print(f"Transcribed {ran} Recording(s).")

    view = queue_module.view(db, config, getattr(args, "service", None))

    if getattr(args, "format", "text") == "json":
        print(json.dumps(queue_module.as_json(view), ensure_ascii=False, indent=2))
        return 0

    if not view.anything:
        print("Nothing is waiting, and nothing has been transcribed on this machine yet.")
        return 0

    if view.rate:
        print(f"This machine transcribes at about {view.rate:.1f} seconds of work "
              f"per second of Recording.")
        print()

    if view.waiting:
        print(f"Waiting ({len(view.waiting)}):")
        for row in view.waiting:
            wait = queue_module.in_words(row.wait_seconds)
            place = "next" if row.position == 1 else f"{row.position}th in line"
            print(f"  {row.audio_file_id[:8]}  {place:<14}"
                  f"{_queue_length(row.audio_seconds):>9}  {row.filename}")
            print(f"            {row.note_line or '(no note)'}")
            if wait:
                print(f"            done in {wait}")
        print()

    if view.processing:
        print("Processing:")
        for row in view.processing:
            print(f"  {row.audio_file_id[:8]}  {_queue_length(row.audio_seconds):>9}  {row.filename}")
            print(f"            {row.note_line or '(no note)'}")
            print(f"            {row.outcome or 'working'}")
        print()

    if view.completed:
        print(f"Completed ({len(view.completed)}), newest first:")
        for row in view.completed:
            mark = "failed" if row.state == "failed" else "done"
            print(f"  {row.audio_file_id[:8]}  {mark:<7}{_queue_length(row.audio_seconds):>9}  {row.filename}")
            print(f"            {row.note_line or '(no note)'}")
            print(f"            {_queue_cost(row)}")
    return 0


def _queue_length(seconds: Optional[float]) -> str:
    """A recording's length for the queue listing."""
    if not seconds:
        return "-"
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def _queue_cost(row: Any) -> str:
    """What a finished transcription cost, in one line."""
    from src.core import transcription_queue as queue_module

    if row.state == "failed":
        return row.outcome or "did not finish"
    work = row.work
    parts = []
    if row.characters is not None:
        parts.append(f"{row.characters} characters")
    if work and work.clock_seconds:
        parts.append(f"{queue_module.in_words(work.clock_seconds) or f'{work.clock_seconds:.0f} s'} of clock time")
    if work and work.cpu_seconds:
        parts.append(f"{work.cpu_seconds:.0f} s of processor time")
    if work and work.cores_busy:
        parts.append(f"{work.cores_busy:.1f} cores busy")
    if work and work.peak_memory_bytes:
        parts.append(f"{work.peak_memory_bytes / 1e6:.0f} MB peak")
    if work and work.model:
        parts.append(work.model)
    return ", ".join(parts) if parts else "nothing was recorded about the work"


def _resolve_audio_file_id(db: Database, prefix: str) -> Optional[str]:
    """The full id of a Recording from the first characters of its id.

    Ids are given as prefixes everywhere else in the CLI, so they are here too.
    """
    if len(prefix) >= 32:
        return prefix
    for audio_file in db.get_all_audio_files():
        if audio_file["id"].startswith(prefix):
            return audio_file["id"]
    return None


def cmd_transcribe_note(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Transcribe all audio files for a note.

    Args:
        db: Database instance
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    # Enable debug logging if requested
    if getattr(args, 'debug', False):
        from voice_transcription import enable_debug_logging
        enable_debug_logging()

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
            print(f"\n--- {result['audio_file_id'][:UUID_SHORT_LEN]}... ---")
            print(result['content'])

    return 0 if errors == 0 else 1


def cmd_device_list(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Every device of the account, as its card says."""
    devices = db.list_devices()
    own = config.get_device_id_hex()
    if args.format == "json":
        print(json.dumps(devices, indent=2))
        return 0
    if not devices:
        print("No device cards yet.")
        return 0
    for card in devices:
        marks = []
        if card["device_id"] == own:
            marks.append("this device")
        if card["revoked"]:
            marks.append("revoked")
        if card["listens"]:
            marks.append("listening")
        suffix = f"  ({', '.join(marks)})" if marks else ""
        print(f"{card['device_id']}  {card['name'] or '-'}  {card['application']}{suffix}")
        if card["certificate_fingerprint"]:
            print(f"    certificate {card['certificate_fingerprint']}")
        if card["addresses"]:
            print(f"    listens on {card['addresses']}")
    return 0


def cmd_device_revoke(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Revoke a device: its card says so, and every peer refuses it once told."""
    matches = [c for c in db.list_devices() if c["device_id"].startswith(args.device_id)]
    if not matches:
        print(f"Error: No device starts with {args.device_id}. Run 'device list'.", file=sys.stderr)
        return 1
    if len(matches) > 1:
        print(f"Error: {len(matches)} devices start with {args.device_id}; give more of the id.", file=sys.stderr)
        return 1
    card = matches[0]
    if card["device_id"] == config.get_device_id_hex():
        print("Error: This is this device. Revoke it from another device of the account.", file=sys.stderr)
        return 1
    db.revoke_device(card["device_id"])
    print(f"Revoked {card['name'] or card['device_id']}. Every peer refuses it once this has reached them.")
    print("It still holds the bucket key, if one was configured; replace the key if that matters.")
    return 0


def cmd_account_show(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Show which account this database belongs to."""
    notes = len(db.get_all_notes())
    if args.format == "json":
        print(json.dumps({
            "account_id": db.account_id(),
            "database_id": db.database_id(),
            "directory": str(config.get_config_dir()),
            "notes": notes,
        }, indent=2))
    else:
        print(f"Account: {db.account_id()}")
        print(f"Database: {db.database_id()}")
        print(f"Directory: {config.get_config_dir()}")
        print(f"Notes: {notes}")
    return 0


def _format_size(size_bytes: int) -> str:
    """A size in the unit a person reads."""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"


def _index_root(config: Config) -> Optional[str]:
    """The root with the account index, or None on a single-directory installation."""
    return _index_root_of(config.get_root())


def _index_root_of(root: Path) -> Optional[str]:
    """The root when it holds an account index or nothing yet (the index is
    then made), None when it is a single account's directory."""
    from voicecore import account_list
    if not (root / "accounts.db").is_file() and ((root / "notes.db").is_file() or (root / "config.json").is_file()):
        return None
    try:
        account_list(str(root))
    except Exception:  # noqa: BLE001
        return None
    return str(root)


def cmd_account_list(root: Optional[str], args: argparse.Namespace) -> int:
    """Every account of this installation."""
    from voicecore import account_list
    if root is None:
        print("This installation holds one account and no index; see 'account show'.")
        return 0
    accounts = account_list(root)
    if args.format == "json":
        print(json.dumps(accounts, indent=2))
        return 0
    for a in accounts:
        marks = [m for m, on in (("default", a["is_default"]), ("hosted", a["hosted"])) if on]
        suffix = f"  ({', '.join(marks)})" if marks else ""
        print(f"{a['account_id']}  {a['label']}{suffix}")
    return 0


def cmd_account_create(root: Optional[str], args: argparse.Namespace) -> int:
    """Make a new account on this installation."""
    from voicecore import account_create
    if root is None:
        print("Error: This installation holds one account and no index; set VOICE_CONFIG_DIR to an empty directory to start one with several.", file=sys.stderr)
        return 1
    try:
        entry = account_create(root, getattr(args, "label", None))
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(entry))
    else:
        print(f"Created account {entry['account_id']} ({entry['label']}) in {entry['directory']}")
        print(f"Open it with -a {entry['label']}")
    return 0


def cmd_account_default(root: Optional[str], args: argparse.Namespace) -> int:
    from voicecore import account_set_default
    if root is None:
        print("Error: This installation holds one account and no index.", file=sys.stderr)
        return 1
    try:
        account_set_default(root, args.selector)
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"{args.selector} is now the default account.")
    return 0


def cmd_account_remove(root: Optional[str], args: argparse.Namespace) -> int:
    from voicecore import account_remove
    if root is None:
        print("Error: This installation holds one account and no index.", file=sys.stderr)
        return 1
    try:
        account_remove(root, args.selector)
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Forgot {args.selector}. Its directory under {root} was not touched.")
    return 0


def cmd_account_recording_key(config: Config, args: argparse.Namespace) -> int:
    """Export or import the account's recording key (Stage 15, ENC-1)."""
    from voicecore import recording_key_export, recording_key_import

    config_dir = str(config.config_dir) if config.config_dir else None
    command = getattr(args, "recording_key_command", None)
    if command == "export":
        text = recording_key_export(config_dir)
        if not args.text_only:
            try:
                import segno

                segno.make(text, error="m").terminal(compact=True)
            except ImportError:
                print("(install segno to draw the QR code; the text below is the same key)")
        print(text)
        print("Recording key. Keep this on paper. Without it these recordings cannot be played.")
        return 0
    if command == "import":
        recording_key_import(args.text, config_dir)
        print("The recording key is kept; recordings in the bucket open on this device again.")
        return 0
    print("Error: say export or import", file=sys.stderr)
    return 1


def cmd_storage_encrypt(config: Config, args: argparse.Namespace) -> int:
    """Encryption of new uploads: on, off, or the state (ENC-3)."""
    from voicecore import encryption_state, set_encryption_on

    config_dir = str(config.config_dir) if config.config_dir else None
    if args.state:
        set_encryption_on(args.state == "on", config_dir)
    state = encryption_state(config_dir)
    print(f"Encryption of new uploads: {'on' if state['on'] else 'off'}")
    print(f"Recording key on this device: {'yes' if state['has_key'] else 'no'}; exported: {'yes' if state['exported'] else 'no'}")
    return 0


def cmd_storage_reupload_encrypted(config: Config, args: argparse.Namespace) -> int:
    """Send the plain objects' recordings up again encrypted (ENC-3)."""
    from voicecore import reupload_encrypted

    config_dir = str(config.config_dir) if config.config_dir else None
    result = reupload_encrypted(config_dir)
    print(f"Re-uploaded encrypted: {result.uploaded}; not on this device: {result.skipped}; failed: {result.failed}")
    for error in result.errors:
        print(f"  - {error}")
    return 0 if result.failed == 0 else 1


def cmd_account_show_code(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Show the code another device reads to join this account (PAIR-1)."""
    from voicecore import listen_urls, pairing_offer

    urls = getattr(args, "urls", None) or listen_urls(config.get_sync_server_port())
    if not urls:
        print("Error: This machine's address is not known; give it with --url.", file=sys.stderr)
        return 1
    text = pairing_offer(urls, str(config.get_config_dir()))
    return _print_setup_text(text, args, urls, [
        "Treat this like a password. It is valid for ten minutes and for one device;",
        "the listener must be running ('sync serve') for the other device to reach it.",
    ])


def _print_setup_text(text: str, args: argparse.Namespace, urls: List[str], last_lines: List[str]) -> int:
    """A setup text as a QR code (unless --text-only) and as text, with the warning lines."""
    if args.format == "json":
        print(json.dumps({"setup_text": text, "urls": urls}))
        return 0
    if not getattr(args, "text_only", False):
        try:
            import segno
            segno.make(text, error="m").terminal(compact=True)
        except ImportError:
            print("(install segno to draw the QR code; the text below is the same code)")
    print(text)
    print()
    for line in last_lines:
        print(line)
    return 0


def cmd_account_host(root: Path, args: argparse.Namespace) -> int:
    """Show the grant text with which a holder gives this server an account to host (PAIR-5)."""
    from voicecore import hosting_offer, listen_urls

    if _index_root_of(root) is None:
        print(f"Error: {root} holds one account in its own directory and cannot host others; "
              "set VOICE_CONFIG_DIR to an empty directory for a server.", file=sys.stderr)
        return 1
    urls = getattr(args, "urls", None) or listen_urls(_machine_port(root))
    if not urls:
        print("Error: This machine's address is not known; give it with --url.", file=sys.stderr)
        return 1
    text = hosting_offer(str(root), urls, getattr(args, "label", None))
    return _print_setup_text(text, args, urls, [
        "Treat this like a password. It is valid for ten minutes and for one account;",
        "the listener must be running ('sync serve') for the holder to reach it.",
        "On the device that holds the account: account grant-host <this text>.",
    ])


def _machine_port(root: Path) -> int:
    """The listen port of a root's machine settings, or the default."""
    try:
        return int(json.loads((root / "config.json").read_text(encoding="utf-8")).get("sync", {}).get("server_port") or 8384)
    except (OSError, ValueError):
        return 8384


def cmd_account_grant_host(config: Config, args: argparse.Namespace) -> int:
    """Give a server this device's account, by its grant text (PAIR-5)."""
    client = SyncClient(str(config.get_config_dir()))
    try:
        granted = client.grant_host(args.setup_text, getattr(args, "label", None) or "")
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(granted))
    else:
        print(f"{granted['peer_name']} ({granted['peer_id']}) at {granted['peer_url']} now hosts account {granted['account_id']}.")
        print(f"Run 'sync deliver {granted['peer_id']}' to send it your notes and recordings.")
    return 0


def cmd_account_hide_code(config: Config, args: argparse.Namespace) -> int:
    """Withdraw the code."""
    from voicecore import pairing_withdraw
    pairing_withdraw(str(config.get_config_dir()))
    print("The code is withdrawn.")
    return 0


def cmd_account_join(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Join an account from a setup text (PAIR-4)."""
    client = SyncClient(str(config.get_config_dir()))
    try:
        joined = client.join(args.setup_text)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(joined))
    else:
        print(f"Joined account {joined['account_id']}.")
        print(f"Peer: {joined['peer_name']} ({joined['peer_id']}) at {joined['peer_url']}")
        print("Run 'sync now' to exchange notes.")
    return 0


def cmd_account_snapshots(db: Database, args: argparse.Namespace) -> int:
    """List the snapshots beside the database, newest first."""
    snapshots = db.list_snapshots()
    if args.format == "json":
        print(json.dumps(snapshots, indent=2))
        return 0
    if not snapshots:
        print("No snapshots yet. One is taken before every sync, move and restore.")
        return 0
    for snap in snapshots:
        print(f"{snap['name']}  {snap['note_count']} notes  {_format_size(snap['size_bytes'])}")
    return 0


def cmd_account_snapshot(db: Database, args: argparse.Namespace) -> int:
    """Take a snapshot now."""
    path = db.snapshot()
    if args.format == "json":
        print(json.dumps({"path": path}))
    else:
        print(f"Snapshot written: {path}")
    return 0


def cmd_account_restore(db: Database, args: argparse.Namespace) -> int:
    """Replace the database with a snapshot, after a confirmation."""
    names = [snap["name"] for snap in db.list_snapshots()]
    if args.name not in names:
        print(f"Error: No snapshot named {args.name}. Run 'account snapshots' to list them.", file=sys.stderr)
        return 1
    if not getattr(args, "yes", False):
        answer = input(f"Replace the database with {args.name}? The current state is snapshotted first. [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing changed.")
            return 1
    db.restore_snapshot(args.name)
    print(f"Restored {args.name}. The state it replaced is the newest snapshot.")
    return 0


def cmd_account_move(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Move the database to another account: the deliberate way to merge two
    accounts. With a setup text, the other account's device is paired with, its
    tags are pulled and tags with one path become one, and everything is
    exchanged; with a bare id, only the id is rewritten."""
    current = db.account_id()
    if args.current_account != current:
        print(
            f"Error: This database belongs to account {current}; the id typed was {args.current_account}. "
            "Type the full current id to confirm the move.",
            file=sys.stderr,
        )
        return 1
    notes = len(db.get_all_notes())
    if args.to_account.startswith("voice://pair?"):
        db.close()
        client = SyncClient(str(config.get_config_dir()))
        try:
            moved = client.move_to(args.to_account)
        except Exception as e:  # noqa: BLE001
            print(f"Error: {e}", file=sys.stderr)
            return 1
        if args.format == "json":
            print(json.dumps({**moved, "notes_moved": notes}))
        else:
            print(f"Moved {notes} notes from account {current} to {moved['account_id']} through {moved['peer_name']}; {moved['tags_merged']} tags with one path became one.")
            print("A snapshot was taken first; every earlier peer was forgotten.")
        return 0
    if args.to_account == current:
        print("Error: That is already this database's account.", file=sys.stderr)
        return 1
    db.move_to_account(args.to_account)
    print(f"Moved {notes} notes from account {current} to {args.to_account}.")
    print("Every peer was forgotten; the next sync exchanges everything. A snapshot was taken first.")
    return 0


def cmd_account_backup(config: Config, args: argparse.Namespace) -> int:
    """The periodic backup, now (SNAP-5): every account of the root, or this one."""
    from voicecore import backup_now

    root = _index_root(config)
    try:
        made = backup_now(config_dir=None if root else str(config.get_config_dir()), root=root)
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps({"copies": made}))
    else:
        for path in made:
            print(f"Backed up to {path}")
        backup = config.get_backup()
        print(f"The listener and the desktop do this every {backup['interval_hours']} hours, keeping {backup['keep']} copies.")
    return 0


def _peer_by_prefix(config: Config, prefix: str) -> Optional[Dict[str, Any]]:
    matches = [p for p in config.get_peers() if p["peer_id"].startswith(prefix)]
    return matches[0] if len(matches) == 1 else None


def cmd_sync_check(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Check the connection to a peer, or with --all every peer and the bucket as one table (Stage 12, Stage 8)."""
    if getattr(args, "all", False):
        from src.core.storage_setup import check_everything
        rows = check_everything(str(config.get_config_dir()), config, db)
        passed = all(r["passed"] for r in rows)
        if args.format == "json":
            print(json.dumps({"passed": passed, "rows": rows}, indent=2))
        else:
            for r in rows:
                print(f"{'ok  ' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}{'  (' + r['code'] + ')' if r['code'] else ''}")
        return 0 if passed else 1
    if not args.peer_id:
        print("Error: give a peer id, or --all.", file=sys.stderr)
        return 1
    peer = _peer_by_prefix(config, args.peer_id)
    if peer is None:
        print(f"Error: No single peer starts with {args.peer_id}. Run 'sync list-peers'.", file=sys.stderr)
        return 1
    client = SyncClient(str(config.get_config_dir()))
    rows = client.check(peer["peer_id"])
    passed = all(r["passed"] for r in rows)
    if args.format == "json":
        print(json.dumps({"peer_id": peer["peer_id"], "passed": passed, "rows": rows}, indent=2))
        return 0 if passed else 1
    width = max(len(r["name"]) for r in rows)
    for r in rows:
        mark = "ok  " if r["passed"] else "FAIL"
        code = f"  ({r['code']})" if r["code"] else ""
        print(f"{mark}  {r['name']:<{width}}  {r['detail']}{code}")
    return 0 if passed else 1


def _request_line(result: Any) -> str:
    """The request id of an operation, for the end of its result (Stage 12)."""
    request_id = getattr(result, "request_id", "")
    return f"  Request {request_id}" if request_id else ""


def cmd_sync_operation(db: Database, config: Config, operation: str, args: argparse.Namespace) -> int:
    """Deliver, exchange, send or fetch with one peer (the terms table)."""
    peer = _peer_by_prefix(config, args.peer_id)
    if peer is None:
        print(f"Error: No single peer starts with {args.peer_id}. Run 'sync list-peers'.", file=sys.stderr)
        return 1
    from src.core.discovery import run_with_discovery
    client = SyncClient(str(config.get_config_dir()))
    method = getattr(client, {"deliver": "deliver", "exchange": "exchange", "send": "send_to_peer", "fetch": "fetch_from_peer"}[operation])
    result = run_with_discovery(config, db.account_id(), peer, method)
    if args.format == "json":
        print(json.dumps({"peer_id": peer["peer_id"], "operation": operation, **_sync_result_to_json(result)}, indent=2))
        return 0 if result.success else 1
    verb = operation.capitalize()
    parts = []
    if operation in ("deliver", "exchange"):
        parts.append(f"received {result.pulled} changes, sent {result.pushed}")
    if result.sent:
        parts.append(f"sent {result.sent} recordings")
    if result.fetched:
        parts.append(f"fetched {result.fetched} recordings")
    if result.bytes_moved:
        parts.append(f"{result.bytes_moved / (1024 * 1024):.1f} MB moved")
    sentence = ", ".join(parts) if parts else "nothing to move"
    if result.success:
        print(f"{verb} with {peer['peer_name']}: {sentence}.")
    else:
        print(f"{verb} with {peer['peer_name']} failed: {sentence}.")
        for error in result.errors:
            print(f"  - {error}")
    _print_sync_warnings(result, "  ")
    if _request_line(result):
        print(_request_line(result))
    return 0 if result.success else 1


def not_duplicated_sentence(counts: Dict[str, int]) -> str:
    """The one line of Stage 10: what exists on this device only."""
    notes, recordings = counts["notes"], counts["recordings"]
    if notes == 0 and recordings == 0:
        return "Everything is duplicated off this device."
    note_part = f"{notes} note{'s' if notes != 1 else ''}"
    recording_part = f"{recordings} recording{'s' if recordings != 1 else ''}"
    return f"{note_part} and {recording_part} are not duplicated off this device."


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
            "account_id": db.account_id(),
            "device_id": device_id,
            "device_name": device_name,
            "sync_enabled": sync_config.get("enabled", False),
            "server_port": sync_config.get("server_port", 8384),
            "peer_count": len(sync_config.get("peers", [])),
        }
        # Get conflict counts
        conflict_mgr = ConflictManager(db)
        status["conflicts"] = conflict_mgr.get_unresolved_count()
        status["not_duplicated"] = db.not_duplicated(config.get_audiofile_directory())
        status["peers"] = db.peer_summaries()
        print(json.dumps(status, indent=2))
    else:
        print(f"Account: {db.account_id()}")
        print(f"Device ID: {device_id}")
        print(f"Device Name: {device_name}")
        print(f"Sync Enabled: {sync_config.get('enabled', False)}")
        print(f"Server Port: {sync_config.get('server_port', 8384)}")
        print(f"Configured Peers: {len(sync_config.get('peers', []))}")
        print()
        print(not_duplicated_sentence(db.not_duplicated(config.get_audiofile_directory())))
        for peer in db.peer_summaries():
            reached = format_timestamp(peer["last_reached_at"]) if peer.get("last_reached_at") else "never"
            operation = f", last operation: {peer['last_operation']}" if peer.get("last_operation") else ""
            print(f"  {peer['peer_name'] or peer['peer_id']}: last reached {reached}{operation}")

        # Show conflict counts
        conflict_mgr = ConflictManager(db)
        counts = conflict_mgr.get_unresolved_count()
        if counts["total"] > 0:
            print(f"\nUnresolved Conflicts: {counts['total']}")
            labels = {
                "text": "Text edited on both sides",
                "delete": "Deleted on one side, changed on the other",
                "membership": "Link removed on one side, kept on the other",
                "scalar": "Value changed on both sides",
                "flags": "State changed on both sides",
            }
            for kind, label in labels.items():
                if counts.get(kind, 0) > 0:
                    print(f"  - {label}: {counts[kind]}")
            print("  Run 'sync conflicts' to list them.")

    return 0


def cmd_sync_list_peers(db: Database, config: Config, args: argparse.Namespace) -> int:
    """List configured sync peers.

    Args:
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success)
    """
    peers = config.get_peers()
    last = config.last_peer_id()
    summaries = {p["peer_id"]: p for p in db.peer_summaries()}
    for peer in peers:
        summary = summaries.get(peer["peer_id"], {})
        peer["last_reached_at"] = summary.get("last_reached_at")
        peer["last_operation"] = summary.get("last_operation") or ""
        peer["is_last"] = peer["peer_id"] == last

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
            print(f"  ID: {peer['peer_id']}{'  (last used)' if peer['is_last'] else ''}")
            print(f"  Name: {peer['peer_name']}")
            if peer["last_reached_at"]:
                print(f"  Last reached: {format_timestamp(peer['last_reached_at'])}, last operation: {peer['last_operation']}")
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
    config.forget_peer(peer_id)

    if args.format == "json":
        print(json.dumps({"removed": True, "peer_id": peer_id}))
    else:
        print(f"Forgot peer: {peer_name} ({peer_id}). Its card will not bring it back; add it again to undo.")

    return 0


def cmd_sync_rename_peer(config: Config, args: argparse.Namespace) -> int:
    """A local name for a peer, shown in place of its card's (Stage 5)."""
    peer = _peer_by_prefix(config, args.peer_id)
    if peer is None:
        print(f"Error: No single peer starts with {args.peer_id}. Run 'sync list-peers'.", file=sys.stderr)
        return 1
    try:
        config.rename_peer(peer["peer_id"], args.name)
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps({"renamed": True, "peer_id": peer["peer_id"], "name": args.name}))
    else:
        print(f"{peer['peer_id']} is called {args.name} on this device.")
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
        # Sync with specific peer; when it is not reached at the remembered
        # address, the network is asked where it is (Stage 7)
        from src.core.discovery import run_with_discovery
        client = SyncClient(str(config.get_config_dir()))
        peer = _peer_by_prefix(config, peer_id) or {"peer_id": peer_id, "peer_name": peer_id[:UUID_SHORT_LEN], "peer_url": ""}
        peer_id = peer["peer_id"]
        result = run_with_discovery(config, db.account_id(), peer, client.sync_with_peer)

        if args.format == "json":
            print(json.dumps({"peer_id": peer_id, **_sync_result_to_json(result)}, indent=2))
        else:
            if result.success:
                print(f"Sync with {peer_id} completed:")
                print(f"  Pulled: {result.pulled} changes")
                print(f"  Pushed: {result.pushed} changes")
                if result.conflicts > 0:
                    print(f"  Conflicts: {result.conflicts} (run 'sync conflicts')")
                if result.errors:
                    print(f"  Errors: {len(result.errors)}")
                    for error in result.errors:
                        print(f"    - {error}")
                _print_sync_warnings(result, "  ")
                if _request_line(result):
                    print(_request_line(result))
            else:
                print(f"Sync with {peer_id} failed:")
                for error in result.errors:
                    print(f"  - {error}")
                _print_sync_warnings(result, "  ")
                if _request_line(result):
                    print(_request_line(result))
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
            output = {pid: _sync_result_to_json(result) for pid, result in results.items()}
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
                _print_sync_warnings(result, "    ")

        return 0 if all_success else 1

    return 0


def _print_sync_warnings(result: Any, indent: str = "  ") -> None:
    """Print non-fatal sync warnings (e.g. cloud uploads to be retried)."""
    warnings = getattr(result, "warnings", None) or []
    if warnings:
        print(f"{indent}Warnings ({len(warnings)}):")
        for warning in warnings:
            print(f"{indent}  - {warning}")


def _sync_result_to_json(result: Any) -> Dict[str, Any]:
    """Serialise a SyncResult for --format json output."""
    return {
        "success": result.success,
        "pulled": result.pulled,
        "pushed": result.pushed,
        "conflicts": result.conflicts,
        "sent": getattr(result, "sent", 0),
        "fetched": getattr(result, "fetched", 0),
        "bytes_moved": getattr(result, "bytes_moved", 0),
        "errors": result.errors,
        "warnings": list(getattr(result, "warnings", None) or []),
        "request_id": getattr(result, "request_id", ""),
        "clock_skew_seconds": getattr(result, "clock_skew_seconds", 0),
    }


def _find_version(versions: list, prefix: str):
    """One version whose id starts with prefix; None if none, error text if ambiguous."""
    matches = [v for v in versions if v.id.startswith(prefix.lower())]
    if not matches:
        return None, f"No version starting with '{prefix}'"
    if len(matches) > 1:
        return None, f"Version prefix '{prefix}' is ambiguous ({len(matches)} matches)"
    return matches[0], None


def cmd_note_history(db: Database, args: argparse.Namespace) -> int:
    """List the versions of a note's content, or print one of them."""
    # Deleted notes keep their history too
    note = db.get_note(args.note_id) or db.get_note_raw(args.note_id)
    if not note:
        print(f"Error: Note with ID {args.note_id} not found.", file=sys.stderr)
        return 1
    mgr = ConflictManager(db)
    versions = mgr.get_field_history("note", note["id"], "content")
    version_id = getattr(args, "version_id", None)
    if version_id:
        v, err = _find_version(versions, version_id)
        if err:
            print(f"Error: {err}", file=sys.stderr)
            return 1
        if args.format == "json":
            print(json.dumps(v.__dict__, indent=2, ensure_ascii=False))
        else:
            print(v.content or "", end="" if (v.content or "").endswith("\n") else "\n")
        return 0
    if args.format == "json":
        print(json.dumps([v.__dict__ for v in versions], indent=2, ensure_ascii=False))
        return 0
    current = db.get_note_raw(note["id"]) or {}
    print(f"History of note {note['id'][:UUID_SHORT_LEN]} ({len(versions)} versions, oldest first):")
    for v in versions:
        kind = "merge" if v.merge_parent_id else ("root" if v.parent_id is None else "edit")
        if v.conflict_kind:
            kind += f", {v.conflict_kind} conflict"
        first_line = (v.content or "").split("\n", 1)[0]
        if len(first_line) > 60:
            first_line = first_line[:57] + "..."
        marker = " *" if (v.content or "") == current.get("content") else ""
        print(f"  [{v.id[:UUID_SHORT_LEN]}] {format_timestamp(v.created_at, v.created_at_offset)}  {v.device_label:<16} {kind:<22} {first_line}{marker}")
    print("  (* = current content)  Show one: note-history <note> --show <version>   Restore: note-restore <note> <version>")
    return 0


def cmd_note_restore(db: Database, args: argparse.Namespace) -> int:
    """Make an earlier version the current content: a normal edit that syncs."""
    note = db.get_note(args.note_id)
    if not note:
        print(f"Error: Note with ID {args.note_id} not found.", file=sys.stderr)
        return 1
    mgr = ConflictManager(db)
    versions = mgr.get_field_history("note", note["id"], "content")
    v, err = _find_version(versions, args.version_id)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    if (db.get_note_raw(note["id"]) or {}).get("content") == v.content:
        print("That version is already the current content.")
        return 0
    db.update_note(note["id"], v.content or "")
    print(f"Restored note {note['id'][:UUID_SHORT_LEN]} to version {v.id[:UUID_SHORT_LEN]} ({format_timestamp(v.created_at, v.created_at_offset)})")
    return 0


def cmd_sync_conflicts(db: Database, args: argparse.Namespace) -> int:
    """List sync conflicts.

    Every conflict is a field on which two devices disagreed. The merged
    value is already live (text keeps both versions between markers); the
    record exists so that the user reviews it.
    """
    conflict_mgr = ConflictManager(db)
    include_resolved = getattr(args, "all", False)
    conflicts = conflict_mgr.get_conflicts(include_resolved=include_resolved)

    note_filter = getattr(args, "note", None)
    if note_filter:
        note = db.get_note(note_filter)
        if not note:
            print(f"Error: Note with ID {note_filter} not found.", file=sys.stderr)
            return 1
        wanted = {c.id for c in conflict_mgr.get_note_conflicts(note["id"])}
        conflicts = [c for c in conflicts if c.id in wanted]

    show_details = getattr(args, "details", False)

    if args.format == "json":
        output = []
        for c in conflicts:
            item = c.to_dict()
            if show_details:
                v = conflict_mgr.get_conflict_versions(c)
                item["versions"] = {
                    "base": v.base.content if v.base else None,
                    "version_a": v.version_a.content if v.version_a else None,
                    "version_b": v.version_b.content if v.version_b else None,
                    "merge": v.merge.content if v.merge else None,
                }
            output.append(item)
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 0

    if not conflicts:
        if note_filter:
            print(f"No unresolved conflicts for note {note_filter}.")
        else:
            print("No unresolved conflicts.")
        return 0

    print(f"{'Conflicts' if include_resolved else 'Unresolved Conflicts'} ({len(conflicts)}):\n")
    for c in conflicts:
        state = " (resolved)" if c.is_resolved else ""
        print(f"  [{c.id[:UUID_SHORT_LEN]}] {c.entity_type} {c.entity_id[:UUID_SHORT_LEN]} {c.field}: {c.describe()}{state}")
        print(f"    Detected: {format_timestamp(c.created_at)}")
        if show_details:
            v = conflict_mgr.get_conflict_versions(c)
            for label, ver in (("Base", v.base), (c.device_a_label, v.version_a),
                               (c.device_b_label, v.version_b), ("Merged (current)", v.merge)):
                if ver is None:
                    continue
                print(f"    {label}:")
                for line in (ver.content or "").split("\n"):
                    print(f"      {line}")
            print()
    print("Resolve with: sync resolve <id>              (accept the merged value)")
    print("              sync resolve <id> --content-file FILE   (replace the value)")
    return 0


def cmd_sync_resolve(db: Database, args: argparse.Namespace) -> int:
    """Resolve a sync conflict.

    Without content the merged value is accepted as it stands. With
    --content-file or --content the field is set to the given text. Either
    way a new version is written, so the resolution reaches every peer.
    """
    conflict_mgr = ConflictManager(db)
    content: Optional[str] = None
    content_file = getattr(args, "content_file", None)
    inline = getattr(args, "content", None)
    if content_file and inline is not None:
        print("Error: use either --content-file or --content, not both", file=sys.stderr)
        return 1
    if content_file:
        try:
            content = Path(content_file).read_text(encoding="utf-8")
        except OSError as e:
            print(f"Error: cannot read {content_file}: {e}", file=sys.stderr)
            return 1
    elif inline is not None:
        content = inline

    success, conflict, error = conflict_mgr.find_and_resolve_conflict(args.conflict_id, content)
    if not success:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    what = f"{conflict.entity_type} {conflict.entity_id[:UUID_SHORT_LEN]} {conflict.field}"
    if content is None:
        print(f"Accepted merged value for {what}")
    else:
        print(f"Resolved {what} with the supplied content")
    return 0


CONFIG_KEYS = {
    "device_name": "Name shown on conflicts and in sync logs",
    "audiofile_directory": "Folder for audio files on this device",
    "default_interface": "Interface when none is given: gui, tui, cli or web",
    "sync.server_port": "Port of this device's sync server",
    "sync.enabled": "true or false",
    "sync.mirror_audio_files": "true or false: download every cloud audio file on each sync (desktop/server only)",
}


def cmd_config(config: Config, args: argparse.Namespace) -> int:
    """Show or change this device's local configuration (config.json)."""
    sub = getattr(args, "config_command", None)
    if sub == "set":
        key, value = args.key, args.value
        try:
            if key == "device_name":
                config.set_device_name(value)
            elif key == "audiofile_directory":
                path = Path(value).expanduser()
                path.mkdir(parents=True, exist_ok=True)
                config.set_audiofile_directory(str(path.resolve()))
            elif key == "sync.server_port":
                config.set_sync_server_port(int(value))
            elif key == "sync.enabled":
                config.set_sync_enabled(value.lower() in ("1", "true", "yes", "on"))
            elif key == "sync.mirror_audio_files":
                config.set_mirror_audio_files(value.lower() in ("1", "true", "yes", "on"))
            elif key == "default_interface":
                config.set("default_interface", value)
            else:
                print(f"Error: unknown key '{key}'. Known keys: {', '.join(CONFIG_KEYS)}", file=sys.stderr)
                return 1
        except (ValueError, OSError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        print(f"Set {key}")
        return 0

    def current() -> Dict[str, Any]:
        sync_cfg = config.get_sync_config()
        return {
            "directory": str(config.get_config_dir()),
            "device_id": config.get_device_id_hex(),
            "device_name": config.get_device_name(),
            "audiofile_directory": config.get_audiofile_directory(),
            "default_interface": config.get("default_interface"),
            "sync.server_port": sync_cfg.get("server_port"),
            "sync.enabled": sync_cfg.get("enabled"),
            "sync.mirror_audio_files": config.get_mirror_audio_files(),
        }

    if sub == "get":
        values = current()
        if args.key not in values:
            print(f"Error: unknown key '{args.key}'. Known keys: {', '.join(values)}", file=sys.stderr)
            return 1
        value = values[args.key]
        if args.format == "json":
            print(json.dumps({args.key: value}, ensure_ascii=False))
        else:
            print("" if value is None else str(value))
        return 0

    values = current()
    if args.format == "json":
        print(json.dumps(values, indent=2, ensure_ascii=False))
    else:
        for key, value in values.items():
            print(f"{key} = {'' if value is None else value}")
    return 0


def cmd_settings(config: Config, db: Database, args: argparse.Namespace) -> int:
    """Show or change synced settings (shared by every device)."""
    sub = getattr(args, "settings_command", None)
    if sub == "list" or sub is None:
        settings = db.get_all_settings()
        if args.format == "json":
            print(json.dumps(settings, indent=2, ensure_ascii=False))
        elif not settings:
            print("No synced settings.")
        else:
            for key in sorted(settings):
                value = settings[key]
                if key.endswith(".api_key") and value:
                    value = value[:4] + "…" if len(value) > 4 else "…"
                print(f"{key} = {value}")
        return 0
    if sub == "get":
        value = db.get_setting(args.key)
        if args.format == "json":
            print(json.dumps({args.key: value}, ensure_ascii=False))
        elif value is None:
            print(f"Error: setting '{args.key}' is not set", file=sys.stderr)
            return 1
        else:
            print(value)
        return 0
    if sub == "set":
        try:
            set_synced_setting(config, db, args.key, args.value)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        print(f"Set {args.key}")
        return 0
    print("Error: unknown settings command", file=sys.stderr)
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
                _print_sync_warnings(result, "  ")
            else:
                print(f"Full re-sync with {peer_id} failed:")
                for error in result.errors:
                    print(f"  - {error}")
                _print_sync_warnings(result, "  ")
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
                _print_sync_warnings(result, "    ")

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
    # An indexed root is served whole, every account in it (Stage 3); a
    # directory that is the account itself is served alone.
    root = _index_root(config)
    port = getattr(args, 'port', None) or config.get_sync_server_port()
    return _serve(str(config.get_config_dir()) if root is None else None, root, port, args)


def cmd_sync_serve_root(root: Path, args: argparse.Namespace) -> int:
    """'sync serve' on a root that holds no account of its own: every hosted account."""
    port = getattr(args, 'port', None) or _machine_port(root)
    return _serve(None, str(root), port, args)


def _announcers(config_dir: Optional[str], root: Optional[str], port: int) -> List[Any]:
    """One announcement per account served (Stage 7): the hash of its id, this device, the fingerprint."""
    from voicecore import account_list, certificate_fingerprint
    from src.core.discovery import Announcer

    machine_dir = root or config_dir
    try:
        fingerprint = certificate_fingerprint(str(machine_dir))
    except Exception:  # noqa: BLE001 - made when the listener starts
        fingerprint = ""
    machine = Config(config_dir=Path(config_dir) if config_dir else Path(root), root=Path(root) if root else None)
    accounts = []
    if root:
        try:
            accounts = [a["account_id"] for a in account_list(root)]
        except Exception:  # noqa: BLE001
            accounts = []
    elif config_dir:
        try:
            accounts = [Database(Path(machine.get("database_file"))).account_id()]
        except Exception:  # noqa: BLE001
            accounts = []
    return [Announcer(a, machine.get_device_id_hex(), machine.get_device_name(), port, fingerprint) for a in accounts if a]


def _serve(config_dir: Optional[str], root: Optional[str], port: int, args: argparse.Namespace) -> int:
    verbose = getattr(args, 'verbose', False)
    no_color = getattr(args, 'no_color', False)
    plain_http = getattr(args, 'plain_http', False)

    # Announced on the network while serving, unless plain http (loopback only)
    announcers = [] if plain_http or getattr(args, "no_announce", False) else _announcers(config_dir, root, port)
    for announcer in announcers:
        try:
            announcer.start()
        except Exception as e:  # noqa: BLE001 - serving does not depend on it
            print(f"Not announced on the network: {e}", file=sys.stderr)

    # Use Rust sync server via voicecore bindings
    # The server handles its own startup message and Ctrl-C
    try:
        start_sync_server(
            config_dir=config_dir,
            host=getattr(args, 'host', '0.0.0.0'),
            port=port,
            plain_http=plain_http,
            verbose=verbose,
            ansi_colors=not no_color,
            root=root,
        )
    except KeyboardInterrupt:
        # Rust already handled the shutdown, just exit cleanly
        pass
    finally:
        for announcer in announcers:
            announcer.stop()

    return 0


def cmd_sync_discover(db: Database, config: Config, args: argparse.Namespace) -> int:
    """The devices of this account announcing on the network (Stage 7)."""
    from src.core.discovery import browse

    found = browse(db.account_id(), float(getattr(args, "timeout", 3.0)))
    known = {p["peer_id"] for p in config.get_peers()}
    if args.format == "json":
        print(json.dumps([{"device_id": f.device_id, "name": f.name, "urls": f.urls, "certificate_fingerprint": f.certificate_fingerprint, "is_peer": f.device_id in known} for f in found], indent=2))
        return 0
    if not found:
        print("No device of this account is announcing on this network.")
        return 0
    for f in found:
        mark = "peer" if f.device_id in known else "not a peer yet: sync add-peer, or pair"
        print(f"{f.name} ({f.device_id[:UUID_SHORT_LEN]}) at {', '.join(f.urls)}  [{mark}]")
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


def cmd_maintenance_rebuild_cache(db: Database, args: argparse.Namespace) -> int:
    """Rebuild all cache fields for notes.

    The cache fields store pre-computed data for faster display:
    - di_cache_note_pane_display: Tags, conflicts, attachments for Note pane
    - di_cache_note_list_pane_display: Date, marked status, content preview for List pane

    Args:
        db: Database instance
        args: Parsed command-line arguments (optional note_id)

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        note_id = getattr(args, 'note_id', None)
        if note_id:
            print(f"Rebuilding all caches for note {note_id}...")
            db.rebuild_all_caches_for_note(note_id)
            print("Cache rebuild complete.")
        else:
            print("Rebuilding all caches for all notes...")
            result = db.rebuild_all_database_caches()
            print(f"Cache rebuild complete.")
            print(f"  Notes processed: {result['notes_processed']}")
            print(f"  Cache fields rebuilt: {result['cache_fields_rebuilt']}")
            if result.get('errors'):
                print(f"  Errors: {len(result['errors'])}")
                for error in result['errors']:
                    print(f"    - {error}")
        return 0
    except Exception as e:
        print(f"Error rebuilding cache: {e}", file=sys.stderr)
        return 1


def cmd_maintenance_rebuild_all_caches(db: Database, args: argparse.Namespace) -> int:
    """Rebuild all di_* cache fields in the entire database.

    Uses the cache registry to identify all cache fields across all tables
    and rebuilds them.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        verbose = getattr(args, 'verbose', False)

        # Show cache registry info if verbose
        if verbose:
            print("Cache Registry:")
            registry = db.get_cache_registry_info()
            for entry in registry:
                print(f"  {entry['table']}.{entry['column']}")
                print(f"    {entry['description']}")
            print()

        print("Rebuilding all database caches...")
        result = db.rebuild_all_database_caches()

        print(f"Cache rebuild complete.")
        print(f"  Notes processed: {result['notes_processed']}")
        print(f"  Cache fields rebuilt: {result['cache_fields_rebuilt']}")
        if result.get('errors'):
            print(f"  Errors: {len(result['errors'])}")
            for error in result['errors']:
                print(f"    - {error}")

        return 0 if not result.get('errors') else 1
    except Exception as e:
        print(f"Error rebuilding caches: {e}", file=sys.stderr)
        return 1


def cmd_calculate_missing_data(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Calculate data that was never calculated: lengths, dates, caches.

    One operation covering every gap that can be closed, with a survey first so
    the user can see what is missing before anything changes. See
    `core.missing_data`.

    Args:
        db: Database instance
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    from src.core import missing_data

    survey = missing_data.survey(db, config)
    print("What is missing:")
    print(survey.summary())

    if getattr(args, "dry_run", False):
        return 0
    if not survey.total_calculable:
        return 0

    print()
    report = missing_data.calculate_missing_data(
        db, config,
        durations=not getattr(args, "no_durations", False),
        file_dates=not getattr(args, "no_dates", False),
        caches=not getattr(args, "no_caches", False),
        limit=getattr(args, "limit", None),
        progress=lambda line: print(f"  {line}"),
    )
    print()
    print("Calculated:")
    print(report.summary())
    for detail in report.details:
        print(detail)
    return 0


def cmd_maintenance_audio_rebuild_durations(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Calculate the length of Recordings that have none.

    The durations half of ``calculate-missing-data``, kept under its old name.
    The work itself is in ``src/core/missing_data.py``, which every interface
    uses, so there is one rule for what a length is read from rather than two.

    Args:
        db: Database instance
        config: Configuration object
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    from src.core import missing_data

    try:
        dry_run = getattr(args, 'dry_run', False)

        if not config.get_audiofile_directory():
            print("Error: audiofile_directory not configured.", file=sys.stderr)
            print("Run: voice config set audiofile_directory /path/to/audio/files", file=sys.stderr)
            return 1

        survey = missing_data.survey(db, config)
        missing = next((g.count for g in survey.gaps if g.key == "duration"), 0)
        if not missing:
            print("All audio files have duration set.")
            return 0

        print(f"Found {missing} audio files with missing duration.")
        if dry_run:
            print("Dry run - no changes will be made.")
            return 0

        report = missing_data.calculate_missing_data(
            db, config,
            durations=True, file_dates=False, caches=False,
            limit=getattr(args, 'limit', None),
            progress=lambda line: print(f"  {line}"),
        )
        updated = report.calculated.get("duration", 0)
        errors = report.failed.get("duration", 0) + report.failed.get("absent_file", 0)
        print(f"\nSummary: {updated} updated, {errors} errors, {missing - updated - errors} skipped")
        return 0 if errors == 0 else 1
    except Exception as e:
        print(f"Error rebuilding audio durations: {e}", file=sys.stderr)
        return 1


# ============================================================================
# Storage commands
# ============================================================================

def cmd_storage_status(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Show current cloud storage configuration.

    Args:
        db: Database instance
        config: Config instance (for local-only options such as mirroring)
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        mirror = config.get_mirror_audio_files()
        config = db.get_file_storage_config()
        output_format = getattr(args, 'format', 'text')

        if output_format == "json":
            payload = dict(config) if config else {"provider": "none", "config": None}
            payload["mirror_audio_files"] = mirror
            print(json.dumps(payload))
        else:
            if config:
                provider = config.get("provider", "none")
                if provider == "none":
                    print("Cloud storage: Disabled")
                    print("Audio files are stored locally only.")
                else:
                    print(f"Cloud storage: Enabled ({provider})")
                    storage_config = config.get("config", {})
                    if provider == "s3":
                        print(f"  Bucket: {storage_config.get('bucket', 'N/A')}")
                        print(f"  Region: {storage_config.get('region', 'N/A')}")
                        if storage_config.get("prefix"):
                            print(f"  Prefix: {storage_config.get('prefix')}")
                        if storage_config.get("endpoint"):
                            print(f"  Endpoint: {storage_config.get('endpoint')}")
                        print(f"  Access Key ID: {storage_config.get('access_key_id', 'N/A')[:8]}...")
            else:
                print("Cloud storage: Not configured")
                print("Audio files are stored locally only.")
            if mirror:
                print("Mirror: enabled (every sync downloads all cloud audio files to this device)")
            else:
                print("Mirror: disabled (audio files are downloaded on demand)")
        return 0
    except Exception as e:
        print(f"Error getting storage configuration: {e}", file=sys.stderr)
        return 1


def cmd_storage_mirror(config: Config, args: argparse.Namespace) -> int:
    """Enable or disable mirroring of all cloud audio files on this device.

    Mirroring is local-only and intended for desktop or server installations
    that should hold a complete copy of the media as a backup of the bucket.
    """
    enable = args.mirror_action == "enable"
    config.set_mirror_audio_files(enable)
    if enable:
        print("Mirror enabled: every sync will download all cloud audio files to this device.")
        print("Run 'storage download-missing' to fetch everything now.")
    else:
        print("Mirror disabled: audio files will be downloaded on demand only.")
    return 0


def cmd_storage_download_missing(config: Config, args: argparse.Namespace) -> int:
    """Download every audio file that is in cloud storage but not on this device."""
    if not config.get_audiofile_directory():
        print("Error: audiofile_directory not configured.", file=sys.stderr)
        print("Run: voice config set audiofile_directory /path/to/audio/files", file=sys.stderr)
        return 1

    print("Downloading audio files that are in cloud storage but not on this device...")
    try:
        result = download_missing_audio_files(config.get_config_dir())
    except RuntimeError as e:
        print(f"Error downloading files: {e}", file=sys.stderr)
        return 1

    print(f"Download complete: {describe_download_result(result)}")
    for error in result.errors:
        print(f"  - {error}", file=sys.stderr)
    return 0 if result.failed == 0 else 1


def cmd_storage_configure_s3(db: Database, args: argparse.Namespace) -> int:
    """Configure S3 storage for audio files.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        s3_config = {
            "bucket": args.bucket,
            "region": args.region,
            "access_key_id": args.access_key_id,
            "secret_access_key": args.secret_access_key,
        }

        if args.prefix:
            s3_config["prefix"] = args.prefix
        if args.endpoint:
            s3_config["endpoint"] = args.endpoint

        db.set_file_storage_config("s3", json.dumps(s3_config))

        print(f"S3 storage configured successfully.")
        print(f"  Bucket: {args.bucket}")
        print(f"  Region: {args.region}")
        if args.prefix:
            print(f"  Prefix: {args.prefix}")
        if args.endpoint:
            print(f"  Endpoint: {args.endpoint}")
        print("\nThis configuration will sync to other devices.")
        return 0
    except Exception as e:
        print(f"Error configuring S3 storage: {e}", file=sys.stderr)
        return 1


def cmd_storage_setup(db: Database, config: Config, args: argparse.Namespace) -> int:
    """The bucket wizard from the command line (Stage 8): the same steps as the
    GUI's, asked one at a time, or taken from the flags with --yes."""
    from src.core import storage_setup

    state = storage_setup.SetupState()
    quiet = args.format == "json" or getattr(args, "yes", False)

    def ask(prompt: str, default: str = "", secret: bool = False) -> str:
        if secret:
            import getpass
            return getpass.getpass(prompt)
        answer = input(f"{prompt}{' [' + default + ']' if default else ''}: ").strip()
        return answer or default

    if not quiet:
        print("Make the key in the Amazon console, one step at a time:")
        for n, step in enumerate(storage_setup.CONSOLE_STEPS, 1):
            print(f"  {n}. {step}")
        print("\nThe policy text to paste in step 3:\n")
        print(storage_setup.policy_text())
        print()
    key_id = getattr(args, "access_key_id", None) or ask("Access key ID")
    secret = getattr(args, "secret_access_key", None) or ask("Secret access key: ", secret=True)
    state.endpoint = (getattr(args, "endpoint", None) or ("" if quiet else ask("Endpoint (empty for Amazon)"))).strip()
    problem = storage_setup.take_key(state, key_id, secret)
    if problem:
        print(f"Error: {problem}", file=sys.stderr)
        return 1
    region = getattr(args, "region", None)
    if not region:
        nearest = storage_setup.nearest_region() or "us-east-1"
        region = nearest if quiet else ask("Region", nearest)
    state.region = region
    state.bucket = getattr(args, "bucket", None) or (storage_setup.suggest_bucket_name() if quiet else ask("Bucket name", storage_setup.suggest_bucket_name()))
    state.prefix = (getattr(args, "prefix", None) or "").strip()

    report: Dict[str, Any] = {"bucket": state.bucket, "region": state.region, "saved": False}
    problem = storage_setup.create_bucket(state)
    if problem:
        report["error"] = f"Not made: {problem}"
        print(json.dumps(report) if args.format == "json" else f"Error: {report['error']}", file=sys.stdout if args.format == "json" else sys.stderr)
        return 1
    report["hardened"] = storage_setup.harden(state)
    lifecycle_problem = storage_setup.set_lifecycle(state)
    report["lifecycle"] = lifecycle_problem or "set"
    trip_problem = storage_setup.round_trip(state)
    report["round_trip"] = trip_problem or "passed"
    if trip_problem:
        print(json.dumps(report) if args.format == "json" else f"Error: the round trip failed: {trip_problem}", file=sys.stdout if args.format == "json" else sys.stderr)
        return 1
    storage_setup.save(state, db)
    report["saved"] = True
    if args.format == "json":
        print(json.dumps(report, indent=2))
        return 0
    print(f"Bucket {state.bucket} in {state.region}: made, private.")
    for row in report["hardened"]:
        print(f"  {'ok  ' if row['passed'] else 'FAIL'} {row['name']}: {row['detail']}")
    print(f"  {'ok  ' if not lifecycle_problem else 'FAIL'} Lifecycle rules: {report['lifecycle']}")
    print("  ok   Round trip: a small object was written, read back and compared.")
    print("Saved. Every device of the account receives the bucket at its next sync; the phone can upload after that.")
    print(storage_setup.WHAT_THE_BUCKET_HOLDS)
    return 0


def cmd_storage_replace_key(db: Database, args: argparse.Namespace) -> int:
    """A new key for the existing bucket (Stage 14), tested exactly as the first."""
    from src.core import storage_setup

    secret = getattr(args, "secret_access_key", None)
    if not secret:
        import getpass
        secret = getpass.getpass("New secret access key: ")
    problem = storage_setup.replace_key(db, args.access_key_id, secret)
    if problem:
        print(f"Error: {problem}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps({"replaced": True}))
    else:
        print("Saved. Every device gets the new key at its next sync; deactivate the old key in the console (Users → voice → Security credentials).")
    return 0


def cmd_storage_check(config: Config, args: argparse.Namespace) -> int:
    """The bucket as it is: one row per thing that can be wrong."""
    from voicecore import bucket_check

    rows = bucket_check(str(config.get_config_dir()))
    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"{'ok  ' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    return 0 if all(r["passed"] for r in rows) else 1


def cmd_storage_disable(db: Database, args: argparse.Namespace) -> int:
    """Disable cloud storage.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        db.set_file_storage_config("none", None)
        print("Cloud storage disabled.")
        print("Audio files will be stored locally only.")
        return 0
    except Exception as e:
        print(f"Error disabling storage: {e}", file=sys.stderr)
        return 1


def cmd_storage_upload_pending(config: Config, args: argparse.Namespace) -> int:
    """Upload pending audio files to cloud storage.

    Args:
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    from voicecore import upload_pending_audio_files

    try:
        config_dir = config.config_dir
        print(f"Uploading pending audio files to cloud storage...")

        result = upload_pending_audio_files(str(config_dir) if config_dir else None)

        print(f"\nUpload complete:")
        print(f"  Uploaded: {result.uploaded}")
        print(f"  Skipped:  {result.skipped} (not on this device; their own device uploads them)")
        print(f"  Failed:   {result.failed}")
        if result.deferred:
            print(f"  Deferred: {result.deferred} (not attempted after a failure; retried on next sync)")

        if result.errors:
            print("\nErrors:")
            for error in result.errors:
                print(f"  - {error}")

        return 0 if result.failed == 0 else 1
    except Exception as e:
        print(f"Error uploading files: {e}", file=sys.stderr)
        return 1


def cmd_delete_note(db: Database, args: argparse.Namespace) -> int:
    """Soft-delete a note (its history is kept and the deletion syncs)."""
    note = db.get_note(args.note_id)
    if not note:
        print(f"Error: Note with ID {args.note_id} not found.", file=sys.stderr)
        return 1
    db.delete_note(note["id"])
    if args.format == "json":
        print(json.dumps({"id": note["id"], "deleted": True}))
    else:
        print(f"Deleted note {note['id'][:UUID_SHORT_LEN]} (it is in the trash: see trash-list, note-recover)")
    return 0


def cmd_trash_list(db: Database, args: argparse.Namespace) -> int:
    """List the notes in the trash: deleted, still here, newest first."""
    notes = db.get_deleted_notes()

    if args.format == "json":
        print(json.dumps(notes, indent=2, ensure_ascii=False))
        return 0

    if not notes:
        print("The trash is empty.")
        return 0

    for note in notes:
        lines = [line.strip() for line in note["content"].split("\n") if line.strip()]
        first_line = lines[0] if lines else "(no text)"
        if len(first_line) > 80:
            first_line = first_line[:80] + "..."
        deleted = format_timestamp(note.get("deleted_at"), note.get("deleted_at_offset"))
        print(f"{note['id'][:UUID_SHORT_LEN]} | deleted {deleted} | {first_line}")
    print()
    print(f"{len(notes)} note(s) in the trash. "
          "Recover one with note-recover <id>, remove it for good with note-purge <id>.")
    return 0


def cmd_note_recover(db: Database, args: argparse.Namespace) -> int:
    """Take a note out of the trash."""
    try:
        recovered = db.undelete_note(args.note_id)
    except ValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if not recovered:
        print(f"Error: No note with ID {args.note_id} is in the trash.", file=sys.stderr)
        return 1
    note = db.get_note(args.note_id)
    if args.format == "json":
        print(json.dumps({"id": note["id"] if note else args.note_id, "recovered": True}))
    else:
        print(f"Recovered note {note['id'][:UUID_SHORT_LEN] if note else args.note_id}")
    return 0


def cmd_note_purge(db: Database, args: argparse.Namespace) -> int:
    """Remove a note in the trash for good, here and on every device."""
    notes = {n["id"]: n for n in db.get_deleted_notes()}
    match = None
    for note_id, note in notes.items():
        if note_id == args.note_id or note_id.startswith(args.note_id):
            if match is not None:
                print(f"Error: {args.note_id} matches more than one note in the trash.", file=sys.stderr)
                return 1
            match = note
    if match is None:
        print(f"Error: No note with ID {args.note_id} is in the trash.", file=sys.stderr)
        return 1

    if not args.yes:
        lines = [line.strip() for line in match["content"].split("\n") if line.strip()]
        first_line = lines[0] if lines else "(no text)"
        print(f"About to remove note {match['id'][:UUID_SHORT_LEN]} for good: {first_line[:80]}")
        print("This cannot be undone, and it removes the note from every device it syncs with.")
        answer = input("Type the word 'delete' to go ahead: ")
        if answer.strip().lower() != "delete":
            print("Nothing was removed.")
            return 1

    audio_ids = db.purge_note(match["id"])
    removed_files = _remove_audio_files(audio_ids)

    if args.format == "json":
        print(json.dumps({"id": match["id"], "purged": True, "audio_files": audio_ids,
                          "files_removed": removed_files}))
    else:
        print(f"Removed note {match['id'][:UUID_SHORT_LEN]} for good"
              + (f", with {len(audio_ids)} recording(s)" if audio_ids else ""))
    return 0


def _remove_audio_files(audio_ids: List[str]) -> List[str]:
    """Delete the files of recordings that were purged, and say which went.

    The database says which recordings were removed; where their files live
    is the application's business, not the core's.
    """
    removed: List[str] = []
    if not audio_ids:
        return removed
    config = Config()
    directory = config.get_audiofile_directory()
    if not directory:
        return removed
    folder = Path(directory)
    for audio_id in audio_ids:
        for path in folder.glob(f"{audio_id}.*"):
            try:
                path.unlink()
                removed.append(str(path))
            except OSError as e:
                print(f"Warning: could not delete {path}: {e}", file=sys.stderr)
    return removed


def cmd_rename_tag(db: Database, args: argparse.Namespace) -> int:
    """Rename a tag. A concurrent rename elsewhere is merged and flagged."""
    try:
        tag = db.get_tag(args.tag_id)
    except ValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if not tag:
        print(f"Error: Tag with ID {args.tag_id} not found.", file=sys.stderr)
        return 1
    try:
        db.rename_tag(tag["id"], args.name)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps({"id": tag["id"], "name": args.name}, ensure_ascii=False))
    else:
        print(f"Renamed tag '{tag['name']}' to '{args.name}'")
    return 0


def cmd_move_tag(db: Database, args: argparse.Namespace) -> int:
    """Move a tag under another tag, or to the top level with --root."""
    try:
        tag = db.get_tag(args.tag_id)
    except ValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if not tag:
        print(f"Error: Tag with ID {args.tag_id} not found.", file=sys.stderr)
        return 1
    parent = None
    if not getattr(args, "root", False):
        if not args.parent:
            print("Error: give a parent tag ID or --root", file=sys.stderr)
            return 1
        parent_tag = db.get_tag(args.parent)
        if not parent_tag:
            print(f"Error: Tag with ID {args.parent} not found.", file=sys.stderr)
            return 1
        parent = parent_tag["id"]
    try:
        db.reparent_tag(tag["id"], parent)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps({"id": tag["id"], "parent_id": parent}))
    else:
        print(f"Moved tag '{tag['name']}' " + (f"under {parent[:UUID_SHORT_LEN]}" if parent else "to the top level"))
    return 0


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
        help="Create a new Note"
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

    # note-delete command
    delete_note_parser = cli_subparsers.add_parser(
        "note-delete",
        help="Delete a note (soft delete: history is kept, the deletion syncs)"
    )
    delete_note_parser.add_argument("note_id", type=str, help="Note ID (UUID hex string, prefix allowed)")

    # tag-rename / tag-move commands
    rename_tag_parser = cli_subparsers.add_parser("tag-rename", help="Rename a tag")
    rename_tag_parser.add_argument("tag_id", type=str, help="Tag ID (UUID hex string, prefix allowed)")
    rename_tag_parser.add_argument("name", type=str, help="New name")
    move_tag_parser = cli_subparsers.add_parser("tag-move", help="Move a tag under another tag or to the top level")
    move_tag_parser.add_argument("tag_id", type=str, help="Tag ID (UUID hex string, prefix allowed)")
    move_tag_parser.add_argument("parent", nargs="?", type=str, help="New parent tag ID")
    move_tag_parser.add_argument("--root", action="store_true", help="Move to the top level")

    # note-history command
    history_parser = cli_subparsers.add_parser(
        "note-history",
        help="List every version of a note's content (oldest first)"
    )
    history_parser.add_argument("note_id", type=str, help="Note ID (UUID hex string, prefix allowed)")
    history_parser.add_argument(
        "--show",
        dest="version_id",
        type=str,
        help="Print the full content of one version (ID or prefix) instead of the list"
    )

    # note-restore command
    restore_parser = cli_subparsers.add_parser(
        "note-restore",
        help="Make an earlier version the current content (a new edit; nothing is lost)"
    )
    restore_parser.add_argument("note_id", type=str, help="Note ID (UUID hex string, prefix allowed)")
    restore_parser.add_argument("version_id", type=str, help="Version ID (or prefix) from note-history")

    # trash-list command
    cli_subparsers.add_parser(
        "trash-list",
        help="List the notes in the trash (deleted, recoverable)"
    )

    # note-recover command
    recover_parser = cli_subparsers.add_parser(
        "note-recover",
        help="Take a note out of the trash"
    )
    recover_parser.add_argument("note_id", type=str, help="Note ID (UUID hex string, prefix allowed)")

    # note-purge command
    purge_parser = cli_subparsers.add_parser(
        "note-purge",
        help="Remove a note in the trash for good, on every device"
    )
    purge_parser.add_argument("note_id", type=str, help="Note ID (UUID hex string, prefix allowed)")
    purge_parser.add_argument(
        "--yes",
        action="store_true",
        help="Do not ask for confirmation (for scripts)"
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

    # audiofile-download command
    download_audio_parser = cli_subparsers.add_parser(
        "audiofile-download",
        help="Download an audio file from cloud storage to this device"
    )
    download_audio_parser.add_argument(
        "audio_id",
        type=str,
        help="Audio file ID (or prefix) to download"
    )

    # note-audiofiles-download command
    download_note_parser = cli_subparsers.add_parser(
        "note-audiofiles-download",
        help="Download all missing audio files attached to a note from cloud storage"
    )
    download_note_parser.add_argument(
        "note_id",
        type=str,
        help="Note ID (or prefix) whose audio files to download"
    )

    # transcription-queue command
    queue_parser = cli_subparsers.add_parser(
        "transcription-queue",
        help="What is waiting to be transcribed here, what is running, and what it cost"
    )
    queue_parser.add_argument(
        "--next",
        dest="next",
        metavar="RECORDING",
        help="Transcribe this Recording next (id or the first characters of one)"
    )
    queue_parser.add_argument(
        "--remove",
        dest="remove",
        metavar="RECORDING",
        help="Take this Recording out of the queue"
    )
    queue_parser.add_argument(
        "--clear",
        action="store_true",
        help="Forget everything waiting (what is running is not stopped)"
    )
    queue_parser.add_argument(
        "--run",
        action="store_true",
        help="Transcribe what is waiting, one at a time, and wait for it"
    )
    queue_parser.add_argument(
        "--limit",
        type=int,
        help="With --run: transcribe at most this many"
    )
    queue_parser.add_argument(
        "--service",
        help="Only this transcription service's finished work (e.g. local_whisper)"
    )
    queue_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)"
    )

    # transcribe-backlog command
    backlog_parser = cli_subparsers.add_parser(
        "transcribe-backlog",
        help="Transcribe long Recordings the phone could not (this machine only, opt in)"
    )
    backlog_parser.add_argument(
        "--min-minutes",
        dest="min_minutes",
        type=int,
        help="Only Recordings at least this long (default: the phone's limit, 10)"
    )
    backlog_parser.add_argument(
        "--limit",
        type=int,
        help="Transcribe at most this many in one run"
    )
    backlog_parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="List what is waiting and stop"
    )
    backlog_parser.add_argument(
        "--force",
        action="store_true",
        help="Transcribe them even though this machine is not set to"
    )
    backlog_parser.add_argument(
        "--enable",
        action="store_true",
        help="Set this machine to transcribe long Recordings, and stop"
    )
    backlog_parser.add_argument(
        "--disable",
        action="store_true",
        help="Set this machine not to transcribe long Recordings, and stop"
    )
    backlog_parser.add_argument(
        "--language",
        type=str,
        help="Language hint (ISO 639-1 code, e.g., 'en', 'he')"
    )
    backlog_parser.add_argument(
        "--model",
        type=str,
        help="Model name or path"
    )
    backlog_parser.add_argument(
        "--backend",
        type=str,
        default="local_whisper",
        help="Transcription backend (default: local_whisper)"
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
        choices=["local_whisper", "assemblyai", "google_cloud", "speechtext_ai"],
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
    transcribe_audio_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging (shows HTTP requests/responses)"
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
        choices=["local_whisper", "assemblyai", "google_cloud", "speechtext_ai"],
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
    transcribe_note_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging (shows HTTP requests/responses)"
    )

    # sync command with subcommands
    sync_parser = cli_subparsers.add_parser(
        "sync",
        help="Sync operations (status, peers, conflicts)"
    )
    sync_subparsers = sync_parser.add_subparsers(dest="sync_command", help="Sync commands")

    # sync status
    sync_subparsers.add_parser("status", help="Show sync status and device info")

    # sync discover
    discover_parser = sync_subparsers.add_parser("discover", help="The devices of this account announcing on the local network")
    discover_parser.add_argument("--timeout", type=float, default=3.0, help="Seconds to listen for answers (default 3)")

    # sync check
    check_parser = sync_subparsers.add_parser("check", help="Check the connection to a peer: reachability, certificate, account, key, clock, free space, listener, each with its code")
    check_parser.add_argument("peer_id", type=str, nargs="?", help="Peer device ID, or a unique prefix of it")
    check_parser.add_argument("--all", action="store_true", help="Every peer and the bucket, as one table")

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

    # sync deliver / exchange / send / fetch: the file operations of the terms table
    for name, help_text in [
        ("deliver", "Sync, then send the recordings the peer lacks"),
        ("exchange", "Sync, then send the recordings the peer lacks and fetch the ones this device lacks"),
        ("send", "Send the recordings the peer lacks, without a sync"),
        ("fetch", "Fetch the recordings this device lacks from the peer, without a sync"),
    ]:
        op_parser = sync_subparsers.add_parser(name, help=help_text)
        op_parser.add_argument("peer_id", type=str, help="Peer device ID, or a unique prefix of it")

    # sync remove-peer
    remove_peer_parser = sync_subparsers.add_parser("remove-peer", help="Forget a peer on this device: it leaves the list and its card does not bring it back")
    remove_peer_parser.add_argument("peer_id", type=str, help="Peer device ID to forget")

    # sync rename-peer
    rename_peer_parser = sync_subparsers.add_parser("rename-peer", help="A local name for a peer, shown in place of its card's")
    rename_peer_parser.add_argument("peer_id", type=str, help="Peer device ID, or a unique prefix of it")
    rename_peer_parser.add_argument("name", type=str, help="The name")

    # sync now
    sync_now_parser = sync_subparsers.add_parser("now", help="Perform sync with peers")
    sync_now_parser.add_argument(
        "--peer",
        dest="peer_id",
        type=str,
        help="Sync with specific peer ID (default: all peers)"
    )

    # sync conflicts
    conflicts_parser = sync_subparsers.add_parser("conflicts", help="List unresolved sync conflicts")
    conflicts_parser.add_argument(
        "--note",
        type=str,
        help="Filter conflicts by note ID (or prefix)"
    )
    conflicts_parser.add_argument(
        "--details",
        action="store_true",
        help="Show the base, both sides and the merged value of each conflict"
    )
    conflicts_parser.add_argument(
        "--all",
        action="store_true",
        help="Include resolved conflicts"
    )

    # sync resolve
    resolve_parser = sync_subparsers.add_parser(
        "resolve",
        help="Resolve a sync conflict: accept the merged value, or replace it"
    )
    resolve_parser.add_argument(
        "conflict_id",
        type=str,
        help="Conflict ID (or prefix) to resolve"
    )
    resolve_parser.add_argument(
        "--content-file",
        dest="content_file",
        type=str,
        help="File whose text becomes the field's value (default: accept the merged value)"
    )
    resolve_parser.add_argument(
        "--content",
        dest="content",
        type=str,
        help="Text that becomes the field's value"
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
    serve_parser.add_argument(
        "--no-announce",
        action="store_true",
        help="Do not announce this listener on the local network"
    )
    serve_parser.add_argument(
        "--plain-http",
        action="store_true",
        help="Serve plain http instead of https. Allowed only on a loopback address: for a reverse proxy in front, or a test"
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

    # calculate-missing-data command
    fill_parser = cli_subparsers.add_parser(
        "calculate-missing-data",
        help="Calculate what was never calculated: Recording lengths, creation dates, display caches"
    )
    fill_parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Report what is missing and stop"
    )
    fill_parser.add_argument(
        "--limit",
        type=int,
        help="Read at most this many Recordings in one run"
    )
    fill_parser.add_argument(
        "--no-durations",
        dest="no_durations",
        action="store_true",
        help="Leave Recording lengths alone"
    )
    fill_parser.add_argument(
        "--no-dates",
        dest="no_dates",
        action="store_true",
        help="Leave creation dates alone"
    )
    fill_parser.add_argument(
        "--no-caches",
        dest="no_caches",
        action="store_true",
        help="Leave display caches alone"
    )

    # db-maintenance command with subcommands
    config_parser = cli_subparsers.add_parser(
        "config",
        help="This device's local configuration: device name, audio folder, sync port (config.json)"
    )
    config_subparsers = config_parser.add_subparsers(dest="config_command", help="Config commands")
    config_subparsers.add_parser("show", help="Show the local configuration")
    config_get_parser = config_subparsers.add_parser("get", help="Show one value")
    config_get_parser.add_argument("key", type=str, help="One of: " + ", ".join(CONFIG_KEYS))
    config_set_parser = config_subparsers.add_parser("set", help="Set one value")
    config_set_parser.add_argument("key", type=str, help="One of: " + ", ".join(CONFIG_KEYS))
    config_set_parser.add_argument("value", type=str, help="New value")

    settings_parser = cli_subparsers.add_parser(
        "settings",
        help="Synced settings shared by every device (transcription languages, provider API keys)"
    )
    settings_subparsers = settings_parser.add_subparsers(dest="settings_command", help="Settings commands")
    settings_subparsers.add_parser("list", help="List synced settings")
    settings_get_parser = settings_subparsers.add_parser("get", help="Show one synced setting")
    settings_get_parser.add_argument("key", type=str, help="Setting key, e.g. transcription.preferred_languages")
    settings_set_parser = settings_subparsers.add_parser("set", help="Set a synced setting on every device")
    settings_set_parser.add_argument("key", type=str, help="Setting key, e.g. transcription.providers.assemblyai.api_key")
    settings_set_parser.add_argument("value", type=str, help="Value (preferred_languages takes a JSON list)")

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

    # maintenance note-rebuild-caches (rebuild all caches for a single note or all notes)
    rebuild_cache_parser = maintenance_subparsers.add_parser(
        "note-rebuild-caches",
        help="Rebuild all cache fields for notes (di_cache_note_pane_display, di_cache_note_list_pane_display)"
    )
    rebuild_cache_parser.add_argument(
        "note_id",
        nargs="?",
        help="Note ID to rebuild caches for (rebuilds all notes if not specified)"
    )

    # maintenance rebuild-all-caches (rebuild ALL di_* fields in the database)
    rebuild_all_parser = maintenance_subparsers.add_parser(
        "rebuild-all-caches",
        help="Rebuild all di_* cache fields in the entire database"
    )
    rebuild_all_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show cache registry info before rebuilding"
    )

    # maintenance audio-rebuild-durations (find and set duration for audio files)
    audio_duration_parser = maintenance_subparsers.add_parser(
        "audio-rebuild-durations",
        help="Find audio files with missing duration and populate from file metadata"
    )
    audio_duration_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )

    # ========================================================================
    # storage (cloud file storage configuration)
    # ========================================================================
    storage_parser = cli_subparsers.add_parser(
        "storage",
        help="Cloud file storage configuration for syncing audio files"
    )
    storage_subparsers = storage_parser.add_subparsers(dest="storage_command", help="Storage commands")

    # device - the devices of the account, by their cards
    device_parser = cli_subparsers.add_parser("device", help="The devices of the account")
    device_subparsers = device_parser.add_subparsers(dest="device_command", help="Device commands")
    device_subparsers.add_parser("list", help="Every device of the account, with its name, fingerprint and state")
    device_revoke_parser = device_subparsers.add_parser(
        "revoke",
        help="Revoke a device: it is refused by every peer once the revocation has reached them. One way"
    )
    device_revoke_parser.add_argument("device_id", help="The device id, or a unique prefix of it")

    # account - the account this installation holds, its snapshots
    account_parser = cli_subparsers.add_parser(
        "account",
        help="The account this database belongs to, and its snapshots"
    )
    account_subparsers = account_parser.add_subparsers(dest="account_command", help="Account commands")
    account_subparsers.add_parser("show", help="Show the account id and the database id")
    account_subparsers.add_parser("list", help="Every account of this installation, marking the default and the hosted")
    account_create_parser = account_subparsers.add_parser("create", help="Make a new account on this installation")
    account_create_parser.add_argument("--label", help="A name for it, unique on this installation")
    account_default_parser = account_subparsers.add_parser("default", help="Make an account the one opened with no -a")
    account_default_parser.add_argument("selector", help="The account's id, a unique prefix of it, or its label")
    account_remove_parser = account_subparsers.add_parser("remove", help="Forget an account: the index only; its directory stays")
    account_remove_parser.add_argument("selector", help="The account's id, a unique prefix of it, or its label")
    show_code_parser = account_subparsers.add_parser(
        "show-code",
        help="Show the code another device reads to join this account: a QR code and the setup text. Valid ten minutes, once"
    )
    show_code_parser.add_argument(
        "--url", action="append", dest="urls",
        help="Where this installation's listener is reachable (default: https://<this host>:<port>). May repeat"
    )
    show_code_parser.add_argument("--text-only", action="store_true", help="Print the setup text without the QR code")
    account_subparsers.add_parser("hide-code", help="Withdraw the code shown by show-code")
    recording_key_parser = account_subparsers.add_parser(
        "recording-key",
        help="The account's recording key (Stage 15): export it as text and a QR code, or import one from an export"
    )
    recording_key_sub = recording_key_parser.add_subparsers(dest="recording_key_command")
    export_parser = recording_key_sub.add_parser("export", help="Show the key; made now when the account has none. Keep it on paper")
    export_parser.add_argument("--text-only", action="store_true", help="Print the key without the QR code")
    import_parser = recording_key_sub.add_parser("import", help="Keep a key from an export: how a device that lost everything reads the bucket again")
    import_parser.add_argument("text", help="The 43 characters of the key")
    host_parser = account_subparsers.add_parser(
        "host",
        help="Show the grant text with which the holder of an account gives it to this server to host. Needs no account here"
    )
    host_parser.add_argument("--label", help="A name for the hosted account on this server (default: hosted-<id prefix>)")
    host_parser.add_argument(
        "--url", action="append", dest="urls",
        help="Where this server's listener is reachable (default: https://<this host>:<port>). May repeat"
    )
    host_parser.add_argument("--text-only", action="store_true", help="Print the grant text without the QR code")
    grant_parser = account_subparsers.add_parser(
        "grant-host",
        help="Give a server this account to host, from the grant text it showed with 'account host'"
    )
    grant_parser.add_argument("setup_text", help="The grant text, as copied from the server")
    grant_parser.add_argument("--label", help="A name for the account on the server (default: the server's choice)")
    join_parser = account_subparsers.add_parser(
        "join",
        help="Join an account from a setup text shown by another device. Refused if this installation holds notes of another account"
    )
    join_parser.add_argument("setup_text", help="The setup text, as copied from the other device")
    account_subparsers.add_parser("snapshots", help="List the snapshots beside the database, newest first")
    account_subparsers.add_parser("snapshot", help="Take a snapshot of the database now")
    account_subparsers.add_parser("backup", help="The periodic backup, now: copy the database to the backup directory (every account of the root)")
    account_restore_parser = account_subparsers.add_parser(
        "restore",
        help="Replace the database with a snapshot (the state replaced is snapshotted first)"
    )
    account_restore_parser.add_argument("name", help="Snapshot file name, as listed by 'account snapshots'")
    account_restore_parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation")
    account_move_parser = account_subparsers.add_parser(
        "move",
        help="Move this database, notes and all, to another account. Deliberate: the current account id must be typed in full"
    )
    account_move_parser.add_argument("--to", required=True, dest="to_account", help="A code shown by a device of the other account (the setup text), or its account id")
    account_move_parser.add_argument(
        "--current", required=True, dest="current_account",
        help="The full id of the account being given up, typed by hand, as proof that this is meant"
    )

    # storage status - show current configuration
    storage_subparsers.add_parser("status", help="Show current cloud storage configuration")
    encrypt_parser = storage_subparsers.add_parser("encrypt", help="Encryption of recordings in the bucket (Stage 15): on, off, or the state")
    encrypt_parser.add_argument("state", nargs="?", choices=["on", "off"], help="Turn it on (the key must be exported first) or off; nothing prints the state")
    storage_subparsers.add_parser("reupload-encrypted", help="Send the plain objects' recordings up again encrypted, one at a time, resumable")

    # storage setup: the wizard
    setup_parser = storage_subparsers.add_parser("setup", help="The bucket wizard: make the key, make and harden the bucket, test it, save it for every device")
    setup_parser.add_argument("--access-key-id", help="Skip the question")
    setup_parser.add_argument("--secret-access-key", help="Skip the question (the secret is also read without echo when omitted)")
    setup_parser.add_argument("--region", help="Skip the question (default: the nearest by round-trip time)")
    setup_parser.add_argument("--bucket", help="Skip the question (default: a generated voice-… name)")
    setup_parser.add_argument("--prefix", help="A folder inside the bucket, optional")
    setup_parser.add_argument("--endpoint", help="An https address for a service other than Amazon")
    setup_parser.add_argument("--yes", action="store_true", help="Ask nothing: take the flags and the defaults")

    # storage replace-key
    replace_parser = storage_subparsers.add_parser("replace-key", help="A new key for the existing bucket, tested first, then saved for every device")
    replace_parser.add_argument("access_key_id", help="The new access key ID")
    replace_parser.add_argument("--secret-access-key", help="The new secret (read without echo when omitted)")

    # storage check
    storage_subparsers.add_parser("check", help="The bucket as it is: answers the key, round trip, public access blocked, encrypted, TLS only, lifecycle rules")

    # storage configure-s3 - configure S3 storage
    storage_s3_parser = storage_subparsers.add_parser(
        "configure-s3",
        help="Configure AWS S3 (or S3-compatible) storage for audio files"
    )
    storage_s3_parser.add_argument(
        "--bucket",
        required=True,
        help="S3 bucket name"
    )
    storage_s3_parser.add_argument(
        "--region",
        required=True,
        help="AWS region (e.g., us-east-1, eu-west-1)"
    )
    storage_s3_parser.add_argument(
        "--access-key-id",
        required=True,
        help="AWS access key ID"
    )
    storage_s3_parser.add_argument(
        "--secret-access-key",
        required=True,
        help="AWS secret access key"
    )
    storage_s3_parser.add_argument(
        "--prefix",
        help="Optional path prefix for stored files (e.g., 'audio/')"
    )
    storage_s3_parser.add_argument(
        "--endpoint",
        help="Optional custom endpoint URL for S3-compatible services (e.g., DigitalOcean Spaces, MinIO)"
    )

    # storage disable - disable cloud storage
    storage_subparsers.add_parser("disable", help="Disable cloud storage (keep files local only)")

    # storage upload-pending - upload files that haven't been uploaded yet
    storage_subparsers.add_parser(
        "upload-pending",
        help="Upload pending audio files to cloud storage (files not yet uploaded)"
    )

    # storage download-missing - fetch everything that is in the cloud but not here
    storage_subparsers.add_parser(
        "download-missing",
        help="Download every audio file that is in cloud storage but not on this device"
    )

    # storage mirror enable|disable - keep a complete local copy on every sync
    storage_mirror_parser = storage_subparsers.add_parser(
        "mirror",
        help="Enable or disable downloading ALL cloud audio files on every sync (local backup of the bucket)"
    )
    storage_mirror_parser.add_argument(
        "mirror_action",
        choices=["enable", "disable"],
        help="enable: every sync downloads all missing audio files; disable: download on demand only"
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

    # A root without an account of its own: only a listener or a host can run
    if config_dir is None:
        root = Path(getattr(args, "config_root"))
        if args.cli_command == "sync" and getattr(args, "sync_command", None) == "serve":
            return cmd_sync_serve_root(root, args)
        if args.cli_command == "account":
            command = getattr(args, "account_command", None)
            if command == "host":
                return cmd_account_host(root, args)
            index_commands = {"list": cmd_account_list, "create": cmd_account_create, "default": cmd_account_default, "remove": cmd_account_remove}
            if command in index_commands:
                return index_commands[command](_index_root_of(root), args)
        print(f"Error: {root} holds no account; run 'account create', 'account join <setup text>' or 'account host'.", file=sys.stderr)
        return 1

    # Initialize config and database
    config = Config(config_dir=config_dir, root=getattr(args, "config_root", None))
    db_path_str = config.get("database_file")
    db_path = Path(db_path_str)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)
    reconcile_transcription_settings(config, db)

    # Execute command
    try:
        if args.cli_command == "notes-list":
            return cmd_list_notes(db, args)
        elif args.cli_command == "note-delete":
            return cmd_delete_note(db, args)
        elif args.cli_command == "tag-rename":
            return cmd_rename_tag(db, args)
        elif args.cli_command == "tag-move":
            return cmd_move_tag(db, args)
        elif args.cli_command == "note-history":
            return cmd_note_history(db, args)
        elif args.cli_command == "note-restore":
            return cmd_note_restore(db, args)
        elif args.cli_command == "note-show":
            return cmd_show_note(db, args)
        elif args.cli_command == "note-create":
            return cmd_new_note(db, args)
        elif args.cli_command == "note-edit":
            return cmd_edit_note(db, args)
        elif args.cli_command == "trash-list":
            return cmd_trash_list(db, args)
        elif args.cli_command == "note-recover":
            return cmd_note_recover(db, args)
        elif args.cli_command == "note-purge":
            return cmd_note_purge(db, args)
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
        elif args.cli_command == "audiofile-download":
            return cmd_download_audiofile(db, config, args)
        elif args.cli_command == "note-audiofiles-download":
            return cmd_download_note_audiofiles(db, config, args)
        elif args.cli_command == "transcribe-backlog":
            from src.core import transcription_backlog as backlog
            if getattr(args, "enable", False):
                backlog.set_enabled(config, True)
                print(f"This machine will transcribe Recordings over "
                      f"{backlog.minimum_minutes(config)} minutes.")
                return 0
            if getattr(args, "disable", False):
                backlog.set_enabled(config, False)
                print("This machine will not transcribe long Recordings.")
                return 0
            return cmd_transcribe_backlog(db, config, args)
        elif args.cli_command == "audiofile-transcribe":
            return cmd_transcribe_audiofile(db, config, args)
        elif args.cli_command == "note-audiofiles-transcribe":
            return cmd_transcribe_note(db, config, args)
        elif args.cli_command == "config":
            return cmd_config(config, args)
        elif args.cli_command == "settings":
            return cmd_settings(config, db, args)
        elif args.cli_command == "device":
            device_cmd = getattr(args, 'device_command', None)
            if not device_cmd:
                print("Error: No device command specified. Use 'device --help'.", file=sys.stderr)
                return 1
            if device_cmd == "list":
                return cmd_device_list(db, config, args)
            elif device_cmd == "revoke":
                return cmd_device_revoke(db, config, args)
            else:
                print(f"Error: Unknown device command '{device_cmd}'", file=sys.stderr)
                return 1
        elif args.cli_command == "account":
            account_cmd = getattr(args, 'account_command', None)
            if not account_cmd:
                print("Error: No account command specified. Use 'account --help'.", file=sys.stderr)
                return 1
            if account_cmd == "show":
                return cmd_account_show(db, config, args)
            elif account_cmd == "list":
                return cmd_account_list(_index_root(config), args)
            elif account_cmd == "create":
                return cmd_account_create(_index_root(config), args)
            elif account_cmd == "default":
                return cmd_account_default(_index_root(config), args)
            elif account_cmd == "remove":
                return cmd_account_remove(_index_root(config), args)
            elif account_cmd == "show-code":
                return cmd_account_show_code(db, config, args)
            elif account_cmd == "hide-code":
                return cmd_account_hide_code(config, args)
            elif account_cmd == "recording-key":
                return cmd_account_recording_key(config, args)
            elif account_cmd == "host":
                return cmd_account_host(config.get_root(), args)
            elif account_cmd == "grant-host":
                return cmd_account_grant_host(config, args)
            elif account_cmd == "join":
                return cmd_account_join(db, config, args)
            elif account_cmd == "snapshots":
                return cmd_account_snapshots(db, args)
            elif account_cmd == "backup":
                return cmd_account_backup(config, args)
            elif account_cmd == "snapshot":
                return cmd_account_snapshot(db, args)
            elif account_cmd == "restore":
                return cmd_account_restore(db, args)
            elif account_cmd == "move":
                return cmd_account_move(db, config, args)
            else:
                print(f"Error: Unknown account command '{account_cmd}'", file=sys.stderr)
                return 1
        elif args.cli_command == "sync":
            # Handle sync subcommands
            sync_cmd = getattr(args, 'sync_command', None)
            if not sync_cmd:
                print("Error: No sync command specified. Use 'sync --help'.", file=sys.stderr)
                return 1
            if sync_cmd == "status":
                return cmd_sync_status(db, config, args)
            elif sync_cmd == "list-peers":
                return cmd_sync_list_peers(db, config, args)
            elif sync_cmd == "add-peer":
                return cmd_sync_add_peer(config, args)
            elif sync_cmd == "remove-peer":
                return cmd_sync_remove_peer(config, args)
            elif sync_cmd == "rename-peer":
                return cmd_sync_rename_peer(config, args)
            elif sync_cmd == "now":
                return cmd_sync_now(db, config, args)
            elif sync_cmd == "check":
                return cmd_sync_check(db, config, args)
            elif sync_cmd == "discover":
                return cmd_sync_discover(db, config, args)
            elif sync_cmd in ("deliver", "exchange", "send", "fetch"):
                return cmd_sync_operation(db, config, sync_cmd, args)
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
        elif args.cli_command == "transcription-queue":
            return cmd_transcription_queue(db, config, args)
        elif args.cli_command == "calculate-missing-data":
            return cmd_calculate_missing_data(db, config, args)
        elif args.cli_command == "db-maintenance":
            # Handle maintenance subcommands
            maint_cmd = getattr(args, 'maintenance_command', None)
            if not maint_cmd:
                print("Error: No maintenance command specified. Use 'db-maintenance --help'.", file=sys.stderr)
                return 1
            if maint_cmd == "database-normalize":
                return cmd_maintenance_database_normalize(db, args)
            elif maint_cmd == "note-rebuild-caches":
                return cmd_maintenance_rebuild_cache(db, args)
            elif maint_cmd == "rebuild-all-caches":
                return cmd_maintenance_rebuild_all_caches(db, args)
            elif maint_cmd == "audio-rebuild-durations":
                return cmd_maintenance_audio_rebuild_durations(db, config, args)
            else:
                print(f"Error: Unknown maintenance command '{maint_cmd}'", file=sys.stderr)
                return 1
        elif args.cli_command == "storage":
            # Handle storage subcommands
            storage_cmd = getattr(args, 'storage_command', None)
            if not storage_cmd:
                print("Error: No storage command specified. Use 'storage --help'.", file=sys.stderr)
                return 1
            if storage_cmd == "status":
                return cmd_storage_status(db, config, args)
            elif storage_cmd == "setup":
                return cmd_storage_setup(db, config, args)
            elif storage_cmd == "replace-key":
                return cmd_storage_replace_key(db, args)
            elif storage_cmd == "check":
                return cmd_storage_check(config, args)
            elif storage_cmd == "configure-s3":
                return cmd_storage_configure_s3(db, args)
            elif storage_cmd == "disable":
                return cmd_storage_disable(db, args)
            elif storage_cmd == "upload-pending":
                return cmd_storage_upload_pending(config, args)
            elif storage_cmd == "encrypt":
                return cmd_storage_encrypt(config, args)
            elif storage_cmd == "reupload-encrypted":
                return cmd_storage_reupload_encrypted(config, args)
            elif storage_cmd == "download-missing":
                return cmd_storage_download_missing(config, args)
            elif storage_cmd == "mirror":
                return cmd_storage_mirror(config, args)
            else:
                print(f"Error: Unknown storage command '{storage_cmd}'", file=sys.stderr)
                return 1
        else:
            print(f"Error: Unknown command '{args.cli_command}'", file=sys.stderr)
            return 1
    except ValidationError as e:
        print(f"Error: Invalid {e.field} - {e.message}", file=sys.stderr)
        return 1
    finally:
        db.close()

#!/usr/bin/env python3
"""Migrate Voice Classic database to Voice format.

This standalone CLI tool reads a Voice Classic SQLite database and outputs
SQL statements to import the data into a Voice database.

Usage:
    python migrate_from_classic.py <classic_db_path> [--output <output_file>]

Mapping:
    Voice Classic                -> Voice
    recordings                   -> notes + audio_files + note_attachments + transcriptions
    recordings.notes             -> notes.content
    recordings.created_date      -> notes.created_at, audio_files.file_created_at
    recordings.filepath          -> audio_files.filename (basename only)
    recordings.transcription     -> transcriptions.content
    recordings.starred           -> note_tags to _marked tag
    tags                         -> tags
    recording_tags               -> note_tags

System Tags:
    Voice uses deterministic UUIDs for system tags that are consistent across all devices:
    - _system (parent): a1b2c3d4-0000-5000-8000-000000000001
    - _marked (child of _system, for starred notes): a1b2c3d4-0000-5000-8000-000000000002
"""

# Voice system tag UUIDs (must match voicecore/src/database.rs)
SYSTEM_TAG_UUID = "a1b2c3d40000500080000000000000001"  # hex without hyphens
MARKED_TAG_UUID = "a1b2c3d40000500080000000000000002"  # hex without hyphens

import argparse
import os
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, TextIO


def generate_uuid7(timestamp: Optional[datetime] = None) -> bytes:
    """Generate a UUID7 with optional timestamp.

    UUID7 format (RFC 9562):
    - First 48 bits: Unix timestamp in milliseconds
    - Version nibble: 7
    - 12 bits: Random
    - Variant bits: 10
    - 62 bits: Random

    Args:
        timestamp: Optional datetime for the UUID timestamp. If None, uses current time.

    Returns:
        16 bytes representing the UUID7
    """
    import struct

    if timestamp is None:
        timestamp = datetime.now()

    # Convert to milliseconds since Unix epoch
    unix_ms = int(timestamp.timestamp() * 1000)

    # Get random bytes
    rand_bytes = os.urandom(10)

    # Build the UUID7
    # First 6 bytes: timestamp (48 bits)
    # Bytes 6-7: version (4 bits) + random (12 bits)
    # Bytes 8-15: variant (2 bits) + random (62 bits)

    time_bytes = struct.pack(">Q", unix_ms)[2:]  # 6 bytes, big endian

    # Byte 6: high 4 bits of version (0111) + high 4 bits of random
    byte6 = 0x70 | (rand_bytes[0] & 0x0F)

    # Byte 7: low 8 bits from random
    byte7 = rand_bytes[1]

    # Byte 8: variant (10xxxxxx) + 6 bits random
    byte8 = 0x80 | (rand_bytes[2] & 0x3F)

    # Bytes 9-15: random
    remaining = rand_bytes[3:10]

    return time_bytes + bytes([byte6, byte7, byte8]) + remaining


def uuid_to_hex(uuid_bytes: bytes) -> str:
    """Convert UUID bytes to hex string for Voice database."""
    return uuid_bytes.hex()


def escape_sql_string(s: str) -> str:
    """Escape a string for SQL by doubling single quotes."""
    if s is None:
        return "NULL"
    return "'" + s.replace("'", "''") + "'"


def format_datetime(dt_str: Optional[str]) -> str:
    """Format datetime string, ensuring proper zero-padding.

    Converts various datetime formats to 'YYYY-MM-DD HH:MM:SS'.
    """
    if dt_str is None:
        return "NULL"

    # Try to parse and reformat to ensure consistent format
    try:
        # Handle ISO format with timezone
        if "T" in dt_str:
            dt_str = dt_str.replace("T", " ").split("+")[0].split("Z")[0]

        # Parse the datetime
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
            try:
                dt = datetime.strptime(dt_str.strip(), fmt)
                return escape_sql_string(dt.strftime("%Y-%m-%d %H:%M:%S"))
            except ValueError:
                continue

        # If parsing fails, return as-is but escaped
        return escape_sql_string(dt_str)
    except Exception:
        return escape_sql_string(dt_str)


def format_datetime_raw(dt_str: Optional[str]) -> Optional[str]:
    """Format datetime string without SQL escaping."""
    if dt_str is None:
        return None

    try:
        if "T" in dt_str:
            dt_str = dt_str.replace("T", " ").split("+")[0].split("Z")[0]

        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
            try:
                dt = datetime.strptime(dt_str.strip(), fmt)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
        return dt_str
    except Exception:
        return dt_str


def migrate_database(
    classic_db_path: Path,
    output: TextIO,
    verbose: bool = False
) -> None:
    """Migrate Voice Classic database to Voice SQL format.

    Args:
        classic_db_path: Path to the Voice Classic SQLite database
        output: File-like object to write SQL statements to
        verbose: If True, print progress to stderr
    """
    if not classic_db_path.exists():
        raise FileNotFoundError(f"Database not found: {classic_db_path}")

    conn = sqlite3.connect(classic_db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Maps to track old ID -> new UUID mappings
    recording_id_map: Dict[int, bytes] = {}  # recording_id -> note_id
    audio_file_id_map: Dict[int, bytes] = {}  # recording_id -> audio_file_id
    tag_id_map: Dict[int, bytes] = {}

    # Write header
    output.write("-- Voice Classic to Voice migration\n")
    output.write(f"-- Generated: {datetime.now().isoformat()}\n")
    output.write(f"-- Source: {classic_db_path}\n")
    output.write("-- \n")
    output.write("-- Run this SQL against a Voice database to import the data.\n")
    output.write("-- Make sure the Voice database schema is already created.\n")
    output.write("\n")
    output.write("BEGIN TRANSACTION;\n\n")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # =========================================================================
    # Migrate tags first (notes reference tags via note_tags)
    # =========================================================================
    if verbose:
        print("Migrating tags...", file=sys.stderr)

    cursor.execute("SELECT id, name, parent_id FROM tags ORDER BY id")
    tags = cursor.fetchall()

    output.write("-- Tags\n")

    # First pass: create UUID mappings for all tags
    for tag in tags:
        tag_id_map[tag["id"]] = generate_uuid7()

    # Second pass: generate INSERT statements
    for tag in tags:
        old_id = tag["id"]
        new_id = tag_id_map[old_id]
        name = tag["name"]
        old_parent_id = tag["parent_id"]

        new_parent_id = "NULL"
        if old_parent_id is not None:
            if old_parent_id in tag_id_map:
                new_parent_id = escape_sql_string(uuid_to_hex(tag_id_map[old_parent_id]))
            else:
                if verbose:
                    print(f"  Warning: Tag {old_id} has unknown parent {old_parent_id}",
                          file=sys.stderr)

        output.write(
            f"INSERT INTO tags (id, name, parent_id, created_at, modified_at) "
            f"VALUES ({escape_sql_string(uuid_to_hex(new_id))}, {escape_sql_string(name)}, "
            f"{new_parent_id}, '{now_str}', NULL);\n"
        )

    if verbose:
        print(f"  Migrated {len(tags)} tags", file=sys.stderr)

    output.write("\n")

    # =========================================================================
    # Migrate recordings -> notes, audio_files, note_attachments, transcriptions
    # =========================================================================
    if verbose:
        print("Migrating recordings...", file=sys.stderr)

    cursor.execute("""
        SELECT id, filepath, created_date, duration, transcription, notes, summary, starred
        FROM recordings
        ORDER BY id
    """)
    recordings = cursor.fetchall()

    output.write("-- Notes (from recordings)\n")

    notes_migrated = 0
    audio_files_migrated = 0
    transcriptions_migrated = 0

    for recording in recordings:
        old_id = recording["id"]
        filepath = recording["filepath"]
        created_date = recording["created_date"]
        transcription = recording["transcription"]
        notes_content = recording["notes"]
        summary = recording["summary"]

        # Generate UUID7 with the original created timestamp if possible
        try:
            ts = datetime.fromisoformat(created_date.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            ts = datetime.now()

        # Create Note
        note_id = generate_uuid7(ts)
        recording_id_map[old_id] = note_id

        # Note content: use notes field, or empty string if none
        content = notes_content if notes_content else ""

        formatted_created = format_datetime_raw(created_date) or now_str

        output.write(
            f"INSERT INTO notes (id, created_at, content, modified_at, deleted_at) "
            f"VALUES ({escape_sql_string(uuid_to_hex(note_id))}, "
            f"{escape_sql_string(formatted_created)}, "
            f"{escape_sql_string(content)}, NULL, NULL);\n"
        )
        notes_migrated += 1

    output.write("\n")
    output.write("-- Audio files (from recordings)\n")

    for recording in recordings:
        old_id = recording["id"]
        filepath = recording["filepath"]
        created_date = recording["created_date"]
        summary = recording["summary"]

        # Generate UUID7 for audio file
        try:
            ts = datetime.fromisoformat(created_date.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            ts = datetime.now()

        audio_file_id = generate_uuid7(ts)
        audio_file_id_map[old_id] = audio_file_id

        # Extract filename from filepath
        filename = os.path.basename(filepath) if filepath else f"recording_{old_id}.ogg"

        formatted_created = format_datetime_raw(created_date) or now_str

        # Summary field
        summary_sql = escape_sql_string(summary) if summary else "NULL"

        output.write(
            f"INSERT INTO audio_files (id, imported_at, filename, file_created_at, summary, modified_at, deleted_at) "
            f"VALUES ({escape_sql_string(uuid_to_hex(audio_file_id))}, "
            f"'{now_str}', "
            f"{escape_sql_string(filename)}, "
            f"{escape_sql_string(formatted_created)}, "
            f"{summary_sql}, NULL, NULL);\n"
        )
        audio_files_migrated += 1

    output.write("\n")
    output.write("-- Note attachments (linking audio files to notes)\n")

    for recording in recordings:
        old_id = recording["id"]

        if old_id not in recording_id_map or old_id not in audio_file_id_map:
            continue

        note_id = recording_id_map[old_id]
        audio_file_id = audio_file_id_map[old_id]

        # Generate UUID for the attachment association
        attachment_assoc_id = generate_uuid7()

        output.write(
            f"INSERT INTO note_attachments (id, note_id, attachment_id, attachment_type, created_at, modified_at, deleted_at) "
            f"VALUES ({escape_sql_string(uuid_to_hex(attachment_assoc_id))}, "
            f"{escape_sql_string(uuid_to_hex(note_id))}, "
            f"{escape_sql_string(uuid_to_hex(audio_file_id))}, "
            f"'audio_file', '{now_str}', NULL, NULL);\n"
        )

    output.write("\n")
    output.write("-- Transcriptions (from recordings with transcription text)\n")

    for recording in recordings:
        old_id = recording["id"]
        transcription = recording["transcription"]
        created_date = recording["created_date"]

        # Skip recordings without transcription
        if not transcription or not transcription.strip():
            continue

        if old_id not in audio_file_id_map:
            continue

        audio_file_id = audio_file_id_map[old_id]

        # Generate UUID for transcription
        try:
            ts = datetime.fromisoformat(created_date.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            ts = datetime.now()

        transcription_id = generate_uuid7(ts)

        formatted_created = format_datetime_raw(created_date) or now_str

        output.write(
            f"INSERT INTO transcriptions (id, audio_file_id, content, service, state, created_at, modified_at, deleted_at) "
            f"VALUES ({escape_sql_string(uuid_to_hex(transcription_id))}, "
            f"{escape_sql_string(uuid_to_hex(audio_file_id))}, "
            f"{escape_sql_string(transcription)}, "
            f"'voice-classic-import', "
            f"'original !verified !verbatim !cleaned !polished', "
            f"{escape_sql_string(formatted_created)}, NULL, NULL);\n"
        )
        transcriptions_migrated += 1

    if verbose:
        print(f"  Migrated {notes_migrated} notes", file=sys.stderr)
        print(f"  Migrated {audio_files_migrated} audio files", file=sys.stderr)
        print(f"  Migrated {transcriptions_migrated} transcriptions", file=sys.stderr)

    output.write("\n")

    # =========================================================================
    # Migrate recording_tags -> note_tags
    # =========================================================================
    if verbose:
        print("Migrating recording_tags to note_tags...", file=sys.stderr)

    cursor.execute("SELECT recording_id, tag_id FROM recording_tags")
    recording_tags = cursor.fetchall()

    output.write("-- Note tags (from recording_tags)\n")

    migrated_tags = 0
    skipped_tags = 0
    for rt in recording_tags:
        old_recording_id = rt["recording_id"]
        old_tag_id = rt["tag_id"]

        # Skip if recording wasn't migrated
        if old_recording_id not in recording_id_map:
            skipped_tags += 1
            continue

        # Skip if tag doesn't exist
        if old_tag_id not in tag_id_map:
            if verbose:
                print(f"  Warning: Unknown tag {old_tag_id} for recording {old_recording_id}",
                      file=sys.stderr)
            skipped_tags += 1
            continue

        new_note_id = recording_id_map[old_recording_id]
        new_tag_id = tag_id_map[old_tag_id]

        output.write(
            f"INSERT INTO note_tags (note_id, tag_id, created_at, modified_at, deleted_at) "
            f"VALUES ({escape_sql_string(uuid_to_hex(new_note_id))}, "
            f"{escape_sql_string(uuid_to_hex(new_tag_id))}, "
            f"'{now_str}', NULL, NULL);\n"
        )
        migrated_tags += 1

    if verbose:
        print(f"  Migrated {migrated_tags} note-tag associations, skipped {skipped_tags}",
              file=sys.stderr)

    output.write("\n")

    # =========================================================================
    # Migrate starred recordings -> note_tags with _marked tag
    # =========================================================================
    if verbose:
        print("Migrating starred recordings...", file=sys.stderr)

    cursor.execute("SELECT id FROM recordings WHERE starred = 1")
    starred_recordings = cursor.fetchall()

    if starred_recordings:
        output.write("-- Starred notes (recordings with starred = 1)\n")
        output.write(f"-- Using _marked tag UUID: {MARKED_TAG_UUID}\n")

        starred_count = 0
        for sr in starred_recordings:
            old_id = sr["id"]

            if old_id not in recording_id_map:
                if verbose:
                    print(f"  Warning: Starred recording {old_id} wasn't migrated",
                          file=sys.stderr)
                continue

            note_id = recording_id_map[old_id]

            output.write(
                f"INSERT OR IGNORE INTO note_tags (note_id, tag_id, created_at, modified_at, deleted_at) "
                f"VALUES ({escape_sql_string(uuid_to_hex(note_id))}, "
                f"{escape_sql_string(MARKED_TAG_UUID)}, "
                f"'{now_str}', NULL, NULL);\n"
            )
            starred_count += 1

        if verbose:
            print(f"  Migrated {starred_count} starred recordings to _marked tag",
                  file=sys.stderr)

        output.write("\n")

    output.write("COMMIT;\n")

    conn.close()

    starred_count = len(starred_recordings) if starred_recordings else 0

    if verbose:
        print("\nMigration complete!", file=sys.stderr)
        print(f"  Notes: {notes_migrated}", file=sys.stderr)
        print(f"  Audio files: {audio_files_migrated}", file=sys.stderr)
        print(f"  Transcriptions: {transcriptions_migrated}", file=sys.stderr)
        print(f"  Tags: {len(tags)}", file=sys.stderr)
        print(f"  Note-tag associations: {migrated_tags}", file=sys.stderr)
        print(f"  Starred notes: {starred_count}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Voice Classic database to Voice format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Output to stdout
    python migrate_from_classic.py /path/to/classic.db

    # Output to file
    python migrate_from_classic.py /path/to/classic.db -o migration.sql

    # With verbose output
    python migrate_from_classic.py /path/to/classic.db -v -o migration.sql

    # Then import into Voice database
    sqlite3 voice.db < migration.sql

Migration Details:
    Each Voice Classic recording becomes:
    - A Note (with the recording's notes field as content)
    - An AudioFile (with the recording's filepath as filename)
    - A NoteAttachment linking the AudioFile to the Note
    - A Transcription (if the recording had transcription text)

    Tags and recording-tag associations are also migrated.
    Starred recordings are linked to the _marked system tag.

Audio File Management:
    After running the SQL migration, you need to copy the audio files to
    Voice's audio directory. The audio files are renamed to use the new
    UUID-based naming convention:

    1. Find Voice's audio directory (check ~/.config/voice/config.json)
    2. For each audio file in the SQL output, copy the file:
       cp /original/path/to/file.mp3 ~/.config/voice/audio/<audio_file_id>.mp3

    The audio_file_id values are in the SQL output as hex strings.
"""
    )
    parser.add_argument(
        "classic_db",
        type=Path,
        help="Path to the Voice Classic SQLite database"
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output SQL file (default: stdout)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print progress to stderr"
    )

    args = parser.parse_args()

    try:
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                migrate_database(args.classic_db, f, args.verbose)
            if args.verbose:
                print(f"\nSQL written to: {args.output}", file=sys.stderr)
        else:
            migrate_database(args.classic_db, sys.stdout, args.verbose)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except sqlite3.Error as e:
        print(f"Database error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

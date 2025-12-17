#!/usr/bin/env python3
"""Command-line interface for Voice Rewrite.

This module provides a CLI for interacting with notes and tags without the GUI.
Uses only core/ modules - no Qt/PySide6 dependencies.

Commands:
    list-notes              List all notes
    show-note <id>          Show details of a specific note
    list-tags               List all tags in hierarchy
    search                  Search notes by text and/or tags

All commands support:
    -d, --config-dir PATH   Custom configuration directory
    --format FORMAT         Output format: text (default), json, csv
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Optional

# Add src to path for both direct execution and module execution
_src_path = Path(__file__).parent
if str(_src_path) not in sys.path:
    sys.path.insert(0, str(_src_path))

from core.config import Config
from core.database import Database
from core.validation import ValidationError

# Configure logging
logging.basicConfig(
    level=logging.WARNING,  # Less verbose for CLI
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


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

        for i, note in enumerate(notes):
            if i > 0:
                print("\n" + "=" * 60 + "\n")
            # Show truncated version in list
            content = note["content"]
            if len(content) > 100:
                content = content[:100] + "..."
            print(f"ID: {note['id']} | Created: {note['created_at']}")
            if note.get("tag_names"):
                print(f"Tags: {note['tag_names']}")
            print(content)

    return 0


def cmd_show_note(db: Database, args: argparse.Namespace) -> int:
    """Show details of a specific note.

    Args:
        db: Database instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for not found)
    """
    note = db.get_note(args.note_id)

    if not note:
        print(f"Error: Note with ID {args.note_id} not found.", file=sys.stderr)
        return 1

    print(format_note(note, args.format))
    return 0


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
    # Build tag_id_groups from tag paths
    # For ambiguous tags, all matching tags' descendants go into ONE group (OR logic)
    tag_id_groups: List[List[int]] = []
    any_tag_not_found = False

    if args.tags:
        for tag_path in args.tags:
            # Get ALL tags matching this path
            matching_tags = db.get_all_tags_by_path(tag_path)

            if matching_tags:
                # Collect all descendants from all matching tags into ONE group (OR logic)
                all_descendants: List[int] = []
                for tag in matching_tags:
                    descendants = db.get_tag_descendants(tag["id"])
                    all_descendants.extend(descendants)

                # Remove duplicates
                all_descendants = list(set(all_descendants))
                tag_id_groups.append(all_descendants)

                # Warn if ambiguous (multiple matches)
                if len(matching_tags) > 1:
                    print(f"Warning: Tag '{tag_path}' is ambiguous - matching {len(matching_tags)} tags (using OR logic)", file=sys.stderr)
            else:
                print(f"Warning: Tag '{tag_path}' not found.", file=sys.stderr)
                any_tag_not_found = True

    # If any requested tag was not found, return empty results
    if any_tag_not_found:
        notes = []
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


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for CLI.

    Returns:
        Configured ArgumentParser instance
    """
    parser = argparse.ArgumentParser(
        description="Voice Rewrite - Command-line interface for notes and tags",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # Global options
    parser.add_argument(
        "-d", "--config-dir",
        type=Path,
        default=None,
        help="Custom configuration directory (default: ~/.config/voicerewrite/)"
    )

    parser.add_argument(
        "--format",
        choices=["text", "json", "csv"],
        default="text",
        help="Output format (default: text)"
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # list-notes command
    subparsers.add_parser(
        "list-notes",
        help="List all notes"
    )

    # show-note command
    show_parser = subparsers.add_parser(
        "show-note",
        help="Show details of a specific note"
    )
    show_parser.add_argument(
        "note_id",
        type=int,
        help="ID of the note to show"
    )

    # list-tags command
    subparsers.add_parser(
        "list-tags",
        help="List all tags in hierarchy"
    )

    # search command
    search_parser = subparsers.add_parser(
        "search",
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

    return parser


def main() -> NoReturn:
    """Main CLI entry point.

    Exits:
        Exits with command return code
    """
    parser = create_parser()
    args = parser.parse_args()

    # Check if command was provided
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Initialize config
    config = Config(config_dir=args.config_dir)

    # Initialize database
    db_path_str = config.get("database_file")
    db_path = Path(db_path_str)
    db = Database(db_path)

    # Execute command
    try:
        if args.command == "list-notes":
            exit_code = cmd_list_notes(db, args)
        elif args.command == "show-note":
            exit_code = cmd_show_note(db, args)
        elif args.command == "list-tags":
            exit_code = cmd_list_tags(db, args)
        elif args.command == "search":
            exit_code = cmd_search(db, args)
        else:
            parser.print_help()
            exit_code = 1
    except ValidationError as e:
        print(f"Error: Invalid {e.field} - {e.message}", file=sys.stderr)
        exit_code = 1
    except Exception as e:
        logger.error(f"Error executing command: {e}")
        exit_code = 1
    finally:
        db.close()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

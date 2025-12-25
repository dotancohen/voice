#!/usr/bin/env python3
"""Command-line interface for Voice.

This module provides CLI commands for interacting with notes and tags.
Uses only core/ modules - no Qt/PySide6 dependencies.

Commands:
    list-notes              List all notes
    show-note <id>          Show details of a specific note
    new-note [content]      Create a new note
    edit-note <id> [content] Edit an existing note
    list-tags               List all tags in hierarchy
    search                  Search notes by text and/or tags
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.config import Config
from src.core.conflicts import ConflictManager, ResolutionChoice
from src.core.database import Database
from src.core.search import resolve_tag_term
from src.core.sync import create_sync_server
from src.core.sync_client import SyncClient, sync_all_peers
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
        client = SyncClient(db, config)
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
                    print(f"  Conflicts: {result.conflicts}")
            else:
                print(f"Sync with {peer_id} failed:")
                for error in result.errors:
                    print(f"  - {error}")
                return 1
    else:
        # Sync with all peers
        results = sync_all_peers(db, config)

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
                        print(f"    Conflicts: {result.conflicts}")
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


def cmd_sync_serve(db: Database, config: Config, args: argparse.Namespace) -> int:
    """Start the sync server.

    Args:
        db: Database instance
        config: Config instance
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success)
    """
    host = getattr(args, 'host', '0.0.0.0')
    port = getattr(args, 'port', None) or config.get_sync_server_port()

    device_id = config.get_device_id_hex()
    device_name = config.get_device_name()

    print(f"Starting sync server...")
    print(f"  Device ID:   {device_id}")
    print(f"  Device Name: {device_name}")
    print(f"  Listening:   http://{host}:{port}")
    print(f"  Endpoints:   /sync/status, /sync/changes, /sync/full, /sync/apply")
    print()
    print("Press Ctrl+C to stop.")
    print()

    app = create_sync_server(db, config, host=host, port=port)
    # Run single-threaded because PyDatabase is not thread-safe
    app.run(host=host, port=port, debug=False, threaded=False)

    return 0


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

    # list-notes command
    cli_subparsers.add_parser(
        "list-notes",
        help="List all notes"
    )

    # show-note command
    show_parser = cli_subparsers.add_parser(
        "show-note",
        help="Show details of a specific note"
    )
    show_parser.add_argument(
        "note_id",
        type=str,
        help="ID of the note to show (UUID hex string)"
    )

    # new-note command
    new_note_parser = cli_subparsers.add_parser(
        "new-note",
        help="Create a new note"
    )
    new_note_parser.add_argument(
        "content",
        nargs="?",
        type=str,
        help="Note content (reads from stdin if not provided)"
    )

    # edit-note command
    edit_note_parser = cli_subparsers.add_parser(
        "edit-note",
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

    # list-tags command
    cli_subparsers.add_parser(
        "list-tags",
        help="List all tags in hierarchy"
    )

    # search command
    search_parser = cli_subparsers.add_parser(
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
        if args.cli_command == "list-notes":
            return cmd_list_notes(db, args)
        elif args.cli_command == "show-note":
            return cmd_show_note(db, args)
        elif args.cli_command == "new-note":
            return cmd_new_note(db, args)
        elif args.cli_command == "edit-note":
            return cmd_edit_note(db, args)
        elif args.cli_command == "list-tags":
            return cmd_list_tags(db, args)
        elif args.cli_command == "search":
            return cmd_search(db, args)
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
            else:
                print(f"Error: Unknown sync command '{sync_cmd}'", file=sys.stderr)
                return 1
        else:
            print(f"Error: Unknown command '{args.cli_command}'", file=sys.stderr)
            return 1
    except ValidationError as e:
        print(f"Error: Invalid {e.field} - {e.message}", file=sys.stderr)
        return 1
    finally:
        db.close()

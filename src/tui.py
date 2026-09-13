#!/usr/bin/env python3
"""TUI (Text User Interface) for Voice using Textual.

This module provides a terminal-based interface for interacting with notes and tags.
Uses only core/ modules - no Qt/PySide6 dependencies.

Features:
    - Tags tree with collapsible hierarchy
    - Notes list with search functionality
    - Note detail view with editing
    - RTL (Hebrew/Arabic) display support

Search:
    - Click tag: Adds tag:Name to search field and runs search
    - Type in search field + Enter: Search by text and/or tags
    - tag:Name syntax for tag filtering
    - Multiple tags are ANDed together
    - Free text searches note content
    - Press 'a' to clear search and show all notes
    - Up Arrow from notes list: Access search field
    - Down Arrow from search field: Return to notes list

Controls:
    - Tab: Navigate between panes (tags, notes list, detail)
    - Up/Down: Navigate lists (Up at top of notes list → search field)
    - Left/Right: Collapse/Expand tags
    - Enter: Select item / Run search
    - e: Edit selected note
    - s: Save changes
    - a: Show all notes (clear search)
    - q: Quit

RTL Support:
    Display uses Unicode RLI/PDI markers with CSS text-align:right.
    Editing is LTR-only (Textual limitation - see tui_demos/docs/RTL_TEXTUAL.md).
"""

from __future__ import annotations

import argparse
import logging
import unicodedata
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.text import Text as RichText

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    Collapsible,
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    TextArea,
    Tree,
)
from textual.widgets.tree import TreeNode


from src.core.audio_player import AudioPlayer, PlaybackState, format_time, is_mpv_available
from src.core.transcription_flags import DEFAULT_FLAGS as DEFAULT_TRANSCRIPTION_FLAGS
from src.core.audiofile_manager import AudioFileManager
from src.core.cloud_storage import (
    STATUS_IN_CLOUD,
    STATUS_PENDING,
    audio_file_status,
    describe_download_result,
    download_audio_files_for_note,
    missing_audio_files,
)
from src.core.config import Config
from src.core.conflicts import Conflict, ConflictManager
from src.core.database import Database
from src.core.synced_settings import reconcile_transcription_settings
from src.core.models import UUID_SHORT_LEN
from src.core.note_editor import NoteEditorMixin
from src.core.search import build_tag_search_term, execute_search
from src.core.timestamp_utils import format_timestamp
from src.core.waveform import decode_waveform, waveform_with_progress, WAVEFORM_BAR_COUNT

# Re-export for tests
__all__ = ["VoiceTUI", "run", "add_tui_subparser", "TagsTree", "NotesList", "NotesListView", "NoteDetail", "SearchInput"]

logger = logging.getLogger(__name__)


# Unicode Bidirectional Control Characters
# LLM NOTE: We use RLI/PDI (Right-to-Left Isolate / Pop Directional Isolate) which are
# the modern Unicode 6.3+ approach. They create a directional "bubble" that doesn't
# affect surrounding text. If RTL display has issues, try the older RLE/PDF approach:
#   RLE = '\u202B'  # Right-to-Left Embedding
#   PDF = '\u202C'  # Pop Directional Formatting
# Use RLE instead of RLI and PDF instead of PDI below. Both approaches require
# text-align:right CSS in addition to the markers.
RLI = '\u2067'  # Right-to-Left Isolate
PDI = '\u2069'  # Pop Directional Isolate
LRI = '\u2066'  # Left-to-Right Isolate (for embedding LTR in RTL context)


def detect_rtl(text: str) -> bool:
    """Detect if text should be displayed RTL based on first strong character."""
    for char in text:
        bidi = unicodedata.bidirectional(char)
        if bidi in ('R', 'AL', 'RLE', 'RLO', 'RLI'):  # RTL characters
            return True
        elif bidi in ('L', 'LRE', 'LRO', 'LRI'):  # LTR characters
            return False
    return False  # Default to LTR


def format_rtl(text: str) -> str:
    """Add RTL isolate markers for proper bidirectional display.

    LLM NOTE: This wraps RTL text with RLI/PDI markers. The markers alone are not
    sufficient - the containing widget must also use text-align:right CSS for
    proper RTL display in Textual.
    """
    if detect_rtl(text):
        return RLI + text + PDI
    return text


def make_rtl_text(text: str) -> RichText:
    """Create a Rich Text object with proper RTL handling.

    LLM NOTE: This function adds RLI/PDI markers for RTL text.
    The containing widget MUST have CSS class "rtl" (text-align: right).
    Do NOT use Rich's justify="right" as it causes layout overflow in Textual.
    """
    if detect_rtl(text):
        rtl_text = RLI + text + PDI
        return RichText(rtl_text)
    return RichText(text)


class TagsTree(Tree[Dict[str, Any]]):
    """Collapsible tags tree widget."""

    GUIDE_DEPTH = 2  # Indentation spaces for child nodes

    def __init__(self, db: Database) -> None:
        super().__init__("Tags", id="tags-tree")
        self.db = db

    def on_key(self, event: Key) -> None:
        """Handle arrow keys for expand/collapse."""
        if event.key == "right":
            node = self.cursor_node
            if node and not node.is_expanded and node.allow_expand:
                node.expand()
                # Move focus to first child
                self.action_cursor_down()
                event.stop()
        elif event.key == "left":
            node = self.cursor_node
            if node:
                if node.is_expanded:
                    # Collapse current node
                    node.collapse()
                    event.stop()
                elif node.parent and node.parent != self.root:
                    # On leaf or collapsed node: move to parent and collapse it
                    self.select_node(node.parent)
                    node.parent.collapse()
                    event.stop()

    def on_mount(self) -> None:
        """Build the tree when mounted."""
        self.root.expand()
        tags = self.db.get_all_tags()

        # Filter out _system tag and its descendants
        system_tag_id = self.db.get_system_tag_id_hex()
        if system_tag_id:
            tags = [
                tag for tag in tags
                if tag["id"] != system_tag_id and tag.get("parent_id") != system_tag_id
            ]

        # Build set of tags that have children (for determining leaf vs branch)
        tags_with_children = {tag["parent_id"] for tag in tags if tag["parent_id"] is not None}

        # Build mapping of parent_id -> list of children
        children_by_parent: Dict[Optional[int], List[Dict[str, Any]]] = {}
        for tag in tags:
            parent_id = tag["parent_id"]
            if parent_id not in children_by_parent:
                children_by_parent[parent_id] = []
            children_by_parent[parent_id].append(tag)

        def add_tag_recursive(parent_node: TreeNode, tag: Dict[str, Any]) -> None:
            """Recursively add a tag and all its descendants."""
            label = make_rtl_text(tag["name"]) if detect_rtl(tag["name"]) else tag["name"]
            if tag["id"] in tags_with_children:
                node = parent_node.add(label, data=tag)
            else:
                node = parent_node.add_leaf(label, data=tag)
            # Recursively add children
            for child in children_by_parent.get(tag["id"], []):
                add_tag_recursive(node, child)

        # Start from root tags (parent_id=None) and build recursively
        for tag in children_by_parent.get(None, []):
            add_tag_recursive(self.root, tag)


class TagManagementScreen(ModalScreen[None]):
    """Modal screen for managing tags on a note.

    Features:
    - Shows all tags hierarchically with collapse/expand
    - Filter field filters on each keypress
    - Shows full hierarchy path when filtering (e.g., Geography > Europe > France > Paris)
    - Checkboxes to add/remove tags from the note
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
    ]

    CSS = """
    TagManagementScreen {
        align: center middle;
    }

    #tag-management-dialog {
        width: 80;
        height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #tag-filter-input {
        margin-bottom: 1;
    }

    #tag-list-container {
        height: 1fr;
        border: solid $primary-darken-2;
        padding: 0 1;
    }

    .tag-item {
        height: auto;
        padding: 0 1;
    }

    .tag-item-row {
        height: 3;
        width: 100%;
    }

    .tag-item-selected {
        background: $accent;
    }

    .tag-path {
        color: $text-muted;
        text-style: italic;
    }

    .tag-toggle {
        width: 3;
        min-width: 3;
        height: 1;
        padding: 0;
        margin: 0;
        background: transparent;
        border: none;
    }

    .tag-toggle:hover {
        background: $primary-darken-1;
    }

    #tag-management-buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    """

    def __init__(self, db: Database, note_id: str) -> None:
        super().__init__()
        self.db = db
        self.note_id = note_id
        self._all_tags: List[Dict[str, Any]] = []
        self._note_tag_ids: set = set()
        self._tag_paths: Dict[str, str] = {}  # tag_id -> full path
        self._filtered_tags: List[Dict[str, Any]] = []
        self._children_by_parent: Dict[str, set] = {}  # parent_id -> set of child ids
        self._collapsed_ids: set = set()  # Set of collapsed tag IDs

    def compose(self) -> ComposeResult:
        with Vertical(id="tag-management-dialog"):
            yield Label("Manage Tags for Note", id="tag-management-title")
            yield Input(placeholder="Filter tags...", id="tag-filter-input")
            yield VerticalScroll(id="tag-list-container")
            with Horizontal(id="tag-management-buttons"):
                yield Button("Close", id="close-btn", variant="primary")

    def on_mount(self) -> None:
        """Load tags when mounted."""
        self._load_tags()
        self._update_display()
        # Focus the filter input
        self.query_one("#tag-filter-input", Input).focus()

    def _load_tags(self) -> None:
        """Load all tags and compute paths."""
        all_tags = self.db.get_all_tags()

        # Filter out _system tag and its descendants
        system_tag_id = self.db.get_system_tag_id_hex()
        if system_tag_id:
            all_tags = [
                tag for tag in all_tags
                if tag["id"] != system_tag_id and tag.get("parent_id") != system_tag_id
            ]

        note_tags = self.db.get_note_tags(self.note_id)
        self._note_tag_ids = {t["id"] for t in note_tags}

        # Build tag lookup by ID
        tag_by_id = {t["id"]: t for t in all_tags}

        # Build children map
        self._children_by_parent = {}
        for tag in all_tags:
            parent_id = tag.get("parent_id")
            if parent_id:
                if parent_id not in self._children_by_parent:
                    self._children_by_parent[parent_id] = set()
                self._children_by_parent[parent_id].add(tag["id"])

        # Compute full path for each tag
        self._tag_paths = {}
        for tag in all_tags:
            path_parts = []
            current = tag
            while current:
                path_parts.insert(0, current["name"])
                parent_id = current.get("parent_id")
                current = tag_by_id.get(parent_id) if parent_id else None
            self._tag_paths[tag["id"]] = " > ".join(path_parts)

        # Sort tags by their full path to get hierarchical order
        self._all_tags = sorted(all_tags, key=lambda t: self._tag_paths[t["id"]].lower())
        self._filtered_tags = self._all_tags[:]

    def _has_children(self, tag_id: str) -> bool:
        """Check if a tag has children."""
        return tag_id in self._children_by_parent

    def _is_hidden_by_collapse(self, tag: Dict[str, Any]) -> bool:
        """Check if tag is hidden due to a collapsed ancestor."""
        tag_by_id = {t["id"]: t for t in self._all_tags}
        current = tag.get("parent_id")
        while current:
            if current in self._collapsed_ids:
                return True
            parent_tag = tag_by_id.get(current)
            current = parent_tag.get("parent_id") if parent_tag else None
        return False

    def _toggle_collapse(self, tag_id: str) -> None:
        """Toggle collapse state of a tag."""
        if tag_id in self._collapsed_ids:
            self._collapsed_ids.discard(tag_id)
        else:
            self._collapsed_ids.add(tag_id)
        self._update_display()

    def _filter_tags(self, filter_text: str) -> None:
        """Filter tags based on input text."""
        if not filter_text.strip():
            self._filtered_tags = self._all_tags[:]
        else:
            filter_lower = filter_text.lower()
            # Match tags where the path contains the filter text
            self._filtered_tags = [
                tag for tag in self._all_tags
                if filter_lower in self._tag_paths[tag["id"]].lower()
            ]

    def _update_display(self) -> None:
        """Update the tag list display."""
        container = self.query_one("#tag-list-container", VerticalScroll)
        container.remove_children()

        filter_text = self.query_one("#tag-filter-input", Input).value.strip()
        is_filtering = bool(filter_text)

        for tag in self._filtered_tags:
            tag_id = tag["id"]

            # Skip hidden tags when not filtering
            if not is_filtering and self._is_hidden_by_collapse(tag):
                continue

            is_selected = tag_id in self._note_tag_ids
            has_children = self._has_children(tag_id)
            is_collapsed = tag_id in self._collapsed_ids

            # Show path when filtering, otherwise just name with hierarchy
            if is_filtering:
                display_text = self._tag_paths[tag_id]
                # Simple checkbox for filtered view
                checkbox = Checkbox(
                    display_text,
                    value=is_selected,
                    id=f"tag-checkbox-{tag_id}",
                    classes="tag-item" + (" tag-item-selected" if is_selected else "")
                )
                checkbox.tag_id = tag_id
                container.mount(checkbox)
            else:
                # Show indented hierarchy with collapse toggle
                depth = self._get_tag_depth(tag)
                indent = "  " * depth

                # Create horizontal container for toggle + checkbox
                row = Horizontal(classes="tag-item-row")

                # Add indent spacing
                if depth > 0:
                    indent_label = Static(indent, classes="tag-indent")
                    row.compose_add_child(indent_label)

                # Add collapse toggle for parent tags
                if has_children:
                    toggle_char = "▶" if is_collapsed else "▼"
                    toggle_btn = Button(toggle_char, classes="tag-toggle", id=f"toggle-{tag_id}")
                    toggle_btn.tag_id = tag_id
                    row.compose_add_child(toggle_btn)
                else:
                    # Spacer for alignment
                    spacer = Static("   ", classes="tag-toggle-spacer")
                    row.compose_add_child(spacer)

                # Add checkbox
                checkbox = Checkbox(
                    tag["name"],
                    value=is_selected,
                    id=f"tag-checkbox-{tag_id}",
                    classes="tag-item" + (" tag-item-selected" if is_selected else "")
                )
                checkbox.tag_id = tag_id
                row.compose_add_child(checkbox)

                container.mount(row)

    def _get_tag_depth(self, tag: Dict[str, Any]) -> int:
        """Get the depth of a tag in the hierarchy."""
        tag_by_id = {t["id"]: t for t in self._all_tags}
        depth = 0
        current = tag
        while current.get("parent_id"):
            depth += 1
            current = tag_by_id.get(current["parent_id"], {})
        return depth

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle filter input changes."""
        if event.input.id == "tag-filter-input":
            self._filter_tags(event.value)
            self._update_display()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "close-btn":
            self.dismiss(None)
        elif event.button.id and event.button.id.startswith("toggle-"):
            tag_id = getattr(event.button, 'tag_id', None)
            if tag_id:
                self._toggle_collapse(tag_id)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox toggle - add/remove tag from note."""
        checkbox = event.checkbox
        tag_id = getattr(checkbox, 'tag_id', None)
        if not tag_id:
            return

        if event.value:
            # Add tag to note
            success = self.db.add_tag_to_note(self.note_id, tag_id)
            if success:
                self._note_tag_ids.add(tag_id)
                self.notify(f"Tag added")
            else:
                self.notify("Failed to add tag", severity="error")
                checkbox.value = False
        else:
            # Remove tag from note
            success = self.db.remove_tag_from_note(self.note_id, tag_id)
            if success:
                self._note_tag_ids.discard(tag_id)
                self.notify(f"Tag removed")
            else:
                self.notify("Failed to remove tag", severity="error")
                checkbox.value = True

    def action_close(self) -> None:
        """Close the modal."""
        self.dismiss(None)


class HistoryScreen(ModalScreen[bool]):
    """Every version of a note's content, oldest first, with restore.

    Restoring is an ordinary edit (nothing is lost, and it syncs). Dismisses
    with True when something was restored.
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
    ]

    CSS = """
    HistoryScreen {
        align: center middle;
    }

    #history-dialog {
        width: 90%;
        height: 85%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #history-list {
        height: 40%;
        border: solid $primary-darken-2;
    }

    #history-content {
        height: 1fr;
        border: solid $primary-darken-2;
        padding: 0 1;
    }

    #history-buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    """

    def __init__(self, db: Database, note_id: str) -> None:
        super().__init__()
        self.db = db
        self.note_id = note_id
        self.versions: List[Any] = []
        self.restored = False

    def compose(self) -> ComposeResult:
        with Vertical(id="history-dialog"):
            yield Label(f"History of note {self.note_id[:UUID_SHORT_LEN]} (oldest first)", id="history-title")
            yield ListView(id="history-list")
            yield Static("", id="history-content")
            with Horizontal(id="history-buttons"):
                yield Button("Restore this version", id="history-restore-btn", variant="warning")
                yield Button("Close", id="history-close-btn", variant="primary")

    def on_mount(self) -> None:
        self._load()

    def _load(self) -> None:
        self.versions = ConflictManager(self.db).get_field_history("note", self.note_id, "content")
        current = (self.db.get_note_raw(self.note_id) or {}).get("content")
        lv = self.query_one("#history-list", ListView)
        lv.clear()
        for v in self.versions:
            kind = "merge" if v.merge_parent_id else ("original" if v.parent_id is None else "edit")
            if v.conflict_kind:
                kind += f" ({v.conflict_kind} conflict)"
            first = (v.content or "").split("\n", 1)[0][:50]
            mark = "  <- current" if (v.content or "") == current else ""
            lv.append(ListItem(Label(f"{format_timestamp(v.created_at, v.created_at_offset)}  {v.device_label}  {kind}  {first}{mark}")))
        if self.versions:
            lv.index = len(self.versions) - 1
            self._show(len(self.versions) - 1)

    def _show(self, index: int) -> None:
        if 0 <= index < len(self.versions):
            self.query_one("#history-content", Static).update(self.versions[index].content or "")

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        lv = self.query_one("#history-list", ListView)
        if lv.index is not None:
            self._show(lv.index)

    def selected_version(self) -> Optional[Any]:
        lv = self.query_one("#history-list", ListView)
        if lv.index is not None and 0 <= lv.index < len(self.versions):
            return self.versions[lv.index]
        return None

    def restore_selected(self) -> bool:
        v = self.selected_version()
        if v is None:
            return False
        current = (self.db.get_note_raw(self.note_id) or {}).get("content")
        if (v.content or "") == current:
            self.app.notify("That version is already the current content", severity="warning")
            return False
        self.db.update_note(self.note_id, v.content or "")
        self.restored = True
        self.app.notify(f"Restored version from {format_timestamp(v.created_at, v.created_at_offset)}")
        self._load()
        return True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "history-restore-btn":
            self.restore_selected()
        elif event.button.id == "history-close-btn":
            self.dismiss(self.restored)

    def action_close(self) -> None:
        self.dismiss(self.restored)


class TrashScreen(ModalScreen[bool]):
    """The trash bin: the notes that were deleted and are still recoverable.

    Deleting a note has always been a soft delete, so nothing has been lost.
    From here a note goes back to the list, or out of the database for good
    on every device.

    Dismisses with True when something changed, so the caller reloads.
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
    ]

    CSS = """
    TrashScreen {
        align: center middle;
    }

    #trash-dialog {
        width: 90%;
        height: 85%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #trash-list {
        height: 1fr;
        border: solid $primary-darken-2;
    }

    #trash-content {
        height: 30%;
        border: solid $primary-darken-2;
        padding: 0 1;
    }

    #trash-buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    """

    def __init__(self, db: Database, audiofile_directory: Optional[Path] = None) -> None:
        super().__init__()
        self.db = db
        self.audiofile_directory = audiofile_directory
        self.notes: List[Dict[str, Any]] = []
        self.changed = False
        self.confirm_purge_id: Optional[str] = None

    def compose(self) -> ComposeResult:
        with Vertical(id="trash-dialog"):
            yield Label("Trash", id="trash-title")
            yield ListView(id="trash-list")
            yield Static("", id="trash-content")
            with Horizontal(id="trash-buttons"):
                yield Button("Recover", id="trash-recover-btn", variant="primary")
                yield Button("Delete for good", id="trash-purge-btn", variant="error")
                yield Button("Close", id="trash-close-btn")

    def on_mount(self) -> None:
        self._load()

    def _load(self) -> None:
        self.notes = self.db.get_deleted_notes()
        self.confirm_purge_id = None
        title = self.query_one("#trash-title", Label)
        title.update(f"Trash ({len(self.notes)} note(s))" if self.notes else "Trash (empty)")
        lv = self.query_one("#trash-list", ListView)
        lv.clear()
        for note in self.notes:
            lines = [line.strip() for line in (note["content"] or "").split("\n") if line.strip()]
            first = lines[0][:60] if lines else "(no text)"
            deleted = format_timestamp(note.get("deleted_at"), note.get("deleted_at_offset"))
            lv.append(ListItem(Label(f"deleted {deleted}  {first}")))
        if self.notes:
            lv.index = 0
            self._show(0)
        else:
            self.query_one("#trash-content", Static).update("Nothing has been deleted.")

    def _show(self, index: int) -> None:
        if 0 <= index < len(self.notes):
            self.query_one("#trash-content", Static).update(self.notes[index]["content"] or "(no text)")

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        lv = self.query_one("#trash-list", ListView)
        if lv.index is not None:
            self.confirm_purge_id = None
            self._show(lv.index)

    def selected_note(self) -> Optional[Dict[str, Any]]:
        lv = self.query_one("#trash-list", ListView)
        if lv.index is not None and 0 <= lv.index < len(self.notes):
            return self.notes[lv.index]
        return None

    def recover_selected(self) -> None:
        note = self.selected_note()
        if note is None:
            return
        if self.db.undelete_note(note["id"]):
            self.changed = True
            self.app.notify(f"Recovered note {note['id'][:UUID_SHORT_LEN]}")
            self._load()

    def purge_selected(self) -> None:
        """Remove the selected note for good. Asks once, in place."""
        note = self.selected_note()
        if note is None:
            return
        if self.confirm_purge_id != note["id"]:
            # First press asks; the second press does it. No dialog to
            # dismiss by accident, and no way to do it with one keystroke.
            self.confirm_purge_id = note["id"]
            self.app.notify(
                "This removes the note for good, on every device. Press again to confirm.",
                severity="warning",
            )
            return
        audio_ids = self.db.purge_note(note["id"])
        removed = purge_audio_files(audio_ids, self.audiofile_directory)
        self.changed = True
        self.app.notify(
            f"Removed note {note['id'][:UUID_SHORT_LEN]} for good"
            + (f" and {removed} recording file(s)" if removed else "")
        )
        self._load()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "trash-recover-btn":
            self.recover_selected()
        elif event.button.id == "trash-purge-btn":
            self.purge_selected()
        elif event.button.id == "trash-close-btn":
            self.dismiss(self.changed)

    def action_close(self) -> None:
        self.dismiss(self.changed)


class TranscriptionQueueScreen(ModalScreen[bool]):
    """What is waiting to be transcribed on this machine, and what it cost.

    Three groups, read downwards as time runs forwards: what is **waiting**,
    what is being **worked on**, and what is **done**. Newest first within each
    group, as in the notes list, so the order the waiting Recordings will really
    be reached in is printed on the row itself.

    A waiting Recording can be moved to the front (the one being worked on is
    never interrupted) or taken out. A finished one shows how much text came
    out, how long the Recording was, and what the work cost in clock time,
    processor time and memory — which is where the waiting estimates come from.

    Dismisses with True when the queue changed.
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("n", "do_next", "Do next"),
        Binding("r", "remove", "Remove"),
        Binding("f5", "reload", "Reload"),
    ]

    CSS = """
    TranscriptionQueueScreen {
        align: center middle;
    }

    #queue-dialog {
        width: 90%;
        height: 85%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #queue-list {
        height: 1fr;
        border: solid $primary-darken-2;
    }

    #queue-detail {
        height: 30%;
        border: solid $primary-darken-2;
        padding: 0 1;
    }

    #queue-buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    """

    def __init__(self, db: Database, config: Config) -> None:
        super().__init__()
        self.db = db
        self.config = config
        self.rows: List[Any] = []
        self.changed = False

    def compose(self) -> ComposeResult:
        with Vertical(id="queue-dialog"):
            yield Label("Transcription queue", id="queue-title")
            yield ListView(id="queue-list")
            yield Static("", id="queue-detail")
            with Horizontal(id="queue-buttons"):
                yield Button("Do next", id="queue-next-btn", variant="primary")
                yield Button("Remove", id="queue-remove-btn", variant="error")
                yield Button("Close", id="queue-close-btn")

    def on_mount(self) -> None:
        self._load()

    def _load(self) -> None:
        from src.core import transcription_queue as queue_module

        view = queue_module.view(self.db, self.config)
        title = self.query_one("#queue-title", Label)
        if view.rate:
            title.update(
                f"Transcription queue — about {view.rate:.1f} s of work per second of audio here"
            )
        else:
            title.update("Transcription queue")

        # One flat list, in the order the groups are read: waiting, then what is
        # being worked on, then what is done. The group is said on each row.
        self.rows = list(view.waiting) + list(view.processing) + list(view.completed)
        lv = self.query_one("#queue-list", ListView)
        lv.clear()
        for row in self.rows:
            lv.append(ListItem(Label(self._line(row))))
        if self.rows:
            lv.index = 0
            self._show(0)
        else:
            self.query_one("#queue-detail", Static).update(
                "Nothing is waiting, and nothing has been transcribed on this machine yet."
            )

    def _line(self, row: Any) -> str:
        """One row: what group it is in, its place, and what it is."""
        from src.core import transcription_queue as queue_module

        length = f"{int(row.audio_seconds) // 60}:{int(row.audio_seconds) % 60:02d}" if row.audio_seconds else "-"
        note = (row.note_line or "(no note)")[:48]
        if row.state == "waiting":
            place = "next" if row.position == 1 else f"{row.position}th"
            wait = queue_module.in_words(row.wait_seconds)
            tail = f" · done in {wait}" if wait else ""
            return f"waiting  {place:<6} {length:>7}  {note}{tail}"
        if row.state == "processing":
            return f"working         {length:>7}  {note}"
        mark = "failed" if row.state == "failed" else "done"
        return f"{mark:<8}        {length:>7}  {note}"

    def _show(self, index: int) -> None:
        if not (0 <= index < len(self.rows)):
            return
        row = self.rows[index]
        lines = [f"{row.filename}", f"Note: {row.note_line or '(none)'}"]
        if row.model:
            lines.append(f"Model: {row.model}")
        if row.state == "waiting":
            from src.core import transcription_queue as queue_module

            lines.append(f"Place in the queue: {row.position}")
            wait = queue_module.in_words(row.wait_seconds)
            lines.append(f"Done in: {wait or 'no estimate yet'}")
        elif row.state == "processing":
            lines.append(row.outcome or "working")
        else:
            work = row.work
            if row.characters is not None:
                lines.append(f"Text: {row.characters} characters")
            if work and work.clock_seconds:
                lines.append(f"Clock time: {work.clock_seconds:.0f} s")
            if work and work.cpu_seconds:
                lines.append(f"Processor time: {work.cpu_seconds:.0f} s")
            if work and work.cores_busy:
                lines.append(f"Cores busy: {work.cores_busy:.2f}")
            if work and work.peak_memory_bytes:
                lines.append(f"Memory, peak: {work.peak_memory_bytes / 1e6:.0f} MB")
            if work and work.speed_vs_realtime:
                lines.append(f"Speed: {work.speed_vs_realtime:.2f}× real time")
            if row.state == "failed" and row.outcome:
                lines.append(row.outcome)
        self.query_one("#queue-detail", Static).update("\n".join(lines))

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        lv = self.query_one("#queue-list", ListView)
        if lv.index is not None:
            self._show(lv.index)

    def _selected(self) -> Optional[Any]:
        lv = self.query_one("#queue-list", ListView)
        if lv.index is not None and 0 <= lv.index < len(self.rows):
            return self.rows[lv.index]
        return None

    def action_do_next(self) -> None:
        from src.core import transcription_queue as queue_module

        row = self._selected()
        if row is None or row.state != "waiting":
            self.app.notify("Only a Recording that is waiting can be moved.", severity="warning")
            return
        if queue_module.Queue(self.config.config_dir).do_next(row.audio_file_id):
            self.changed = True
            self.app.notify("It will be transcribed next.")
            self._load()
        else:
            self.app.notify("It is already next.", severity="warning")

    def action_remove(self) -> None:
        from src.core import transcription_queue as queue_module

        row = self._selected()
        if row is None or row.state != "waiting":
            self.app.notify("Only a Recording that is waiting can be taken out.", severity="warning")
            return
        if queue_module.Queue(self.config.config_dir).remove(row.audio_file_id):
            self.changed = True
            self.app.notify("Taken out of the queue.")
            self._load()

    def action_reload(self) -> None:
        self._load()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "queue-next-btn":
            self.action_do_next()
        elif event.button.id == "queue-remove-btn":
            self.action_remove()
        elif event.button.id == "queue-close-btn":
            self.dismiss(self.changed)

    def action_close(self) -> None:
        self.dismiss(self.changed)


def purge_audio_files(audio_ids: List[str], directory: Optional[Path]) -> int:
    """Delete the files of recordings that were purged; return how many went.

    The database says which recordings were removed; where their files live
    is the application's business, not the core's.
    """
    if not audio_ids or directory is None:
        return 0
    removed = 0
    for audio_id in audio_ids:
        for path in Path(directory).glob(f"{audio_id}.*"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


class ResolveConflictScreen(ModalScreen[bool]):
    """Side-by-side resolution of one text conflict.

    Shows version A, version B and the common ancestor read-only, and the
    result in an editable area (starting from the merged text). Saving writes
    the field once, which resolves the conflict on every device. Dismisses
    with True when saved.
    """

    BINDINGS = [
        Binding("escape", "close", "Cancel"),
    ]

    CSS = """
    ResolveConflictScreen {
        align: center middle;
    }

    #resolve-dialog {
        width: 95%;
        height: 90%;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }

    #resolve-sides {
        height: 40%;
    }

    .resolve-side {
        width: 1fr;
        border: solid $primary-darken-2;
        padding: 0 1;
    }

    #resolve-base {
        height: 5;
        border: solid $primary-darken-2;
        padding: 0 1;
    }

    #resolve-result {
        height: 1fr;
    }

    #resolve-buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    """

    def __init__(self, db: Database, conflict: Conflict) -> None:
        super().__init__()
        self.db = db
        self.conflict = conflict
        self.versions = ConflictManager(db).get_conflict_versions(conflict)
        self.resolved = False

    def compose(self) -> ComposeResult:
        c = self.conflict
        v = self.versions
        with Vertical(id="resolve-dialog"):
            yield Label(f"{c.describe()}. Edit the result, then Save.", id="resolve-title")
            with Horizontal(id="resolve-sides"):
                yield Static(f"[b]{c.device_a_label} (A)[/b]\n" + (v.version_a.content if v.version_a else ""), classes="resolve-side", id="resolve-side-a")
                yield Static(f"[b]{c.device_b_label} (B)[/b]\n" + (v.version_b.content if v.version_b else ""), classes="resolve-side", id="resolve-side-b")
            yield Static("[b]Common ancestor[/b]\n" + ((v.base.content if v.base else "") or ""), id="resolve-base")
            yield TextArea((v.merge.content if v.merge else "") or "", id="resolve-result", language=None)
            with Horizontal(id="resolve-buttons"):
                yield Button("Start from A", id="resolve-use-a")
                yield Button("Start from B", id="resolve-use-b")
                yield Button("Start from merged", id="resolve-use-merge")
                yield Button("Save", id="resolve-save-btn", variant="success")
                yield Button("Cancel", id="resolve-cancel-btn")

    def result_text(self) -> str:
        return self.query_one("#resolve-result", TextArea).text

    def save(self) -> bool:
        text = self.result_text()
        ok = ConflictManager(self.db).resolve_with_content(self.conflict.id, text)
        if not ok:
            self.app.notify("This conflict was already resolved", severity="warning")
        self.resolved = True
        return ok

    def on_button_pressed(self, event: Button.Pressed) -> None:
        area = self.query_one("#resolve-result", TextArea)
        v = self.versions
        if event.button.id == "resolve-use-a":
            area.text = (v.version_a.content if v.version_a else "") or ""
        elif event.button.id == "resolve-use-b":
            area.text = (v.version_b.content if v.version_b else "") or ""
        elif event.button.id == "resolve-use-merge":
            area.text = (v.merge.content if v.merge else "") or ""
        elif event.button.id == "resolve-save-btn":
            self.save()
            self.dismiss(True)
        elif event.button.id == "resolve-cancel-btn":
            self.dismiss(False)

    def action_close(self) -> None:
        self.dismiss(False)


class SearchInput(Input):
    """Search input that skips tab focus - use Up Arrow from list to access."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Skip this widget in tab order
        self.can_focus = False

    def on_key(self, event: Key) -> None:
        """Handle Down Arrow to focus the notes list and select first item."""
        if event.key == "down":
            listview = self.app.query_one("#notes-listview", NotesListView)
            # Only move to list if there are items
            if len(listview.children) > 0:
                listview.focus()
                if listview.index is None:
                    listview.index = 0
                event.stop()

    def on_blur(self) -> None:
        """Disable focus again when leaving the search input."""
        self.can_focus = False


class TUIAudioPlayer(Container):
    """TUI audio player widget with ASCII waveform and controls.

    Features:
    - ASCII waveform display that shows playback progress
    - Play/pause button
    - Skip back 3s and 10s buttons
    - Time display (MM:SS or HH:MM:SS)
    - File list with selection and transcription count
    """

    def __init__(self, audiofile_directory: Optional[Path] = None) -> None:
        super().__init__(id="tui-audio-player")
        self.audiofile_directory = audiofile_directory
        self._player = AudioPlayer()
        self._audio_files: List[Dict[str, Any]] = []
        self._file_paths: List[Path] = []
        self._waveforms: Dict[int, List[float]] = {}
        self._transcription_counts: Dict[str, int] = {}
        self._update_interval: float = 0.1
        self._db: Optional[Database] = None
        # Audio files not on this device, split by whether they can be fetched
        self._missing_in_cloud: List[Dict[str, Any]] = []
        self._missing_pending: List[Dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Static("No audio files", id="audio-waveform")
        yield Static("00:00 / 00:00", id="audio-time")
        yield Horizontal(
            Button("⏪10", id="skip-10-btn"),
            Button("⏪3", id="skip-3-btn"),
            Button("▶", id="play-btn"),
            Button("1x", id="speed-btn", disabled=True),
            Button("⬇ Download", id="download-btn", variant="warning"),
            id="audio-controls"
        )
        yield Static("", id="audio-missing-label", classes="media-missing")
        yield Static("", id="audio-files-label")

    def on_mount(self) -> None:
        """Start update timer when mounted."""
        self.set_interval(self._update_interval, self._update_display)
        self.query_one("#download-btn", Button).display = False
        self.query_one("#audio-missing-label", Static).display = False

    def has_downloadable_media(self) -> bool:
        """Whether some audio files of the current note can be fetched from the cloud."""
        return bool(self._missing_in_cloud)

    def _update_missing_media(self) -> None:
        """Show the 'media missing' notice and Download button when appropriate."""
        if not self.audiofile_directory:
            self._missing_in_cloud, self._missing_pending = [], []
        else:
            missing = missing_audio_files(self._audio_files, self.audiofile_directory)
            self._missing_in_cloud = missing[STATUS_IN_CLOUD]
            self._missing_pending = missing[STATUS_PENDING]

        label = self.query_one("#audio-missing-label", Static)
        button = self.query_one("#download-btn", Button)
        parts = []
        if self._missing_in_cloud:
            parts.append(
                f"Media missing: {len(self._missing_in_cloud)} file(s) not on this device. "
                "Press Download or 'd' to fetch from cloud storage."
            )
        if self._missing_pending:
            parts.append(
                f"{len(self._missing_pending)} file(s) not uploaded by their device yet."
            )
        label.update(" ".join(parts))
        label.display = bool(parts)
        button.display = bool(self._missing_in_cloud)

    def set_downloading(self, downloading: bool) -> None:
        """Reflect an in-progress download in the controls."""
        button = self.query_one("#download-btn", Button)
        button.disabled = downloading
        button.label = "Downloading…" if downloading else "⬇ Download"

    def set_audio_files(
        self,
        audio_files: List[Dict[str, Any]],
        db: Database,
        transcription_counts: Optional[Dict[str, int]] = None,
    ) -> None:
        """Set the audio files to display.

        Args:
            audio_files: List of audio file dicts.
            db: Database for getting file paths.
            transcription_counts: Optional dict mapping audio_file_id to transcription count.
        """
        self._audio_files = audio_files
        self._db = db
        self._file_paths = []
        self._waveforms = {}
        self._transcription_counts = transcription_counts or {}

        if not audio_files or not self.audiofile_directory:
            self.query_one("#audio-files-label", Static).update("No audio files")
            self._update_missing_media()
            return

        # Build file paths and file display strings
        manager = AudioFileManager(self.audiofile_directory)
        file_display = []
        for af in audio_files:
            audio_id = af.get("id", "")
            filename = af.get("filename", "")
            t_count = self._transcription_counts.get(audio_id, 0)
            path = manager.get_record_path(af)
            marker = "" if path.is_file() else " (missing)"
            file_display.append(f"{filename}{marker} | T:{t_count}")
            self._file_paths.append(path)

        self._update_missing_media()

        # Set files in player
        self._player.set_audio_files(self._file_paths)

        # Waveforms: from the levels a device kept (FILE-20), else decoded
        # here (synchronous for simplicity) and the levels kept
        for i, path in enumerate(self._file_paths):
            audio_id = audio_files[i].get("id", "")
            stored = db.waveform_bars(audio_id, WAVEFORM_BAR_COUNT) if audio_id else None
            if stored:
                self._waveforms[i] = stored
            elif path.exists():
                accumulator = decode_waveform(path, WAVEFORM_BAR_COUNT)
                self._waveforms[i] = accumulator.bars() if accumulator else []
                if accumulator and audio_id and accumulator.levels():
                    db.set_waveform_levels(audio_id, accumulator.levels())

        # Update files label
        files_text = ", ".join(file_display[:2])
        if len(file_display) > 2:
            files_text += f" (+{len(file_display) - 2} more)"
        self.query_one("#audio-files-label", Static).update(f"Files: {files_text}")

        # Update waveform display
        self._update_display()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id
        if button_id == "play-btn":
            self._on_play_pause()
        elif button_id == "skip-10-btn":
            self._player.skip_back(10)
        elif button_id == "skip-3-btn":
            self._player.skip_back(3)

    def _on_play_pause(self) -> None:
        """Handle play/pause."""
        state = self._player.state
        if state.current_file_index < 0 and self._file_paths:
            self._player.play_file(0)
        else:
            self._player.toggle_play_pause()
        self._update_display()

    def _update_display(self) -> None:
        """Update the waveform and time display."""
        state = self._player.state

        # Update play button
        play_btn = self.query_one("#play-btn", Button)
        play_btn.label = "⏸" if state.is_playing else "▶"

        # Update time
        time_label = self.query_one("#audio-time", Static)
        current = format_time(state.current_position)
        total = format_time(state.duration)
        time_label.update(f"{current} / {total}")

        # Update waveform
        waveform_widget = self.query_one("#audio-waveform", Static)
        if state.current_file_index >= 0:
            waveform = self._waveforms.get(state.current_file_index, [])
            progress = state.current_position / state.duration if state.duration > 0 else 0
            # Use terminal width - some margin
            width = 60
            ascii_waveform = waveform_with_progress(waveform, progress, width)
            waveform_widget.update(ascii_waveform)
        elif self._waveforms:
            # Show first file's waveform
            waveform = self._waveforms.get(0, [])
            ascii_waveform = waveform_with_progress(waveform, 0.0, 60)
            waveform_widget.update(ascii_waveform)

    def cleanup(self) -> None:
        """Clean up resources."""
        self._player.release()


class TUITranscriptionBox(Container):
    """A single transcription display with edit capability."""

    def __init__(
        self,
        transcription: Dict[str, Any],
        db: Database,
        index: int,
    ) -> None:
        super().__init__(id=f"transcription-box-{index}")
        self._transcription = transcription
        self._db = db
        self._index = index
        self._is_editing = False
        self._original_content = ""
        self._original_state = ""

    def compose(self) -> ComposeResult:
        service = self._transcription.get("service", "Unknown")
        content = self._transcription.get("content", "")
        state = self._transcription.get("state", DEFAULT_TRANSCRIPTION_FLAGS)
        created_at = format_timestamp(self._transcription.get("created_at"), self._transcription.get("created_at_offset"))

        # Preview text (first 100 chars)
        preview = content[:100].replace("\n", " ")
        if len(content) > 100:
            preview += "..."

        with Collapsible(title=f"{service} - {created_at}", collapsed=True):
            # View mode widgets
            yield Static(content, id=f"trans-view-{self._index}", classes="transcription-content")
            yield Static(f"State: {state}", id=f"trans-state-view-{self._index}", classes="transcription-state")

            # Edit mode widgets (hidden initially)
            yield TextArea(id=f"trans-edit-{self._index}", language=None)
            yield Input(value=state, id=f"trans-state-edit-{self._index}", placeholder="State")

            # Buttons
            yield Horizontal(
                Button("Edit", id=f"trans-edit-btn-{self._index}", variant="primary"),
                Button("Save", id=f"trans-save-btn-{self._index}", variant="success"),
                Button("Cancel", id=f"trans-cancel-btn-{self._index}"),
                id=f"trans-buttons-{self._index}"
            )

    def on_mount(self) -> None:
        """Hide edit widgets initially."""
        self.query_one(f"#trans-edit-{self._index}", TextArea).display = False
        self.query_one(f"#trans-state-edit-{self._index}", Input).display = False
        self.query_one(f"#trans-save-btn-{self._index}", Button).display = False
        self.query_one(f"#trans-cancel-btn-{self._index}", Button).display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id or ""

        if button_id == f"trans-edit-btn-{self._index}":
            self._start_editing()
            event.stop()
        elif button_id == f"trans-save-btn-{self._index}":
            self._save_changes()
            event.stop()
        elif button_id == f"trans-cancel-btn-{self._index}":
            self._cancel_editing()
            event.stop()

    def _start_editing(self) -> None:
        """Start editing mode."""
        content = self._transcription.get("content", "")
        state = self._transcription.get("state", DEFAULT_TRANSCRIPTION_FLAGS)

        self._original_content = content
        self._original_state = state
        self._is_editing = True

        # Load content into edit widgets
        self.query_one(f"#trans-edit-{self._index}", TextArea).load_text(content)
        self.query_one(f"#trans-state-edit-{self._index}", Input).value = state

        # Toggle visibility
        self.query_one(f"#trans-view-{self._index}", Static).display = False
        self.query_one(f"#trans-state-view-{self._index}", Static).display = False
        self.query_one(f"#trans-edit-{self._index}", TextArea).display = True
        self.query_one(f"#trans-state-edit-{self._index}", Input).display = True
        self.query_one(f"#trans-edit-btn-{self._index}", Button).display = False
        self.query_one(f"#trans-save-btn-{self._index}", Button).display = True
        self.query_one(f"#trans-cancel-btn-{self._index}", Button).display = True

        # Focus the text area
        self.query_one(f"#trans-edit-{self._index}", TextArea).focus()

    def _save_changes(self) -> None:
        """Save changes to database."""
        new_content = self.query_one(f"#trans-edit-{self._index}", TextArea).text
        new_state = self.query_one(f"#trans-state-edit-{self._index}", Input).value

        transcription_id = self._transcription.get("id", "")
        try:
            success = self._db.update_transcription(
                transcription_id, new_content, state=new_state
            )
            if success:
                # Update internal state
                self._transcription["content"] = new_content
                self._transcription["state"] = new_state
                self._original_content = new_content
                self._original_state = new_state

                # Update view widgets
                self.query_one(f"#trans-view-{self._index}", Static).update(new_content)
                self.query_one(f"#trans-state-view-{self._index}", Static).update(f"State: {new_state}")

                self.app.notify("Transcription saved!")
                logger.info(f"Saved transcription {transcription_id}")
            else:
                self.app.notify("Failed to save transcription", severity="error")
                logger.warning(f"Failed to save transcription {transcription_id}")
        except Exception as e:
            self.app.notify(f"Error: {e}", severity="error")
            logger.error(f"Error saving transcription {transcription_id}: {e}")

        self._cancel_editing()

    def _cancel_editing(self) -> None:
        """Cancel editing and restore view mode."""
        self._is_editing = False

        # Toggle visibility back
        self.query_one(f"#trans-view-{self._index}", Static).display = True
        self.query_one(f"#trans-state-view-{self._index}", Static).display = True
        self.query_one(f"#trans-edit-{self._index}", TextArea).display = False
        self.query_one(f"#trans-state-edit-{self._index}", Input).display = False
        self.query_one(f"#trans-edit-btn-{self._index}", Button).display = True
        self.query_one(f"#trans-save-btn-{self._index}", Button).display = False
        self.query_one(f"#trans-cancel-btn-{self._index}", Button).display = False


class TUITranscriptionsContainer(Container):
    """Container for displaying and editing transcriptions in TUI."""

    def __init__(self, db: Database) -> None:
        super().__init__(id="tui-transcriptions")
        self._db = db
        self._audio_file_id: Optional[str] = None
        self._transcription_boxes: List[TUITranscriptionBox] = []

    def compose(self) -> ComposeResult:
        yield Label("Transcriptions", id="transcriptions-header")
        yield Container(id="transcriptions-content")

    def set_audio_file(
        self,
        audio_file_id: Optional[str],
        transcriptions: List[Dict[str, Any]],
    ) -> None:
        """Set the audio file and its transcriptions.

        Args:
            audio_file_id: Audio file UUID hex string, or None to clear
            transcriptions: List of transcription dicts
        """
        self._audio_file_id = audio_file_id

        # Update header
        count = len(transcriptions)
        self.query_one("#transcriptions-header", Label).update(f"Transcriptions ({count})")

        # Clear existing boxes
        content = self.query_one("#transcriptions-content", Container)
        content.remove_children()
        self._transcription_boxes = []

        # Add new boxes
        for i, t in enumerate(transcriptions):
            box = TUITranscriptionBox(t, self._db, i)
            self._transcription_boxes.append(box)
            content.mount(box)


class NotesListView(ListView):
    """ListView widget for displaying notes."""

    def __init__(self) -> None:
        super().__init__(id="notes-listview")

    def on_focus(self) -> None:
        """Handle focus: select item or redirect to search if empty."""
        if len(self.children) == 0:
            # No notes - focus search bar instead
            search_input = self.app.query_one("#search-input", SearchInput)
            search_input.can_focus = True
            self.app.call_later(search_input.focus)
        elif self.index is None:
            # Has notes but none selected - select first
            self.index = 0

    def on_key(self, event: Key) -> None:
        """Handle Up Arrow at top to focus search input."""
        if event.key == "up":
            # If at the first item, no selection, or empty list, focus search input
            if self.index is None or self.index == 0 or len(self.children) == 0:
                search_input = self.app.query_one("#search-input", SearchInput)
                search_input.can_focus = True
                search_input.focus()
                event.stop()


class NotesList(Container):
    """Notes list container with search input."""

    def __init__(self, db: Database) -> None:
        super().__init__(id="notes-list")
        self.db = db
        self.notes: List[Dict[str, Any]] = []
        self.current_filter_tag: Optional[Dict[str, Any]] = None
        self.current_search: str = ""

    def compose(self) -> ComposeResult:
        yield SearchInput(placeholder="Search (tag:Name or free text)...", id="search-input")
        yield NotesListView()

    def on_mount(self) -> None:
        """Load notes when mounted."""
        self.refresh_notes()

    def _populate_list(self, notes: List[Dict[str, Any]]) -> None:
        """Populate the list view with notes."""
        listview = self.query_one("#notes-listview", NotesListView)
        listview.clear()
        self.notes = []

        # Star icons
        STAR_FILLED = "★"  # U+2605
        STAR_EMPTY = "☆"   # U+2606

        for note in notes:
            # Check if note is marked (starred)
            is_marked = self.db.is_note_marked(note["id"])

            note_dict = {
                "id": note["id"],
                "content": note["content"],
                "created_at": note["created_at"],
                "tag_names": note.get("tag_names", ""),
                "is_marked": is_marked
            }
            self.notes.append(note_dict)

            content_preview = note["content"][:50].replace("\n", " ")
            if len(note["content"]) > 50:
                content_preview += "..."
            tags = note_dict["tag_names"] or "No tags"

            # Add star icon to header
            star = STAR_FILLED if is_marked else STAR_EMPTY
            header_line = f"{star} #{note['id']} | {tags}"
            is_rtl = detect_rtl(content_preview) or detect_rtl(tags)

            # LLM NOTE: For list items, we only use CSS text-align:right for RTL.
            # Do NOT use RLI/PDI markers here - they cause rendering artifacts
            # where text bleeds into adjacent panes. The markers work fine for
            # single-widget display but cause issues in ListView context.
            rich_text = RichText()
            # Apply gold color to filled star
            if is_marked:
                rich_text.append(star, style="bold yellow")
                rich_text.append(f" #{note['id']} | {tags}", style="bold")
            else:
                rich_text.append(header_line, style="bold")
            rich_text.append("\n")
            rich_text.append(content_preview)
            static = Static(rich_text, classes="rtl" if is_rtl else "")
            listview.append(ListItem(static))

    def refresh_notes(self, filter_tag: Optional[Dict[str, Any]] = None) -> None:
        """Refresh the notes list, optionally filtered by tag."""
        self.current_filter_tag = filter_tag

        if filter_tag:
            # Get notes by tag (including descendants)
            tag_ids = self.db.get_tag_descendants(filter_tag["id"])
            notes = self.db.filter_notes(tag_ids)
        else:
            notes = self.db.get_all_notes()

        self._populate_list(notes)

    def perform_search(self, search_text: str) -> None:
        """Execute search and update notes list."""
        self.current_search = search_text
        self.current_filter_tag = None

        if not search_text.strip():
            # Empty search - show all notes
            notes = self.db.get_all_notes()
            self._populate_list(notes)
            return

        result = execute_search(self.db, search_text)

        if result.not_found_tags:
            self.app.notify(f"Tags not found: {', '.join(result.not_found_tags)}", severity="warning")

        if result.ambiguous_tags:
            self.app.notify(f"Ambiguous tags: {', '.join(result.ambiguous_tags)}", severity="information")

        self._populate_list(result.notes)

    def set_search_text(self, text: str) -> None:
        """Set the search input text."""
        search_input = self.query_one("#search-input", SearchInput)
        search_input.value = text

    def get_search_text(self) -> str:
        """Get the current search input text."""
        search_input = self.query_one("#search-input", SearchInput)
        return search_input.value

    def append_search_term(self, term: str) -> None:
        """Append a search term if not already present."""
        current = self.get_search_text()
        if term.lower() not in current.lower():
            new_text = f"{current} {term}".strip()
            self.set_search_text(new_text)

    def clear_search(self) -> None:
        """Clear the search and show all notes."""
        self.set_search_text("")
        self.current_search = ""
        self.current_filter_tag = None
        self.refresh_notes()


class NoteDetail(Container, NoteEditorMixin):
    """Note detail view with editing.

    LLM NOTE: TextArea doesn't support RTL CSS. We use dual-mode display:
    - View mode: Static widget with RLI/PDI markers + CSS text-align:right
    - Edit mode: TextArea (LTR only - Textual limitation)
    Press Edit button to edit, Save to save, Cancel to discard.

    Inherits from NoteEditorMixin to share editing state logic with GUI.
    """

    def __init__(
        self,
        db: Database,
        audiofile_directory: Optional[Path] = None,
        config_dir: Optional[Path] = None,
    ) -> None:
        super().__init__(id="note-detail")
        self.db = db
        self.audiofile_directory = audiofile_directory
        self.config_dir = config_dir
        self.init_editor_state()  # Initialize mixin state
        self.is_rtl: bool = False
        self._audio_player: Optional[TUIAudioPlayer] = None
        self._transcriptions_container: Optional[TUITranscriptionsContainer] = None
        self._downloading: bool = False

    def action_download_media(self) -> None:
        """Download the current note's missing audio files from cloud storage.

        Runs in a worker thread so the UI stays responsive; the note is
        reloaded when the download finishes.
        """
        note_id = self.current_note_id
        if not note_id:
            self.app.notify("Select a note first", severity="warning")
            return
        if not self.audiofile_directory:
            self.app.notify("audiofile_directory is not configured", severity="error")
            return
        if self._downloading:
            self.app.notify("A download is already running")
            return
        if self._audio_player is not None and not self._audio_player.has_downloadable_media():
            self.app.notify("No media to download for this note")
            return

        self._downloading = True
        if self._audio_player is not None:
            self._audio_player.set_downloading(True)
        self.app.notify("Downloading media from cloud storage…")
        self.run_worker(
            partial(self._download_media_blocking, note_id),
            thread=True,
            exclusive=True,
            group="media-download",
            name="media-download",
        )

    def _download_media_blocking(self, note_id: str) -> None:
        """Worker thread body: download and report back on the UI thread."""
        try:
            result = download_audio_files_for_note(note_id, self.config_dir)
            message = f"Media: {describe_download_result(result)}"
            ok = result.failed == 0
            if result.errors:
                message += " — " + "; ".join(result.errors)
        except Exception as e:  # noqa: BLE001 - surface any failure to the user
            message = f"Download failed: {e}"
            ok = False
        self.app.call_from_thread(self._on_media_download_finished, note_id, message, ok)

    def _on_media_download_finished(self, note_id: str, message: str, ok: bool) -> None:
        """Back on the UI thread: reload the note so the player picks up the files."""
        self._downloading = False
        if self._audio_player is not None:
            self._audio_player.set_downloading(False)
        self.app.notify(message, severity="information" if ok else "error", timeout=8)
        if self.current_note_id == note_id:
            self.load_note(note_id)

    def compose(self) -> ComposeResult:
        yield Label("Select a note to view", id="note-header")
        # Conflict warning (hidden initially)
        yield Label("", id="note-conflict-warning", classes="conflict-warning")
        # View mode: Static with RTL support (CONTENT FIRST)
        yield Static("", id="note-view")
        # Edit mode: TextArea (hidden initially)
        yield TextArea(id="note-edit", language=None)
        # Transcriptions container (above waveform, hidden initially)
        self._transcriptions_container = TUITranscriptionsContainer(self.db)
        yield self._transcriptions_container
        # Audio player (hidden initially, shown when audio files present)
        self._audio_player = TUIAudioPlayer(audiofile_directory=self.audiofile_directory)
        yield self._audio_player
        # Attachments text (for non-audio or when player not available)
        yield Label("", id="note-attachments")
        yield Horizontal(
            Button("Edit", id="edit-btn", variant="primary"),
            Button("Tags", id="tags-btn"),
            Button("Save", id="save-btn", variant="success"),
            Button("Cancel", id="cancel-btn"),
            Button("Accept merge", id="accept-conflict-btn", variant="warning"),
            Button("Resolve…", id="resolve-conflict-btn", variant="error"),
            Button("History", id="history-btn"),
            id="note-buttons"
        )

    def on_mount(self) -> None:
        """Hide edit mode, transcriptions, audio player, and conflict warning initially."""
        self.query_one("#note-edit", TextArea).display = False
        self.query_one("#save-btn", Button).display = False
        self.query_one("#cancel-btn", Button).display = False
        self.query_one("#tui-transcriptions").display = False
        self.query_one("#tui-audio-player").display = False
        self.query_one("#note-conflict-warning").display = False
        self.query_one("#accept-conflict-btn", Button).display = False
        self.query_one("#resolve-conflict-btn", Button).display = False

    def load_note(self, note_id: str) -> None:
        """Load and display note details.

        Args:
            note_id: ID of the note to display (hex string)
        """
        note = self.db.get_note(note_id)
        if note:
            tags = note.get("tag_names") or ""
            self.is_rtl = detect_rtl(tags) or detect_rtl(note["content"])

            # Update header
            header = self.query_one("#note-header", Label)
            header_text = f"Note #{note['id']} | {format_timestamp(note['created_at'], note.get('created_at_offset'))} | Tags: {tags or 'None'}"
            if self.is_rtl:
                header.update(make_rtl_text(header_text))
                header.add_class("rtl")
            else:
                header.update(header_text)
                header.remove_class("rtl")

            # Check for conflicts
            conflict_warning = self.query_one("#note-conflict-warning", Label)
            accept_btn = self.query_one("#accept-conflict-btn", Button)
            try:
                conflict_mgr = ConflictManager(self.db)
                description = conflict_mgr.describe_note_conflicts(note_id)
                resolve_btn = self.query_one("#resolve-conflict-btn", Button)
                if description:
                    conflict_warning.update(description)
                    conflict_warning.display = True
                    accept_btn.display = True
                    resolve_btn.display = any(c.kind == "text" for c in conflict_mgr.get_note_conflicts(note_id))
                else:
                    conflict_warning.display = False
                    accept_btn.display = False
                    resolve_btn.display = False
            except Exception as e:
                logger.warning(f"Error checking conflicts for note {note_id}: {e}")
                conflict_warning.display = False
                accept_btn.display = False
                self.query_one("#resolve-conflict-btn", Button).display = False

            # Update attachments - displayed BELOW content per requirements
            attachments_label = self.query_one("#note-attachments", Label)
            audio_player = self.query_one("#tui-audio-player")
            transcriptions_container = self.query_one("#tui-transcriptions")
            try:
                audio_files = self.db.get_audio_files_for_note(note_id)
                if audio_files:
                    # Get transcription counts and transcriptions for each audio file
                    transcription_counts = {}
                    all_transcriptions: List[Dict[str, Any]] = []
                    for af in audio_files:
                        audio_id = af.get("id", "")
                        transcriptions = self.db.get_transcriptions_for_audio_file(audio_id)
                        transcription_counts[audio_id] = len(transcriptions)
                        all_transcriptions.extend(transcriptions)

                    # Show transcriptions if any exist
                    if all_transcriptions:
                        first_audio_id = audio_files[0].get("id", "")
                        first_transcriptions = self.db.get_transcriptions_for_audio_file(first_audio_id)
                        self._transcriptions_container.set_audio_file(first_audio_id, first_transcriptions)
                        transcriptions_container.display = True
                    else:
                        transcriptions_container.display = False

                    # Use audio player if audiofile directory is configured and MPV available
                    if self.audiofile_directory and is_mpv_available():
                        self._audio_player.set_audio_files(
                            audio_files, self.db, transcription_counts
                        )
                        audio_player.display = True
                        attachments_label.update("")
                    else:
                        # Fallback to text display
                        audio_player.display = False
                        attachment_lines = []
                        for af in audio_files:
                            id_short = af.get("id", "")[:UUID_SHORT_LEN]
                            filename = af.get("filename", "unknown")
                            t_count = transcription_counts.get(af.get("id", ""), 0)
                            imported_at = format_timestamp(af.get("imported_at"), af.get("imported_at_offset")) or "unknown"
                            file_created_at = format_timestamp(af.get("file_created_at"), af.get("file_created_at_offset")) or "unknown"
                            media = ""
                            if self.audiofile_directory:
                                status = audio_file_status(af, self.audiofile_directory)
                                if status == STATUS_IN_CLOUD:
                                    media = " | media missing (press 'd' to download)"
                                elif status == STATUS_PENDING:
                                    media = " | media missing (not uploaded yet)"
                            attachment_lines.append(
                                f"  {id_short}... | {filename} | T:{t_count} | {imported_at} | {file_created_at}{media}"
                            )
                        attachments_text = f"Attachments ({len(audio_files)}):\n" + "\n".join(attachment_lines)
                        attachments_label.update(attachments_text)
                else:
                    audio_player.display = False
                    transcriptions_container.display = False
                    attachments_label.update("Attachments: None")
            except Exception as e:
                logger.warning(f"Error loading attachments for note {note_id}: {e}")
                audio_player.display = False
                transcriptions_container.display = False
                attachments_label.update("Attachments: None")

            # Use mixin to handle content and state
            self.load_note_content(note_id, note["content"])

    # ===== NoteEditorMixin abstract method implementations =====

    def _ui_set_content_editable(self, editable: bool) -> None:
        """Toggle between view (Static) and edit (TextArea) widgets."""
        self.query_one("#note-view", Static).display = not editable
        self.query_one("#note-edit", TextArea).display = editable

    def _ui_set_content_text(self, text: str) -> None:
        """Set content in both view and edit widgets."""
        # Update view widget with per-line RTL formatting
        view = self.query_one("#note-view", Static)
        lines = text.split('\n')
        formatted_lines = []
        for line in lines:
            if detect_rtl(line):
                formatted_lines.append(RLI + line + PDI)
            else:
                formatted_lines.append(line)
        view.update('\n'.join(formatted_lines))
        view.remove_class("rtl")  # Don't force right-align on mixed content

        # Also update edit widget for when editing starts
        self.query_one("#note-edit", TextArea).load_text(text)

    def _ui_get_content_text(self) -> str:
        """Get the current content from the edit widget."""
        return self.query_one("#note-edit", TextArea).text

    def _ui_focus_content(self) -> None:
        """Set focus to the edit widget."""
        self.query_one("#note-edit", TextArea).focus()

    def _ui_show_edit_buttons(self) -> None:
        """Show Save/Cancel buttons, hide Edit button."""
        self.query_one("#edit-btn", Button).display = False
        self.query_one("#save-btn", Button).display = True
        self.query_one("#cancel-btn", Button).display = True

    def _ui_show_view_buttons(self) -> None:
        """Show Edit button, hide Save/Cancel buttons."""
        self.query_one("#edit-btn", Button).display = True
        self.query_one("#save-btn", Button).display = False
        self.query_one("#cancel-btn", Button).display = False

    def _ui_on_note_saved(self) -> None:
        """Called after a note is saved. Show notification."""
        self.app.notify(f"Note saved!")
        # Refresh the view to show updated content
        self.load_note(self.current_note_id)

    def accept_conflicts(self) -> None:
        """Accept the merged values of every conflict on the current note."""
        if not self.current_note_id:
            return
        if self.editing:
            self.app.notify("Save or cancel your edit first", severity="warning")
            return
        try:
            n = ConflictManager(self.db).accept_note_conflicts(self.current_note_id)
        except Exception as e:
            logger.error(f"Failed to accept conflicts for note {self.current_note_id}: {e}")
            self.app.notify(f"Could not accept merge: {e}", severity="error")
            return
        self.app.notify(f"Accepted merged value for {n} conflict(s)")
        self.load_note(self.current_note_id)


class VoiceTUI(App):
    """Voice TUI Application."""

    # LLM NOTE: RTL display in Textual requires BOTH:
    # 1. Unicode RLI/PDI markers around RTL text
    # 2. CSS text-align: right on the widget
    # Do NOT use Rich's justify="right" as it causes overflow issues.
    #
    # Border colors are loaded from config in __init__ and applied via CSS variables.

    def __init__(self, db: Database, config: Config) -> None:
        super().__init__()
        self.db = db
        self.config = config
        # Load border colors from config
        tui_colors = config.get_tui_colors()
        self._border_focused = tui_colors["focused"]
        self._border_unfocused = tui_colors["unfocused"]

    @property
    def CSS(self) -> str:
        """Generate CSS with colors from config."""
        return f"""
    Screen {{
        layout: horizontal;
    }}

    #tags-tree {{
        width: 20%;
        height: 100%;
        border: solid {self._border_unfocused};
    }}

    #tags-tree:focus-within {{
        border: solid {self._border_focused};
    }}

    #notes-list {{
        width: 30%;
        height: 100%;
        border: solid {self._border_unfocused};
        overflow: hidden;
    }}

    #notes-list:focus-within {{
        border: solid {self._border_focused};
    }}

    #search-input {{
        height: 3;
        margin: 0 0 1 0;
    }}

    #notes-listview {{
        height: 1fr;
        overflow: hidden;
    }}

    #notes-listview ListItem {{
        overflow: hidden;
    }}

    #notes-listview Static {{
        width: 100%;
        overflow: hidden;
    }}

    #note-detail {{
        width: 50%;
        height: 100%;
        border: solid {self._border_unfocused};
        padding: 1;
    }}

    #note-detail:focus-within {{
        border: solid {self._border_focused};
    }}

    #note-header {{
        height: 3;
        background: $surface;
        padding: 1;
    }}

    #note-conflict-warning {{
        height: auto;
        min-height: 2;
        color: red;
        text-style: bold;
        padding: 0 1;
        background: $error 20%;
    }}

    #note-attachments {{
        height: 2;
        color: $text-muted;
        padding: 0 1;
    }}

    #tui-audio-player {{
        height: auto;
        max-height: 10;
        padding: 1;
        background: $surface;
        border: solid $primary;
    }}

    #audio-waveform {{
        height: 1;
        padding: 0 1;
    }}

    #audio-time {{
        height: 1;
        text-align: center;
    }}

    #audio-controls {{
        height: 3;
        align: center middle;
    }}

    #audio-controls Button {{
        margin: 0 1;
    }}

    #audio-files-label {{
        height: 1;
        color: $text-muted;
    }}

    #tui-transcriptions {{
        height: auto;
        max-height: 15;
        padding: 0 1;
        margin: 1 0;
        overflow-y: auto;
    }}

    #transcriptions-header {{
        height: 1;
        color: $text;
        text-style: bold;
        margin-bottom: 1;
    }}

    #transcriptions-content {{
        height: auto;
    }}

    .transcription-content {{
        height: auto;
        max-height: 8;
        margin: 0 1;
        overflow-y: auto;
    }}

    .transcription-state {{
        height: 1;
        color: $text-muted;
        margin: 0 1;
    }}

    .rtl {{
        text-align: right;
        width: 100%;
        overflow: hidden;
    }}

    #note-view {{
        height: 1fr;
        margin: 1 0;
        overflow-y: auto;
    }}

    #note-edit {{
        height: 1fr;
        margin: 1 0;
    }}

    #note-buttons {{
        height: 3;
        align: center middle;
    }}

    .media-missing {{
        color: $warning;
        text-style: bold;
        margin: 0 0 1 0;
    }}

    Button {{
        margin: 0 1;
    }}

    """

    TITLE = "Voice"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("n", "new_note", "New Note"),
        Binding("r", "refresh", "Refresh"),
        Binding("s", "save", "Save Note"),
        Binding("a", "show_all", "All Notes"),
        Binding("t", "manage_tags", "Tags"),
        Binding("m", "toggle_star", "Star"),
        Binding("d", "download_media", "Download media"),
        Binding("ctrl+t", "show_trash", "Trash"),
        Binding("ctrl+f", "calculate_missing_data", "Calculate missing data"),
        Binding("ctrl+k", "show_transcription_queue", "Transcription queue"),
    ]

    def compose(self) -> ComposeResult:
        yield TagsTree(self.db)
        yield NotesList(self.db)
        audiofile_directory = self.config.get("audiofile_directory")
        yield NoteDetail(
            self.db,
            audiofile_directory=Path(audiofile_directory) if audiofile_directory else None,
            config_dir=self.config.get_config_dir(),
        )
        footer = Footer()
        footer.command_palette_key_display = "● ^p"
        yield footer

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle note selection from the notes listview."""
        notes_list = self.query_one("#notes-list", NotesList)
        listview = self.query_one("#notes-listview", NotesListView)
        if event.list_view == listview:
            idx = event.list_view.index or 0
            if idx < len(notes_list.notes):
                note = notes_list.notes[idx]
                detail = self.query_one("#note-detail", NoteDetail)
                detail.load_note(note["id"])

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle tag selection - build search term and run search."""
        if event.node.data:  # Has tag data (not root node)
            tag = event.node.data
            notes_list = self.query_one("#notes-list", NotesList)

            # Build search term (uses full path for ambiguous tags)
            tag_search = build_tag_search_term(self.db, tag["id"])

            # Append to search field if not already there
            notes_list.append_search_term(tag_search)

            # Execute the search
            search_text = notes_list.get_search_text()
            notes_list.perform_search(search_text)
            self.notify(f"Search: {search_text}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter pressed in search input."""
        if event.input.id == "search-input":
            notes_list = self.query_one("#notes-list", NotesList)
            notes_list.perform_search(event.value)
            if event.value:
                self.notify(f"Search: {event.value}")
            else:
                self.notify("Showing all notes")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        detail = self.query_one("#note-detail", NoteDetail)
        if event.button.id == "edit-btn":
            detail.start_editing()
        elif event.button.id == "tags-btn":
            self._open_tag_management()
        elif event.button.id == "save-btn":
            detail.save_note()
            # Refresh notes list (preserve search)
            notes_list = self.query_one("#notes-list", NotesList)
            search_text = notes_list.get_search_text()
            if search_text:
                notes_list.perform_search(search_text)
            else:
                notes_list.refresh_notes()
        elif event.button.id == "cancel-btn":
            detail.cancel_editing()
        elif event.button.id == "accept-conflict-btn":
            detail.accept_conflicts()
        elif event.button.id == "resolve-conflict-btn":
            self._open_resolve_conflict()
        elif event.button.id == "history-btn":
            self._open_history()
        elif event.button.id == "download-btn":
            detail.action_download_media()

    def action_download_media(self) -> None:
        """Download missing media for the selected note from cloud storage."""
        detail = self.query_one("#note-detail", NoteDetail)
        detail.action_download_media()

    def action_calculate_missing_data(self) -> None:
        """Calculate what was never calculated: lengths, dates, display caches.

        Reads the audio files, so it runs in a worker thread and reports what it
        found when it is done. See `core.missing_data`.
        """
        from src.core import missing_data

        survey = missing_data.survey(self.db, self.config)
        if not survey.anything_missing:
            self.notify("Nothing is missing.")
            return
        if not survey.total_calculable:
            self.notify(
                f"{survey.gaps[0].count} gap(s) cannot be calculated; see the manual.",
                severity="warning",
            )
            return

        self.notify(f"Calculating {survey.total_calculable} item(s)…")

        def work() -> None:
            report = missing_data.calculate_missing_data(self.db, self.config)
            self.call_from_thread(self._missing_data_calculated, report)

        self.run_worker(work, thread=True, exclusive=False)

    def _missing_data_calculated(self, report) -> None:
        """Say what was calculated, and show it."""
        if report.total_calculated:
            self.notify(f"Calculated {report.total_calculated} item(s)")
            self.action_refresh()
        else:
            self.notify("Nothing could be calculated", severity="warning")

    def action_show_transcription_queue(self) -> None:
        """Open the transcription queue: what is waiting here and what it cost."""
        self.push_screen(TranscriptionQueueScreen(self.db, self.config))

    def action_show_trash(self) -> None:
        """Open the trash bin: recover a deleted note, or remove it for good."""
        audiofile_directory = self.config.get("audiofile_directory")

        def finished(changed: Optional[bool]) -> None:
            if changed:
                self.action_refresh()

        self.push_screen(
            TrashScreen(
                self.db,
                Path(audiofile_directory) if audiofile_directory else None,
            ),
            finished,
        )

    def action_refresh(self) -> None:
        """Refresh the notes list with current search."""
        notes_list = self.query_one("#notes-list", NotesList)
        search_text = notes_list.get_search_text()
        if search_text:
            notes_list.perform_search(search_text)
        else:
            notes_list.refresh_notes()
        self.notify("Refreshed!")

    def action_save(self) -> None:
        """Save the current note."""
        detail = self.query_one("#note-detail", NoteDetail)
        detail.save_note()

    def action_show_all(self) -> None:
        """Show all notes (clear search)."""
        notes_list = self.query_one("#notes-list", NotesList)
        notes_list.clear_search()
        self.notify("Search cleared - showing all notes")

    def action_new_note(self) -> None:
        """Create a new note and open it for editing."""
        # Create the note
        note_id = self.db.create_note()

        # Clear search and refresh notes list
        notes_list = self.query_one("#notes-list", NotesList)
        notes_list.clear_search()

        # Show the new note in detail pane and start editing
        detail = self.query_one("#note-detail", NoteDetail)
        detail.load_note(note_id)
        detail.start_editing()

        self.notify(f"Created note #{note_id}")

    def _open_tag_management(self) -> None:
        """Open tag management modal for the current note."""
        detail = self.query_one("#note-detail", NoteDetail)
        if detail.current_note_id:
            self.push_screen(
                TagManagementScreen(self.db, detail.current_note_id),
                self._on_tag_management_closed
            )
        else:
            self.notify("Select a note first", severity="warning")

    def _open_history(self) -> None:
        """Open the version history of the current note."""
        detail = self.query_one("#note-detail", NoteDetail)
        if not detail.current_note_id:
            self.notify("Select a note first", severity="warning")
            return
        if detail.editing:
            self.notify("Save or cancel your edit first", severity="warning")
            return
        self.push_screen(HistoryScreen(self.db, detail.current_note_id), self._on_note_changed_in_screen)

    def _open_resolve_conflict(self) -> None:
        """Resolve the current note's text conflict side by side."""
        detail = self.query_one("#note-detail", NoteDetail)
        if not detail.current_note_id:
            self.notify("Select a note first", severity="warning")
            return
        if detail.editing:
            self.notify("Save or cancel your edit first", severity="warning")
            return
        conflicts = [c for c in ConflictManager(self.db).get_note_conflicts(detail.current_note_id) if c.kind == "text"]
        if not conflicts:
            self.notify("No text conflict on this note; use Accept merge or edit the note", severity="warning")
            return
        self.push_screen(ResolveConflictScreen(self.db, conflicts[0]), self._on_note_changed_in_screen)

    def _on_note_changed_in_screen(self, changed: Optional[bool]) -> None:
        """After a modal that may have written the note: reload it and the list."""
        detail = self.query_one("#note-detail", NoteDetail)
        if detail.current_note_id:
            detail.load_note(detail.current_note_id)
        if changed:
            notes_list = self.query_one("#notes-list", NotesList)
            search_text = notes_list.get_search_text()
            if search_text:
                notes_list.perform_search(search_text)
            else:
                notes_list.refresh_notes()

    def _on_tag_management_closed(self, result: None) -> None:
        """Called when tag management modal is closed."""
        # Refresh the note detail to show updated tags
        detail = self.query_one("#note-detail", NoteDetail)
        if detail.current_note_id:
            detail.load_note(detail.current_note_id)
        # Refresh notes list to update tag display
        notes_list = self.query_one("#notes-list", NotesList)
        search_text = notes_list.get_search_text()
        if search_text:
            notes_list.perform_search(search_text)
        else:
            notes_list.refresh_notes()

    def action_manage_tags(self) -> None:
        """Open tag management for current note (keyboard shortcut)."""
        self._open_tag_management()

    def action_toggle_star(self) -> None:
        """Toggle star (marked) state of current note."""
        detail = self.query_one("#note-detail", NoteDetail)
        if not detail.current_note_id:
            self.notify("Select a note first", severity="warning")
            return

        # Toggle the marked state
        new_state = self.db.toggle_note_marked(detail.current_note_id)
        star = "★" if new_state else "☆"
        self.notify(f"Note {star} {'starred' if new_state else 'unstarred'}")

        # Refresh notes list to update star display
        notes_list = self.query_one("#notes-list", NotesList)
        search_text = notes_list.get_search_text()
        if search_text:
            notes_list.perform_search(search_text)
        else:
            notes_list.refresh_notes()


def add_tui_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add TUI subparser and its arguments.

    Args:
        subparsers: Parent subparsers object to add TUI parser to
    """
    tui_parser = subparsers.add_parser(
        "tui",
        help="Launch terminal user interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""
Terminal User Interface for Voice.

Built with Textual, provides a full-featured notes interface in the terminal.
Supports Hebrew/Arabic display (editing is LTR-only due to Textual limitations).

Controls:
  Up/Down      Navigate lists
  Left/Right   Collapse/Expand tags
  Enter        Select item
  e            Edit selected note
  s            Save changes
  a            Show all notes
  q            Quit
""",
    )

    # TUI currently has no additional arguments
    # Future: could add --theme for color schemes


def run(config_dir: Optional[Path], args: argparse.Namespace) -> int:
    """Run TUI with given arguments.

    Args:
        config_dir: Custom configuration directory or None for default
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success)
    """
    # Suppress console logging during TUI - it interferes with Textual's display
    # Remove all StreamHandlers temporarily
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    for handler in original_handlers:
        if isinstance(handler, logging.StreamHandler):
            root_logger.removeHandler(handler)

    # Initialize config and database
    config = Config(config_dir=config_dir, root=getattr(args, "config_root", None))
    db_path_str = config.get("database_file")
    db_path = Path(db_path_str)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = Database(db_path)
    reconcile_transcription_settings(config, db)

    # Create and run TUI app
    app = VoiceTUI(db, config)

    try:
        app.run()
    finally:
        db.close()
        # Restore original handlers
        for handler in original_handlers:
            if handler not in root_logger.handlers:
                root_logger.addHandler(handler)

    return 0

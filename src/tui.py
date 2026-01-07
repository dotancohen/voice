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

# Default transcription state
DEFAULT_TRANSCRIPTION_STATE = "original !verified !verbatim !cleaned !polished"

from src.core.audio_player import AudioPlayer, PlaybackState, format_time, is_mpv_available
from src.core.config import Config
from src.core.conflicts import ConflictManager
from src.core.database import Database
from src.core.models import UUID_SHORT_LEN
from src.core.note_editor import NoteEditorMixin
from src.core.search import build_tag_search_term, execute_search
from src.core.waveform import extract_waveform, waveform_with_progress, WAVEFORM_BAR_COUNT

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


def format_rtl_block(text: str) -> str:
    """Format a multi-line text block with proper RTL handling per line."""
    lines = text.split('\n')
    formatted_lines = [format_rtl(line) for line in lines]
    return '\n'.join(formatted_lines)


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

    def compose(self) -> ComposeResult:
        yield Static("No audio files", id="audio-waveform")
        yield Static("00:00 / 00:00", id="audio-time")
        yield Horizontal(
            Button("⏪10", id="skip-10-btn"),
            Button("⏪3", id="skip-3-btn"),
            Button("▶", id="play-btn"),
            Button("1x", id="speed-btn", disabled=True),
            id="audio-controls"
        )
        yield Static("", id="audio-files-label")

    def on_mount(self) -> None:
        """Start update timer when mounted."""
        self.set_interval(self._update_interval, self._update_display)

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
            return

        # Build file paths and file display strings
        file_display = []
        for af in audio_files:
            audio_id = af.get("id", "")
            filename = af.get("filename", "")
            t_count = self._transcription_counts.get(audio_id, 0)
            file_display.append(f"{filename} | T:{t_count}")

            if "." in filename:
                ext = filename.rsplit(".", 1)[-1].lower()
                path = self.audiofile_directory / f"{audio_id}.{ext}"
                self._file_paths.append(path)
            else:
                self._file_paths.append(Path())

        # Set files in player
        self._player.set_audio_files(self._file_paths)

        # Extract waveforms (synchronous for simplicity)
        for i, path in enumerate(self._file_paths):
            if path.exists():
                waveform = extract_waveform(path, WAVEFORM_BAR_COUNT)
                self._waveforms[i] = waveform

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
        state = self._transcription.get("state", DEFAULT_TRANSCRIPTION_STATE)
        created_at = self._transcription.get("created_at", "")

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
        state = self._transcription.get("state", DEFAULT_TRANSCRIPTION_STATE)

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

        for note in notes:
            note_dict = {
                "id": note["id"],
                "content": note["content"],
                "created_at": note["created_at"],
                "tag_names": note.get("tag_names", "")
            }
            self.notes.append(note_dict)

            content_preview = note["content"][:50].replace("\n", " ")
            if len(note["content"]) > 50:
                content_preview += "..."
            tags = note_dict["tag_names"] or "No tags"
            header_line = f"#{note['id']} | {tags}"
            is_rtl = detect_rtl(content_preview) or detect_rtl(tags)

            # LLM NOTE: For list items, we only use CSS text-align:right for RTL.
            # Do NOT use RLI/PDI markers here - they cause rendering artifacts
            # where text bleeds into adjacent panes. The markers work fine for
            # single-widget display but cause issues in ListView context.
            rich_text = RichText()
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

    def show_all_notes(self) -> None:
        """Show all notes (clear filter and search)."""
        self.clear_search()


class NoteDetail(Container, NoteEditorMixin):
    """Note detail view with editing.

    LLM NOTE: TextArea doesn't support RTL CSS. We use dual-mode display:
    - View mode: Static widget with RLI/PDI markers + CSS text-align:right
    - Edit mode: TextArea (LTR only - Textual limitation)
    Press Edit button to edit, Save to save, Cancel to discard.

    Inherits from NoteEditorMixin to share editing state logic with GUI.
    """

    def __init__(self, db: Database, audiofile_directory: Optional[Path] = None) -> None:
        super().__init__(id="note-detail")
        self.db = db
        self.audiofile_directory = audiofile_directory
        self.init_editor_state()  # Initialize mixin state
        self.is_rtl: bool = False
        self._audio_player: Optional[TUIAudioPlayer] = None
        self._transcriptions_container: Optional[TUITranscriptionsContainer] = None

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
            header_text = f"Note #{note['id']} | {note['created_at']} | Tags: {tags or 'None'}"
            if self.is_rtl:
                header.update(make_rtl_text(header_text))
                header.add_class("rtl")
            else:
                header.update(header_text)
                header.remove_class("rtl")

            # Check for conflicts
            conflict_warning = self.query_one("#note-conflict-warning", Label)
            try:
                conflict_mgr = ConflictManager(self.db)
                conflict_types = conflict_mgr.get_note_conflict_types(note_id)
                if conflict_types:
                    types_str = ", ".join(conflict_types)
                    conflict_warning.update(f"WARNING: This note has unresolved {types_str} conflict(s)")
                    conflict_warning.display = True
                else:
                    conflict_warning.display = False
            except Exception as e:
                logger.warning(f"Error checking conflicts for note {note_id}: {e}")
                conflict_warning.display = False

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
                            imported_at = af.get("imported_at", "unknown")
                            file_created_at = af.get("file_created_at", "unknown")
                            attachment_lines.append(
                                f"  {id_short}... | {filename} | T:{t_count} | {imported_at} | {file_created_at}"
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
        height: 2;
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
    ]

    def compose(self) -> ComposeResult:
        yield TagsTree(self.db)
        yield NotesList(self.db)
        audiofile_directory = self.config.get("audiofile_directory")
        yield NoteDetail(self.db, audiofile_directory=Path(audiofile_directory) if audiofile_directory else None)
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
    config = Config(config_dir=config_dir)
    db_path_str = config.get("database_file")
    db_path = Path(db_path_str)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = Database(db_path)

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

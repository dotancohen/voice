#!/usr/bin/env python3
"""TUI (Text User Interface) for Voice Rewrite using Textual.

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
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.widgets import (
    Button,
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

from src.core.config import Config
from src.core.database import Database
from src.core.note_editor import NoteEditorMixin
from src.core.search import build_tag_search_term, execute_search

# Re-export for tests
__all__ = ["VoiceRewriteTUI", "run", "add_tui_subparser", "TagsTree", "NotesList", "NotesListView", "NoteDetail", "SearchInput"]

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

    def __init__(self, db: Database) -> None:
        super().__init__(id="note-detail")
        self.db = db
        self.init_editor_state()  # Initialize mixin state
        self.is_rtl: bool = False

    def compose(self) -> ComposeResult:
        yield Label("Select a note to view", id="note-header")
        # View mode: Static with RTL support
        yield Static("", id="note-view")
        # Edit mode: TextArea (hidden initially)
        yield TextArea(id="note-edit", language=None)
        yield Horizontal(
            Button("Edit", id="edit-btn", variant="primary"),
            Button("Save", id="save-btn", variant="success"),
            Button("Cancel", id="cancel-btn"),
            id="note-buttons"
        )

    def on_mount(self) -> None:
        """Hide edit mode initially."""
        self.query_one("#note-edit", TextArea).display = False
        self.query_one("#save-btn", Button).display = False
        self.query_one("#cancel-btn", Button).display = False

    def show_note(self, note_id: str) -> None:
        """Display a note in view mode.

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
        self.show_note(self.current_note_id)


class VoiceRewriteTUI(App):
    """Voice Rewrite TUI Application."""

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

    TITLE = "Voice Rewrite"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("n", "new_note", "New Note"),
        Binding("r", "refresh", "Refresh"),
        Binding("s", "save", "Save Note"),
        Binding("a", "show_all", "All Notes"),
    ]

    def compose(self) -> ComposeResult:
        yield TagsTree(self.db)
        yield NotesList(self.db)
        yield NoteDetail(self.db)
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
                detail.show_note(note["id"])

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle tag selection - build search term and run search."""
        if event.node.data:  # Has tag data (not root node)
            tag = event.node.data
            notes_list = self.query_one("#notes-list", NotesList)

            # Build search term (uses full path for ambiguous tags)
            tag_search = build_tag_search_term(self.db, tag["id"])

            # Append to search field if not already there
            notes_list.append_search_term(tag_search)

            # Run the search
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
        detail.show_note(note_id)
        detail.start_editing()

        self.notify(f"Created note #{note_id}")


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
Terminal User Interface for Voice Rewrite.

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
    app = VoiceRewriteTUI(db, config)

    try:
        app.run()
    finally:
        db.close()
        # Restore original handlers
        for handler in original_handlers:
            if handler not in root_logger.handlers:
                root_logger.addHandler(handler)

    return 0

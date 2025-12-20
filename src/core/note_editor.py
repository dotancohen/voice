"""Note editor state management.

This module provides a mixin class for managing note editing state
that can be used by different UI frameworks (Qt, Textual, etc.).

The class handles:
- Tracking current note and editing state
- Mode transitions (view <-> edit)
- Save/cancel operations

UI implementations should subclass NoteEditorMixin and implement
the _ui_* methods for framework-specific widget updates.

Note: This uses a simple mixin pattern (not ABC) to avoid metaclass
conflicts with Qt and other frameworks that have their own metaclasses.
"""

from __future__ import annotations

import logging
from typing import Optional

from .database import Database

logger = logging.getLogger(__name__)


class NoteEditorMixin:
    """Mixin providing note editing state management.

    This class manages the state machine for note editing:
    - View mode: content is read-only, Edit button visible
    - Edit mode: content is editable, Save/Cancel buttons visible

    Subclasses must implement the _ui_* methods to handle
    framework-specific UI updates.

    Attributes:
        db: Database connection
        current_note_id: ID of currently displayed note (hex string)
        current_note_content: Content of current note (for cancel restoration)
        editing: Whether currently in edit mode
    """

    # These should be set by the implementing class
    db: Database
    current_note_id: Optional[str]
    current_note_content: str
    editing: bool

    def init_editor_state(self) -> None:
        """Initialize editor state. Call this in subclass __init__."""
        self.current_note_id = None
        self.current_note_content = ""
        self.editing = False

    # ===== UI hook methods - override in subclass =====

    def _ui_set_content_editable(self, editable: bool) -> None:
        """Set whether the content area is editable.

        Args:
            editable: True to allow editing, False for read-only
        """
        raise NotImplementedError("Subclass must implement _ui_set_content_editable")

    def _ui_set_content_text(self, text: str) -> None:
        """Set the content area text.

        Args:
            text: Text to display
        """
        raise NotImplementedError("Subclass must implement _ui_set_content_text")

    def _ui_get_content_text(self) -> str:
        """Get the current content area text.

        Returns:
            Current text in the content area
        """
        raise NotImplementedError("Subclass must implement _ui_get_content_text")

    def _ui_focus_content(self) -> None:
        """Set focus to the content area."""
        raise NotImplementedError("Subclass must implement _ui_focus_content")

    def _ui_show_edit_buttons(self) -> None:
        """Show Save/Cancel buttons, hide Edit button."""
        raise NotImplementedError("Subclass must implement _ui_show_edit_buttons")

    def _ui_show_view_buttons(self) -> None:
        """Show Edit button, hide Save/Cancel buttons."""
        raise NotImplementedError("Subclass must implement _ui_show_view_buttons")

    def _ui_on_note_saved(self) -> None:
        """Called after a note is saved. Refresh UI as needed."""
        raise NotImplementedError("Subclass must implement _ui_on_note_saved")

    # ===== State management methods =====

    def start_editing(self) -> None:
        """Switch to edit mode.

        Does nothing if no note is loaded.
        """
        if self.current_note_id is None:
            return

        self.editing = True
        self._ui_set_content_editable(True)
        self._ui_focus_content()
        self._ui_show_edit_buttons()

        logger.info(f"Started editing note {self.current_note_id}")

    def cancel_editing(self) -> None:
        """Cancel editing and restore original content."""
        if self.current_note_id is not None:
            # Restore original content
            self._ui_set_content_text(self.current_note_content)
        self._set_view_mode()

    def _set_view_mode(self) -> None:
        """Switch to view mode (read-only)."""
        self.editing = False
        self._ui_set_content_editable(False)
        self._ui_show_view_buttons()

    def save_note(self) -> None:
        """Save the current note and return to view mode.

        Does nothing if no note is loaded.
        """
        if self.current_note_id is None:
            return

        content = self._ui_get_content_text()
        self.db.update_note(self.current_note_id, content)
        self.current_note_content = content

        logger.info(f"Saved note {self.current_note_id}")

        self._set_view_mode()
        self._ui_on_note_saved()

    def load_note_content(self, note_id: str, content: str) -> None:
        """Load note content into the editor.

        Call this when switching to a new note. Exits edit mode
        if currently editing.

        Args:
            note_id: ID of the note (hex string)
            content: Note content to display
        """
        # Exit editing mode if switching notes
        if self.editing:
            self._set_view_mode()

        self.current_note_id = note_id
        self.current_note_content = content
        self._ui_set_content_text(content)

    def clear_editor(self) -> None:
        """Clear the editor and reset state."""
        self.current_note_id = None
        self.current_note_content = ""
        self._ui_set_content_text("")
        self._set_view_mode()

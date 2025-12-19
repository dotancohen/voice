"""Notes list pane displaying notes with two-line format.

This module provides the center pane showing a list of notes with search functionality.
Each note displays created_at on the first line and truncated content on the second line.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QPainter,
    QPalette,
    QTextCharFormat,
    QTextCursor,
    QFont,
    QTextDocument,
    QAbstractTextDocumentLayout,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QStyle,
)

from src.core.config import Config
from src.core.database import Database
from src.core.search import (
    parse_search_input,
    get_tag_full_path,
    find_ambiguous_tags,
    execute_search,
    build_tag_search_term,
)

logger = logging.getLogger(__name__)

# Button focus style - makes focused buttons visually distinct
BUTTON_STYLE = """
    QPushButton {
        padding: 5px 15px;
    }
    QPushButton:focus {
        border: 2px solid #3daee9;
        background-color: #3daee9;
        color: white;
    }
"""

# Constants
CONTENT_TRUNCATE_LENGTH = 100

# Custom item data roles (typed to satisfy mypy)
ROLE_NOTE_ID = Qt.ItemDataRole.UserRole
ROLE_HTML_TEXT = Qt.ItemDataRole(int(Qt.ItemDataRole.UserRole) + 1)


class SearchTextEdit(QTextEdit):
    """Custom QTextEdit that triggers search on Enter key."""

    returnPressed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the search text edit."""
        super().__init__(parent)
        self.setTabChangesFocus(True)  # Tab moves to next widget

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle key press events."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Trigger search on Enter, don't insert newline
            if event.modifiers() == Qt.KeyboardModifier.NoModifier:
                self.returnPressed.emit()
                event.accept()
                return
        super().keyPressEvent(event)


class NotesListWidget(QListWidget):
    """Custom list widget that emits itemActivated on Space key."""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle key press - emit itemActivated on Space."""
        if event.key() == Qt.Key.Key_Space:
            item = self.currentItem()
            if item:
                self.itemActivated.emit(item)
                event.accept()
                return
        super().keyPressEvent(event)


class HTMLDelegate(QStyledItemDelegate):
    """Custom delegate to render HTML in list widget items."""

    def __init__(self, parent: Optional[QWidget] = None, theme: str = "dark") -> None:
        """Initialize the delegate.

        Args:
            parent: Parent widget
            theme: UI theme ("dark" or "light")
        """
        super().__init__(parent)
        self.theme = theme

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: Union[QModelIndex, QPersistentModelIndex]) -> None:
        """Paint the item with HTML rendering."""
        # Get the HTML text from UserRole+1
        html_text = index.data(ROLE_HTML_TEXT)
        if not html_text:
            super().paint(painter, option, index)
            return

        # Create text document for rendering
        doc = QTextDocument()
        doc.setTextWidth(option.rect.width() - 2)  # Ultra-minimal margin
        doc.setDefaultFont(option.font)

        # Determine text color based on selection state
        if option.state & QStyle.StateFlag.State_Selected:
            text_color = option.palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText)
        else:
            text_color = option.palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Text)

        # Set HTML with proper text color and ultra-tight line height
        html_with_color = f'<div style="color: {text_color.name()}; line-height: 1.0;">{html_text}</div>'
        doc.setHtml(html_with_color)

        # Calculate actual content height
        content_height = int(doc.size().height())

        # Save painter state
        painter.save()

        # Draw selection background based on actual content height
        if option.state & QStyle.StateFlag.State_Selected:
            selection_rect = option.rect.adjusted(0, 0, 0, -(option.rect.height() - content_height - 1))
            painter.fillRect(selection_rect, option.palette.highlight())

        # Translate painter to item position with ultra-minimal padding
        painter.translate(option.rect.left() + 1, option.rect.top())

        # Draw the document
        context = QAbstractTextDocumentLayout.PaintContext()
        doc.documentLayout().draw(painter, context)

        # Restore painter state
        painter.restore()

        # Draw subtle dividing line based on actual content height
        painter.save()
        from PySide6.QtGui import QPen
        # Choose color based on theme
        if self.theme == "light":
            line_color = QColor("#cccccc")  # Medium gray for light theme
        else:
            line_color = QColor("#505050")  # Lighter gray for dark theme
        pen = QPen(line_color)
        pen.setWidth(1)
        painter.setPen(pen)
        # Draw 1px line at actual content bottom
        divider_y = option.rect.top() + content_height + 1
        painter.drawLine(
            option.rect.left(),
            divider_y,
            option.rect.right(),
            divider_y
        )
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: Union[QModelIndex, QPersistentModelIndex]) -> QSize:
        """Calculate size hint for item."""
        html_text = index.data(ROLE_HTML_TEXT)
        if not html_text:
            return super().sizeHint(option, index)

        # Create text document to calculate size
        doc = QTextDocument()
        # Apply same line height as in paint
        html_with_style = f'<div style="line-height: 1.0;">{html_text}</div>'
        doc.setHtml(html_with_style)
        doc.setTextWidth(option.rect.width() - 2 if option.rect.width() > 0 else 400)
        doc.setDefaultFont(option.font)

        # Return size with absolute minimal padding + space for 1px dividing line
        return QSize(int(doc.idealWidth()) + 2, int(doc.size().height()) + 1 + 2)


class NotesListPane(QWidget):
    """Pane displaying list of notes with two-line format and search.

    Each note shows:
    - Line 1: created_at timestamp (YYYY-MM-DD HH:MM:SS)
    - Line 2: content (truncated to 100 characters with "...")

    Search supports:
    - Free-text search in note content
    - tag:tagname syntax for tag filtering (case-insensitive)
    - Hierarchical paths like tag:Europe/France/Paris

    Signals:
        note_selected: Emitted when a note is clicked (note_id: int)

    Attributes:
        config: Configuration manager
        db: Database connection
        search_field: QLineEdit for search input
        search_button: QPushButton to trigger search
        list_widget: QListWidget for displaying notes
        warning_color: Hex color for highlighting ambiguous tags
    """

    note_selected = Signal(int)  # Emits note_id

    def __init__(
        self, config: Config, db: Database, theme: str = "dark", parent: Optional[QWidget] = None
    ) -> None:
        """Initialize the notes list pane.

        Args:
            config: Configuration manager
            db: Database connection
            theme: UI theme ("dark" or "light")
            parent: Parent widget (default None)
        """
        super().__init__(parent)
        self.config = config
        self.db = db
        self.theme = theme
        self.warning_color = self.config.get_warning_color(theme=theme)
        self._updating_search_field = False  # Flag to prevent recursive updates

        self.setup_ui()
        self.load_notes()

        logger.info("Notes list pane initialized")

    def setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create search toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)

        # Create search field container with embedded clear button
        search_container = QFrame()
        search_container.setFrameShape(QFrame.Shape.StyledPanel)
        search_container.setMaximumHeight(35)
        container_layout = QHBoxLayout(search_container)
        container_layout.setContentsMargins(0, 0, 2, 0)
        container_layout.setSpacing(0)

        self.search_field = SearchTextEdit()
        self.search_field.setPlaceholderText("Search notes... (use tag:tagname for tags)")
        self.search_field.setAcceptRichText(False)  # Use plain text to prevent formatting inheritance
        # Configure as single-line input with no frame (container provides the frame)
        self.search_field.setFrameShape(QFrame.Shape.NoFrame)
        self.search_field.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.search_field.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.search_field.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        # Enable undo/redo functionality
        self.search_field.setUndoRedoEnabled(True)
        self.search_field.textChanged.connect(self.on_search_field_edited)
        self.search_field.returnPressed.connect(self.perform_search)

        # Clear button embedded inside search field
        self.clear_button = QToolButton()
        self.clear_button.setText("\u00d7")  # × symbol
        self.clear_button.setToolTip("Clear search")
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.setFixedSize(24, 24)
        self.clear_button.setStyleSheet("""
            QToolButton {
                border: none;
                background: transparent;
                font-size: 16px;
                font-weight: bold;
                color: #888;
            }
            QToolButton:hover {
                color: #fff;
                background: #555;
                border-radius: 12px;
            }
        """)
        self.clear_button.clicked.connect(self.clear_search)

        container_layout.addWidget(self.search_field)
        container_layout.addWidget(self.clear_button)

        self.search_button = QPushButton("Search")
        self.search_button.setStyleSheet(BUTTON_STYLE)
        self.search_button.clicked.connect(self.perform_search)

        toolbar.addWidget(search_container, 1)  # stretch factor 1
        toolbar.addWidget(self.search_button)

        layout.addLayout(toolbar)

        # Create list widget
        self.list_widget = NotesListWidget()
        self.list_widget.itemClicked.connect(self.on_note_clicked)
        self.list_widget.itemActivated.connect(self.on_note_clicked)  # Enter/Space keys

        # Set custom delegate for HTML rendering (with theme-aware dividing lines)
        self.list_widget.setItemDelegate(HTMLDelegate(self.list_widget, theme=self.theme))

        layout.addWidget(self.list_widget)

    def load_notes(self, notes: Optional[List[Dict[str, Any]]] = None) -> None:
        """Load notes into the list widget.

        Args:
            notes: List of note dictionaries. If None, loads all notes from database.
        """
        self.list_widget.clear()

        if notes is None:
            notes = self.db.get_all_notes()

        for note in notes:
            item = self.create_note_item(note)
            self.list_widget.addItem(item)

        logger.info(f"Loaded {len(notes)} notes into list")

    def create_note_item(self, note: Dict[str, Any]) -> QListWidgetItem:
        """Create a list item for a note with two-line format.

        Args:
            note: Note dictionary from database

        Returns:
            QListWidgetItem configured with note data.
        """
        # Format created_at timestamp
        created_at = note.get("created_at", "Unknown")

        # Truncate and clean content
        content = note.get("content", "")
        # Replace newlines and carriage returns with spaces
        content = content.replace("\n", " ").replace("\r", "")
        # Truncate if too long
        if len(content) > CONTENT_TRUNCATE_LENGTH:
            content = content[:CONTENT_TRUNCATE_LENGTH] + "..."

        # Create two-line text with bold date
        html_text = f"<b>{created_at}</b><br>{content}"

        # Create item
        item = QListWidgetItem()
        item.setData(ROLE_NOTE_ID, note["id"])  # Store note_id

        # Store the HTML for custom delegate rendering
        item.setData(ROLE_HTML_TEXT, html_text)

        # Set plain text for display role (used by default rendering/accessibility)
        plain_text = f"{created_at}\n{content}"
        item.setText(plain_text)

        return item

    def on_note_clicked(self, item: QListWidgetItem) -> None:
        """Handle note click event.

        Args:
            item: Clicked list widget item
        """
        note_id = item.data(ROLE_NOTE_ID)
        logger.info(f"Note selected: ID {note_id}")
        self.note_selected.emit(note_id)

    def select_note_by_id(self, note_id: int) -> bool:
        """Select a note in the list by its ID.

        Args:
            note_id: ID of the note to select

        Returns:
            True if the note was found and selected, False otherwise.
        """
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.data(ROLE_NOTE_ID) == note_id:
                self.list_widget.setCurrentItem(item)
                logger.info(f"Selected note {note_id} in list")
                return True
        logger.warning(f"Note {note_id} not found in list")
        return False

    def filter_by_tag(self, tag_id: int) -> None:
        """Handle tag selection from sidebar.

        Adds the clicked tag to search field.
        If ambiguous (multiple tags with same name): adds full path with yellow highlighting.
        If not ambiguous (single tag): uses just the tag name and runs search immediately.

        Args:
            tag_id: Tag ID from sidebar selection
        """
        # Get the clicked tag's information
        tag = self.db.get_tag(tag_id)
        if not tag:
            logger.warning(f"Tag ID {tag_id} not found")
            return

        tag_name = tag["name"]
        logger.info(f"Sidebar tag clicked: {tag_name} (ID: {tag_id})")

        # Build the appropriate search term (uses full path if ambiguous)
        tag_search = build_tag_search_term(self.db, tag_id)

        # Check if already in search field
        current_text = self.search_field.toPlainText()
        if tag_search.lower() not in current_text.lower():
            # Append to search field
            new_text = f"{current_text} {tag_search}".strip()
            self.search_field.setPlainText(new_text)

        # Run search immediately (highlighting will happen in on_search_field_edited)
        self.perform_search()

    def on_search_field_edited(self) -> None:
        """Handle search field text changes and highlight ambiguous tags."""
        # Prevent recursive updates
        if self._updating_search_field:
            return

        self._updating_search_field = True
        try:
            # Get plain text to avoid recursive updates
            text = self.search_field.toPlainText()

            # Parse to find tag terms and check which are ambiguous
            parsed = parse_search_input(text)
            ambiguous_tag_terms = find_ambiguous_tags(self.db, parsed.tag_terms)

            # Save cursor position before making changes
            cursor_position = self.search_field.textCursor().position()

            # Block signals to prevent recursive updates
            self.search_field.blockSignals(True)

            # Apply highlighting if there are ambiguous tags
            if ambiguous_tag_terms:
                self._apply_highlighting(text, ambiguous_tag_terms, cursor_position)
            else:
                # No ambiguous tags - ensure all text is default color
                self._clear_all_formatting(text, cursor_position)

            self.search_field.blockSignals(False)
        finally:
            self._updating_search_field = False

    def _clear_all_formatting(self, text: str, cursor_position: int) -> None:
        """Clear all formatting and set text to default color.

        Args:
            text: The text to set
            cursor_position: Position to restore cursor to
        """
        # Set the text
        self.search_field.setPlainText(text)

        # Create default color format for all text
        default_format = QTextCharFormat()
        default_format.setForeground(self.palette().color(QPalette.ColorRole.Text))

        # Apply default color to entire document
        cursor = self.search_field.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.setCharFormat(default_format)

        # Restore cursor position
        cursor.clearSelection()
        cursor.setPosition(min(cursor_position, len(text)))
        self.search_field.setTextCursor(cursor)

    def _apply_highlighting(self, text: str, ambiguous_terms: List[str], cursor_position: int) -> None:
        """Apply warning color highlighting to ambiguous tag terms in the search field.

        Args:
            text: The full search text
            ambiguous_terms: List of ambiguous tag terms (e.g., ["tag:bar"])
            cursor_position: Position to restore cursor to
        """
        # Set the plain text first
        self.search_field.setPlainText(text)

        # Create text formats
        default_format = QTextCharFormat()
        default_format.setForeground(self.palette().color(QPalette.ColorRole.Text))

        warning_format = QTextCharFormat()
        warning_format.setForeground(QColor(self.warning_color))

        # Get cursor for formatting
        cursor = self.search_field.textCursor()

        # First, set all text to default color
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.setCharFormat(default_format)

        # Find and highlight ambiguous terms
        text_lower = text.lower()
        for term in ambiguous_terms:
            term_lower = term.lower()
            pos = 0
            while True:
                # Find next occurrence of this term (case-insensitive)
                idx = text_lower.find(term_lower, pos)
                if idx == -1:
                    break

                # Select the match and apply warning format
                cursor.setPosition(idx)
                cursor.setPosition(idx + len(term), QTextCursor.MoveMode.KeepAnchor)
                cursor.setCharFormat(warning_format)

                pos = idx + len(term)

        # Restore cursor position
        cursor.clearSelection()
        cursor.setPosition(min(cursor_position, len(text)))
        self.search_field.setTextCursor(cursor)

    def clear_search(self) -> None:
        """Clear the search field and show all notes."""
        self.search_field.clear()
        self.load_notes()
        logger.info("Search cleared, showing all notes")

    def perform_search(self) -> None:
        """Perform search based on search field content.

        Parses tag: keywords and free text, then searches database.
        Ambiguous tags (matching multiple tags) use OR logic within the group.
        """
        search_text = self.search_field.toPlainText().strip()
        logger.info(f"Performing search: '{search_text}'")

        # Execute search using the search module
        result = execute_search(self.db, search_text)

        # Log any not-found tags
        for tag in result.not_found_tags:
            logger.warning(f"Tag path '{tag}' not found")

        # Update display
        self.load_notes(result.notes)

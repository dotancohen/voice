"""Notes list pane displaying notes with two-line format.

This module provides the center pane showing a list of notes with search functionality.
Each note displays created_at on the first line and truncated content on the second line.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QSize, Qt, Signal
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QColor,
    QKeyEvent,
    QPainter,
    QPalette,
    QPen,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
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
    build_tag_search_term,
    execute_search,
    find_ambiguous_tags,
    parse_search_input,
)
from src.core.timestamp_utils import format_timestamp
from src.ui.styles import BUTTON_STYLE

logger = logging.getLogger(__name__)

# Constants
CONTENT_TRUNCATE_LENGTH = 200

# Custom item data roles (typed to satisfy mypy)
ROLE_NOTE_ID = Qt.ItemDataRole.UserRole
ROLE_HTML_TEXT = Qt.ItemDataRole(int(Qt.ItemDataRole.UserRole) + 1)
ROLE_MARKED = Qt.ItemDataRole(int(Qt.ItemDataRole.UserRole) + 2)

# Star icons and colors
STAR_FILLED = "★"  # U+2605
STAR_EMPTY = "☆"   # U+2606
STAR_COLOR_GOLD = "#FFD700"
STAR_COLOR_GRAY = "#888888"
STAR_CLICK_REGION_WIDTH = 20  # pixels


def format_duration(seconds: int) -> str:
    """Format duration in seconds as [h:]mm:ss.

    Args:
        seconds: Duration in whole seconds

    Returns:
        Formatted string like "00:03", "01:30", or "1:07:00"
    """
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"


def detect_text_direction(text: str) -> str:
    """Detect text direction based on first strong directional character.

    Args:
        text: Text to analyze

    Returns:
        "rtl" if text starts with RTL characters (Hebrew, Arabic, etc.), "ltr" otherwise
    """
    import unicodedata
    for char in text:
        bidi_class = unicodedata.bidirectional(char)
        # R = Right-to-Left, AL = Arabic Letter, AN = Arabic Number
        if bidi_class in ('R', 'AL'):
            return "rtl"
        # L = Left-to-Right
        elif bidi_class == 'L':
            return "ltr"
        # Skip neutral/weak characters and continue looking
    return "ltr"  # Default to LTR if no strong characters found


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
    """Custom delegate to render HTML in list widget items.

    Signals:
        star_clicked: Emitted when the star icon is clicked (note_id: str)
    """

    star_clicked = Signal(str)  # Emits note_id when star is clicked

    def __init__(self, parent: Optional[QWidget] = None, theme: str = "dark") -> None:
        """Initialize the delegate.

        Args:
            parent: Parent widget
            theme: UI theme ("dark" or "light")
        """
        super().__init__(parent)
        self.theme = theme

    def editorEvent(
        self,
        event: QEvent,
        model: Any,
        option: QStyleOptionViewItem,
        index: Union[QModelIndex, QPersistentModelIndex]
    ) -> bool:
        """Handle mouse events on the item.

        Detects clicks in the star region and emits star_clicked signal.
        """
        if event.type() == QEvent.Type.MouseButtonRelease:
            # Check if click is in star region (first STAR_CLICK_REGION_WIDTH pixels)
            click_x = event.pos().x() - option.rect.x()
            if click_x < STAR_CLICK_REGION_WIDTH:
                note_id = index.data(ROLE_NOTE_ID)
                if note_id:
                    self.star_clicked.emit(note_id)
                    return True
        return super().editorEvent(event, model, option, index)

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

    note_selected = Signal(str)  # Emits note_id (UUID hex string)

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

        # Create search field container with star filter and clear buttons
        search_container = QFrame()
        search_container.setFrameShape(QFrame.Shape.StyledPanel)
        search_container.setMaximumHeight(35)
        container_layout = QHBoxLayout(search_container)
        container_layout.setContentsMargins(2, 0, 2, 0)
        container_layout.setSpacing(0)

        # Star filter button (leftmost) - toggles is:marked in search
        self.star_filter_button = QToolButton()
        self.star_filter_button.setText(STAR_EMPTY)
        self.star_filter_button.setToolTip("Toggle starred notes filter (is:marked)")
        self.star_filter_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.star_filter_button.setFixedSize(24, 24)
        self.star_filter_button.setStyleSheet(f"""
            QToolButton {{
                border: none;
                background: transparent;
                font-size: 16px;
                color: {STAR_COLOR_GRAY};
            }}
            QToolButton:hover {{
                background: #555;
                border-radius: 12px;
            }}
        """)
        self.star_filter_button.clicked.connect(self.toggle_marked_filter)

        # Clear button (to the left of search field)
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

        self.search_field = SearchTextEdit()
        self.search_field.setPlaceholderText("Search notes... (use tag:tagname or is:marked)")
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

        # Layout: [star] [clear] [search field]
        container_layout.addWidget(self.star_filter_button)
        container_layout.addWidget(self.clear_button)
        container_layout.addWidget(self.search_field)

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
        self.delegate = HTMLDelegate(self.list_widget, theme=self.theme)
        self.delegate.star_clicked.connect(self.on_star_clicked)
        self.list_widget.setItemDelegate(self.delegate)

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

    def _build_note_item_display(self, note: Dict[str, Any]) -> tuple:
        """Build HTML and plain text display for a note item.

        Args:
            note: Note dictionary from database

        Returns:
            Tuple of (html_text, plain_text, is_marked)
        """
        import json

        # Try to use cached data if available
        list_cache = note.get("list_display_cache")
        duration_seconds = None
        tags: List[str] = []
        if list_cache:
            try:
                cache_data = json.loads(list_cache)
                # "date" in cache is pre-formatted string; fallback formats the integer timestamp
                created_at = cache_data.get("date") or format_timestamp(note.get("created_at")) or "Unknown"
                is_marked = cache_data.get("marked", False)
                content = cache_data.get("content_preview", "")
                duration_seconds = cache_data.get("duration_seconds")
                tags = cache_data.get("tags", [])
                # Truncate cached preview if longer than display limit
                if len(content) > CONTENT_TRUNCATE_LENGTH:
                    content = content[:CONTENT_TRUNCATE_LENGTH] + "..."
                elif len(note.get("content", "")) > len(content):
                    # Original was truncated by cache, add ellipsis
                    content = content + "..."
            except (json.JSONDecodeError, TypeError):
                # Fall back to computing values
                list_cache = None

        if not list_cache:
            # No cache or cache parse failed - compute values
            # Format Unix timestamp for display
            created_at = format_timestamp(note.get("created_at")) or "Unknown"
            is_marked = self.db.is_note_marked(note["id"])
            content = note.get("content", "")
            # Replace newlines and carriage returns with spaces
            content = content.replace("\n", " ").replace("\r", "")
            # Truncate if too long
            if len(content) > CONTENT_TRUNCATE_LENGTH:
                content = content[:CONTENT_TRUNCATE_LENGTH] + "..."
            # Tags not available without cache
            tags = []

        # Build star HTML
        if is_marked:
            star_html = f'<span style="color: {STAR_COLOR_GOLD};">{STAR_FILLED}</span>'
        else:
            star_html = f'<span style="color: {STAR_COLOR_GRAY};">{STAR_EMPTY}</span>'

        # Format duration if available
        duration_str = ""
        if duration_seconds is not None and duration_seconds > 0:
            duration_str = f" | {format_duration(duration_seconds)}"

        # Format tags if available
        tags_str = ""
        if tags:
            tags_str = f" | {', '.join(tags)}"

        # Create two-line text with star, bold date/time, optional duration, optional tags
        # Top row is forced LTR so date/duration/tags display correctly even with RTL content
        # Bottom row: explicit direction, single line with overflow hidden
        content_dir = detect_text_direction(content)
        html_text = (
            f'<div dir="ltr">{star_html} <b>{created_at}</b>{duration_str}{tags_str}</div>'
            f'<div dir="{content_dir}" style="overflow: hidden;">{content}</div>'
        )

        # Plain text for accessibility
        star_plain = STAR_FILLED if is_marked else STAR_EMPTY
        plain_text = f"{star_plain} {created_at}\n{content}"

        return html_text, plain_text, is_marked

    def create_note_item(self, note: Dict[str, Any]) -> QListWidgetItem:
        """Create a list item for a note with two-line format.

        Args:
            note: Note dictionary from database

        Returns:
            QListWidgetItem configured with note data.
        """
        html_text, plain_text, is_marked = self._build_note_item_display(note)

        # Create item
        item = QListWidgetItem()
        item.setData(ROLE_NOTE_ID, note["id"])  # Store note_id
        item.setData(ROLE_MARKED, is_marked)  # Store marked state
        item.setData(ROLE_HTML_TEXT, html_text)
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

    def on_star_clicked(self, note_id: str) -> None:
        """Handle star icon click to toggle marked state.

        Args:
            note_id: ID of the note whose star was clicked
        """
        # Toggle the marked state in the database
        new_state = self.db.toggle_note_marked(note_id)
        logger.info(f"Toggled marked state for note {note_id[:8]}... to {new_state}")

        # Find and update the item in the list
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.data(ROLE_NOTE_ID) == note_id:
                # Rebuild the item display from fresh note data
                note = self.db.get_note(note_id)
                if note:
                    self._refresh_item_display(item, note)

                # Force repaint
                self.list_widget.update()
                break

    def _refresh_item_display(self, item: QListWidgetItem, note: Dict[str, Any]) -> None:
        """Refresh a list item's display from note data.

        Args:
            item: The list widget item to refresh
            note: Note dictionary from database
        """
        html_text, plain_text, is_marked = self._build_note_item_display(note)
        item.setData(ROLE_MARKED, is_marked)
        item.setData(ROLE_HTML_TEXT, html_text)
        item.setText(plain_text)

    def refresh_note_item(self, note_id: str) -> bool:
        """Refresh a specific note item in the list.

        This is called when a note's tags or other display data changes
        and the list item needs to be updated.

        Args:
            note_id: ID of the note to refresh

        Returns:
            True if the item was found and refreshed, False otherwise.
        """
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.data(ROLE_NOTE_ID) == note_id:
                # Fetch fresh note data and rebuild display
                note = self.db.get_note(note_id)
                if note:
                    self._refresh_item_display(item, note)
                    self.list_widget.update()
                    logger.info(f"Refreshed list item for note {note_id[:8]}...")
                    return True
                else:
                    logger.warning(f"Note {note_id[:8]}... not found when refreshing")
                    return False
        logger.debug(f"Note {note_id[:8]}... not in current list view")
        return False

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

            # Update star filter button state based on search text
            self._update_star_filter_button_state(text)

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
        self._update_star_filter_button_state("")
        self.load_notes()
        logger.info("Search cleared, showing all notes")

    def toggle_marked_filter(self) -> None:
        """Toggle is:marked filter in the search field."""
        import re
        current_text = self.search_field.toPlainText()

        if "is:marked" in current_text.lower():
            # Remove is:marked (case-insensitive)
            new_text = re.sub(r'\bis:marked\b', '', current_text, flags=re.IGNORECASE)
            # Collapse multiple spaces and strip
            new_text = re.sub(r'\s+', ' ', new_text).strip()
            self.search_field.setPlainText(new_text)
            logger.info("Removed is:marked filter from search")
        else:
            # Add is:marked at the beginning
            new_text = f"is:marked {current_text}".strip()
            self.search_field.setPlainText(new_text)
            logger.info("Added is:marked filter to search")

        # Run search with the updated query
        self.perform_search()

    def _update_star_filter_button_state(self, search_text: str) -> None:
        """Update the star filter button appearance based on search text.

        Args:
            search_text: Current search field text
        """
        if "is:marked" in search_text.lower():
            self.star_filter_button.setText(STAR_FILLED)
            self.star_filter_button.setStyleSheet(f"""
                QToolButton {{
                    border: none;
                    background: transparent;
                    font-size: 16px;
                    color: {STAR_COLOR_GOLD};
                }}
                QToolButton:hover {{
                    background: #555;
                    border-radius: 12px;
                }}
            """)
        else:
            self.star_filter_button.setText(STAR_EMPTY)
            self.star_filter_button.setStyleSheet(f"""
                QToolButton {{
                    border: none;
                    background: transparent;
                    font-size: 16px;
                    color: {STAR_COLOR_GRAY};
                }}
                QToolButton:hover {{
                    background: #555;
                    border-radius: 12px;
                }}
            """)

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

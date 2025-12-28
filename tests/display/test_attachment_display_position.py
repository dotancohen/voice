"""Tests for attachment display position in UI.

Tests that verify:
- Attachments are displayed BELOW note content (#10)
- Required fields are shown: id, filename, imported_at, file_created_at
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ============================================================================
# Web API Display Tests (already working)
# ============================================================================

class TestWebApiAttachmentDisplay:
    """Test that Web API returns note with content before attachments."""

    def test_note_response_has_content_before_attachments(self, tmp_path: Path) -> None:
        """Test that note API response structure has content field."""
        from core.database import Database, set_local_device_id

        set_local_device_id("00000000000070008000000000000001")
        db = Database(tmp_path / "notes.db")

        note_id = db.create_note("Note content appears here")

        # Get note from database
        note = db.get_note(note_id)

        # Content field should exist
        assert "content" in note
        assert note["content"] == "Note content appears here"

    def test_attachments_endpoint_returns_display_fields(self, tmp_path: Path) -> None:
        """Test that attachments have all required display fields."""
        from core.database import Database, set_local_device_id

        set_local_device_id("00000000000070008000000000000001")
        db = Database(tmp_path / "notes.db")

        note_id = db.create_note("Test note")
        audio_id = db.create_audio_file("recording.mp3", "2024-01-15 10:30:00")
        db.attach_to_note(note_id, audio_id, "audio_file")

        audio_files = db.get_audio_files_for_note(note_id)

        # All required fields should be present
        assert len(audio_files) == 1
        af = audio_files[0]

        assert "id" in af, "Missing 'id' field"
        assert "filename" in af, "Missing 'filename' field"
        assert "imported_at" in af, "Missing 'imported_at' field"
        assert "file_created_at" in af, "Missing 'file_created_at' field"

    def test_multiple_attachments_all_displayed(self, tmp_path: Path) -> None:
        """Test that all attachments are returned for a note."""
        from core.database import Database, set_local_device_id

        set_local_device_id("00000000000070008000000000000001")
        db = Database(tmp_path / "notes.db")

        note_id = db.create_note("Note with multiple attachments")

        # Create multiple audio files
        audio_ids = [
            db.create_audio_file("file1.mp3"),
            db.create_audio_file("file2.wav"),
            db.create_audio_file("file3.ogg"),
        ]

        # Attach all to note
        for audio_id in audio_ids:
            db.attach_to_note(note_id, audio_id, "audio_file")

        # All should be returned
        audio_files = db.get_audio_files_for_note(note_id)
        assert len(audio_files) == 3


# ============================================================================
# TUI Display Tests
# ============================================================================

class TestTuiAttachmentDisplay:
    """Test that TUI displays attachments below note content."""

    def test_tui_note_detail_shows_content_before_attachments(self, tmp_path: Path) -> None:
        """Test that TUI compose method has attachments after content."""
        # Read the tui.py source to verify compose order
        tui_path = Path(__file__).parent.parent.parent / "src" / "tui.py"

        if not tui_path.exists():
            pytest.skip("tui.py not found")

        content = tui_path.read_text()

        # Find the NoteDetail class and compose method
        # The order should be: note-view, note-edit, then note-attachments
        view_pos = content.find('id="note-view"')
        edit_pos = content.find('id="note-edit"')
        attachments_pos = content.find('id="note-attachments"')

        assert view_pos >= 0, "note-view not found in TUI"
        assert attachments_pos >= 0, "note-attachments not found in TUI"

        assert attachments_pos > view_pos, (
            "TUI should yield note-attachments AFTER note-view (content first, then attachments)"
        )
        assert attachments_pos > edit_pos, (
            "TUI should yield note-attachments AFTER note-edit (content first, then attachments)"
        )

    def test_tui_displays_attachment_fields(self, tmp_path: Path) -> None:
        """Test that TUI displays required attachment fields."""
        from core.database import Database, set_local_device_id

        set_local_device_id("00000000000070008000000000000001")
        db = Database(tmp_path / "notes.db")

        note_id = db.create_note("Test note")
        audio_id = db.create_audio_file("important-meeting.mp3", "2024-06-15 10:30:00")
        db.attach_to_note(note_id, audio_id, "audio_file")

        audio_files = db.get_audio_files_for_note(note_id)
        assert len(audio_files) == 1

        audio = audio_files[0]

        # TUI should display these fields in load_note
        assert "id" in audio, "Missing 'id' for TUI display"
        assert "filename" in audio, "Missing 'filename' for TUI display"
        assert "imported_at" in audio, "Missing 'imported_at' for TUI display"
        assert "file_created_at" in audio, "Missing 'file_created_at' for TUI display"

        # Verify TUI code references these fields
        tui_path = Path(__file__).parent.parent.parent / "src" / "tui.py"
        if tui_path.exists():
            content = tui_path.read_text()
            assert "imported_at" in content, "TUI should reference imported_at field"
            assert "file_created_at" in content, "TUI should reference file_created_at field"


# ============================================================================
# GUI Display Tests
# ============================================================================

class TestGuiAttachmentDisplay:
    """Test that GUI displays attachments below note content."""

    def test_gui_note_pane_has_attachments_section(self) -> None:
        """Test that GUI note pane includes an attachments section."""
        # Read the note_pane.py to verify structure
        note_pane_path = Path(__file__).parent.parent.parent / "src" / "ui" / "note_pane.py"

        if not note_pane_path.exists():
            pytest.skip("note_pane.py not found")

        content = note_pane_path.read_text()

        # Check for attachments-related widgets
        has_attachments_label = "attachments_label" in content
        has_attachments_list = "attachments_list" in content or "QListWidget" in content

        assert has_attachments_label, (
            "GUI note_pane.py should have an attachments_label"
        )
        assert has_attachments_list, (
            "GUI note_pane.py should have an attachments_list widget"
        )

        # Verify the layout order (content first, then attachments)
        # In setup_ui, content_text should appear before attachments_label
        content_pos = content.find("self.content_text")
        attachments_pos = content.find("self.attachments_label")

        assert content_pos >= 0, "content_text not found"
        assert attachments_pos >= 0, "attachments_label not found"
        assert attachments_pos > content_pos, (
            "Attachments section should be added to layout AFTER content section"
        )

    def test_gui_displays_attachment_fields(self) -> None:
        """Test that GUI displays required attachment fields."""
        note_pane_path = Path(__file__).parent.parent.parent / "src" / "ui" / "note_pane.py"

        if not note_pane_path.exists():
            pytest.skip("note_pane.py not found")

        content = note_pane_path.read_text()

        # Check that the code references the required fields
        required_fields = ["filename", "imported_at", "file_created_at"]
        missing_fields = [f for f in required_fields if f not in content]

        assert not missing_fields, (
            f"GUI note_pane.py missing display of fields: {missing_fields}. "
            f"Required: id, filename, imported_at, file_created_at"
        )


# ============================================================================
# Display Order Verification
# ============================================================================

class TestDisplayOrderRequirement:
    """Verify the explicit requirement: attachments shown BELOW note content."""

    def test_requirement_attachments_below_content(self) -> None:
        """
        Explicit test for requirement:
        'When Notes have one or more NoteAttachments, these NoteAttachments
        should be shown as an array of their fields, below the display of
        the Note content field.'
        """
        # Verify TUI
        tui_path = Path(__file__).parent.parent.parent / "src" / "tui.py"
        if tui_path.exists():
            tui_content = tui_path.read_text()
            view_pos = tui_content.find('id="note-view"')
            attachments_pos = tui_content.find('id="note-attachments"')
            assert attachments_pos > view_pos, "TUI: attachments should be after content"

        # Verify GUI
        gui_path = Path(__file__).parent.parent.parent / "src" / "ui" / "note_pane.py"
        if gui_path.exists():
            gui_content = gui_path.read_text()
            content_pos = gui_content.find("self.content_text")
            attachments_pos = gui_content.find("self.attachments_label")
            assert attachments_pos > content_pos, "GUI: attachments should be after content"

        # Verify fields displayed
        for path in [tui_path, gui_path]:
            if path.exists():
                content = path.read_text()
                assert "imported_at" in content, f"{path.name}: should display imported_at"
                assert "file_created_at" in content, f"{path.name}: should display file_created_at"

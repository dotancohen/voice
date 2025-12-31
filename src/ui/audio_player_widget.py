"""Audio player widget for PySide6 GUI.

This module provides an audio player widget with waveform visualization
and playback controls for the desktop GUI.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from src.core.audio_player import AudioPlayer, PlaybackState, format_time, is_mpv_available
from src.core.waveform import WAVEFORM_BAR_COUNT, extract_waveform
from src.ui.styles import BUTTON_STYLE

logger = logging.getLogger(__name__)


class WaveformWidget(QWidget):
    """Widget that displays a waveform visualization and allows seeking.

    Signals:
        seek_requested: Emitted when user clicks to seek (fraction 0.0 to 1.0)
    """

    seek_requested = Signal(float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._waveform: List[float] = []
        self._progress: float = 0.0
        self._played_color = QColor("#3daee9")  # KDE Breeze blue
        self._unplayed_color = QColor("#4d4d4d")  # Gray
        self._background_color = QColor("#2d2d2d")  # Dark gray
        self.setMinimumHeight(60)
        self.setMaximumHeight(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

    def set_waveform(self, waveform: List[float]) -> None:
        """Set the waveform data to display."""
        self._waveform = waveform
        self.update()

    def set_progress(self, progress: float) -> None:
        """Set the playback progress (0.0 to 1.0)."""
        self._progress = max(0.0, min(1.0, progress))
        self.update()

    def mousePressEvent(self, event) -> None:
        """Handle click to seek."""
        if event.button() == Qt.LeftButton:
            fraction = event.pos().x() / self.width()
            self.seek_requested.emit(max(0.0, min(1.0, fraction)))

    def paintEvent(self, event) -> None:
        """Paint the waveform."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Background
        painter.fillRect(self.rect(), self._background_color)

        if not self._waveform:
            # Draw placeholder bars
            self._draw_placeholder(painter)
            return

        bar_count = len(self._waveform)
        bar_width = self.width() / bar_count
        actual_bar_width = max(1, bar_width - 1)
        max_bar_height = self.height() * 0.9
        center_y = self.height() / 2

        for i, amplitude in enumerate(self._waveform):
            x = i * bar_width
            bar_height = max(2, amplitude * max_bar_height)

            # Choose color based on progress
            bar_progress = i / bar_count
            if bar_progress <= self._progress:
                painter.fillRect(
                    int(x), int(center_y - bar_height / 2),
                    int(actual_bar_width), int(bar_height),
                    self._played_color
                )
            else:
                painter.fillRect(
                    int(x), int(center_y - bar_height / 2),
                    int(actual_bar_width), int(bar_height),
                    self._unplayed_color
                )

        # Draw playhead
        if self._progress > 0:
            playhead_x = int(self._progress * self.width())
            pen = QPen(self._played_color)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawLine(playhead_x, 0, playhead_x, self.height())

    def _draw_placeholder(self, painter: QPainter) -> None:
        """Draw placeholder waveform."""
        bar_count = 50
        bar_width = self.width() / bar_count
        actual_bar_width = max(1, bar_width - 1)
        max_bar_height = self.height() * 0.4
        center_y = self.height() / 2

        for i in range(bar_count):
            x = i * bar_width
            amplitude = 0.3 + (i % 5) * 0.1
            bar_height = amplitude * max_bar_height

            painter.fillRect(
                int(x), int(center_y - bar_height / 2),
                int(actual_bar_width), int(bar_height),
                self._unplayed_color
            )


class AudioPlayerWidget(QFrame):
    """Audio player widget with waveform and controls.

    Features:
    - Waveform display that doubles as seek bar
    - Play/pause button
    - Skip back 3s and 10s buttons
    - Speed control button (placeholder)
    - Time display (MM:SS or HH:MM:SS)
    - Audio file list with selection and transcription count
    """

    # Emitted when user requests transcription of an audio file
    transcribe_requested = Signal(str)  # audio_file_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)

        self._player = AudioPlayer()
        self._waveforms: Dict[int, List[float]] = {}
        self._audio_files: List[Dict] = []
        self._file_paths: List[Path] = []
        self._transcription_counts: Dict[str, int] = {}

        self._setup_ui()
        self._connect_signals()

        # Update timer
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_ui)
        self._update_timer.start(100)

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Check if MPV is available
        if not is_mpv_available():
            error_label = QLabel("MPV is not installed. Audio playback is unavailable.")
            error_label.setStyleSheet("color: red;")
            layout.addWidget(error_label)

        # Waveform
        self._waveform_widget = WaveformWidget()
        layout.addWidget(self._waveform_widget)

        # Time display
        time_layout = QHBoxLayout()
        self._current_time_label = QLabel("00:00")
        self._duration_label = QLabel("00:00")
        time_layout.addWidget(self._current_time_label)
        time_layout.addStretch()
        time_layout.addWidget(self._duration_label)
        layout.addLayout(time_layout)

        # Controls
        controls_layout = QHBoxLayout()
        controls_layout.addStretch()

        # Skip back 10s
        self._skip_10_button = QPushButton("⏪ 10s")
        self._skip_10_button.setStyleSheet(BUTTON_STYLE)
        self._skip_10_button.clicked.connect(lambda: self._player.skip_back(10))
        controls_layout.addWidget(self._skip_10_button)

        # Skip back 3s
        self._skip_3_button = QPushButton("⏪ 3s")
        self._skip_3_button.setStyleSheet(BUTTON_STYLE)
        self._skip_3_button.clicked.connect(lambda: self._player.skip_back(3))
        controls_layout.addWidget(self._skip_3_button)

        # Play/Pause
        self._play_button = QPushButton("▶")
        self._play_button.setStyleSheet(BUTTON_STYLE + "QPushButton { font-size: 18px; padding: 10px 20px; }")
        self._play_button.clicked.connect(self._on_play_pause)
        controls_layout.addWidget(self._play_button)

        # Speed (placeholder)
        self._speed_button = QPushButton("1x")
        self._speed_button.setStyleSheet(BUTTON_STYLE)
        self._speed_button.setEnabled(False)
        self._speed_button.setToolTip("Speed control (not yet implemented)")
        controls_layout.addWidget(self._speed_button)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        # Audio file list
        list_label = QLabel("Audio Files")
        layout.addWidget(list_label)

        self._file_list = QListWidget()
        self._file_list.setMaximumHeight(150)
        self._file_list.itemClicked.connect(self._on_file_selected)
        layout.addWidget(self._file_list)

    def _connect_signals(self) -> None:
        """Connect signals."""
        self._waveform_widget.seek_requested.connect(self._on_seek)
        self._player.set_on_state_change(self._on_state_change)

    def set_audio_files(
        self,
        audio_files: List[Dict],
        get_file_path: callable,
        transcription_counts: Optional[Dict[str, int]] = None,
    ) -> None:
        """Set the audio files to display.

        Args:
            audio_files: List of audio file dicts (with 'id', 'filename' keys).
            get_file_path: Callable that takes audio_id and returns file path.
            transcription_counts: Optional dict mapping audio_file_id to transcription count.
        """
        self._audio_files = audio_files
        self._transcription_counts = transcription_counts or {}
        self._file_list.clear()
        self._file_paths = []
        self._waveforms = {}

        for af in audio_files:
            audio_id = af.get("id", "")
            filename = af.get("filename", "Unknown")
            t_count = self._transcription_counts.get(audio_id, 0)

            # Format: "filename | T: N"
            display_text = f"{filename} | T: {t_count}"
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, audio_id)
            self._file_list.addItem(item)

            # Get file path
            path = get_file_path(audio_id)
            self._file_paths.append(Path(path) if path else Path())

        # Set files in player
        self._player.set_audio_files(self._file_paths)

        # Extract waveforms in background (synchronous for now)
        for i, path in enumerate(self._file_paths):
            if path.exists():
                waveform = extract_waveform(path, WAVEFORM_BAR_COUNT)
                self._waveforms[i] = waveform

        # Update waveform display if we have files
        if self._waveforms:
            self._waveform_widget.set_waveform(self._waveforms.get(0, []))

    def update_transcription_count(self, audio_file_id: str, count: int) -> None:
        """Update the transcription count for an audio file.

        Args:
            audio_file_id: Audio file UUID hex string
            count: New transcription count
        """
        self._transcription_counts[audio_file_id] = count

        # Find and update the list item
        for i in range(self._file_list.count()):
            item = self._file_list.item(i)
            if item.data(Qt.UserRole) == audio_file_id:
                # Find the audio file dict
                for af in self._audio_files:
                    if af.get("id") == audio_file_id:
                        filename = af.get("filename", "Unknown")
                        item.setText(f"{filename} | T: {count}")
                        break
                break

    def get_selected_audio_file_id(self) -> Optional[str]:
        """Get the currently selected audio file ID.

        Returns:
            Audio file UUID hex string, or None if nothing selected
        """
        current = self._file_list.currentItem()
        if current:
            return current.data(Qt.UserRole)
        return None

    def _on_play_pause(self) -> None:
        """Handle play/pause button click."""
        state = self._player.state
        if state.current_file_index < 0 and self._file_paths:
            self._player.play_file(0)
            self._select_file_in_list(0)
        else:
            self._player.toggle_play_pause()

    def _on_seek(self, fraction: float) -> None:
        """Handle seek request from waveform."""
        self._player.seek_to_fraction(fraction)

    def _on_file_selected(self, item: QListWidgetItem) -> None:
        """Handle file selection from list."""
        row = self._file_list.row(item)
        self._player.play_file(row)

    def _on_state_change(self, state: PlaybackState) -> None:
        """Handle state change from player."""
        # Update is handled by timer for thread safety

    def _update_ui(self) -> None:
        """Update UI from current state."""
        state = self._player.state

        # Update play button
        self._play_button.setText("⏸" if state.is_playing else "▶")

        # Update time
        self._current_time_label.setText(format_time(state.current_position))
        self._duration_label.setText(format_time(state.duration))

        # Update waveform progress
        if state.duration > 0:
            progress = state.current_position / state.duration
            self._waveform_widget.set_progress(progress)

        # Update waveform for current file
        if state.current_file_index >= 0:
            waveform = self._waveforms.get(state.current_file_index, [])
            self._waveform_widget.set_waveform(waveform)
            self._select_file_in_list(state.current_file_index)

    def _select_file_in_list(self, index: int) -> None:
        """Select a file in the list widget."""
        if 0 <= index < self._file_list.count():
            self._file_list.setCurrentRow(index)

    def cleanup(self) -> None:
        """Clean up resources."""
        self._update_timer.stop()
        self._player.release()

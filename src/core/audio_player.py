"""Audio player using MPV.

This module provides audio playback functionality using the MPV media player.
Supports playing a list of audio files with seeking and playback control.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


def is_mpv_available() -> bool:
    """Check if MPV is installed and available."""
    return shutil.which("mpv") is not None


@dataclass
class PlaybackState:
    """Current playback state."""

    is_playing: bool = False
    current_position: float = 0.0  # seconds
    duration: float = 0.0  # seconds
    current_file_index: int = -1
    playback_speed: float = 1.0


class AudioPlayer:
    """Audio player using MPV subprocess.

    Provides:
    - Playing a list of audio files
    - Auto-advancement to next file
    - Seeking via position or fraction
    - Skip back functionality
    - Playback speed control (placeholder for now)
    """

    def __init__(self) -> None:
        """Initialize the audio player."""
        self._process: Optional[subprocess.Popen] = None
        self._state = PlaybackState()
        self._files: List[Path] = []
        self._position_thread: Optional[threading.Thread] = None
        self._stop_position_thread = threading.Event()
        self._on_state_change: Optional[Callable[[PlaybackState], None]] = None
        self._on_file_ended: Optional[Callable[[], None]] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> PlaybackState:
        """Get the current playback state."""
        return self._state

    def set_on_state_change(self, callback: Optional[Callable[[PlaybackState], None]]) -> None:
        """Set callback for state changes."""
        self._on_state_change = callback

    def set_on_file_ended(self, callback: Optional[Callable[[], None]]) -> None:
        """Set callback for when a file finishes playing."""
        self._on_file_ended = callback

    def set_audio_files(self, files: List[Path | str]) -> None:
        """Set the list of audio files to play.

        Args:
            files: List of file paths.
        """
        self.stop()
        self._files = [Path(f) for f in files if Path(f).exists()]
        self._state = PlaybackState(current_file_index=-1)
        self._notify_state_change()

    def play_file(self, index: int) -> bool:
        """Play a specific file by index.

        Args:
            index: Index in the audio files list.

        Returns:
            True if playback started successfully.
        """
        if index < 0 or index >= len(self._files):
            return False

        if not is_mpv_available():
            logger.error("MPV is not installed. Cannot play audio.")
            return False

        self.stop()

        file_path = self._files[index]
        if not file_path.exists():
            logger.warning(f"Audio file not found: {file_path}")
            return False

        try:
            # Start MPV with IPC socket for control
            self._process = subprocess.Popen(
                [
                    "mpv",
                    "--no-video",
                    "--really-quiet",
                    "--terminal=no",
                    str(file_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Get duration using ffprobe (mpv doesn't output duration in this mode)
            from .waveform import get_audio_duration
            duration = get_audio_duration(file_path) or 0.0

            self._state = PlaybackState(
                is_playing=True,
                current_position=0.0,
                duration=duration,
                current_file_index=index,
                playback_speed=1.0,
            )
            self._notify_state_change()

            # Start position tracking thread
            self._start_position_thread()

            return True

        except subprocess.SubprocessError as e:
            logger.error(f"Failed to start MPV: {e}")
            return False

    def toggle_play_pause(self) -> None:
        """Toggle play/pause."""
        if self._state.current_file_index < 0 and self._files:
            # Start playing first file
            self.play_file(0)
        elif self._process is not None:
            # MPV subprocess mode doesn't support pause, so we stop/restart
            # For now, just stop
            if self._state.is_playing:
                self.stop()
            else:
                # Resume from current position
                self.seek_to(self._state.current_position)
                self.play_file(self._state.current_file_index)

    def stop(self) -> None:
        """Stop playback."""
        self._stop_position_thread.set()
        if self._position_thread:
            self._position_thread.join(timeout=1.0)
            self._position_thread = None

        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
            except Exception as e:
                logger.warning(f"Error stopping MPV: {e}")
            self._process = None

        self._state.is_playing = False
        self._notify_state_change()

    def seek_to(self, position_seconds: float) -> None:
        """Seek to a specific position in seconds.

        Note: With subprocess mode, we restart playback from the position.
        """
        position = max(0.0, min(position_seconds, self._state.duration))
        self._state.current_position = position
        self._notify_state_change()

        # Restart playback from this position if currently playing
        if self._state.is_playing and self._state.current_file_index >= 0:
            self._restart_at_position(position)

    def seek_to_fraction(self, fraction: float) -> None:
        """Seek to a fraction of the duration (0.0 to 1.0)."""
        position = fraction * self._state.duration
        self.seek_to(position)

    def skip_back(self, seconds: int) -> None:
        """Skip back by the specified number of seconds."""
        new_position = max(0.0, self._state.current_position - seconds)
        self.seek_to(new_position)

    def release(self) -> None:
        """Release player resources."""
        self.stop()

    def _restart_at_position(self, position: float) -> None:
        """Restart playback at a specific position."""
        if self._state.current_file_index < 0 or self._state.current_file_index >= len(self._files):
            return

        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=1.0)
            except:
                pass

        file_path = self._files[self._state.current_file_index]

        try:
            self._process = subprocess.Popen(
                [
                    "mpv",
                    "--no-video",
                    "--really-quiet",
                    "--terminal=no",
                    f"--start={position}",
                    str(file_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._state.current_position = position
            self._state.is_playing = True
            self._notify_state_change()
        except subprocess.SubprocessError as e:
            logger.error(f"Failed to restart MPV: {e}")

    def _start_position_thread(self) -> None:
        """Start the position tracking thread."""
        self._stop_position_thread.clear()
        self._position_thread = threading.Thread(target=self._track_position, daemon=True)
        self._position_thread.start()

    def _track_position(self) -> None:
        """Track playback position by polling process status."""
        start_time = time.time()
        start_position = self._state.current_position

        while not self._stop_position_thread.is_set():
            if self._process is None:
                break

            # Check if process ended
            poll_result = self._process.poll()
            if poll_result is not None:
                # Process ended
                self._state.is_playing = False
                self._state.current_position = self._state.duration
                self._notify_state_change()

                # Auto-play next file
                if self._state.current_file_index < len(self._files) - 1:
                    if self._on_file_ended:
                        self._on_file_ended()
                    self.play_file(self._state.current_file_index + 1)
                break

            # Update position based on elapsed time
            elapsed = time.time() - start_time
            new_position = start_position + elapsed * self._state.playback_speed
            new_position = min(new_position, self._state.duration)

            if new_position != self._state.current_position:
                self._state.current_position = new_position
                self._notify_state_change()

            time.sleep(0.1)

    def _notify_state_change(self) -> None:
        """Notify listeners of state change."""
        if self._on_state_change:
            try:
                self._on_state_change(self._state)
            except Exception as e:
                logger.warning(f"Error in state change callback: {e}")


def format_time(seconds: float) -> str:
    """Format seconds to MM:SS or HH:MM:SS for files over 60 minutes.

    Args:
        seconds: Time in seconds.

    Returns:
        Formatted time string.
    """
    if seconds <= 0:
        return "00:00"

    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

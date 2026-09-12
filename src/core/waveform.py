"""Waveform extraction for audio files.

This module extracts waveform amplitude data from audio files for visualization.
Uses FFmpeg/FFprobe for decoding.
"""

from __future__ import annotations

import array
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Number of bars to display in waveform visualization
WAVEFORM_BAR_COUNT = 150

# When a recording is large enough that its waveform is drawn only when the
# user asks for it.
#
# Drawing one means decoding the whole recording: on this desktop about 870
# times real time, so an hour is a few seconds and eight hours most of a
# minute, and on a phone many times slower. The duration is the measure that
# matters — the work tracks the length of the audio — and the size is the
# guard for when the duration is not known or the header is wrong. 100 MiB is
# about 52 minutes of 16 kHz WAV, 1.8 hours of Opus at 128 kb/s, or 2.4 hours
# of AAC at 96.
#
# The same two numbers are in VoiceAndroid's `util/MagicNumbers.kt`, and both
# user manuals state them.
LONG_RECORDING_SECONDS = 60 * 60
LARGE_RECORDING_BYTES = 100 * 1024 * 1024

# What the user is offered in place of the waveform of a large recording. The
# same two lines as on the phone.
GENERATE_WAVEFORM_PROMPT = (
    "Click to generate waveform\n"
    "Resource intensive operation on large file"
)

# How much decoded audio is read at a time. Large enough that the reading is
# not the slow part, small enough that memory never depends on the length of
# the recording: 64 kB is four seconds of 8 kHz mono.
BLOCK_BYTES = 64 * 1024


def _check_ffmpeg() -> bool:
    """Check if ffmpeg is available."""
    return shutil.which("ffmpeg") is not None


def _check_ffprobe() -> bool:
    """Check if ffprobe is available."""
    return shutil.which("ffprobe") is not None


def get_audio_duration(file_path: Path | str) -> Optional[float]:
    """Get the duration of an audio file in seconds.

    Args:
        file_path: Path to the audio file.

    Returns:
        Duration in seconds, or None if it couldn't be determined.
    """
    if not _check_ffprobe():
        logger.warning("ffprobe not found, cannot get audio duration")
        return None

    file_path = Path(file_path)
    if not file_path.exists():
        return None

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, ValueError) as e:
        logger.warning(f"Error getting duration for {file_path}: {e}")

    return None



class WaveformAccumulator:
    """The bars of a waveform, built as the audio arrives.

    Holds a few hundred floats and nothing else, however long the recording
    is. The number of samples is not known in advance, so the accumulator
    starts fine and halves its own resolution whenever it runs out of slots:
    two slots become one, and every slot from then on covers twice as much
    audio. The picture is the same either way, and the memory never moves.

    This replaced turning the whole recording into a list of samples. An hour
    of audio is about 29 million samples, and a Python ``int`` is 28 bytes
    plus a pointer: a gigabyte for one recording, which is how the Android
    application was killed by the same mistake on 2026-09-10 (see
    ``BUGS-THE-TESTS-MISSED.md``).
    """

    SLOTS_PER_BAR = 8

    def __init__(self, bar_count: int = WAVEFORM_BAR_COUNT) -> None:
        self._bar_count = max(1, bar_count)
        self._slots = [0.0] * (self._bar_count * self.SLOTS_PER_BAR)
        self._filled = 0
        self._samples_per_slot = 1
        self._in_slot = 0
        self._peak = 0.0
        self._any = False

    def expect(self, total_samples: int) -> None:
        """Say roughly how many samples are coming, where that is known."""
        if total_samples > 0 and self._filled == 0 and self._in_slot == 0:
            self._samples_per_slot = max(1, total_samples // len(self._slots))

    def add_samples(self, samples) -> None:
        """Add a block of 16-bit samples (anything iterable of ints)."""
        for sample in samples:
            self._any = True
            value = float(abs(sample))
            if value > self._peak:
                self._peak = value
            self._in_slot += 1
            if self._in_slot >= self._samples_per_slot:
                self._commit()

    def bars(self) -> List[float]:
        """The bars, scaled so the loudest fills the height."""
        if not self._any:
            return []
        if self._in_slot > 0:
            self._commit()
        if self._filled == 0:
            return []

        loudest = max(self._slots[: self._filled])

        def scaled(value: float) -> float:
            return value / loudest if loudest > 0 else 0.0

        if self._filled <= self._bar_count:
            return [scaled(v) for v in self._slots[: self._filled]]

        bars: List[float] = []
        for bar in range(self._bar_count):
            start = bar * self._filled // self._bar_count
            end = max(start + 1, (bar + 1) * self._filled // self._bar_count)
            bars.append(scaled(max(self._slots[start : min(end, self._filled)])))
        return bars

    def _commit(self) -> None:
        if self._filled == len(self._slots):
            self._halve()
        self._slots[self._filled] = self._peak
        self._filled += 1
        self._peak = 0.0
        self._in_slot = 0

    def _halve(self) -> None:
        write = 0
        read = 0
        while read < self._filled:
            a = self._slots[read]
            b = self._slots[read + 1] if read + 1 < self._filled else 0.0
            self._slots[write] = max(a, b)
            write += 1
            read += 2
        for i in range(write, len(self._slots)):
            self._slots[i] = 0.0
        self._filled = write
        self._samples_per_slot *= 2


def is_large_recording(
    file_path: Path | str,
    duration_seconds: Optional[float] = None,
) -> bool:
    """Whether drawing this recording's waveform is worth asking about first.

    A recording of a meeting, or of somebody sleeping, is kept, played and
    synced like any other; only the decoding of the whole of it to draw a
    picture is offered rather than assumed.

    Args:
        file_path: The recording.
        duration_seconds: Its length where that is already known. Read from
            the file when it is not, which costs one ffprobe call.

    Returns:
        True when the recording is past either limit.
    """
    path = Path(file_path)
    try:
        if path.exists() and path.stat().st_size >= LARGE_RECORDING_BYTES:
            return True
    except OSError:
        return False

    if duration_seconds is None:
        duration_seconds = get_audio_duration(path)
    return bool(duration_seconds and duration_seconds >= LONG_RECORDING_SECONDS)


def extract_waveform(file_path: Path | str, bar_count: int = WAVEFORM_BAR_COUNT) -> List[float]:
    """Extract waveform data from an audio file.

    Args:
        file_path: Path to the audio file.
        bar_count: Number of bars in the output waveform.

    Returns:
        List of normalized amplitude values (0.0 to 1.0), one per bar.
        Returns empty list if extraction fails.
    """
    if not _check_ffmpeg():
        logger.warning("ffmpeg not found, cannot extract waveform")
        return []

    file_path = Path(file_path)
    if not file_path.exists():
        logger.warning(f"File not found: {file_path}")
        return []

    accumulator = WaveformAccumulator(bar_count)
    duration = get_audio_duration(file_path)
    if duration:
        accumulator.expect(int(duration * 8000))

    process = None
    try:
        # ffmpeg decodes to raw 16-bit PCM mono at 8 kHz — fine for a picture
        # of the loudness — and it is read in blocks as it arrives. Nothing
        # holds the whole recording: a long one would otherwise be a list of
        # tens of millions of Python ints, which is gigabytes.
        process = subprocess.Popen(
            [
                "ffmpeg",
                "-i", str(file_path),
                "-ar", "8000",
                "-ac", "1",
                "-f", "s16le",
                "-",  # Output to stdout
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert process.stdout is not None
        block = array.array("h")
        while True:
            chunk = process.stdout.read(BLOCK_BYTES)
            if not chunk:
                break
            # An odd tail byte would break the unpacking; keep it for the
            # next block.
            if len(chunk) % 2:
                chunk = chunk[:-1]
            del block[:]
            block.frombytes(chunk)
            if sys.byteorder != "little":
                block.byteswap()
            accumulator.add_samples(block)

        process.stdout.close()
        if process.wait(timeout=300) != 0:
            logger.warning(f"ffmpeg failed for {file_path}")
            return []

        return accumulator.bars()

    except subprocess.TimeoutExpired:
        logger.warning(f"ffmpeg took too long for {file_path}")
        return []
    except Exception as e:
        logger.warning(f"Error extracting waveform for {file_path}: {e}")
        return []
    finally:
        if process is not None and process.poll() is None:
            process.kill()


def waveform_with_progress(
    waveform: List[float],
    progress: float,
    width: int = 50,
    played_char: str = "█",
    unplayed_char: str = "░",
) -> str:
    """Create ASCII progress bar with waveform indication.

    Args:
        waveform: List of normalized amplitude values (0.0 to 1.0).
        progress: Current playback position (0.0 to 1.0).
        width: Number of characters wide.
        played_char: Character for played portion.
        unplayed_char: Character for unplayed portion.

    Returns:
        ASCII progress bar string.
    """
    if not waveform:
        # Simple progress bar without waveform
        played = int(progress * width)
        return played_char * played + unplayed_char * (width - played)

    # Resample waveform to width
    if len(waveform) != width:
        resampled = []
        for i in range(width):
            src_start = int(i * len(waveform) / width)
            src_end = int((i + 1) * len(waveform) / width)
            if src_start < src_end:
                resampled.append(max(waveform[src_start:src_end]))
            else:
                resampled.append(waveform[src_start] if src_start < len(waveform) else 0.0)
        waveform = resampled

    # Build progress bar with waveform character selection
    # Use block height characters based on amplitude
    played_blocks = " ▁▂▃▄▅▆▇█"
    unplayed_blocks = " ░░░░░░░░"  # Use lighter character for unplayed

    played_pos = int(progress * width)
    result = ""

    for i, amp in enumerate(waveform):
        block_idx = min(int(amp * 8), 8)
        if i < played_pos:
            result += played_blocks[block_idx]
        else:
            result += unplayed_blocks[block_idx] if block_idx > 0 else "░"

    return result

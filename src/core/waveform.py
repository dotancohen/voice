"""Waveform extraction for audio files.

This module extracts waveform amplitude data from audio files for visualization.
Uses FFmpeg/FFprobe for decoding.
"""

from __future__ import annotations

import logging
import shutil
import struct
import subprocess
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Number of bars to display in waveform visualization
WAVEFORM_BAR_COUNT = 150


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

    try:
        # Use ffmpeg to decode to raw 16-bit PCM mono audio
        # -ar 8000: low sample rate for faster processing
        # -ac 1: mono
        # -f s16le: signed 16-bit little-endian PCM
        result = subprocess.run(
            [
                "ffmpeg",
                "-i", str(file_path),
                "-ar", "8000",
                "-ac", "1",
                "-f", "s16le",
                "-",  # Output to stdout
            ],
            capture_output=True,
            timeout=60,
        )

        if result.returncode != 0:
            logger.warning(f"ffmpeg failed for {file_path}: {result.stderr.decode()[:200]}")
            return []

        pcm_data = result.stdout
        if not pcm_data:
            return []

        # Convert to list of 16-bit samples
        sample_count = len(pcm_data) // 2
        samples = struct.unpack(f"<{sample_count}h", pcm_data)

        if not samples:
            return []

        # Downsample to bar_count bars
        return _downsample_to_waveform(list(samples), bar_count)

    except subprocess.TimeoutExpired:
        logger.warning(f"ffmpeg timeout for {file_path}")
        return []
    except subprocess.SubprocessError as e:
        logger.warning(f"ffmpeg error for {file_path}: {e}")
        return []
    except struct.error as e:
        logger.warning(f"Error unpacking PCM data for {file_path}: {e}")
        return []


def _downsample_to_waveform(samples: List[int], bar_count: int) -> List[float]:
    """Downsample PCM samples to amplitude values for bars.

    Args:
        samples: List of 16-bit PCM samples.
        bar_count: Number of output bars.

    Returns:
        List of normalized amplitude values (0.0 to 1.0).
    """
    if not samples:
        return []

    samples_per_bar = len(samples) // bar_count

    if samples_per_bar <= 0:
        # Fewer samples than bars
        return [abs(s) / 32768.0 for s in samples[:bar_count]]

    result = []
    max_amplitude = 0.0

    for bar in range(bar_count):
        start = bar * samples_per_bar
        end = min(start + samples_per_bar, len(samples))

        # Find peak amplitude in this segment
        peak = max(abs(s) for s in samples[start:end]) if start < end else 0
        amplitude = float(peak)
        result.append(amplitude)
        max_amplitude = max(max_amplitude, amplitude)

    # Normalize to 0.0 - 1.0 range
    if max_amplitude > 0:
        return [a / max_amplitude for a in result]
    return [0.0] * bar_count


def waveform_to_ascii(waveform: List[float], width: int = 50, height: int = 1) -> str:
    """Convert waveform data to ASCII art.

    Args:
        waveform: List of normalized amplitude values (0.0 to 1.0).
        width: Number of characters wide.
        height: Number of lines tall (1 for simple bar, >1 for vertical bars).

    Returns:
        ASCII art representation of the waveform.
    """
    if not waveform:
        return "─" * width

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

    if height == 1:
        # Single-line waveform using block characters
        # ▁▂▃▄▅▆▇█
        blocks = " ▁▂▃▄▅▆▇█"
        return "".join(blocks[min(int(a * 8), 8)] for a in waveform)
    else:
        # Multi-line waveform
        lines = []
        for row in range(height - 1, -1, -1):
            threshold = (row + 0.5) / height
            line = ""
            for a in waveform:
                if a >= threshold:
                    line += "█"
                elif a >= threshold - 0.5 / height:
                    line += "▄"
                else:
                    line += " "
            lines.append(line)
        return "\n".join(lines)


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

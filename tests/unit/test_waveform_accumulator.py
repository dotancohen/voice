"""Building a waveform without holding the recording.

An hour of audio is about 29 million samples. Turned into a list of Python
ints that is a gigabyte, which is how the Android application was killed on
2026-09-10 by the same mistake in the same feature (entry 15 in
``BUGS-THE-TESTS-MISSED.md``). Every test here is about the length of the
recording not mattering.
"""

from __future__ import annotations

import pytest

from core.waveform import WAVEFORM_BAR_COUNT, WaveformAccumulator, _downsample_to_waveform


def test_an_hour_of_audio_gives_the_agreed_number_of_bars():
    # An hour at 8 kHz: 28 800 000 samples, fed in blocks as ffmpeg would.
    accumulator = WaveformAccumulator()
    for _ in range(2_000):
        accumulator.add_samples(range(0, 14_400))
    bars = accumulator.bars()
    assert len(bars) == WAVEFORM_BAR_COUNT
    assert all(0.0 <= bar <= 1.0 for bar in bars)


def test_the_bars_describe_the_whole_recording_not_its_beginning():
    accumulator = WaveformAccumulator()
    accumulator.expect(1_000_000)
    accumulator.add_samples([100] * 900_000)
    accumulator.add_samples([30_000] * 100_000)
    bars = accumulator.bars()
    assert len(bars) == WAVEFORM_BAR_COUNT
    assert bars[-1] == pytest.approx(1.0)
    assert bars[0] < 0.02


def test_a_recording_longer_than_its_header_said_is_still_drawn():
    accumulator = WaveformAccumulator()
    accumulator.expect(8_000)          # the header claims one second
    accumulator.add_samples([500] * 150_000)   # ten arrive
    accumulator.add_samples([20_000] * 10_000)
    bars = accumulator.bars()
    assert 0 < len(bars) <= WAVEFORM_BAR_COUNT
    assert bars[-1] == pytest.approx(1.0)


def test_no_audio_gives_no_bars():
    assert WaveformAccumulator().bars() == []


def test_silence_is_flat_not_scaled_up_into_noise():
    accumulator = WaveformAccumulator()
    accumulator.expect(100_000)
    accumulator.add_samples([0] * 100_000)
    bars = accumulator.bars()
    assert bars
    assert all(bar == 0.0 for bar in bars)


def test_a_quiet_recording_is_still_drawn_at_full_height():
    accumulator = WaveformAccumulator()
    accumulator.expect(20_000)
    accumulator.add_samples([10] * 10_000)
    accumulator.add_samples([20] * 10_000)
    bars = accumulator.bars()
    assert bars[0] == pytest.approx(0.5, abs=0.01)
    assert bars[-1] == pytest.approx(1.0)


def test_a_negative_sample_is_as_loud_as_a_positive_one():
    accumulator = WaveformAccumulator()
    accumulator.expect(2_000)
    accumulator.add_samples([-32_768] * 2_000)
    assert all(bar == 1.0 for bar in accumulator.bars())


def test_a_handful_of_samples_gives_a_handful_of_bars():
    bars = _downsample_to_waveform([0, 16_383, 32_767], WAVEFORM_BAR_COUNT)
    assert len(bars) == 3
    assert bars[0] == pytest.approx(0.0)
    assert bars[1] == pytest.approx(0.5, abs=0.001)
    assert bars[2] == pytest.approx(1.0)


def test_the_loud_moment_lands_where_it_happened():
    samples = [0] * 750 + [30_000] + [0] * 749
    bars = _downsample_to_waveform(samples, WAVEFORM_BAR_COUNT)
    assert len(bars) == WAVEFORM_BAR_COUNT
    assert bars.index(1.0) == 75


def test_feeding_it_in_blocks_agrees_with_feeding_it_at_once():
    samples = [((i * 613) % 30_000) for i in range(WAVEFORM_BAR_COUNT * 20)]
    at_once = _downsample_to_waveform(samples, WAVEFORM_BAR_COUNT)

    streamed = WaveformAccumulator()
    streamed.expect(len(samples))
    for start in range(0, len(samples), 97):
        streamed.add_samples(samples[start : start + 97])

    assert len(streamed.bars()) == len(at_once)
    for a, b in zip(at_once, streamed.bars()):
        assert a == pytest.approx(b, abs=0.0001)


def test_the_memory_does_not_depend_on_the_length_of_the_recording():
    """The slots are the whole of it, and there is a fixed number of them."""
    short = WaveformAccumulator()
    short.add_samples([1] * 1_000)
    long = WaveformAccumulator()
    long.add_samples([1] * 5_000_000)
    assert len(short._slots) == len(long._slots)
    assert len(long._slots) == WAVEFORM_BAR_COUNT * WaveformAccumulator.SLOTS_PER_BAR


class TestLargeRecordings:
    """Which recordings are drawn only when the user asks.

    The user records meetings of two and a half hours and a subject sleeping
    for eight. All of them are kept, played and synced; only decoding one to
    draw a picture of it is offered rather than assumed.
    """

    def test_a_short_recording_is_drawn_without_asking(self, tmp_path):
        from core.waveform import is_large_recording

        small = tmp_path / "הקלטה.opus"
        small.write_bytes(b"x" * 1024)
        assert is_large_recording(small, duration_seconds=120) is False

    def test_a_recording_of_an_hour_is_asked_about(self, tmp_path):
        from core.waveform import LONG_RECORDING_SECONDS, is_large_recording

        recording = tmp_path / "פגישה.opus"
        recording.write_bytes(b"x" * 1024)
        assert is_large_recording(recording, duration_seconds=LONG_RECORDING_SECONDS) is True
        assert is_large_recording(recording, duration_seconds=LONG_RECORDING_SECONDS - 1) is False

    def test_eight_hours_of_sleep_is_asked_about(self, tmp_path):
        from core.waveform import is_large_recording

        recording = tmp_path / "שינה.opus"
        recording.write_bytes(b"x" * 1024)
        assert is_large_recording(recording, duration_seconds=8 * 3600) is True

    def test_a_large_file_is_asked_about_whatever_its_length(self, tmp_path):
        from core.waveform import LARGE_RECORDING_BYTES, is_large_recording

        # Sparse, so the test does not write 100 MiB to disk
        big = tmp_path / "ארוכה.wav"
        with open(big, "wb") as f:
            f.truncate(LARGE_RECORDING_BYTES)
        assert is_large_recording(big, duration_seconds=60) is True

    def test_a_file_that_is_not_there_is_not_large(self, tmp_path):
        from core.waveform import is_large_recording

        assert is_large_recording(tmp_path / "nothing.opus", duration_seconds=10) is False

    def test_the_limits_are_the_ones_the_manual_states(self):
        from core.waveform import LARGE_RECORDING_BYTES, LONG_RECORDING_SECONDS

        assert LONG_RECORDING_SECONDS == 60 * 60
        assert LARGE_RECORDING_BYTES == 100 * 1024 * 1024

    def test_the_prompt_is_the_same_as_on_the_phone(self):
        from core.waveform import GENERATE_WAVEFORM_PROMPT

        assert GENERATE_WAVEFORM_PROMPT == (
            "Click to generate waveform\nResource intensive operation on large file"
        )

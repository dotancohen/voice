"""The command line's transcription queue: its output format, given before or
after the command (D32)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).parent.parent.parent


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "voice"
    config_dir.mkdir()
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({"database_file": str(config_dir / "notes.db"), "audiofile_directory": str(audio_dir)}))
    return config_dir


def cli(config_dir: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "VOICE_CONFIG_DIR": str(config_dir), "PYTHONPATH": str(PROJECT)}
    return subprocess.run([sys.executable, "-m", "src.main", "cli", *args], capture_output=True, text=True, env=env, cwd=str(PROJECT), timeout=120)


def test_json_given_after_the_command_is_json(config_dir: Path) -> None:
    res = cli(config_dir, "transcription-queue", "--format", "json")
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert {"waiting", "processing", "completed", "rate"} <= set(data)


def test_json_given_before_the_command_is_json_too(config_dir: Path) -> None:
    res = cli(config_dir, "--format", "json", "transcription-queue")
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert {"waiting", "processing", "completed", "rate"} <= set(data)


def test_no_format_is_text(config_dir: Path) -> None:
    res = cli(config_dir, "transcription-queue")
    assert res.returncode == 0, res.stderr
    assert not res.stdout.lstrip().startswith("{")


def test_the_format_after_the_command_wins_over_the_one_before(config_dir: Path) -> None:
    res = cli(config_dir, "--format", "json", "transcription-queue", "--format", "text")
    assert res.returncode == 0, res.stderr
    assert not res.stdout.lstrip().startswith("{")


def test_csv_is_refused_in_words(config_dir: Path) -> None:
    res = cli(config_dir, "--format", "csv", "transcription-queue")
    assert res.returncode == 1
    assert "transcription-queue writes text or json, not csv" in res.stderr

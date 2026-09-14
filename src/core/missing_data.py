"""Calculating data that was never calculated.

Some facts about a Recording are not known when it arrives: a file whose length
could not be read when it was imported has none; a Recording copied without
its filesystem dates has no reliable creation time. None of that is lost data —
it can be read back off the file — but until it is, the application shows less
than it knows.

This module finds those gaps and calculates what is missing. It is one
operation with one report, offered on every interface (CLI, GUI, TUI, Web API),
because the user should not have to remember which interface has the repair in
it. ``VoiceAndroid``'s ``data/MissingData.kt`` is the same operation in the same
words, with the same gap keys.

What is **not** attempted: anything that would be a guess. A Recording's
timezone offset, where it was never recorded, cannot be derived from the file —
writing this machine's offset would state something false about where the user
was. Those gaps are counted and reported, never invented.

**Why the counting is separated from the database.** ``survey_rows`` takes rows,
so each kind of gap is tested with rows that have it, whichever way a database
comes to hold them. See ``VoiceFamily/TECHNICAL-DECISIONS.md`` 6.5.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Gap:
    """One kind of missing data, how many there are, and whether it can be calculated.

    ``calculable`` is false for a gap that nothing on this machine can close.
    """

    key: str
    description: str
    count: int
    calculable: bool = True
    note: str = ""


@dataclass
class Survey:
    """What is missing, before anything is changed."""

    gaps: List[Gap] = field(default_factory=list)

    @property
    def total_calculable(self) -> int:
        return sum(g.count for g in self.gaps if g.calculable)

    @property
    def anything_missing(self) -> bool:
        return any(g.count for g in self.gaps)

    def summary(self) -> str:
        """One line per gap, for a person to read."""
        if not self.anything_missing:
            return "Nothing is missing."
        lines = []
        for gap in self.gaps:
            if not gap.count:
                continue
            suffix = "" if gap.calculable else "  (cannot be calculated: %s)" % gap.note
            lines.append(f"{gap.count:>6}  {gap.description}{suffix}")
        return "\n".join(lines)


@dataclass
class Report:
    """What was calculated, and what could not be."""

    calculated: Dict[str, int] = field(default_factory=dict)
    failed: Dict[str, int] = field(default_factory=dict)
    details: List[str] = field(default_factory=list)

    @property
    def total_calculated(self) -> int:
        return sum(self.calculated.values())

    def summary(self) -> str:
        if not self.calculated and not self.failed:
            return "Nothing needed calculating."
        lines = [
            f"{count:>6}  {key}"
            for key, count in sorted(self.calculated.items()) if count
        ]
        for key, count in sorted(self.failed.items()):
            if count:
                lines.append(f"{count:>6}  {key} — could not be read")
        return "\n".join(lines)


def audio_path(audio_dir: Optional[Path], audio_file: Dict[str, Any]) -> Optional[Path]:
    """Where a Recording's file is: the audio directory and the name the row
    stores (``disk_name``, FILE-15). A name is never derived from the id.

    None when there is no audio directory, the row names no file, or the file
    is not on this machine.
    """
    if audio_dir is None or not audio_file.get("disk_name"):
        return None
    from src.core.audiofile_manager import AudioFileManager

    path = AudioFileManager(str(audio_dir)).get_record_path(audio_file)
    return path if path.is_file() else None


def survey_rows(
    recordings: Iterable[Dict[str, Any]],
    file_is_here: Callable[[Dict[str, Any]], bool],
) -> Survey:
    """What is missing, counted from rows.

    Args:
        recordings: Audio file rows, as ``get_all_audio_files`` returns them.
        file_is_here: Whether that Recording's file is on this machine.

    Returns:
        One Gap per kind of missing data, in the order a report shows them.
    """
    missing_duration = 0
    missing_created = 0
    missing_file = 0
    missing_offset = 0

    for recording in recordings:
        if recording.get("deleted_at"):
            continue
        if not file_is_here(recording):
            missing_file += 1
        if not recording.get("duration_seconds"):
            missing_duration += 1
        if not recording.get("file_created_at"):
            missing_created += 1
        if recording.get("imported_at_offset") is None:
            missing_offset += 1

    return Survey(gaps=[
        Gap("duration", "Recordings with no length recorded", missing_duration),
        Gap("file_created_at", "Recordings with no creation date", missing_created),
        Gap(
            "absent_file", "Recordings whose file is not on this computer",
            missing_file, calculable=False,
            note="download them first, or run this on the device that has them",
        ),
        Gap(
            "timezone", "Recordings with no timezone recorded",
            missing_offset, calculable=False,
            note="it cannot be derived from the file, and guessing it would state "
                 "something false about where the Recording was made",
        ),
    ])


def survey(db, config) -> Survey:
    """What is missing, without changing anything.

    Cheap: it reads the database and checks which files exist, but it does not
    open any audio.
    """
    audio_dir_str = config.get_audiofile_directory()
    audio_dir = Path(audio_dir_str) if audio_dir_str else None

    return survey_rows(
        db.get_all_audio_files(),
        lambda recording: audio_path(audio_dir, recording) is not None,
    )


def calculate_missing_data(
    db,
    config,
    *,
    durations: bool = True,
    file_dates: bool = True,
    limit: Optional[int] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> Report:
    """Calculate what can be calculated, and report what happened.

    Args:
        db: The database.
        config: This machine's configuration, for the audio directory.
        durations: Read the length of Recordings that have none.
        file_dates: Read the creation date of Recordings that have none, from
            the filesystem or the file name (the same rule the importer uses).
        limit: At most this many Recordings, for a run that should not take all
            night.
        progress: Called with a line of text as each item is done, so an
            interface can show what is happening.

    Returns:
        What was calculated and what could not be.
    """
    from src.core.audiofile_manager import AudioFileManager
    from src.core.waveform import get_audio_duration

    report = Report()
    audio_dir_str = config.get_audiofile_directory()
    audio_dir = Path(audio_dir_str) if audio_dir_str else None

    def say(line: str) -> None:
        logger.info(line)
        if progress:
            progress(line)

    if audio_dir is None and (durations or file_dates):
        report.details.append(
            "No audio directory is configured, so nothing could be read off the files."
        )
        durations = file_dates = False

    if durations or file_dates:
        manager = AudioFileManager(str(audio_dir)) if audio_dir else None
        done = 0
        for recording in db.get_all_audio_files():
            if recording.get("deleted_at"):
                continue
            if limit is not None and done >= limit:
                break
            needs_duration = durations and not recording.get("duration_seconds")
            needs_date = file_dates and not recording.get("file_created_at")
            if not (needs_duration or needs_date):
                continue

            here = audio_path(audio_dir, recording)
            if here is None:
                report.failed["absent_file"] = report.failed.get("absent_file", 0) + 1
                continue

            did_something = False

            if needs_duration:
                seconds = get_audio_duration(here)
                if seconds:
                    db.update_audio_file_duration(recording["id"], int(round(seconds)))
                    report.calculated["duration"] = report.calculated.get("duration", 0) + 1
                    did_something = True
                    say(f"{recording.get('filename', '')}: {int(round(seconds))} seconds")
                else:
                    report.failed["duration"] = report.failed.get("duration", 0) + 1

            if needs_date and manager is not None:
                # The date a recorder wrote into the name is in the recorded
                # filename; the name on disk may differ (a collision suffix).
                made = manager.get_file_created_at(here, recording.get("filename"))
                if made is not None:
                    db.update_audio_file_created_at(recording["id"], int(made.timestamp()))
                    report.calculated["file_created_at"] = (
                        report.calculated.get("file_created_at", 0) + 1
                    )
                    did_something = True
                    say(f"{recording.get('filename', '')}: made {made:%Y-%m-%d %H:%M}")
                else:
                    report.failed["file_created_at"] = report.failed.get("file_created_at", 0) + 1

            if did_something:
                done += 1

    return report

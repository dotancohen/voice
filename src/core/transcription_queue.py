"""The recordings waiting to be transcribed on this computer, and what the
finished ones cost.

Transcribing locally takes the whole machine: the model wants a gigabyte of
memory and every core, so two at once are slower than two in turn. So there is
a queue, and it is **one queue for the whole installation** rather than one per
interface: the file at ``<config_dir>/transcription_queue.json`` holds the order
and says which recording is being worked on, so the GUI, the TUI, the CLI and
the Web API all show the same queue and can all reorder it. The file is local to
this machine and is never synced — what this computer is busy with is not a fact
about the user's notes.

What a finished transcription cost is **not** kept here. It is in the
transcription's own ``service_response`` in the database, which means it survives
restarts, reaches the other devices, and is the same record the note screen
shows. This module only reads it back and does arithmetic with it: how fast this
computer transcribes is what says how long the recordings still waiting will
take.

``VoiceAndroid``'s ``transcription/TranscriptionWork.kt`` and
``transcription/JobQueue.kt`` are the same logic in the same words, so a queue
read on the phone and a queue read here say the same things.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# The name of the queue file inside the configuration directory. Local to this
# machine: never synced, never in the database.
QUEUE_FILE = "transcription_queue.json"

# How long a claim is believed. A process that claimed a recording and then died
# (a crash, a kill, a power cut) would otherwise block the queue for ever; after
# this long with no sign of life the claim is ignored and the recording is
# available again.
CLAIM_STALE_SECONDS = 15 * 60


@dataclass
class Waiting:
    """One recording waiting to be transcribed."""

    audio_file_id: str
    filename: str
    # The provider configuration the work will run with, as transcribe_async
    # takes it: which service, which model, which language.
    provider: Dict[str, Any] = field(default_factory=dict)
    queued_at: float = field(default_factory=time.time)
    audio_seconds: Optional[float] = None

    def as_json(self) -> Dict[str, Any]:
        return {
            "audio_file_id": self.audio_file_id,
            "filename": self.filename,
            "provider": self.provider,
            "queued_at": self.queued_at,
            "audio_seconds": self.audio_seconds,
        }

    @staticmethod
    def of_json(data: Dict[str, Any]) -> "Waiting":
        return Waiting(
            audio_file_id=data["audio_file_id"],
            filename=data.get("filename", ""),
            provider=data.get("provider") or {},
            queued_at=data.get("queued_at") or time.time(),
            audio_seconds=data.get("audio_seconds"),
        )


@dataclass
class Work:
    """What one transcription cost, read back from its ``service_response``.

    Every field is optional: a transcription made by an older version of the
    application, or by a cloud service, recorded less than this one does. The
    keys are the ones the phone writes, so both applications read each other's.
    """

    audio_seconds: Optional[float] = None
    clock_seconds: Optional[float] = None
    cpu_seconds: Optional[float] = None
    cores_busy: Optional[float] = None
    peak_memory_bytes: Optional[int] = None
    speed_vs_realtime: Optional[float] = None
    model: Optional[str] = None

    @property
    def seconds_per_audio_second(self) -> Optional[float]:
        """Seconds of work per second of audio: the number that predicts a wait."""
        if not self.audio_seconds or not self.clock_seconds:
            return None
        if self.audio_seconds <= 0 or self.clock_seconds <= 0:
            return None
        return self.clock_seconds / self.audio_seconds


def work_of(service_response: Optional[str]) -> Work:
    """Read what was recorded about a transcription, or nothing where it was not."""
    if not service_response:
        return Work()
    try:
        data = json.loads(service_response)
    except (ValueError, TypeError):
        return Work()
    if not isinstance(data, dict):
        return Work()
    performance = data.get("performance") if isinstance(data.get("performance"), dict) else {}

    def number(source: Dict[str, Any], key: str) -> Optional[float]:
        value = source.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return None

    memory = performance.get("peak_native_heap_bytes") or performance.get("peak_memory_bytes")
    return Work(
        audio_seconds=number(data, "duration_seconds"),
        # The whole job where it was recorded, the transcribing call otherwise:
        # what the user waits for is the whole job.
        clock_seconds=(
            number(performance, "total_seconds")
            or number(performance, "elapsed_seconds")
            or number(data, "elapsed_time")
        ),
        cpu_seconds=number(performance, "cpu_seconds"),
        cores_busy=number(performance, "cpu_cores_busy"),
        peak_memory_bytes=int(memory) if isinstance(memory, (int, float)) and memory > 0 else None,
        speed_vs_realtime=number(performance, "speed_vs_realtime"),
        model=performance.get("model") or data.get("model") or None,
    )


def rate_from(finished: List[Work], model: Optional[str] = None) -> Optional[float]:
    """Seconds of work per second of audio, from what this computer has done.

    Readings for the same model are used where there are any, because a larger
    model is several times slower; otherwise every reading is used. The median is
    taken rather than the mean, so one transcription that ran while the machine
    was busy with something else does not move the estimate for everything
    behind it.

    None when nothing has finished here yet, which is the honest answer: the
    first transcription on a new machine has nothing to go on.
    """
    for_model = [w for w in finished if model and w.model == model]
    pool = sorted(
        rate
        for rate in ((w.seconds_per_audio_second for w in (for_model or finished)))
        if rate
    )
    if not pool:
        return None
    return pool[len(pool) // 2]


def wait_seconds(
    audio_seconds_ahead: Optional[float],
    own_audio_seconds: Optional[float],
    rate: Optional[float],
) -> Optional[float]:
    """How long until a recording is transcribed, in seconds.

    None when the rate or a length is not known, because a made-up number here
    is worse than none: the user plans around it.
    """
    if not rate or rate <= 0:
        return None
    if audio_seconds_ahead is None or own_audio_seconds is None:
        return None
    if audio_seconds_ahead < 0 or own_audio_seconds < 0:
        return None
    return (audio_seconds_ahead + own_audio_seconds) * rate


def in_words(seconds: Optional[float]) -> Optional[str]:
    """A wait as a person says it: "about 4 minutes", "about 1 hour 10 minutes"."""
    if not seconds or seconds <= 0:
        return None
    whole = int(round(seconds))
    if whole < 90:
        return "about a minute"
    if whole < 3600:
        return f"about {int(round(whole / 60))} minutes"
    hours = whole // 3600
    minutes = int(round((whole % 3600) / 60))
    hour_word = "hour" if hours == 1 else "hours"
    if minutes == 0:
        return f"about {hours} {hour_word}"
    return f"about {hours} {hour_word} {minutes} minutes"


class Queue:
    """The order recordings are transcribed in, shared by every interface.

    A small JSON file, rewritten atomically: every change is read-modify-write,
    so two interfaces adding at the same moment cannot lose one another's work.
    The file is not a log — a recording leaves it the moment its transcription
    starts, because from then on the database's "Pending..." row is the record.
    """

    def __init__(self, config_dir: Path | str):
        self.path = Path(config_dir) / QUEUE_FILE

    # ---------------------------------------------------------------- reading

    def _read(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {"version": 1, "jobs": [], "claim": None}
        except (ValueError, OSError) as e:
            # A half-written or hand-edited file must not stop transcription.
            logger.warning(f"The transcription queue file could not be read ({e}); starting empty")
            return {"version": 1, "jobs": [], "claim": None}
        if not isinstance(data, dict):
            return {"version": 1, "jobs": [], "claim": None}
        data.setdefault("jobs", [])
        data.setdefault("claim", None)
        return data

    def _write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Written beside the real file and moved over it, so a crash never
        # leaves a half-written queue.
        handle = tempfile.NamedTemporaryFile(
            "w", dir=str(self.path.parent), prefix=".queue-", suffix=".part",
            delete=False, encoding="utf-8",
        )
        try:
            json.dump(data, handle, ensure_ascii=False, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, self.path)

    def list(self) -> List[Waiting]:
        """What is waiting, in the order it will be worked."""
        return [Waiting.of_json(job) for job in self._read().get("jobs", [])]

    def claim_now(self) -> Optional[Dict[str, Any]]:
        """The recording being transcribed now, or None.

        A claim older than :data:`CLAIM_STALE_SECONDS` is ignored: the process
        that made it is gone, and the queue must not be blocked by a crash.
        """
        claim = self._read().get("claim")
        if not claim:
            return None
        since = claim.get("since") or 0
        if time.time() - since > CLAIM_STALE_SECONDS:
            return None
        return claim

    # ---------------------------------------------------------------- writing

    def add(self, job: Waiting) -> bool:
        """Put a recording at the back of the queue.

        False when that recording is already waiting or is being transcribed
        now: asking twice is a slip, and doing it twice costs the user a wait
        for nothing.
        """
        data = self._read()
        if any(j.get("audio_file_id") == job.audio_file_id for j in data["jobs"]):
            return False
        claim = data.get("claim") or {}
        if claim.get("audio_file_id") == job.audio_file_id:
            return False
        data["jobs"].append(job.as_json())
        self._write(data)
        return True

    def do_next(self, audio_file_id: str) -> bool:
        """Move a waiting recording to the front, so it is transcribed next.

        The recording being worked on is not interrupted: it is minutes into
        work that would have to start again, which would cost more than the
        wait. "Next" means next after that one.
        """
        data = self._read()
        index = next(
            (i for i, j in enumerate(data["jobs"]) if j.get("audio_file_id") == audio_file_id),
            None,
        )
        if index is None or index == 0:
            return False
        data["jobs"].insert(0, data["jobs"].pop(index))
        self._write(data)
        return True

    def remove(self, audio_file_id: str) -> bool:
        """Take a waiting recording out of the queue."""
        data = self._read()
        before = len(data["jobs"])
        data["jobs"] = [j for j in data["jobs"] if j.get("audio_file_id") != audio_file_id]
        if len(data["jobs"]) == before:
            return False
        self._write(data)
        return True

    def clear(self) -> int:
        """Forget everything waiting. Returns how many were waiting.

        The recording being transcribed now is not affected: stopping that one
        is the transcriber's business, not the queue's.
        """
        data = self._read()
        count = len(data["jobs"])
        data["jobs"] = []
        self._write(data)
        return count

    def take_next(self, pid: Optional[int] = None) -> Optional[Waiting]:
        """Claim the next recording for this process, or None.

        Nothing is taken while another process holds a live claim, because the
        model wants the whole machine.
        """
        data = self._read()
        claim = data.get("claim")
        if claim and time.time() - (claim.get("since") or 0) <= CLAIM_STALE_SECONDS:
            return None
        if not data["jobs"]:
            if claim:
                data["claim"] = None
                self._write(data)
            return None
        job = Waiting.of_json(data["jobs"].pop(0))
        data["claim"] = {
            "audio_file_id": job.audio_file_id,
            "filename": job.filename,
            "provider": job.provider,
            "audio_seconds": job.audio_seconds,
            "pid": pid if pid is not None else os.getpid(),
            "since": time.time(),
        }
        self._write(data)
        return job

    def release(self, audio_file_id: str) -> None:
        """Say that a recording is no longer being worked on."""
        data = self._read()
        claim = data.get("claim") or {}
        if claim.get("audio_file_id") == audio_file_id:
            data["claim"] = None
            self._write(data)

    def audio_seconds_ahead(self, audio_file_id: str) -> Optional[float]:
        """How much audio is in front of a waiting recording, in seconds.

        The recording being transcribed now counts: the user waits for it too.
        None when any recording in front has no length recorded, so that no
        estimate is offered rather than a wrong one.
        """
        data = self._read()
        claim = data.get("claim") or {}
        total = 0.0
        if claim.get("audio_file_id") and claim.get("audio_file_id") != audio_file_id:
            running = claim.get("audio_seconds")
            if running is None:
                return None
            total += float(running)
        for job in data["jobs"]:
            if job.get("audio_file_id") == audio_file_id:
                return total
            seconds = job.get("audio_seconds")
            if seconds is None:
                return None
            total += float(seconds)
        return None


# ---------------------------------------------------------------- the view


@dataclass
class Row:
    """One recording in the queue view.

    The same shape whether it is waiting, being worked on, or finished; what
    differs is which fields are filled in. ``note_line`` is what makes a row
    mean something to a person: a filename says little, the note says what it is.
    """

    audio_file_id: str
    filename: str
    state: str  # "waiting", "processing", "done", "failed"
    model: Optional[str] = None
    language: Optional[str] = None
    note_id: Optional[str] = None
    note_line: Optional[str] = None
    audio_seconds: Optional[float] = None
    position: Optional[int] = None
    wait_seconds: Optional[float] = None
    work: Optional[Work] = None
    characters: Optional[int] = None
    outcome: Optional[str] = None
    finished_at: Optional[int] = None
    transcription_id: Optional[str] = None


@dataclass
class View:
    """Everything in the queue, in three groups.

    Waiting first, then what is being worked on, then what is done: reading down
    is reading forwards in time. Within each group the newest is first, as in
    every list of notes, so the order the waiting recordings will really be
    reached in is on the row itself (:attr:`Row.position`).
    """

    waiting: List[Row] = field(default_factory=list)
    processing: List[Row] = field(default_factory=list)
    completed: List[Row] = field(default_factory=list)
    rate: Optional[float] = None

    @property
    def anything(self) -> bool:
        return bool(self.waiting or self.processing or self.completed)


def _note_of(db, audio_file_id: str) -> tuple[Optional[str], Optional[str]]:
    """The note a recording is in, and that note's first line."""
    try:
        note_ids = db.get_notes_for_audio_file(audio_file_id)
    except Exception as e:
        logger.debug(f"No note found for {audio_file_id[:8]}: {e}")
        return None, None
    if not note_ids:
        return None, None
    note_id = note_ids[0]
    try:
        note = db.get_note(note_id)
    except Exception:
        note = None
    line = None
    if note:
        content = (note.get("content") or "").strip()
        line = content.splitlines()[0][:80] if content else "(no text)"
    return note_id, line


def view(db, config, service: Optional[str] = None, completed_shown: int = 40) -> View:
    """The whole queue, for any interface to show.

    Args:
        db: The database.
        config: This machine's configuration, for the queue file's directory.
        service: Only this transcription service's finished work, or every
            service when None.
        completed_shown: How many finished transcriptions to show. A queue view
            is a screenful of recent work, not a history.
    """
    queue = Queue(config.config_dir)

    finished_rows = []
    try:
        finished_rows = db.get_recent_transcriptions(service, completed_shown)
    except Exception as e:
        logger.warning(f"Could not read the finished transcriptions: {e}")

    completed: List[Row] = []
    works: List[Work] = []
    for row in finished_rows:
        content = row.get("content") or ""
        if content.startswith("Pending..."):
            continue  # still waiting or being worked on; not finished work
        work = work_of(row.get("service_response"))
        works.append(work)
        note_id, note_line = _note_of(db, row["audio_file_id"])
        audio = db.get_audio_file(row["audio_file_id"]) or {}
        failed = content.startswith("Error:")
        completed.append(Row(
            audio_file_id=row["audio_file_id"],
            filename=audio.get("filename") or row["audio_file_id"][:8],
            state="failed" if failed else "done",
            model=work.model,
            note_id=note_id,
            note_line=note_line,
            audio_seconds=work.audio_seconds or (audio.get("duration_seconds") or None),
            work=work,
            characters=len(content),
            outcome=content[:200] if failed else None,
            finished_at=row.get("modified_at") or row.get("created_at"),
            transcription_id=row.get("id"),
        ))

    claim = queue.claim_now()
    waiting_jobs = queue.list()
    rate = rate_from(
        works,
        (claim or {}).get("provider", {}).get("model")
        or (waiting_jobs[0].provider.get("model") if waiting_jobs else None),
    )

    processing: List[Row] = []
    if claim:
        note_id, note_line = _note_of(db, claim["audio_file_id"])
        audio = db.get_audio_file(claim["audio_file_id"]) or {}
        since = claim.get("since") or time.time()
        processing.append(Row(
            audio_file_id=claim["audio_file_id"],
            filename=claim.get("filename") or audio.get("filename") or "",
            state="processing",
            model=(claim.get("provider") or {}).get("model"),
            language=(claim.get("provider") or {}).get("language"),
            note_id=note_id,
            note_line=note_line,
            audio_seconds=claim.get("audio_seconds") or (audio.get("duration_seconds") or None),
            outcome=f"Working for {in_words(time.time() - since) or 'less than a minute'}",
        ))

    waiting: List[Row] = []
    for position, job in enumerate(waiting_jobs, start=1):
        note_id, note_line = _note_of(db, job.audio_file_id)
        audio = db.get_audio_file(job.audio_file_id) or {}
        own = job.audio_seconds or (audio.get("duration_seconds") or None)
        waiting.append(Row(
            audio_file_id=job.audio_file_id,
            filename=job.filename or audio.get("filename") or "",
            state="waiting",
            model=job.provider.get("model"),
            language=job.provider.get("language"),
            note_id=note_id,
            note_line=note_line,
            audio_seconds=own,
            position=position,
            wait_seconds=wait_seconds(queue.audio_seconds_ahead(job.audio_file_id), own, rate),
        ))

    # Newest first within each group, as the notes list shows notes.
    return View(
        waiting=list(reversed(waiting)),
        processing=processing,
        completed=completed,
        rate=rate,
    )


def as_json(view: View) -> Dict[str, Any]:
    """The view as plain data: what the Web API returns and the CLI prints.

    One shape for every interface, so a script written against the CLI's JSON
    reads the Web API's too.
    """
    def row_as_json(row: Row) -> Dict[str, Any]:
        work = row.work
        return {
            "audio_file_id": row.audio_file_id,
            "filename": row.filename,
            "state": row.state,
            "model": row.model,
            "language": row.language,
            "note_id": row.note_id,
            "note_line": row.note_line,
            "audio_seconds": row.audio_seconds,
            "position": row.position,
            "wait_seconds": row.wait_seconds,
            "wait": in_words(row.wait_seconds),
            "characters": row.characters,
            "outcome": row.outcome,
            "finished_at": row.finished_at,
            "transcription_id": row.transcription_id,
            "work": None if work is None else {
                "audio_seconds": work.audio_seconds,
                "clock_seconds": work.clock_seconds,
                "cpu_seconds": work.cpu_seconds,
                "cores_busy": work.cores_busy,
                "peak_memory_bytes": work.peak_memory_bytes,
                "speed_vs_realtime": work.speed_vs_realtime,
                "model": work.model,
            },
        }

    return {
        "waiting": [row_as_json(r) for r in view.waiting],
        "processing": [row_as_json(r) for r in view.processing],
        "completed": [row_as_json(r) for r in view.completed],
        "rate": view.rate,
    }


def enqueue(db, config, audio_file_id: str, provider: Dict[str, Any]) -> Optional[str]:
    """Put a recording in the queue. Returns a reason when it cannot be.

    Nothing is transcribed by this call: :func:`run_next` does the work, which is
    what keeps it to one recording at a time across every interface.
    """
    audio = db.get_audio_file(audio_file_id)
    if not audio:
        return "There is no such recording"
    if audio.get("deleted_at"):
        return "That recording is in the trash"
    job = Waiting(
        audio_file_id=audio_file_id,
        filename=audio.get("filename") or "",
        provider=provider,
        audio_seconds=audio.get("duration_seconds") or None,
    )
    if not Queue(config.config_dir).add(job):
        return "That recording is already in the queue"
    return None


def run_next(
    db,
    config,
    service,
    progress: Optional[Callable[[str], None]] = None,
    on_complete: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    on_error: Optional[Callable[[str, str], None]] = None,
) -> Optional[str]:
    """Transcribe the next recording in the queue, and wait for it to finish.

    Returns its transcription id, or None when nothing was waiting or another
    process is already transcribing. One recording at a time is the whole point:
    the local model wants every core, so two at once are slower than two in turn.

    Args:
        db: The database.
        config: This machine's configuration.
        service: A ``TranscriptionService``.
        progress: Called with a line of text as the work moves on.
        on_complete: Passed to the transcription service, so an interface can
            refresh itself the moment a transcription lands.
        on_error: Likewise for a transcription that failed.
    """
    queue = Queue(config.config_dir)
    job = queue.take_next()
    if job is None:
        return None

    def say(line: str) -> None:
        logger.info(line)
        if progress:
            progress(line)

    say(f"Transcribing {job.filename}")
    finished: Dict[str, Any] = {}

    def landed(transcription_id: str, result: Dict[str, Any]) -> None:
        finished["id"] = transcription_id
        say(f"{job.filename}: done")
        if on_complete:
            on_complete(transcription_id, result)

    def failed(transcription_id: str, message: str) -> None:
        finished["id"] = transcription_id
        say(f"{job.filename}: {message}")
        if on_error:
            on_error(transcription_id, message)

    try:
        transcription_id = service.transcribe_async(
            job.audio_file_id, job.provider, on_complete=landed, on_error=failed
        )
        # The service does the work in a thread of its own; this waits for it,
        # because the queue's promise is one at a time.
        service.wait_for(transcription_id)
        return transcription_id
    except Exception as e:
        logger.error(f"Could not transcribe {job.audio_file_id[:8]}: {e}")
        say(f"{job.filename}: {e}")
        return None
    finally:
        queue.release(job.audio_file_id)


def drain(
    db,
    config,
    service,
    limit: Optional[int] = None,
    progress: Optional[Callable[[str], None]] = None,
    on_complete: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    on_error: Optional[Callable[[str, str], None]] = None,
) -> int:
    """Transcribe everything in the queue, one at a time. Returns how many ran."""
    done = 0
    while limit is None or done < limit:
        ran = run_next(
            db, config, service,
            progress=progress, on_complete=on_complete, on_error=on_error,
        )
        if ran is None:
            break
        done += 1
    return done

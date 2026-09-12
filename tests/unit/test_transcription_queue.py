"""The recordings waiting to be transcribed here, and what the finished ones cost.

Transcribing locally takes the whole machine, so there is one queue for the whole
installation: a file every interface reads and writes. These tests cover what the
user can see and do — the order, moving one recording to the front, the estimate
of how long the waiting will take — and the rule that an estimate is never
invented: where a length or a rate is missing, no number is offered.

The wording and the arithmetic must match ``VoiceAndroid``'s
``transcription/TranscriptionWork.kt`` and ``transcription/JobQueue.kt``, so that
a queue read on the phone and a queue read here say the same things.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import transcription_queue as queue_module
from core.database import Database


class FakeConfig:
    """Just enough configuration: where the queue file goes."""

    def __init__(self, config_dir: Path, audio_dir: Path | None = None):
        self.config_dir = Path(config_dir)
        self._audio_dir = str(audio_dir) if audio_dir else None

    def get_audiofile_directory(self):
        return self._audio_dir


@pytest.fixture
def db():
    return Database(":memory:")


@pytest.fixture
def config(tmp_path):
    return FakeConfig(tmp_path)


def waiting(audio_file_id: str, seconds: float | None = 60.0, model: str = "small") -> queue_module.Waiting:
    return queue_module.Waiting(
        audio_file_id=audio_file_id,
        filename=f"הקלטה-{audio_file_id}.opus",
        provider={"provider_id": "local_whisper", "model": model},
        audio_seconds=seconds,
    )


def response(
    audio: float | None = 120.0,
    total: float | None = 300.0,
    cpu: float | None = 1100.0,
    cores: float | None = 3.7,
    memory: int | None = 1_400_000_000,
    speed: float | None = 0.4,
    model: str | None = "small",
) -> str:
    performance = {}
    if total is not None:
        performance["total_seconds"] = total
    if cpu is not None:
        performance["cpu_seconds"] = cpu
    if cores is not None:
        performance["cpu_cores_busy"] = cores
    if memory is not None:
        performance["peak_native_heap_bytes"] = memory
    if speed is not None:
        performance["speed_vs_realtime"] = speed
    if model is not None:
        performance["model"] = model
    body = {"performance": performance}
    if audio is not None:
        body["duration_seconds"] = audio
    return json.dumps(body)


class TestReadingWhatItCost:
    """What a transcription cost, read back from its service response."""

    def test_every_measure_is_read(self):
        work = queue_module.work_of(response())
        assert work.audio_seconds == 120.0
        assert work.clock_seconds == 300.0
        assert work.cpu_seconds == 1100.0
        assert work.cores_busy == 3.7
        assert work.peak_memory_bytes == 1_400_000_000
        assert work.speed_vs_realtime == 0.4
        assert work.model == "small"

    def test_an_older_row_with_only_an_elapsed_time_is_still_read(self):
        work = queue_module.work_of('{"duration_seconds": 60, "elapsed_time": 90.5}')
        assert work.clock_seconds == 90.5
        assert work.audio_seconds == 60.0

    @pytest.mark.parametrize("nothing", [None, "", "not json", "[]", "{}"])
    def test_nothing_recorded_reads_as_nothing_known(self, nothing):
        work = queue_module.work_of(nothing)
        assert work.clock_seconds is None
        assert work.audio_seconds is None
        assert work.seconds_per_audio_second is None

    def test_the_rate_is_work_per_second_of_audio(self):
        work = queue_module.work_of(response(audio=120.0, total=300.0))
        assert work.seconds_per_audio_second == pytest.approx(2.5)

    def test_a_recording_of_no_length_gives_no_rate(self):
        assert queue_module.work_of(response(audio=0.0)).seconds_per_audio_second is None


class TestTheRate:
    """How fast this machine transcribes, from what it has already done."""

    def test_the_median_of_what_this_machine_did(self):
        finished = [
            queue_module.Work(audio_seconds=100, clock_seconds=100),
            queue_module.Work(audio_seconds=100, clock_seconds=200),
            queue_module.Work(audio_seconds=100, clock_seconds=900),
        ]
        assert queue_module.rate_from(finished) == pytest.approx(2.0)

    def test_readings_for_the_model_in_use_are_preferred(self):
        finished = [
            queue_module.Work(audio_seconds=100, clock_seconds=100, model="tiny"),
            queue_module.Work(audio_seconds=100, clock_seconds=600, model="large-v3"),
        ]
        assert queue_module.rate_from(finished, "large-v3") == pytest.approx(6.0)
        assert queue_module.rate_from(finished, "tiny") == pytest.approx(1.0)

    def test_a_model_never_used_here_falls_back_to_every_reading(self):
        finished = [queue_module.Work(audio_seconds=100, clock_seconds=200, model="tiny")]
        assert queue_module.rate_from(finished, "medium") == pytest.approx(2.0)

    def test_nothing_finished_yet_gives_no_rate(self):
        assert queue_module.rate_from([]) is None
        assert queue_module.rate_from([queue_module.Work()]) is None


class TestTheWait:
    """How long until a recording is transcribed."""

    def test_everything_in_front_and_the_recording_itself(self):
        assert queue_module.wait_seconds(480.0, 120.0, 2.5) == pytest.approx(1500.0)

    def test_first_in_the_queue_waits_only_for_itself(self):
        assert queue_module.wait_seconds(0.0, 120.0, 2.5) == pytest.approx(300.0)

    def test_without_a_rate_or_a_length_no_estimate_is_offered(self):
        assert queue_module.wait_seconds(480.0, 120.0, None) is None
        assert queue_module.wait_seconds(480.0, None, 2.5) is None
        assert queue_module.wait_seconds(None, 120.0, 2.5) is None
        assert queue_module.wait_seconds(480.0, 120.0, 0) is None

    def test_a_wait_is_said_in_units_a_person_uses(self):
        assert queue_module.in_words(45) == "about a minute"
        assert queue_module.in_words(89) == "about a minute"
        assert queue_module.in_words(100) == "about 2 minutes"
        assert queue_module.in_words(1500) == "about 25 minutes"
        assert queue_module.in_words(3600) == "about 1 hour"
        assert queue_module.in_words(4200) == "about 1 hour 10 minutes"
        assert queue_module.in_words(9000) == "about 2 hours 30 minutes"
        assert queue_module.in_words(None) is None
        assert queue_module.in_words(0) is None


class TestTheQueueFile:
    """The order recordings are transcribed in, shared by every interface."""

    def test_a_new_queue_holds_nothing(self, config):
        queue = queue_module.Queue(config.config_dir)
        assert queue.list() == []
        assert queue.claim_now() is None
        assert queue.take_next() is None

    def test_recordings_are_worked_in_the_order_they_were_asked_for(self, config):
        queue = queue_module.Queue(config.config_dir)
        for name in "abc":
            queue.add(waiting(name))

        assert [job.audio_file_id for job in queue.list()] == ["a", "b", "c"]
        assert queue.take_next().audio_file_id == "a"
        queue.release("a")
        assert queue.take_next().audio_file_id == "b"

    def test_another_interface_sees_the_same_queue(self, config):
        # Two Queue objects over one file: the GUI and the CLI, in different
        # processes, are exactly this.
        one = queue_module.Queue(config.config_dir)
        other = queue_module.Queue(config.config_dir)
        one.add(waiting("a"))
        assert [job.audio_file_id for job in other.list()] == ["a"]
        other.add(waiting("b"))
        assert [job.audio_file_id for job in one.list()] == ["a", "b"]

    def test_the_same_recording_is_not_queued_twice(self, config):
        queue = queue_module.Queue(config.config_dir)
        assert queue.add(waiting("a")) is True
        assert queue.add(waiting("a")) is False
        assert len(queue.list()) == 1

    def test_a_recording_being_worked_on_is_not_queued_again(self, config):
        queue = queue_module.Queue(config.config_dir)
        queue.add(waiting("a"))
        queue.take_next()
        assert queue.add(waiting("a")) is False

    def test_do_next_moves_a_recording_to_the_front(self, config):
        queue = queue_module.Queue(config.config_dir)
        for name in "abc":
            queue.add(waiting(name))

        assert queue.do_next("c") is True
        assert [job.audio_file_id for job in queue.list()] == ["c", "a", "b"]

    def test_do_next_on_the_one_already_first_changes_nothing(self, config):
        queue = queue_module.Queue(config.config_dir)
        queue.add(waiting("a"))
        queue.add(waiting("b"))
        assert queue.do_next("a") is False

    def test_do_next_on_a_recording_that_is_not_waiting_is_refused(self, config):
        queue = queue_module.Queue(config.config_dir)
        queue.add(waiting("a"))
        assert queue.do_next("never-queued") is False

    def test_a_waiting_recording_can_be_taken_out(self, config):
        queue = queue_module.Queue(config.config_dir)
        queue.add(waiting("a"))
        queue.add(waiting("b"))
        assert queue.remove("a") is True
        assert queue.remove("a") is False
        assert [job.audio_file_id for job in queue.list()] == ["b"]

    def test_clearing_leaves_nothing_waiting(self, config):
        queue = queue_module.Queue(config.config_dir)
        queue.add(waiting("a"))
        queue.add(waiting("b"))
        assert queue.clear() == 2
        assert queue.list() == []

    def test_nothing_is_taken_while_another_recording_is_being_worked_on(self, config):
        """One at a time: the model wants the whole machine."""
        queue = queue_module.Queue(config.config_dir)
        queue.add(waiting("a"))
        queue.add(waiting("b"))

        assert queue.take_next().audio_file_id == "a"
        assert queue.take_next() is None, "two at once are slower than two in turn"

        queue.release("a")
        assert queue.take_next().audio_file_id == "b"

    def test_a_claim_from_a_process_that_died_does_not_block_the_queue(self, config, monkeypatch):
        queue = queue_module.Queue(config.config_dir)
        queue.add(waiting("a"))
        queue.add(waiting("b"))
        queue.take_next()

        # Time passes; the process that claimed "a" never came back.
        real_time = queue_module.time.time
        monkeypatch.setattr(
            queue_module.time, "time",
            lambda: real_time() + queue_module.CLAIM_STALE_SECONDS + 1,
        )
        assert queue.claim_now() is None
        assert queue.take_next().audio_file_id == "b"

    def test_the_audio_in_front_decides_the_wait(self, config):
        queue = queue_module.Queue(config.config_dir)
        queue.add(waiting("a", seconds=120))
        queue.add(waiting("b", seconds=300))
        queue.add(waiting("c", seconds=60))

        assert queue.audio_seconds_ahead("a") == pytest.approx(0.0)
        assert queue.audio_seconds_ahead("b") == pytest.approx(120.0)
        assert queue.audio_seconds_ahead("c") == pytest.approx(420.0)

    def test_the_recording_being_worked_on_counts_towards_the_wait(self, config):
        queue = queue_module.Queue(config.config_dir)
        queue.add(waiting("a", seconds=120))
        queue.add(waiting("b", seconds=300))
        queue.take_next()  # "a" is being worked on

        assert queue.audio_seconds_ahead("b") == pytest.approx(120.0)

    def test_an_unknown_length_in_front_means_no_estimate_at_all(self, config):
        queue = queue_module.Queue(config.config_dir)
        queue.add(waiting("a", seconds=None))
        queue.add(waiting("b", seconds=300))

        assert queue.audio_seconds_ahead("a") == pytest.approx(0.0)
        assert queue.audio_seconds_ahead("b") is None

    def test_a_damaged_queue_file_does_not_stop_transcription(self, config):
        path = Path(config.config_dir) / queue_module.QUEUE_FILE
        path.write_text("{ this is not json", encoding="utf-8")
        queue = queue_module.Queue(config.config_dir)
        assert queue.list() == []
        assert queue.add(waiting("a")) is True
        assert [job.audio_file_id for job in queue.list()] == ["a"]


class TestTheView:
    """What every interface shows: waiting, processing, completed."""

    def _recording(self, db, name: str, seconds: int = 120) -> str:
        audio_id = db.create_audio_file(name)
        db.update_audio_file_duration(audio_id, seconds)
        note_id = db.create_note(f"פגישה על {name}")
        db.attach_to_note(note_id, audio_id, "audio_file")
        return audio_id

    def test_an_empty_installation_shows_nothing(self, db, config):
        view = queue_module.view(db, config)
        assert view.waiting == []
        assert view.processing == []
        assert view.completed == []
        assert view.anything is False

    def test_a_waiting_recording_says_where_it_is_and_which_note_it_is_in(self, db, config):
        audio_id = self._recording(db, "הקלטה.opus", seconds = 120)
        assert queue_module.enqueue(db, config, audio_id, {"provider_id": "local_whisper"}) is None

        view = queue_module.view(db, config)

        assert len(view.waiting) == 1
        row = view.waiting[0]
        assert row.state == "waiting"
        assert row.position == 1
        assert row.audio_seconds == 120
        assert row.note_line == "פגישה על הקלטה.opus"
        assert row.filename == "הקלטה.opus"

    def test_the_newest_waiting_recording_is_first_but_says_its_real_place(self, db, config):
        first = self._recording(db, "ראשון.opus")
        second = self._recording(db, "שני.opus")
        queue_module.enqueue(db, config, first, {"provider_id": "local_whisper"})
        queue_module.enqueue(db, config, second, {"provider_id": "local_whisper"})

        view = queue_module.view(db, config)

        assert [row.filename for row in view.waiting] == ["שני.opus", "ראשון.opus"]
        assert [row.position for row in view.waiting] == [2, 1], \
            "the list reads newest first; the position says what will really run next"

    def test_a_recording_being_worked_on_is_in_its_own_group(self, db, config):
        audio_id = self._recording(db, "הקלטה.opus")
        queue_module.enqueue(db, config, audio_id, {"provider_id": "local_whisper"})
        queue_module.Queue(config.config_dir).take_next()

        view = queue_module.view(db, config)

        assert view.waiting == []
        assert len(view.processing) == 1
        assert view.processing[0].state == "processing"
        assert view.processing[0].audio_file_id == audio_id

    def test_a_finished_transcription_shows_what_it_cost(self, db, config):
        audio_id = self._recording(db, "הקלטה.opus")
        db.create_transcription(
            audio_id, "שלום עולם", "local_whisper",
            service_response=response(audio=120.0, total=300.0, cpu=1100.0),
        )

        view = queue_module.view(db, config)

        assert len(view.completed) == 1
        row = view.completed[0]
        assert row.state == "done"
        assert row.characters == len("שלום עולם")
        assert row.work.clock_seconds == 300.0
        assert row.work.cpu_seconds == 1100.0
        assert row.work.peak_memory_bytes == 1_400_000_000
        assert row.note_line == "פגישה על הקלטה.opus"

    def test_a_transcription_that_failed_is_its_own_state(self, db, config):
        audio_id = self._recording(db, "הקלטה.opus")
        db.create_transcription(audio_id, "Error: the model file is missing", "local_whisper")

        view = queue_module.view(db, config)

        assert view.completed[0].state == "failed"
        assert "model file" in view.completed[0].outcome

    def test_a_pending_row_is_not_counted_as_finished_work(self, db, config):
        audio_id = self._recording(db, "הקלטה.opus")
        db.create_transcription(audio_id, "Pending... (2026-09-12 10:00:00)", "local_whisper")

        view = queue_module.view(db, config)

        assert view.completed == [], "it has not finished; it is waiting or being worked on"

    def test_the_rate_comes_from_the_finished_work(self, db, config):
        audio_id = self._recording(db, "הקלטה.opus")
        db.create_transcription(
            audio_id, "שלום", "local_whisper",
            service_response=response(audio=100.0, total=250.0, model="small"),
        )

        view = queue_module.view(db, config)

        assert view.rate == pytest.approx(2.5)

    def test_a_waiting_recording_is_told_how_long_it_will_take(self, db, config):
        done = self._recording(db, "נגמר.opus")
        db.create_transcription(
            done, "שלום", "local_whisper",
            service_response=response(audio=100.0, total=200.0, model="small"),
        )
        audio_id = self._recording(db, "ממתין.opus", seconds=60)
        queue_module.enqueue(
            db, config, audio_id, {"provider_id": "local_whisper", "model": "small"}
        )

        view = queue_module.view(db, config)

        # 60 seconds of audio at 2 seconds of work per second of audio
        assert view.waiting[0].wait_seconds == pytest.approx(120.0)

    def test_no_finished_work_means_no_estimate(self, db, config):
        audio_id = self._recording(db, "ממתין.opus")
        queue_module.enqueue(db, config, audio_id, {"provider_id": "local_whisper"})

        view = queue_module.view(db, config)

        assert view.rate is None
        assert view.waiting[0].wait_seconds is None


class TestEnqueueing:
    """Putting a recording in the queue."""

    def test_a_recording_that_does_not_exist_is_refused(self, db, config):
        problem = queue_module.enqueue(db, config, "0" * 32, {"provider_id": "local_whisper"})
        assert problem and "no such recording" in problem.lower()

    def test_a_recording_in_the_trash_is_refused(self, db, config):
        audio_id = db.create_audio_file("מחוק.opus")
        db.delete_audio_file(audio_id)
        problem = queue_module.enqueue(db, config, audio_id, {"provider_id": "local_whisper"})
        assert problem and "trash" in problem.lower()

    def test_the_same_recording_twice_is_refused(self, db, config):
        audio_id = db.create_audio_file("הקלטה.opus")
        assert queue_module.enqueue(db, config, audio_id, {"provider_id": "local_whisper"}) is None
        problem = queue_module.enqueue(db, config, audio_id, {"provider_id": "local_whisper"})
        assert problem and "already" in problem.lower()

    def test_the_length_is_taken_from_the_database(self, db, config):
        audio_id = db.create_audio_file("הקלטה.opus")
        db.update_audio_file_duration(audio_id, 300)
        queue_module.enqueue(db, config, audio_id, {"provider_id": "local_whisper"})

        job = queue_module.Queue(config.config_dir).list()[0]
        assert job.audio_seconds == 300


class TestTheJsonShape:
    """One shape for the CLI and the Web API."""

    def test_every_group_and_the_rate_are_in_it(self, db, config):
        audio_id = db.create_audio_file("הקלטה.opus")
        db.update_audio_file_duration(audio_id, 120)
        queue_module.enqueue(db, config, audio_id, {"provider_id": "local_whisper"})

        data = queue_module.as_json(queue_module.view(db, config))

        assert set(data) == {"waiting", "processing", "completed", "rate"}
        row = data["waiting"][0]
        assert row["audio_file_id"] == audio_id
        assert row["state"] == "waiting"
        assert row["position"] == 1
        assert "wait" in row, "the wait in words, for a reader who is not doing arithmetic"

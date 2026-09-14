"""The core's Database and SyncClient may be used and freed on any thread.

Python's garbage collector runs on whichever thread triggers it: a zeroconf
thread, a web server's, a worker's. Both classes were marked `unsendable`, and
one freed on another thread raised "is unsendable, but is being dropped on
another thread" and was never closed. The database is now behind a lock.
"""

from __future__ import annotations

import gc
import sys
import threading
from pathlib import Path

import voicecore


def unraisable_during(action) -> list:
    """Run `action` and return the exceptions Python could not raise meanwhile
    (an error while freeing an object is one)."""
    caught = []
    previous = sys.unraisablehook
    sys.unraisablehook = lambda report: caught.append(report.exc_value)
    try:
        action()
    finally:
        sys.unraisablehook = previous
    return caught


def on_another_thread(work) -> None:
    worker = threading.Thread(target=work)
    worker.start()
    worker.join(30)
    assert not worker.is_alive(), "the work on the other thread did not end"


def test_a_database_made_here_is_used_and_freed_on_another_thread(tmp_path: Path) -> None:
    box = {"db": voicecore.Database(str(tmp_path / "מחברת.db"))}
    note_id = box["db"].create_note("פתק שנכתב בחוט הראשי")

    def use_and_free() -> None:
        assert box["db"].get_note(note_id)["content"] == "פתק שנכתב בחוט הראשי"
        box["db"].create_note("פתק שנכתב בחוט אחר")
        del box["db"]

    assert unraisable_during(lambda: on_another_thread(use_and_free)) == []
    reopened = voicecore.Database(str(tmp_path / "מחברת.db"))
    assert sorted(n["content"] for n in reopened.get_all_notes()) == ["פתק שנכתב בחוט אחר", "פתק שנכתב בחוט הראשי"]
    reopened.close()


def test_a_database_in_a_reference_cycle_is_collected_on_another_thread(tmp_path: Path) -> None:
    """The case that failed the suite: a cycle holding the database, collected
    by a thread that did not make it."""

    def leave_a_cycle() -> None:
        holder = {"db": voicecore.Database(str(tmp_path / "מעגל.db"))}
        holder["self"] = holder

    gc.disable()
    try:
        leave_a_cycle()
        assert unraisable_during(lambda: on_another_thread(gc.collect)) == []
    finally:
        gc.enable()


def test_two_threads_write_to_one_database_and_every_note_is_kept(tmp_path: Path) -> None:
    db = voicecore.Database(str(tmp_path / "משותף.db"))

    def write(prefix: str) -> None:
        for i in range(50):
            db.create_note(f"{prefix} מספר {i}")

    workers = [threading.Thread(target=write, args=(name,)) for name in ("ראשון", "שני")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(60)
    assert not any(w.is_alive() for w in workers)
    contents = {n["content"] for n in db.get_all_notes()}
    assert len(contents) == 100
    assert "ראשון מספר 49" in contents and "שני מספר 0" in contents
    db.close()


def test_a_closed_database_says_so_on_any_thread(tmp_path: Path) -> None:
    db = voicecore.Database(str(tmp_path / "סגור.db"))
    db.close()
    errors = []

    def use() -> None:
        try:
            db.create_note("לא ייכתב")
        except Exception as e:  # noqa: BLE001 - the message is what is checked
            errors.append(str(e))

    on_another_thread(use)
    assert errors == ["Database has been closed"]


def test_a_sync_client_made_here_is_freed_on_another_thread(test_config) -> None:
    box = {"client": voicecore.SyncClient(str(test_config.get_config_dir()))}

    def free() -> None:
        del box["client"]

    assert unraisable_during(lambda: on_another_thread(free)) == []

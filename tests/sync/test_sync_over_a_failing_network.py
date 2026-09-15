"""Sync and recording transfers over a network that fails the way real ones do.

Phones move between wifi and mobile data, lose signal in lifts and car parks,
and sit behind proxies that answer errors. Every test here puts a
`FaultyLink` between a device and its device and checks three things: the
operation fails or succeeds as it should, it ends in bounded time, and no
data is lost, duplicated or half-written. A later operation over a working
link completes what the failed one did not.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable, Generator, Tuple

import pytest
from voicecore import SyncClient

from core.database import set_this_device_id
from tests.faulty_network import FaultyLink

from .conftest import DEVICE_A_ID, DEVICE_B_ID, SyncNode, create_sync_node, start_sync_server
from .test_sync_files import give_recording, local_path

MIB = 1024 * 1024


@pytest.fixture
def linked(tmp_path: Path) -> Generator[Tuple[SyncNode, SyncNode, FaultyLink], None, None]:
    """A and B, B listening, and A reaching B only through a faulty link."""
    node_a = create_sync_node("NodeA", DEVICE_A_ID, tmp_path)
    node_b = create_sync_node("NodeB", DEVICE_B_ID, tmp_path)
    for node in (node_a, node_b):
        audio_dir = node.config_dir / "audio"
        audio_dir.mkdir()
        node.config.set_audiofile_directory(str(audio_dir))
    start_sync_server(node_b)
    assert node_b.wait_for_server()
    link = FaultyLink(node_b.port)
    node_a.config.add_device(node_b.device_id_hex, node_b.name, link.url)
    yield node_a, node_b, link
    link.stop()
    node_b.stop_server()
    node_a.db.close()
    node_b.db.close()


def client_of(node: SyncNode) -> SyncClient:
    set_this_device_id(node.device_id)
    return SyncClient(str(node.config_dir))


def within(seconds: float, operation: Callable):
    """Run the operation; fail the test if it has not ended in `seconds`.
    Returns (its result, the seconds it took)."""
    box = {}

    def run():
        try:
            box["value"] = operation()
        except BaseException as e:  # noqa: BLE001 - handed back to the test
            box["error"] = e

    started = time.monotonic()
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    took = time.monotonic() - started
    if worker.is_alive():
        pytest.fail(f"Still running after {seconds:.0f} s: a dead link must end the operation, not hang it")
    # Taken out of the box: an exception's traceback holds `run`'s frame and the
    # frame holds `box`, so while `box` held the exception that cycle kept the
    # nodes' databases alive until the garbage collector's next run
    if "error" in box:
        raise box.pop("error")
    return box.pop("value"), took


def notes_on(node: SyncNode, count: int, size: int = 1000) -> list:
    """`count` notes of `size` characters that do not compress, in Hebrew and hex."""
    set_this_device_id(node.device_id)
    return [node.db.create_note(f"פתק {i} " + os.urandom(size // 2).hex()) for i in range(count)]


def contents(node: SyncNode, note_ids: list) -> dict:
    node.reload_db()
    found = {}
    for note_id in note_ids:
        note = node.db.get_note(note_id)
        if note is not None:
            found[note_id] = note["content"]
    return found


class TestSyncOverAFailingLink:
    def test_a_refused_connection_fails_at_once_and_the_next_sync_completes(self, linked) -> None:
        node_a, node_b, link = linked
        ids = notes_on(node_a, 3)
        link.refuse()
        result, took = within(30, lambda: client_of(node_a).sync_with_device(node_b.device_id_hex))
        assert result.success is False and result.errors
        assert took < 10, f"a refused connection is known at once; it took {took:.1f} s"
        assert len(contents(node_a, ids)) == 3, "the failed sync lost nothing here"

        link.pass_through()
        assert client_of(node_a).sync_with_device(node_b.device_id_hex).success
        assert contents(node_b, ids) == contents(node_a, ids)

    def test_an_error_status_on_the_way_fails_the_sync_and_the_next_one_completes(self, linked) -> None:
        node_a, node_b, link = linked
        ids = notes_on(node_a, 3)
        link.answer(503, connections=1)
        result = client_of(node_a).sync_with_device(node_b.device_id_hex)
        assert result.success is False
        assert any("503" in e for e in result.errors), result.errors
        assert contents(node_b, ids) == {}

        link.pass_through()
        assert client_of(node_a).sync_with_device(node_b.device_id_hex).success
        assert contents(node_b, ids) == contents(node_a, ids)

    def test_a_push_refused_with_500_is_sent_again_by_the_next_sync(self, linked) -> None:
        node_a, node_b, link = linked
        ids = notes_on(node_a, 5)
        link.answer(500, request=b"POST /sync/apply")
        result = client_of(node_a).sync_with_device(node_b.device_id_hex)
        assert result.success is False, "a push the device did not take is not a success"
        assert contents(node_b, ids) == {}

        link.pass_through()
        again = client_of(node_a).sync_with_device(node_b.device_id_hex)
        assert again.success, again.errors
        assert contents(node_b, ids) == contents(node_a, ids)

    def test_a_push_whose_reply_is_lost_is_applied_once(self, linked) -> None:
        """The device applied the push, and the reply saying so never came back.
        The next sync sends the same changes again; the device must take them as
        the changes it already has, not as new edits in conflict with them."""
        node_a, node_b, link = linked
        ids = notes_on(node_a, 5)
        link.drop_replies(request=b"POST /sync/apply")
        result = client_of(node_a).sync_with_device(node_b.device_id_hex)
        assert result.success is False
        assert contents(node_b, ids) == contents(node_a, ids), "the device applied the push before its reply was lost"

        link.pass_through()
        again = client_of(node_a).sync_with_device(node_b.device_id_hex)
        assert again.success, again.errors
        assert again.conflicts == 0
        assert contents(node_b, ids) == contents(node_a, ids)
        assert contents(node_a, ids) == contents(node_b, ids)
        node_b.reload_db()
        assert node_b.db.get_unresolved_conflict_counts()["total"] == 0, "the second push is the same change, not a conflict"

    def test_a_pull_cut_in_the_middle_keeps_only_whole_notes_and_the_next_sync_brings_the_rest(self, linked) -> None:
        node_a, node_b, link = linked
        ids = notes_on(node_b, 400)
        on_b = contents(node_b, ids)
        link.cut_after(bytes_down=150_000)
        result = client_of(node_a).sync_with_device(node_b.device_id_hex)
        assert result.success is False
        arrived = contents(node_a, ids)
        assert len(arrived) < 400
        for note_id, text in arrived.items():
            assert text == on_b[note_id], "a note that arrived arrived whole"

        link.pass_through()
        again = client_of(node_a).sync_with_device(node_b.device_id_hex)
        assert again.success, again.errors
        assert contents(node_a, ids) == on_b

    def test_a_dead_link_ends_the_sync_in_bounded_time(self, linked) -> None:
        """Connected, and nothing ever answers: a phone whose network died
        without closing anything. The sync must give up, not wait minutes."""
        node_a, node_b, link = linked
        notes_on(node_a, 2)
        link.stall()
        result, took = within(150, lambda: client_of(node_a).sync_with_device(node_b.device_id_hex))
        assert result.success is False and result.errors
        assert took < 60, f"a dead link must end the sync within the read timeout; it took {took:.0f} s"

    def test_a_link_that_freezes_in_the_middle_of_a_pull_ends_the_sync_in_bounded_time(self, linked) -> None:
        node_a, node_b, link = linked
        ids = notes_on(node_b, 400)
        link.freeze_after(bytes_down=100_000)
        result, took = within(150, lambda: client_of(node_a).sync_with_device(node_b.device_id_hex))
        assert result.success is False
        assert took < 60, f"a frozen link must end the sync within the read timeout; it took {took:.0f} s"

        link.pass_through()
        assert client_of(node_a).sync_with_device(node_b.device_id_hex).success
        assert contents(node_a, ids) == contents(node_b, ids)

    def test_a_slow_link_completes(self, linked) -> None:
        node_a, node_b, link = linked
        ids = notes_on(node_b, 200)
        link.throttle(150_000)
        result, _ = within(120, lambda: client_of(node_a).sync_with_device(node_b.device_id_hex))
        assert result.success, result.errors
        assert contents(node_a, ids) == contents(node_b, ids)

    def test_edits_on_both_sides_through_repeated_drops_converge(self, linked) -> None:
        node_a, node_b, link = linked
        from_a, from_b = [], []
        for round_ in range(4):
            from_a += notes_on(node_a, 30)
            from_b += notes_on(node_b, 30)
            if round_ % 2:
                link.cut_after(bytes_up=40_000)
            else:
                link.cut_after(bytes_down=40_000)
            client_of(node_a).sync_with_device(node_b.device_id_hex)
        link.pass_through()
        for _ in range(2):
            result = client_of(node_a).sync_with_device(node_b.device_id_hex)
            assert result.success, result.errors
        everything = from_a + from_b
        assert contents(node_a, everything) == contents(node_b, everything)
        assert len(contents(node_a, everything)) == len(everything)


class TestRecordingsOverAFailingLink:
    def test_a_send_cut_in_the_middle_is_resumed_and_arrives_whole(self, linked) -> None:
        node_a, node_b, link = linked
        audio_id, path = give_recording(node_a, 3 * MIB)
        assert client_of(node_a).sync_with_device(node_b.device_id_hex).success
        link.cut_after(bytes_up=MIB)
        for _ in range(4):
            result = client_of(node_a).send_to_device(node_b.device_id_hex)
            node_b.reload_db()
            if local_path(node_b, audio_id).exists():
                break
        assert local_path(node_b, audio_id).read_bytes() == path.read_bytes()
        assert link.bytes_up < 2 * 3 * MIB, f"the send resumed where it was cut instead of starting again ({link.bytes_up} bytes crossed)"
        assert not Path(str(local_path(node_b, audio_id)) + ".part").exists()

    def test_a_fetch_cut_in_the_middle_is_resumed_and_arrives_whole(self, linked) -> None:
        node_a, node_b, link = linked
        audio_id, path = give_recording(node_b, 3 * MIB)
        assert client_of(node_a).sync_with_device(node_b.device_id_hex).success
        link.cut_after(bytes_down=MIB)
        for _ in range(4):
            client_of(node_a).fetch_from_device(node_b.device_id_hex)
            if local_path(node_a, audio_id).exists():
                break
        assert local_path(node_a, audio_id).read_bytes() == path.read_bytes()
        assert link.bytes_down < 2 * 3 * MIB, f"the fetch resumed where it was cut instead of starting again ({link.bytes_down} bytes crossed)"
        assert not Path(str(local_path(node_a, audio_id)) + ".part").exists()

    def test_a_send_over_a_link_slower_than_the_read_timeout_completes(self, linked) -> None:
        """A phone's uplink can take minutes over one recording while the device
        says nothing back; a send that keeps moving is not a dead link."""
        node_a, node_b, link = linked
        audio_id, path = give_recording(node_a, 2 * MIB)
        assert client_of(node_a).sync_with_device(node_b.device_id_hex).success
        link.throttle(40_000)
        result, took = within(240, lambda: client_of(node_a).send_to_device(node_b.device_id_hex))
        assert result.sent == 1, result.errors
        assert took > 35, f"the link was meant to be slower than the read timeout; the send took {took:.0f} s"
        assert local_path(node_b, audio_id).read_bytes() == path.read_bytes()

    def test_a_send_over_a_link_that_freezes_ends_in_bounded_time_and_leaves_no_file(self, linked) -> None:
        node_a, node_b, link = linked
        audio_id, path = give_recording(node_a, 3 * MIB)
        assert client_of(node_a).sync_with_device(node_b.device_id_hex).success
        link.freeze_after(bytes_up=MIB)
        result, took = within(360, lambda: client_of(node_a).send_to_device(node_b.device_id_hex))
        assert result.sent == 0 and result.errors
        # The socket buffers take the whole body before the freeze shows, so
        # each of the three tries waits a minute for an answer, and the third
        # comes a minute after the second (FILE-14)
        assert took < 300, f"three tries of at most a minute each, the third a minute after the second; it took {took:.0f} s"
        node_b.reload_db()
        assert not local_path(node_b, audio_id).exists(), "a file that did not arrive whole is not in its place"

        link.pass_through()
        assert client_of(node_a).send_to_device(node_b.device_id_hex).sent == 1
        assert local_path(node_b, audio_id).read_bytes() == path.read_bytes()

    def test_a_fetch_over_a_link_that_freezes_ends_in_bounded_time_and_leaves_no_file(self, linked) -> None:
        node_a, node_b, link = linked
        audio_id, path = give_recording(node_b, 3 * MIB)
        assert client_of(node_a).sync_with_device(node_b.device_id_hex).success
        link.freeze_after(bytes_down=MIB)
        result, took = within(300, lambda: client_of(node_a).fetch_from_device(node_b.device_id_hex))
        assert result.fetched == 0 and result.errors
        assert took < 210, f"three tries of thirty seconds each, the third a minute after the second; it took {took:.0f} s"
        assert not local_path(node_a, audio_id).exists()

        link.pass_through()
        assert client_of(node_a).fetch_from_device(node_b.device_id_hex).fetched == 1
        assert local_path(node_a, audio_id).read_bytes() == path.read_bytes()

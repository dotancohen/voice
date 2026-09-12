"""Transcription flags travelling between two installations.

The flags live in the transcription's ``state`` field, so a flag set on one
device is only useful if it arrives intact on the others — this application
and the Android one both read that field with their own code, and the words
in it are the only thing they share.

These tests use the real sync machinery: two nodes with running servers, a
transcription created on one and its flags read back on the other. The
Android side cannot be run here, so the fields written are the exact strings
the phone writes, taken from the contract fixture that both test suites read
(see test_transcription_flags_contract.py).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Generator, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core import transcription_flags as flags
from core.database import set_local_device_id

from .conftest import (
    DEVICE_A_ID,
    DEVICE_B_ID,
    SyncNode,
    create_sync_node,
    start_sync_server,
    sync_nodes,
)

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "transcription_flags_contract.json")
    .read_text(encoding="utf-8")
)


@pytest.fixture
def two_nodes_with_audiofiles(tmp_path: Path) -> Generator[Tuple[SyncNode, SyncNode], None, None]:
    """Two nodes that can hold recordings, and so transcriptions."""
    node_a = create_sync_node("NodeA", DEVICE_A_ID, tmp_path)
    node_b = create_sync_node("NodeB", DEVICE_B_ID, tmp_path)

    for node, name in ((node_a, "audiofiles_a"), (node_b, "audiofiles_b")):
        directory = tmp_path / name
        directory.mkdir()
        node.config.set_audiofile_directory(str(directory))

    node_a.config.add_peer(
        peer_id=node_b.device_id_hex, peer_name=node_b.name, peer_url=node_b.url
    )
    node_b.config.add_peer(
        peer_id=node_a.device_id_hex, peer_name=node_a.name, peer_url=node_a.url
    )

    start_sync_server(node_a)
    start_sync_server(node_b)
    if not node_a.wait_for_server():
        pytest.fail("Failed to start sync server A")
    if not node_b.wait_for_server():
        pytest.fail("Failed to start sync server B")

    yield node_a, node_b

    node_a.stop_server()
    node_b.stop_server()
    node_a.db.close()
    node_b.db.close()


def _transcription_on(node: SyncNode, audio_id: str, content: str, state: str) -> str:
    set_local_device_id(node.device_id)
    return node.db.create_transcription(
        audio_file_id=audio_id,
        content=content,
        service="local_whisper",
        state=state,
    )


def _flags_on(node: SyncNode, audio_id: str, transcription_id: str) -> str:
    rows = node.db.get_transcriptions_for_audio_file(audio_id)
    row = next(r for r in rows if r["id"] == transcription_id)
    return row["state"]


class TestFlagsSurviveSync:
    """What is written on one device is read on the other."""

    def test_the_flags_of_a_new_transcription_arrive_unchanged(
        self, two_nodes_with_audiofiles: Tuple[SyncNode, SyncNode]
    ) -> None:
        node_a, node_b = two_nodes_with_audiofiles

        set_local_device_id(node_a.device_id)
        audio_id = node_a.db.create_audio_file("הקלטה.opus")
        transcription_id = _transcription_on(
            node_a, audio_id, "שלום עולם", flags.DEFAULT_FLAGS
        )

        assert sync_nodes(node_a, node_b)["success"] is True
        node_b.reload_db()

        arrived = _flags_on(node_b, audio_id, transcription_id)
        assert arrived == flags.DEFAULT_FLAGS
        assert flags.has_flag(arrived, "original")
        assert not flags.has_flag(arrived, "verified")

    def test_a_flag_set_here_reads_as_set_there(
        self, two_nodes_with_audiofiles: Tuple[SyncNode, SyncNode]
    ) -> None:
        node_a, node_b = two_nodes_with_audiofiles

        set_local_device_id(node_a.device_id)
        audio_id = node_a.db.create_audio_file("פגישה.opus")
        transcription_id = _transcription_on(
            node_a, audio_id, "תמלול", flags.DEFAULT_FLAGS
        )

        # The user presses Verified, and then Cleaned
        current = flags.DEFAULT_FLAGS
        for flag in ("verified", "cleaned"):
            current = flags.toggle_flag(current, flag)
        node_a.db.update_transcription(transcription_id, "תמלול", state=current)

        assert sync_nodes(node_a, node_b)["success"] is True
        node_b.reload_db()

        arrived = _flags_on(node_b, audio_id, transcription_id)
        assert arrived == current
        assert flags.has_flag(arrived, "verified")
        assert flags.has_flag(arrived, "cleaned")
        assert not flags.has_flag(arrived, "polished")

    def test_a_flag_taken_off_reads_as_off_there(
        self, two_nodes_with_audiofiles: Tuple[SyncNode, SyncNode]
    ) -> None:
        node_a, node_b = two_nodes_with_audiofiles

        set_local_device_id(node_a.device_id)
        audio_id = node_a.db.create_audio_file("הרצאה.opus")
        verified = flags.toggle_flag(flags.DEFAULT_FLAGS, "verified")
        transcription_id = _transcription_on(node_a, audio_id, "תמלול", verified)

        assert sync_nodes(node_a, node_b)["success"] is True
        node_b.reload_db()
        assert flags.has_flag(_flags_on(node_b, audio_id, transcription_id), "verified")

        # Changed its mind, and synced again
        node_a.db.update_transcription(
            transcription_id, "תמלול", state=flags.toggle_flag(verified, "verified")
        )
        assert sync_nodes(node_a, node_b)["success"] is True
        node_b.reload_db()

        arrived = _flags_on(node_b, audio_id, transcription_id)
        assert not flags.has_flag(arrived, "verified")
        assert flags.has_flag(arrived, "original"), "the other flags are untouched"

    def test_a_flag_set_on_the_other_device_comes_back_here(
        self, two_nodes_with_audiofiles: Tuple[SyncNode, SyncNode]
    ) -> None:
        node_a, node_b = two_nodes_with_audiofiles

        set_local_device_id(node_a.device_id)
        audio_id = node_a.db.create_audio_file("ראיון.opus")
        transcription_id = _transcription_on(
            node_a, audio_id, "תמלול", flags.DEFAULT_FLAGS
        )
        sync_nodes(node_a, node_b)
        node_b.reload_db()

        # B is the phone: it turns Polished on
        set_local_device_id(node_b.device_id)
        polished = flags.toggle_flag(flags.DEFAULT_FLAGS, "polished")
        node_b.db.update_transcription(transcription_id, "תמלול", state=polished)

        assert sync_nodes(node_b, node_a)["success"] is True
        node_a.reload_db()

        arrived = _flags_on(node_a, audio_id, transcription_id)
        assert flags.has_flag(arrived, "polished")

    @pytest.mark.parametrize("case", CONTRACT["reads"], ids=lambda c: repr(c["field"]))
    def test_a_field_the_phone_could_write_survives_the_journey(
        self, two_nodes_with_audiofiles: Tuple[SyncNode, SyncNode], case
    ) -> None:
        """Every field shape in the contract, written on A and read on B.

        The phone writes the field itself, so this covers the sloppy ones as
        well: an empty field, doubled spaces, a word that merely begins with
        the name of a flag.
        """
        node_a, node_b = two_nodes_with_audiofiles

        set_local_device_id(node_a.device_id)
        audio_id = node_a.db.create_audio_file("contract.opus")
        transcription_id = _transcription_on(node_a, audio_id, "תמלול", case["field"])

        assert sync_nodes(node_a, node_b)["success"] is True
        node_b.reload_db()

        arrived = _flags_on(node_b, audio_id, transcription_id)
        assert arrived == case["field"], "the field must arrive character for character"
        for flag in case["set"]:
            assert flags.has_flag(arrived, flag)
        for flag in case["not_set"]:
            assert not flags.has_flag(arrived, flag)

    def test_two_transcriptions_of_one_recording_keep_their_own_flags(
        self, two_nodes_with_audiofiles: Tuple[SyncNode, SyncNode]
    ) -> None:
        node_a, node_b = two_nodes_with_audiofiles

        set_local_device_id(node_a.device_id)
        audio_id = node_a.db.create_audio_file("שתיים.opus")
        verified = flags.toggle_flag(flags.DEFAULT_FLAGS, "verified")
        first = _transcription_on(node_a, audio_id, "ראשון", verified)
        second = _transcription_on(node_a, audio_id, "שני", flags.DEFAULT_FLAGS)

        assert sync_nodes(node_a, node_b)["success"] is True
        node_b.reload_db()

        assert flags.has_flag(_flags_on(node_b, audio_id, first), "verified")
        assert not flags.has_flag(_flags_on(node_b, audio_id, second), "verified")

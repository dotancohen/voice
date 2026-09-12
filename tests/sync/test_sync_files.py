"""Files between instances (FILE-12..14) from the command line."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from voicecore import SyncClient

from .conftest import SyncNode, start_sync_server


def cli(node: SyncNode, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VOICE_CONFIG_DIR"] = str(node.config_dir)
    env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent)
    return subprocess.run(
        [sys.executable, "-m", "src.main", "cli", "--format", "json", *args],
        capture_output=True, text=True, env=env, cwd=str(Path(__file__).parent.parent.parent),
    )


def give_recording(node: SyncNode, size: int) -> tuple[str, Path]:
    """One recording of `size` bytes in the node's audio directory."""
    audio_dir = node.config_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    node.config.set_audiofile_directory(str(audio_dir))
    source = node.config_dir / "clip.ogg"
    source.write_bytes(bytes(i % 251 for i in range(size)))
    audio_id = node.db.create_audio_file("clip.ogg")
    path = audio_dir / f"{audio_id}.ogg"
    source.rename(path)
    return audio_id, path


def serve(node_b: SyncNode, node_a: SyncNode) -> None:
    """Start B's listener after its audio directory is set, and make it A's peer."""
    start_sync_server(node_b)
    assert node_b.wait_for_server()
    node_a.config.add_peer(node_b.device_id_hex, node_b.name, node_b.url)


class TestFilesBetweenInstances:
    def test_exchange_moves_a_recording_each_way(self, sync_node_a: SyncNode, sync_node_b: SyncNode):
        node_a, node_b = sync_node_a, sync_node_b
        id_a, path_a = give_recording(node_a, 120_000)
        id_b, path_b = give_recording(node_b, 80_000)
        serve(node_b, node_a)

        result = cli(node_a, "sync", "exchange", node_b.device_id_hex[:8])
        assert result.returncode == 0, result.stderr + result.stdout
        report = json.loads(result.stdout)
        assert report["success"] is True
        assert (report["sent"], report["fetched"]) == (1, 1)
        assert report["bytes_moved"] == 200_000

        on_b = node_b.config_dir / "audio" / f"{id_a}.ogg"
        on_a = node_a.config_dir / "audio" / f"{id_b}.ogg"
        assert on_b.read_bytes() == path_a.read_bytes()
        assert on_a.read_bytes() == path_b.read_bytes()
        assert not (on_a.parent / f"{id_b}.ogg.part").exists()

        again = json.loads(cli(node_a, "sync", "exchange", node_b.device_id_hex).stdout)
        assert (again["sent"], again["fetched"], again["bytes_moved"]) == (0, 0, 0)

    def test_deliver_sends_and_a_sync_alone_moves_no_file(self, sync_node_a: SyncNode, sync_node_b: SyncNode):
        node_a, node_b = sync_node_a, sync_node_b
        id_a, _ = give_recording(node_a, 10_000)
        give_recording(node_b, 10)  # B has an audio directory too
        serve(node_b, node_a)

        synced = SyncClient(str(node_a.config_dir)).sync_with_peer(node_b.device_id_hex)
        assert synced.success, synced.errors
        assert not (node_b.config_dir / "audio" / f"{id_a}.ogg").exists(), "a sync never moves a file"

        delivered = json.loads(cli(node_a, "sync", "deliver", node_b.device_id_hex).stdout)
        assert delivered["success"] and delivered["sent"] == 1
        assert (node_b.config_dir / "audio" / f"{id_a}.ogg").exists()

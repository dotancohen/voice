"""Finding each other on the local network (Stage 7): the announcement carries
the hash of the account id, never the id; a browse finds a device of the
account by that hash; an operation that does not reach its peer asks the
network and remembers the address that answers."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.discovery import Announcer, account_hash, browse, find_peer_url, looks_unreachable, run_with_discovery

ACCOUNT = "0199aaaaaaaa7000800000000000000a"
OTHER = "0199aaaaaaaa7000800000000000000b"
DEVICE = "0199bbbbbbbb7000800000000000000c"
LOOPBACK = ["127.0.0.1"]


class TestAccountHash:
    def test_the_broadcast_carries_a_hash_and_never_the_id(self) -> None:
        digest = account_hash(ACCOUNT)
        assert len(digest) == 64 and ACCOUNT not in digest
        assert account_hash(ACCOUNT.upper()) == digest
        assert account_hash(OTHER) != digest


class TestUnreachable:
    def test_a_refusal_is_not_an_unreachable_peer(self) -> None:
        assert looks_unreachable(["Handshake failed: error sending request for url (https://desk:8384/sync/handshake): connect"])
        assert not looks_unreachable(["This device is not known there (DEVICE_UNKNOWN)"])


class TestOnTheLoopback:
    """Real mDNS, on the loopback interface only, so nothing leaves this machine."""

    def test_an_announced_listener_is_found_by_its_account_and_not_by_another(self) -> None:
        announcer = Announcer(ACCOUNT, DEVICE, "Desk", 8384, "AAAA", interfaces=LOOPBACK, addresses=["127.0.0.1"])
        announcer.start()
        try:
            found = find_peer_url(ACCOUNT, DEVICE, timeout_seconds=6.0, interfaces=LOOPBACK)
            assert found is not None, "the listener announced on the loopback was not found"
            assert found.device_id == DEVICE
            assert found.name == "Desk"
            assert found.urls == ["https://127.0.0.1:8384"]
            assert found.certificate_fingerprint == "AAAA"
            assert browse(OTHER, timeout_seconds=1.5, interfaces=LOOPBACK) == [], "another account sees nothing of it"
        finally:
            announcer.stop()


class _Config:
    def __init__(self) -> None:
        self.peers = [{"peer_id": DEVICE, "peer_name": "Desk", "peer_url": "https://10.9.9.9:1"}]
        self.added = []

    def add_peer(self, peer_id, name, url, fingerprint, allow_update):
        self.added.append((peer_id, name, url, fingerprint))
        self.peers[0]["peer_url"] = url


class _Result:
    def __init__(self, success, errors=()):
        self.success, self.errors = success, list(errors)


class TestRunWithDiscovery:
    def test_the_remembered_address_is_tried_first_and_the_network_only_on_silence(self, monkeypatch) -> None:
        config = _Config()
        calls = []

        def operation(peer_id):
            calls.append(config.peers[0]["peer_url"])
            return _Result(len(calls) > 1)

        from src.core import discovery
        monkeypatch.setattr(discovery, "find_peer_url", lambda *a, **k: discovery.Found(DEVICE, "Desk", ["https://192.168.1.7:8384"], "BBBB", account_hash(ACCOUNT)))
        # First run: reached, no browse
        result = run_with_discovery(config, ACCOUNT, config.peers[0], lambda p: _Result(True))
        assert result.success and config.added == []
        # Silence at the remembered address: browse, remember, run again
        calls.clear()
        result = run_with_discovery(config, ACCOUNT, config.peers[0], lambda p: (calls.append(config.peers[0]["peer_url"]), _Result(len(calls) > 1, [] if len(calls) > 1 else ["Handshake failed: connect timed out"]))[1])
        assert result.success
        assert calls == ["https://10.9.9.9:1", "https://192.168.1.7:8384"]
        assert config.added == [(DEVICE, "Desk", "https://192.168.1.7:8384", "BBBB")]

    def test_a_refusal_does_not_browse(self, monkeypatch) -> None:
        config = _Config()
        from src.core import discovery
        monkeypatch.setattr(discovery, "find_peer_url", lambda *a, **k: pytest.fail("browsed after a refusal"))
        result = run_with_discovery(config, ACCOUNT, config.peers[0], lambda p: _Result(False, ["Refused (DEVICE_UNKNOWN)"]))
        assert not result.success and config.added == []

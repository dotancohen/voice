"""Finding each other on the local network (Stage 7).

A listener announces ``_voicesync._tcp`` with the SHA-256 of its account id,
never the id itself, and its certificate fingerprint. A caller browses and
compares hashes; the network learns nothing identifying from the broadcast.
The remembered address is tried first; the browse runs when it fails, and
the first address that answers for the right account wins.
"""

from __future__ import annotations

import hashlib
import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_voicesync._tcp.local."
PROTOCOL_VERSION = "1"

# The sentences a network failure carries, as the core words them
UNREACHABLE_MARKS = ("does not answer", "error sending request", "Connection refused", "connect", "timed out", "Could not reach")


def account_hash(account_id: str) -> str:
    """The SHA-256 of the account id, lowercase hex, as the broadcast carries it."""
    return hashlib.sha256(account_id.strip().lower().encode("ascii")).hexdigest()


def looks_unreachable(errors: Sequence[str]) -> bool:
    """Whether a result's errors say the peer was not reached, as opposed to refused."""
    return any(mark in sentence for sentence in errors for mark in UNREACHABLE_MARKS)


@dataclass
class Found:
    """A device found on the network."""

    device_id: str
    name: str
    urls: List[str]
    certificate_fingerprint: str
    account_hash: str


def _private_addresses(port: int) -> List[str]:
    """This machine's private IPv4 addresses, as the core lists them."""
    from voicecore import listen_urls

    addresses = []
    for url in listen_urls(port):
        host = urlparse(url).hostname or ""
        try:
            socket.inet_aton(host)
        except OSError:
            continue
        addresses.append(host)
    return addresses


class Announcer:
    """Announce this listener while it runs (Stage 7)."""

    def __init__(
        self,
        account_id: str,
        device_id: str,
        device_name: str,
        port: int,
        certificate_fingerprint: str,
        interfaces: Optional[Sequence[str]] = None,
        addresses: Optional[Sequence[str]] = None,
    ) -> None:
        self.account_id = account_id
        self.device_id = device_id
        self.device_name = device_name
        self.port = port
        self.certificate_fingerprint = certificate_fingerprint
        self.interfaces = list(interfaces) if interfaces else None
        self.addresses = list(addresses) if addresses else None
        self._zeroconf = None
        self._info = None

    def start(self) -> None:
        from zeroconf import ServiceInfo, Zeroconf

        addresses = self.addresses if self.addresses is not None else _private_addresses(self.port)
        if not addresses:
            logger.info("Not announcing: no private address on this machine")
            return
        properties = {
            "v": PROTOCOL_VERSION,
            "a": account_hash(self.account_id),
            "d": self.device_id,
            "n": self.device_name,
            "f": self.certificate_fingerprint,
        }
        name = f"{self.device_id[:12]}.{SERVICE_TYPE}"
        self._info = ServiceInfo(
            SERVICE_TYPE,
            name,
            addresses=[socket.inet_aton(a) for a in addresses],
            port=self.port,
            properties=properties,
            server=f"voice-{self.device_id[:12]}.local.",
        )
        self._zeroconf = Zeroconf(interfaces=self.interfaces) if self.interfaces else Zeroconf()
        self._zeroconf.register_service(self._info)
        logger.info(f"Announcing this listener on the network as {name}")

    def stop(self) -> None:
        if self._zeroconf is not None:
            try:
                if self._info is not None:
                    self._zeroconf.unregister_service(self._info)
            finally:
                self._zeroconf.close()
            self._zeroconf = None
            self._info = None


def browse(
    account_id: str,
    timeout_seconds: float = 3.0,
    device_id: Optional[str] = None,
    interfaces: Optional[Sequence[str]] = None,
) -> List[Found]:
    """The devices of this account on the network, within the timeout; with
    a device id, the browse ends as soon as that device answers."""
    from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

    wanted = account_hash(account_id)
    found: List[Found] = []
    done = threading.Event()

    class Listener(ServiceListener):
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name, timeout=1500)
            if info is None:
                return
            props = {k.decode(): (v.decode() if isinstance(v, bytes) else "") for k, v in (info.properties or {}).items() if v is not None}
            if props.get("a") != wanted:
                return
            urls = [f"https://{address}:{info.port}" for address in info.parsed_addresses()]
            entry = Found(props.get("d", ""), props.get("n", ""), urls, props.get("f", ""), props.get("a", ""))
            if entry.device_id and not any(f.device_id == entry.device_id for f in found):
                found.append(entry)
            if device_id and entry.device_id == device_id:
                done.set()

        def update_service(self, zc, type_, name):
            self.add_service(zc, type_, name)

        def remove_service(self, zc, type_, name):
            pass

    zeroconf = Zeroconf(interfaces=list(interfaces)) if interfaces else Zeroconf()
    try:
        browser = ServiceBrowser(zeroconf, SERVICE_TYPE, Listener())
        done.wait(timeout_seconds)
        browser.cancel()
    finally:
        zeroconf.close()
    return found


def find_peer_url(account_id: str, device_id: str, timeout_seconds: float = 3.0, interfaces: Optional[Sequence[str]] = None) -> Optional[Found]:
    """One device of the account, by id, or None within the timeout."""
    for entry in browse(account_id, timeout_seconds, device_id=device_id, interfaces=interfaces):
        if entry.device_id == device_id:
            return entry
    return None


def run_with_discovery(config, account_id: str, peer: dict, operation: Callable[[str], object], timeout_seconds: float = 3.0):
    """Run an operation with the remembered address; when the peer is not
    reached, browse for it, remember the address that answers, and run
    once more (Stage 7: the remembered address first, then the network)."""
    result = operation(peer["peer_id"])
    if getattr(result, "success", False) or not looks_unreachable(list(getattr(result, "errors", []))):
        return result
    try:
        found = find_peer_url(account_id, peer["peer_id"], timeout_seconds)
    except Exception as e:  # noqa: BLE001 - no network, no browse
        logger.info(f"Could not browse the network for {peer['peer_id'][:8]}: {e}")
        return result
    if found is None or not found.urls:
        return result
    url = found.urls[0]
    if url.rstrip("/") == (peer.get("peer_url") or "").rstrip("/"):
        return result
    logger.info(f"{peer['peer_name']} answered from {url}; remembering it")
    config.add_peer(peer["peer_id"], peer["peer_name"], url, found.certificate_fingerprint or None, True)
    return operation(peer["peer_id"])

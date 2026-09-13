"""A network link that fails on command, for testing sync and storage the
way devices really lose their connections.

`FaultyLink` is a TCP proxy on this machine between a client (the core's sync
client, or its bucket client) and a server (a peer's listener, or an S3
server). Point the client at the link's port instead of the server's, then
tell the link how to fail:

- ``refuse()``: nothing listens on the port; a connection is refused.
- ``cut_after(bytes_down=..., bytes_up=...)``: the connection is reset after
  that many bytes in that direction, as when wifi drops mid-transfer.
- ``stall()``: connections are accepted and nothing ever comes back, as on a
  network that has gone dead without closing anything.
- ``answer(status)``: the next requests are answered with that HTTP status
  without reaching the server, as from a failing proxy or an overloaded
  service.
- ``drop_replies()``: the request reaches the server and the server acts on
  it, but its reply never reaches the client.
- ``throttle(bytes_per_second)``: every byte gets through, slowly.
- ``freeze_after(bytes_down=..., bytes_up=...)``: after that many bytes in
  that direction nothing more is forwarded or read, and nothing is closed,
  as when a phone's connection dies in the middle of a transfer.
- ``pass_through()``: the link works again.

``answer`` and ``drop_replies`` can be limited to requests whose first line
starts with ``request`` (for example ``b"POST /sync/apply"``): earlier
requests on the connection pass untouched.

Each fault applies to the connections accepted after it is set, for as many
connections as ``connections`` says (all of them when None). The link counts
the bytes that crossed it in each direction.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import List, Optional

_CHUNK = 64 * 1024


def _reset(sock: socket.socket) -> None:
    """Close with a reset (RST), as a dropped connection looks to the other side."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


class _Fault:
    def __init__(self, kind: str, **settings) -> None:
        self.kind = kind
        self.settings = settings


class FaultyLink:
    def __init__(self, target_port: int, target_host: str = "127.0.0.1") -> None:
        self.target = (target_host, target_port)
        self.lock = threading.Lock()
        self.fault: Optional[_Fault] = None
        self.fault_connections_left: Optional[int] = None
        self.bytes_up = 0
        self.bytes_down = 0
        self.connections = 0
        self.faulted_connections = 0
        self._listener: Optional[socket.socket] = None
        self._stopping = threading.Event()
        self._open: List[socket.socket] = []
        self.port = 0
        self._listen(0)

    # ----- the port -------------------------------------------------------

    def _listen(self, port: int) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen(64)
        listener.settimeout(0.2)
        self._listener = listener
        self.port = listener.getsockname()[1]
        threading.Thread(target=self._accept_loop, args=(listener,), daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self._stopping.set()
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        with self.lock:
            for sock in self._open:
                _reset(sock)
            self._open.clear()

    def __enter__(self) -> "FaultyLink":
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # ----- the faults -----------------------------------------------------

    def _set(self, fault: Optional[_Fault], connections: Optional[int]) -> None:
        with self.lock:
            self.fault = fault
            self.fault_connections_left = connections

    def pass_through(self) -> "FaultyLink":
        self._set(None, None)
        if self._listener is None and not self._stopping.is_set():
            self._listen(self.port)
        return self

    def refuse(self) -> "FaultyLink":
        """Close the port: the next connections are refused by the system."""
        self._set(None, None)
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        # The accept loop sees the closed socket and ends
        time.sleep(0.3)
        return self

    def cut_after(self, bytes_down: Optional[int] = None, bytes_up: Optional[int] = None, connections: Optional[int] = None) -> "FaultyLink":
        """Reset a connection once that many bytes have crossed in that direction."""
        self._set(_Fault("cut", bytes_down=bytes_down, bytes_up=bytes_up), connections)
        return self

    def stall(self, connections: Optional[int] = None) -> "FaultyLink":
        self._set(_Fault("stall"), connections)
        return self

    def answer(self, status: int, connections: Optional[int] = None, body: bytes = b"", request: Optional[bytes] = None) -> "FaultyLink":
        self._set(_Fault("answer", status=status, body=body, request=request), connections)
        return self

    def drop_replies(self, connections: Optional[int] = None, request: Optional[bytes] = None) -> "FaultyLink":
        self._set(_Fault("drop_replies", request=request), connections)
        return self

    def freeze_after(self, bytes_down: Optional[int] = None, bytes_up: Optional[int] = None, connections: Optional[int] = None) -> "FaultyLink":
        self._set(_Fault("freeze", bytes_down=bytes_down, bytes_up=bytes_up), connections)
        return self

    def throttle(self, bytes_per_second: int, connections: Optional[int] = None) -> "FaultyLink":
        self._set(_Fault("throttle", bytes_per_second=bytes_per_second), connections)
        return self

    # ----- the connections ------------------------------------------------

    def _take_fault(self) -> Optional[_Fault]:
        with self.lock:
            self.connections += 1
            if self.fault is None:
                return None
            if self.fault_connections_left is not None:
                if self.fault_connections_left <= 0:
                    return None
                self.fault_connections_left -= 1
            self.faulted_connections += 1
            return self.fault

    def _accept_loop(self, listener: socket.socket) -> None:
        while not self._stopping.is_set():
            try:
                client, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self.lock:
                self._open.append(client)
            threading.Thread(target=self._serve, args=(client, self._take_fault()), daemon=True).start()

    def _serve(self, client: socket.socket, fault: Optional[_Fault]) -> None:
        kind = fault.kind if fault else None
        if kind == "stall":
            self._swallow(client)
            return
        if kind == "answer" and fault.settings.get("request") is None:
            self._answer(client, fault.settings["status"], fault.settings["body"])
            return
        try:
            server = socket.create_connection(self.target, timeout=5)
        except OSError:
            _reset(client)
            return
        server.settimeout(None)
        with self.lock:
            self._open.append(server)
        settings = fault.settings if fault else {}
        rate = settings.get("bytes_per_second") if kind == "throttle" else None
        up_limit = settings.get("bytes_up") if kind in ("cut", "freeze") else None
        down_limit = settings.get("bytes_down") if kind in ("cut", "freeze") else None
        freeze = kind == "freeze"
        request = settings.get("request")
        # drop_replies without a request drops every reply; with one, the
        # replies after that request is seen
        dropping = threading.Event()
        if kind == "drop_replies" and request is None:
            dropping.set()
        ended = threading.Event()

        def pump(source: socket.socket, sink: socket.socket, upward: bool, limit: Optional[int]) -> None:
            moved = 0
            try:
                while not ended.is_set():
                    data = source.recv(_CHUNK)
                    if not data:
                        break
                    if upward and request is not None and data.startswith(request):
                        if kind == "answer":
                            # This request never reaches the server
                            ended.set()
                            self._answer(client, settings["status"], settings["body"])
                            return
                        if kind == "drop_replies":
                            dropping.set()
                    if limit is not None and moved + len(data) >= limit:
                        keep = data[: max(0, limit - moved)]
                        if keep:
                            sink.sendall(keep)
                            self._count(upward, len(keep))
                        if freeze:
                            # Hold both connections open and move nothing more
                            while not ended.is_set() and not self._stopping.is_set():
                                time.sleep(0.2)
                            return
                        break
                    if not upward and dropping.is_set():
                        # The server has acted on the request and answered;
                        # the answer is thrown away and the connection drops
                        time.sleep(0.2)
                        break
                    if rate:
                        time.sleep(len(data) / rate)
                    sink.sendall(data)
                    moved += len(data)
                    self._count(upward, len(data))
            except OSError:
                pass
            finally:
                ended.set()
                _reset(client)
                _reset(server)

        up = threading.Thread(target=pump, args=(client, server, True, up_limit), daemon=True)
        down = threading.Thread(target=pump, args=(server, client, False, down_limit), daemon=True)
        up.start()
        down.start()

    def _count(self, upward: bool, n: int) -> None:
        with self.lock:
            if upward:
                self.bytes_up += n
            else:
                self.bytes_down += n

    def _swallow(self, client: socket.socket) -> None:
        """Read whatever the client sends and never answer, until it gives up."""
        client.settimeout(0.5)
        while not self._stopping.is_set():
            try:
                if not client.recv(_CHUNK):
                    break
            except socket.timeout:
                continue
            except OSError:
                break
        _reset(client)

    def _answer(self, client: socket.socket, status: int, body: bytes) -> None:
        """Read the request's head, then answer with the status and close."""
        client.settimeout(5)
        head = b""
        try:
            while b"\r\n\r\n" not in head and len(head) < 256 * 1024:
                data = client.recv(_CHUNK)
                if not data:
                    break
                head += data
        except OSError:
            pass
        reason = {500: "Internal Server Error", 502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout"}.get(status, "Error")
        response = (
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        ).encode() + body
        try:
            client.sendall(response)
        except OSError:
            pass
        try:
            client.shutdown(socket.SHUT_WR)
            time.sleep(0.05)
        except OSError:
            pass
        _reset(client)

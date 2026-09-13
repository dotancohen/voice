"""A small S3 that lives in a thread, for the wizard's tests: buckets,
objects, tagging, the bucket's own settings, and what the wizard reads back.
It checks that every request is signed (version 4) with the expected key id
and that nothing is deleted, and it can refuse with the codes the wizard
must explain."""

from __future__ import annotations

import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional
from urllib.parse import parse_qs, unquote, urlsplit


import hashlib
import hmac


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


class FakeS3:
    def __init__(self, access_key_id: str = "AKIAIOSFODNN7EXAMPLE", secret_access_key: str = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY") -> None:
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.buckets: Dict[str, Dict[str, bytes]] = {}
        self.tags: Dict[str, Dict[str, Dict[str, str]]] = {}
        self.settings: Dict[str, Dict[str, str]] = {}
        self.requests: list = []
        self.taken_names: set = set()
        self.refuse_with: Optional[str] = None  # an error code every request answers with
        self.lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # quiet
                pass

            def _answer(self, status: int, body: bytes = b"", content_type: str = "application/xml"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _error(self, status: int, code: str):
                self._answer(status, f"<?xml version='1.0'?><Error><Code>{code}</Code><Message>{code}</Message></Error>".encode())

            def _parts(self):
                split = urlsplit(self.path)
                pieces = [p for p in split.path.split("/") if p]
                bucket = pieces[0] if pieces else ""
                key = unquote("/".join(pieces[1:])) if len(pieces) > 1 else ""
                query = parse_qs(split.query, keep_blank_values=True)
                return bucket, key, query

            def _signed(self) -> bool:
                """Signature version 4, checked as the service checks it: the key id
                must be the known one, and the signature must be the one the known
                secret gives for this exact request."""
                auth = self.headers.get("Authorization", "")
                if not auth.startswith("AWS4-HMAC-SHA256"):
                    return False
                fields = dict(part.strip().split("=", 1) for part in auth[len("AWS4-HMAC-SHA256"):].split(",") if "=" in part)
                credential = fields.get("Credential", "")
                if not credential.startswith(fake.access_key_id + "/"):
                    return False
                _, date, region, service, _ = credential.split("/")
                signed_headers = fields.get("SignedHeaders", "").split(";")
                split = urlsplit(self.path)
                canonical_uri = split.path or "/"
                pairs = []
                for part in split.query.split("&") if split.query else []:
                    k, _, v = part.partition("=")
                    pairs.append((k, v))
                canonical_query = "&".join(f"{k}={v}" for k, v in sorted(pairs))
                canonical_headers = "".join(f"{h}:{' '.join((self.headers.get(h) or '').split())}\n" for h in signed_headers)
                payload_hash = self.headers.get("x-amz-content-sha256") or "UNSIGNED-PAYLOAD"
                canonical_request = "\n".join([self.command, canonical_uri, canonical_query, canonical_headers, ";".join(signed_headers), payload_hash])
                amz_date = self.headers.get("x-amz-date", "")
                scope = f"{date}/{region}/{service}/aws4_request"
                string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()])
                k = _hmac(("AWS4" + fake.secret_access_key).encode(), date)
                k = _hmac(k, region)
                k = _hmac(k, service)
                k = _hmac(k, "aws4_request")
                expected = hmac.new(k, string_to_sign.encode(), hashlib.sha256).hexdigest()
                return hmac.compare_digest(expected, fields.get("Signature", ""))

            def _body(self) -> bytes:
                if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
                    chunks = []
                    while True:
                        size_line = self.rfile.readline().strip()
                        size = int(size_line.split(b";")[0] or b"0", 16)
                        if size == 0:
                            self.rfile.readline()
                            break
                        chunks.append(self.rfile.read(size))
                        self.rfile.readline()
                    return b"".join(chunks)
                length = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(length) if length else b""

            def do_PUT(self):  # noqa: N802
                bucket, key, query = self._parts()
                body = self._body()
                with fake.lock:
                    fake.requests.append(("PUT", bucket, key, sorted(query)))
                    if not self._signed():
                        return self._error(403, "SignatureDoesNotMatch")
                    if fake.refuse_with:
                        return self._error(403, fake.refuse_with)
                    if not key and not query:
                        if bucket in fake.taken_names:
                            return self._error(409, "BucketAlreadyExists")
                        fake.buckets.setdefault(bucket, {})
                        fake.settings.setdefault(bucket, {})
                        return self._answer(200)
                    if bucket not in fake.buckets:
                        return self._error(404, "NoSuchBucket")
                    if not key:
                        for setting in ("publicAccessBlock", "encryption", "policy", "lifecycle"):
                            if setting in query:
                                fake.settings[bucket][setting] = body.decode("utf-8", "replace")
                                return self._answer(200)
                        return self._error(400, "InvalidRequest")
                    if "tagging" in query:
                        if key not in fake.buckets[bucket]:
                            return self._error(404, "NoSuchKey")
                        pairs = dict(re.findall(r"<Key>(.*?)</Key><Value>(.*?)</Value>", body.decode("utf-8", "replace")))
                        fake.tags.setdefault(bucket, {})[key] = pairs
                        return self._answer(200)
                    fake.buckets[bucket][key] = body
                    return self._answer(200)

            def do_GET(self):  # noqa: N802
                bucket, key, query = self._parts()
                with fake.lock:
                    fake.requests.append(("GET", bucket, key, sorted(query)))
                    if not self._signed():
                        return self._error(403, "SignatureDoesNotMatch")
                    if fake.refuse_with:
                        return self._error(403, fake.refuse_with)
                    if bucket not in fake.buckets:
                        return self._error(404, "NoSuchBucket")
                    if not key:
                        if "location" in query:
                            return self._answer(200, b"<?xml version='1.0'?><LocationConstraint xmlns='http://s3.amazonaws.com/doc/2006-03-01/'>us-east-1</LocationConstraint>")
                        for setting in ("publicAccessBlock", "encryption", "policy", "lifecycle"):
                            if setting in query:
                                stored = fake.settings[bucket].get(setting)
                                if stored is None:
                                    return self._error(404, "NoSuch" + setting)
                                return self._answer(200, stored.encode())
                        if "list-type" in query or "prefix" in query or "max-keys" in query or not query:
                            keys = "".join(f"<Contents><Key>{k}</Key><Size>{len(v)}</Size></Contents>" for k, v in list(fake.buckets[bucket].items())[:1])
                            return self._answer(200, f"<?xml version='1.0'?><ListBucketResult><Name>{bucket}</Name><KeyCount>{len(fake.buckets[bucket])}</KeyCount><IsTruncated>false</IsTruncated>{keys}</ListBucketResult>".encode())
                        return self._error(400, "InvalidRequest")
                    if "tagging" in query:
                        pairs = fake.tags.get(bucket, {}).get(key, {})
                        return self._answer(200, ("<Tagging><TagSet>" + "".join(f"<Tag><Key>{k}</Key><Value>{v}</Value></Tag>" for k, v in pairs.items()) + "</TagSet></Tagging>").encode())
                    if key not in fake.buckets[bucket]:
                        return self._error(404, "NoSuchKey")
                    return self._answer(200, fake.buckets[bucket][key], "application/octet-stream")

            def do_HEAD(self):  # noqa: N802
                bucket, key, query = self._parts()
                with fake.lock:
                    fake.requests.append(("HEAD", bucket, key, sorted(query)))
                    if bucket not in fake.buckets:
                        return self._answer(404)
                    if key and key not in fake.buckets[bucket]:
                        return self._answer(404)
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(fake.buckets[bucket].get(key, b""))))
                    self.end_headers()

            def do_DELETE(self):  # noqa: N802
                bucket, key, query = self._parts()
                with fake.lock:
                    fake.requests.append(("DELETE", bucket, key, sorted(query)))
                return self._error(403, "AccessDenied")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> "FakeS3":
        self.thread.start()
        return self

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def deleted_anything(self) -> bool:
        return any(m == "DELETE" for m, _, _, _ in self.requests)

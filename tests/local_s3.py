"""An S3 server on this machine for the tests: moto's (Apache 2.0), a real
HTTP server that the core reaches over TCP exactly as it reaches Amazon.

Authentication is on: the key is made in moto's own IAM, every request must be
signed with it (signature version 4), and a wrong secret or an unknown key id
is refused as Amazon refuses it. moto starts checking after its first
``INITIAL_NO_AUTH_ACTION_COUNT`` requests, which are the three that make the
user, its policy and its key; the setting is read when moto is imported, so
this module sets it first and is the only place in the tests that imports moto.

One server serves a whole test session; each test takes a bucket of its own.
The server speaks plain HTTP, so a bucket given the wizard's "TLS only"
policy refuses every write, as Amazon would: tests that upload use a bucket
without that policy, and the hardening test checks the refusal.
"""

from __future__ import annotations

import itertools
import json
import os
import socket

os.environ["INITIAL_NO_AUTH_ACTION_COUNT"] = "3"

import boto3  # noqa: E402
from moto.server import ThreadedMotoServer  # noqa: E402

REGION = "eu-central-1"
_BUCKETS = itertools.count(1)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LocalS3:
    def __init__(self) -> None:
        self.port = _free_port()
        self.endpoint = f"http://127.0.0.1:{self.port}"
        self._server = ThreadedMotoServer(ip_address="127.0.0.1", port=self.port, verbose=False)
        self._server.start()
        iam = boto3.client("iam", endpoint_url=self.endpoint, region_name="us-east-1", aws_access_key_id="unsigned", aws_secret_access_key="unsigned")
        iam.create_user(UserName="voice")
        iam.put_user_policy(
            UserName="voice",
            PolicyName="voice-buckets",
            PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]}),
        )
        key = iam.create_access_key(UserName="voice")["AccessKey"]
        self.access_key_id = key["AccessKeyId"]
        self.secret_access_key = key["SecretAccessKey"]

    def client(self):
        """A boto3 client with the key, for a test to look into the bucket."""
        return boto3.client(
            "s3", endpoint_url=self.endpoint, region_name=REGION,
            aws_access_key_id=self.access_key_id, aws_secret_access_key=self.secret_access_key,
        )

    @staticmethod
    def new_bucket_name() -> str:
        """A bucket name no other test in the session uses, allowed by the wizard."""
        return f"voice-t{next(_BUCKETS):05d}"

    def objects(self, bucket: str) -> dict:
        """Every object in the bucket: key to bytes."""
        s3 = self.client()
        found = {}
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            for item in page.get("Contents", []):
                found[item["Key"]] = s3.get_object(Bucket=bucket, Key=item["Key"])["Body"].read()
        return found

    def unfinished_uploads(self, bucket: str) -> list:
        return self.client().list_multipart_uploads(Bucket=bucket).get("Uploads", [])

    def stop(self) -> None:
        self._server.stop()

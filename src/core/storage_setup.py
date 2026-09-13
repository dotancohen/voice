"""The bucket wizard's steps (Stage 8, Stage 14), without any interface.

The GUI wizard and ``cli storage setup`` both drive this: the same steps in
the same order, the same words for a failure. The bucket calls themselves
are in the core; this module holds the order, the wording and what is kept
between steps. The secret is never written anywhere until the final save.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# What the console shows, one screen at a time (Stage 8 step 1)
CONSOLE_STEPS = [
    "Open https://console.aws.amazon.com/iam/ and sign in.",
    "In the left column choose Users, then Create user. Name it voice. Do not tick console access. Next.",
    "Under permissions choose Attach policies directly, then Create policy. Open the JSON tab, delete what is there, and paste the policy text below. Name the policy voice-bucket. Create it.",
    "Back on the user page, refresh the policy list, tick voice-bucket, Next, Create user.",
    "Open the user voice, choose the Security credentials tab, then Create access key. Choose Application running outside AWS. Next, Create access key.",
    "Copy the Access key and the Secret access key into the next page. The secret is shown once; if it is lost, make another key.",
]

WHAT_THE_BUCKET_HOLDS = (
    "The bucket holds recordings only. Notes, tags and transcriptions travel "
    "between your devices by sync, never through the bucket."
)


@dataclass
class SetupState:
    """What the wizard has so far; kept for the session only, never written."""

    access_key_id: str = ""
    secret_access_key: str = ""
    region: str = ""
    bucket: str = ""
    endpoint: str = ""
    prefix: str = ""
    created: bool = False
    hardened: List[Dict[str, Any]] = field(default_factory=list)
    lifecycle_set: bool = False
    round_trip_key: str = ""
    saved: bool = False

    def key_args(self) -> Dict[str, Any]:
        return {
            "access_key_id": self.access_key_id,
            "secret_access_key": self.secret_access_key,
            "region": self.region,
            "endpoint": self.endpoint or None,
        }


def policy_text() -> str:
    from voicecore import bucket_policy_text

    return bucket_policy_text()


def take_key(state: SetupState, key_id: str, secret: str) -> Optional[str]:
    """Step 2: the pasted key, cleaned. Returns a sentence when something is missing."""
    from voicecore import bucket_clean_key_id, bucket_clean_secret

    state.access_key_id = bucket_clean_key_id(key_id)
    state.secret_access_key = bucket_clean_secret(secret)
    if not state.access_key_id:
        return "The access key id is empty."
    if not state.secret_access_key:
        return "The secret access key is empty."
    if not state.endpoint and (len(state.access_key_id) != 20 or not state.access_key_id.startswith("AKIA")):
        return "An Amazon access key id starts with AKIA and is 20 characters; check what was pasted."
    return None


def regions() -> List[str]:
    from voicecore import bucket_regions

    return list(bucket_regions())


def nearest_region() -> Optional[str]:
    """Step 3: the region whose endpoint answers fastest, or None off the network."""
    from voicecore import bucket_nearest_region

    try:
        return bucket_nearest_region()
    except Exception as e:  # noqa: BLE001
        logger.info(f"Could not measure the regions: {e}")
        return None


def suggest_bucket_name() -> str:
    from voicecore import bucket_suggest_name

    return bucket_suggest_name()


def bucket_name_problem(name: str) -> Optional[str]:
    from voicecore import bucket_name_problem as problem

    return problem(name)


def create_bucket(state: SetupState) -> Optional[str]:
    """Step 4: make the bucket, private. Returns a sentence on failure; a
    taken name gets a suggestion."""
    from voicecore import bucket_create, bucket_exists

    problem = bucket_name_problem(state.bucket)
    if problem:
        return problem
    try:
        if bucket_exists(name=state.bucket, **state.key_args()):
            state.created = True
            return None
    except Exception as e:  # noqa: BLE001 - taken by someone else, or refused
        text = str(e)
        # Another name helps only when this one is taken; a wrong secret
        # or key id is the same with every name
        if "taken" in text:
            return f"{text} Try {suggest_bucket_name()}."
        return text
    try:
        bucket_create(name=state.bucket, **state.key_args())
    except Exception as e:  # noqa: BLE001
        text = str(e)
        if "taken" in text:
            return f"{text} Try {suggest_bucket_name()}."
        return text
    state.created = True
    return None


def harden(state: SetupState) -> List[Dict[str, Any]]:
    """Stage 14: public access blocked, encryption on, TLS only; each verified."""
    from voicecore import bucket_harden

    state.hardened = list(bucket_harden(name=state.bucket, **state.key_args()))
    return state.hardened


def set_lifecycle(state: SetupState) -> Optional[str]:
    """Step 8: the lifecycle rules. Returns a sentence on failure."""
    from voicecore import bucket_set_lifecycle

    try:
        bucket_set_lifecycle(name=state.bucket, **state.key_args())
    except Exception as e:  # noqa: BLE001
        return str(e)
    state.lifecycle_set = True
    return None


def round_trip(state: SetupState) -> Optional[str]:
    """Step 5: write, read back, compare, tag purged. Returns a sentence on failure."""
    from voicecore import bucket_round_trip

    try:
        state.round_trip_key = bucket_round_trip(name=state.bucket, prefix=state.prefix or None, **state.key_args())
    except Exception as e:  # noqa: BLE001
        return str(e)
    return None


def save(state: SetupState, db) -> None:
    """Step 6: through the synced storage configuration, so every device of
    the account receives it at its next sync."""
    import json

    config = {
        "bucket": state.bucket,
        "region": state.region,
        "access_key_id": state.access_key_id,
        "secret_access_key": state.secret_access_key,
    }
    if state.prefix:
        config["prefix"] = state.prefix
    if state.endpoint:
        config["endpoint"] = state.endpoint
    db.set_file_storage_config("s3", json.dumps(config))
    state.saved = True


def saved_state(db) -> Optional[SetupState]:
    """The configuration a device already holds, for "Replace key" and the checks."""
    saved = db.get_file_storage_config()
    if not saved or saved.get("provider") != "s3":
        return None
    config = saved.get("config") or {}
    if isinstance(config, str):
        import json

        config = json.loads(config)
    return SetupState(
        access_key_id=config.get("access_key_id", ""),
        secret_access_key=config.get("secret_access_key", ""),
        region=config.get("region", ""),
        bucket=config.get("bucket", ""),
        endpoint=config.get("endpoint", "") or "",
        prefix=config.get("prefix", "") or "",
        created=True,
        saved=True,
    )


def replace_key(db, key_id: str, secret: str) -> Optional[str]:
    """Stage 14 "Replace key": test the new key on the existing bucket exactly
    as the first run does, then save it through the synced configuration.
    Returns a sentence on failure, None when saved."""
    state = saved_state(db)
    if state is None:
        return "No bucket is configured yet; run the wizard first."
    problem = take_key(state, key_id, secret)
    if problem:
        return problem
    problem = round_trip(state)
    if problem:
        return problem
    save(state, db)
    return None


def check_everything(config_dir: str, config, db) -> List[Dict[str, Any]]:
    """Step 11 "Test everything": the connection check against every peer and
    the bucket, as one table. Each row's name starts with the peer or the bucket."""
    from voicecore import SyncClient, bucket_check

    rows: List[Dict[str, Any]] = []
    client = SyncClient(config_dir)
    for peer in config.get_peers():
        for row in client.check(peer["peer_id"]):
            rows.append({**row, "name": f"{peer['peer_name']}: {row['name']}"})
    for row in bucket_check(config_dir):
        rows.append({**row, "name": f"Bucket: {row['name']}"})
    return rows


def checklist(config, db, listening: bool) -> List[Dict[str, Any]]:
    """The checklist at the top of the sync dialogue (Stage 8): each row its
    state and the one thing that completes it."""
    peers = config.get_peers()
    bucket = saved_state(db)
    counts = db.not_duplicated(config.get_audiofile_directory())
    summaries = db.peer_summaries()
    last = max((p for p in summaries if p.get("last_reached_at")), key=lambda p: p["last_reached_at"], default=None)
    rows = [
        {
            "name": "Paired devices",
            "done": bool(peers),
            "detail": f"{len(peers)} peer{'s' if len(peers) != 1 else ''}" if peers else "None yet",
            "action": "" if peers else "show_code",
            "action_label": "" if peers else "Show my code",
        },
        {
            "name": "Bucket",
            "done": bucket is not None,
            "detail": f"{bucket.bucket} in {bucket.region}" if bucket else "Not set up",
            "action": "" if bucket else "storage_wizard",
            "action_label": "" if bucket else "Set up the bucket",
        },
        {
            "name": "Listener",
            "done": listening,
            "detail": "Listening for peers" if listening else "Not listening",
            "action": "" if listening else "listen",
            "action_label": "" if listening else "Listen for peers",
        },
        {
            "name": "Not duplicated",
            "done": counts["notes"] == 0 and counts["recordings"] == 0,
            "detail": f"{counts['notes']} notes and {counts['recordings']} recordings on this device only" if counts["notes"] or counts["recordings"] else "Everything is somewhere else too",
            "action": "" if (counts["notes"] == 0 and counts["recordings"] == 0) or not peers else "exchange",
            "action_label": "" if (counts["notes"] == 0 and counts["recordings"] == 0) or not peers else "Exchange",
        },
        {
            "name": "Last exchange",
            "done": last is not None,
            "detail": f"{last['peer_name'] or last['peer_id'][:8]}, {last['last_operation']}" if last else "Never",
            "action": "",
            "action_label": "",
        },
    ]
    return rows

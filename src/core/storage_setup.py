"""The bucket wizard's steps (Stage 8, Stage 14), without any interface.

The GUI wizard and ``cli storage setup`` both drive this: the same steps in
the same order, the same words for a failure. The bucket calls themselves
are in the core; this module holds the order, the wording and what is kept
between steps. The secret is never written anywhere until the final save.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# The page of console_pages on which the policy text is pasted
POLICY_STEP = 2

CONSOLE_URL = "https://console.aws.amazon.com/iam/"

# A line of a console page: its words, with "{}" where a value to type goes,
# and the value (None for a line with nothing to type)
ConsoleLine = Tuple[str, Optional[str]]


def console_names() -> Tuple[str, str]:
    """The user name and the policy name for one run of the wizard: the same four
    random digits in both, so the user can find the policy it made and tell this
    key's user and policy from others in the account."""
    digits = f"{secrets.randbelow(10000):04d}"
    return f"voice-{digits}", f"Voice-Recordings-{digits}"


def console_pages(user_name: str, policy_name: str) -> List[Tuple[str, List[ConsoleLine]]]:
    """What to press in the Amazon console, one page at a time (Stage 8 step 1):
    each page's title and its lines. A value to type is kept apart from the
    words, so an interface can put a copy button beside it. The policy is made
    before the user, so the user page finds it without a second tab."""
    return [
        ("Open the Amazon console", [
            ("Open {} and sign in.", CONSOLE_URL),
        ]),
        ("Make the policy", [
            ("In the left column click Policies, then click Create policy.", None),
            ("Click JSON, delete everything in the box, and paste the policy text below. Click Next.", None),
            ("In Policy name type {}.", policy_name),
            ("Click Create policy.", None),
        ]),
        ("Make the user", [
            ("In the left column click IAM Users, then click Create user.", None),
            ("In User name type {}.", user_name),
            ("Leave Provide user access to the AWS Management Console unticked. Click Next.", None),
            ("Click Attach policies directly.", None),
            ("In the search box under Permissions policies type {}, tick the box beside it, and click Next.", policy_name),
            ("Click Create user.", None),
        ]),
        ("Make the access key", [
            ("In the list of users click {}.", user_name),
            ("Click the Security credentials tab. Under Access keys click Create access key.", None),
            ("Click Application running outside AWS, click Next, then click Create access key.", None),
        ]),
        ("Enter the key", [
            ("On the screen that shows the new key, click Show beside Secret access key.", None),
            ("Enter the Access key and the Secret access key below before you leave that screen: the secret is shown only once.", None),
        ]),
    ]


def console_steps(user_name: str, policy_name: str) -> List[str]:
    """The console pages as one sentence each, for the command line."""
    return [
        " ".join(words.format(value) if value is not None else words for words, value in lines)
        for _title, lines in console_pages(user_name, policy_name)
    ]


def copy_values(user_name: str, policy_name: str) -> List[Tuple[str, str]]:
    """Every text the user must put into the console, with its label, so an
    interface can offer a copy button for each instead of asking for a selection."""
    return [
        ("The console's address", CONSOLE_URL),
        ("Policy name", policy_name),
        ("User name", user_name),
        ("Policy text", policy_text()),
    ]


def provider_name(endpoint: str = "") -> str:
    """The name of the storage service an endpoint belongs to: Amazon without an
    endpoint, a known service by its address, otherwise the endpoint's host name.
    The list of services is the core's, the one its refusals name."""
    from voicecore import bucket_provider_name

    return bucket_provider_name(endpoint or None)


def waiting_sentence(endpoint: str = "") -> str:
    """What the wizard says while it waits for the storage service."""
    return f"Waiting for a response from {provider_name(endpoint)}…"


def stores_files_sentence(endpoint: str = "") -> str:
    """What the bucket holds, and what it does not."""
    return (
        f"{provider_name(endpoint)} stores files only, not notes' content. "
        "For full note syncing, be sure to configure sync between devices."
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
    # A name the user chose under Advanced is never replaced; a generated one is
    # replaced by a free one when it turns out taken
    bucket_chosen: bool = False
    renamed_from: str = ""
    # The nearest region that accepts the key, and nearer ones that refused it
    # (switched off for the account)
    nearest: str = ""
    regions_refused: List[str] = field(default_factory=list)
    # One line per result of making the bucket: made, hardened, lifecycle, round trip
    report: List[str] = field(default_factory=list)
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


def key_id_problem(text: str, endpoint: str = "") -> Optional[str]:
    """What is wrong with an entered access key ID, in words, or None; for checking as it is typed."""
    from voicecore import bucket_access_key_id_problem, bucket_clean_key_id

    return bucket_access_key_id_problem(bucket_clean_key_id(text), bool(endpoint))


def secret_problem(text: str, endpoint: str = "") -> Optional[str]:
    """What is wrong with an entered secret access key, in words, or None."""
    from voicecore import bucket_clean_secret, bucket_secret_access_key_problem

    return bucket_secret_access_key_problem(bucket_clean_secret(text), bool(endpoint))


def take_key(state: SetupState, key_id: str, secret: str) -> Optional[str]:
    """Step 2: the entered key, cleaned and checked for its shape (Amazon's:
    20 capital letters and digits starting with AKIA, and a 40-character secret).
    Returns a sentence when something is wrong."""
    from voicecore import bucket_clean_key_id, bucket_clean_secret

    state.access_key_id = bucket_clean_key_id(key_id)
    state.secret_access_key = bucket_clean_secret(secret)
    return key_id_problem(state.access_key_id, state.endpoint) or secret_problem(state.secret_access_key, state.endpoint)


def regions() -> List[str]:
    from voicecore import bucket_regions

    return list(bucket_regions())


def nearest_region(state: Optional[SetupState] = None) -> Optional[str]:
    """Step 3: the nearest region that accepts the key (Amazon), so a region the
    account has not switched on is never proposed; without a key, the region
    whose endpoint answers fastest. None off the network. The nearer regions that
    refused the key are kept in ``state.regions_refused``."""
    from voicecore import bucket_nearest_accepting_region, bucket_nearest_region

    try:
        if state is not None and state.access_key_id and not state.endpoint:
            region, refused = bucket_nearest_accepting_region(state.access_key_id, state.secret_access_key)
            state.regions_refused = list(refused)
            return region
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


def choose_free_bucket(state: SetupState) -> Optional[str]:
    """A generated bucket name that no bucket has, checked with the service, put
    in ``state.bucket``. Returns a sentence when the key is refused."""
    from voicecore import bucket_free_name

    try:
        state.bucket = bucket_free_name(**{k: v for k, v in state.key_args().items()})
    except Exception as e:  # noqa: BLE001 - a refused key, in words
        return str(e)
    state.bucket_chosen = False
    return None


def create_bucket(state: SetupState) -> Optional[str]:
    """Step 4: make the bucket, private. A generated name that turns out taken is
    replaced by a free one (``state.renamed_from`` keeps the old); a name chosen
    under Advanced is not, and its owner is told. Returns a sentence on failure,
    with the service's own words."""
    from voicecore import bucket_create, bucket_name_state

    if not state.bucket:
        problem = choose_free_bucket(state)
        if problem:
            return problem
    problem = bucket_name_problem(state.bucket)
    if problem:
        return problem
    for _ in range(3):
        try:
            name_state = bucket_name_state(name=state.bucket, **state.key_args())
        except Exception as e:  # noqa: BLE001 - the key refused, explained by the core
            return str(e)
        if name_state == "ours":
            state.created = True
            return None
        if name_state == "free":
            break
        if state.bucket_chosen:
            return f"The bucket name {state.bucket} is taken by another account; choose another under Custom bucket name and folder."
        taken = state.bucket
        problem = choose_free_bucket(state)
        if problem:
            return problem
        state.renamed_from = taken
    try:
        bucket_create(name=state.bucket, **state.key_args())
    except Exception as e:  # noqa: BLE001
        return str(e)
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


def devices_of(config) -> List[Tuple[str, str]]:
    """(id, name) of every other device this one syncs with, read from the configuration."""
    return [(p["peer_id"], p["peer_name"] or p["peer_id"][:12]) for p in config.get_peers()]


def check_all_paths(config_dir: str, devices: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
    """Test all syncing paths (Stage 8): the connection check against every
    device in `devices` and the bucket, as one table; each row's name starts
    with the device's name or "Bucket". Opens its own connections, so it may run
    on a thread of its own; `devices` comes from :func:`devices_of`."""
    from voicecore import SyncClient, bucket_check

    rows: List[Dict[str, Any]] = []
    client = SyncClient(config_dir)
    for device_id, name in devices:
        for row in client.check(device_id):
            rows.append({**row, "name": f"{name}: {row['name']}"})
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

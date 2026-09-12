"""The transcription flags, as agreed with the Android application.

A transcription's flags are five words in its ``state`` field, and that field
syncs between this application and the phone. Neither can read the other's
code, so the agreement is written down in
``tests/fixtures/transcription_flags_contract.json`` and both test suites
check their own implementation against it. The Android copy of that file is
``app/src/test/resources/transcription_flags_contract.json`` and must be
identical; a test there reads the same cases.

If a case here fails, the two applications no longer agree on what a
transcription says about itself, and a flag set on one would be misread on
the other after the next sync.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from core import transcription_flags as flags

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "transcription_flags_contract.json"


@pytest.fixture(scope="module")
def contract() -> Dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


ANDROID_COPY = (
    CONTRACT_PATH.parents[2].parent
    / "VoiceAndroid"
    / "app"
    / "src"
    / "test"
    / "resources"
    / "transcription_flags_contract.json"
)


def test_the_contract_is_the_one_this_code_was_written_against(contract):
    assert contract["version"] == 1


def test_the_android_copy_is_the_same_file():
    """The two repositories must hold the same contract, byte for byte.

    Skipped when the Android repository is not checked out beside this one,
    which is the case on a build server that only has this project.
    """
    if not ANDROID_COPY.exists():
        pytest.skip(f"VoiceAndroid is not checked out at {ANDROID_COPY}")
    assert ANDROID_COPY.read_bytes() == CONTRACT_PATH.read_bytes(), (
        "the contract has drifted between the two applications: change both "
        "copies in the same commit"
    )


def test_the_five_flags_are_the_five_in_the_contract(contract):
    assert [f.name for f in flags.ALL] == contract["flags"]


def test_a_new_transcription_carries_the_agreed_field(contract):
    assert flags.DEFAULT_FLAGS == contract["default_field"]


def test_every_description_is_the_agreed_wording(contract):
    assert {f.name: f.description for f in flags.ALL} == contract["descriptions"]


def test_a_field_written_by_the_phone_is_read_the_same_way_here(contract):
    for case in contract["reads"]:
        for flag in case["set"]:
            assert flags.has_flag(case["field"], flag), f"{case['field']!r}: {flag} should be set"
        for flag in case["not_set"]:
            assert not flags.has_flag(case["field"], flag), f"{case['field']!r}: {flag} should not be set"


def test_a_flag_turned_here_is_written_as_the_phone_would_write_it(contract):
    for case in contract["toggles"]:
        result = flags.toggle_flag(case["field"], case["flag"])
        assert result == case["expect_field"], (
            f"toggling {case['flag']} in {case['field']!r}"
        )
        actually_set = [f.name for f in flags.ALL if flags.has_flag(result, f.name)]
        assert actually_set == case["expect_set"] or sorted(actually_set) == sorted(
            case["expect_set"]
        )


def test_nothing_written_by_either_side_grows_a_stray_space(contract):
    for case in contract["toggles"]:
        result = flags.toggle_flag(case["field"], case["flag"])
        assert "  " not in result
        assert result == result.strip()

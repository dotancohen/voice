"""The five flags of a transcription.

They are words written into the transcription's own record and synced to
every device, so their spelling is not a detail of one screen: this
application writing "polish" where the Android one writes "polished" would
leave the two disagreeing about the same transcription for good. The wording
is also printed in both user manuals, so it is pinned here.
"""

from __future__ import annotations

import pytest

from core import transcription_flags as flags


def test_there_are_five_in_the_order_a_transcription_lives_through_them():
    assert [f.name for f in flags.ALL] == [
        "original",
        "verified",
        "verbatim",
        "cleaned",
        "polished",
    ]


def test_each_has_a_title_and_a_line_saying_what_it_means():
    for flag in flags.ALL:
        assert flag.title, flag.name
        assert flag.description, flag.name
        assert flag.title == flag.name.capitalize()


def test_the_wording_is_the_wording_the_user_manuals_carry():
    # Both manuals print this table, and so does the Android application.
    # Changing a line here means changing it in three places, and this test
    # is the reminder.
    assert {f.name: f.description for f in flags.ALL} == {
        "original": "Unmodified transcription from the service",
        "verified": "User has verified the transcription is accurate",
        "verbatim": "Transcription includes filler words, false starts, etc.",
        "cleaned": "Transcription has been cleaned up (remove filler words)",
        "polished": "Transcription has been edited for readability",
    }


def test_no_flag_is_written_twice_and_none_carries_the_negation_mark():
    tags = [f.name for f in flags.ALL]
    assert len(tags) == len(set(tags))
    for tag in tags:
        assert not tag.startswith("!")
        assert " " not in tag


def test_a_new_transcription_is_original_and_nothing_else():
    fresh = flags.DEFAULT_FLAGS
    assert flags.has_flag(fresh, "original")
    for tag in ("verified", "verbatim", "cleaned", "polished"):
        assert not flags.has_flag(fresh, tag)


def test_the_default_flags_name_all_five_so_nothing_is_left_unsaid():
    words = flags.DEFAULT_FLAGS.split(" ")
    assert len(words) == 5
    for flag in flags.ALL:
        assert flag.name in words or f"!{flag.name}" in words


def test_the_default_flags_are_the_ones_the_database_has_always_written():
    # Rows written before this module existed have exactly this string.
    assert flags.DEFAULT_FLAGS == "original !verified !verbatim !cleaned !polished"


@pytest.mark.parametrize("flag", [f.name for f in flags.ALL])
def test_every_one_of_the_five_can_be_turned_on_and_off_again(flag):
    start = flags.DEFAULT_FLAGS
    was_on = flags.has_flag(start, flag)

    once = flags.toggle_flag(start, flag)
    assert flags.has_flag(once, flag) is (not was_on)

    twice = flags.toggle_flag(once, flag)
    assert flags.has_flag(twice, flag) is was_on


def test_turning_one_on_leaves_the_other_four_alone():
    before = flags.DEFAULT_FLAGS
    after = flags.toggle_flag(before, "verified")
    for flag in flags.ALL:
        if flag.name == "verified":
            continue
        assert flags.has_flag(after, flag.name) == flags.has_flag(before, flag.name)


def test_a_flag_is_not_matched_by_a_longer_flag_that_starts_with_it():
    assert not flags.has_flag("verbatim verified_by_me", "verb")
    assert not flags.has_flag("verified_by_me", "verified")
    assert flags.has_flag("verbatim verified_by_me", "verbatim")


def test_the_negation_is_a_word_of_its_own():
    assert flags.has_flag("!verified", "!verified")
    assert not flags.has_flag("!verified", "verified")


def test_a_flag_that_was_never_mentioned_is_added_as_set():
    assert flags.toggle_flag("original", "polished") == "original polished"


def test_a_toggle_never_leaves_a_doubled_or_an_outer_space():
    for start in ("original verified", "original", "!verified", ""):
        result = flags.toggle_flag(start, "verified")
        assert "  " not in result
        assert result == result.strip()


def test_toggling_on_an_empty_field_produces_just_that_flag():
    assert flags.toggle_flag("", "verified") == "verified"


def test_a_field_written_with_sloppy_spacing_is_still_read_correctly():
    field = "  original   !verified "
    assert flags.has_flag(field, "original")
    assert not flags.has_flag(field, "verified")
    assert flags.toggle_flag(field, "verified") == "original verified"


def test_a_toggle_keeps_every_flag_it_did_not_touch():
    start = "original !verified verbatim !cleaned polished"
    result = flags.toggle_flag(start, "cleaned")
    untouched = [w for w in start.split(" ") if not w.endswith("cleaned")]
    assert [w for w in result.split(" ") if not w.endswith("cleaned")] == untouched
    assert flags.has_flag(result, "cleaned")

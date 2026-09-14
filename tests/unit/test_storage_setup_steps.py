"""The bucket wizard's console steps: the names it asks for and the order of
the screens (Stage 8 step 1)."""

from __future__ import annotations

import re

from src.core import storage_setup


def test_the_user_and_the_policy_share_four_random_digits() -> None:
    user, policy = storage_setup.console_names()
    m_user = re.fullmatch(r"voice-(\d{4})", user)
    m_policy = re.fullmatch(r"Voice-Recordings-(\d{4})", policy)
    assert m_user and m_policy, (user, policy)
    assert m_user.group(1) == m_policy.group(1)


def test_each_run_draws_new_digits() -> None:
    drawn = {storage_setup.console_names()[0] for _ in range(50)}
    assert len(drawn) > 1


def test_the_policy_is_made_before_the_user_and_both_are_named() -> None:
    steps = storage_setup.console_steps("voice-1234", "Voice-Recordings-1234")
    policy_step = storage_setup.POLICY_STEP - 1
    assert "Create policy" in steps[policy_step]
    assert "Policy name type Voice-Recordings-1234" in steps[policy_step]
    user_step = next(i for i, s in enumerate(steps) if "Create user" in s)
    assert user_step > policy_step
    assert "User name type voice-1234" in steps[user_step]
    assert "type Voice-Recordings-1234, tick the box beside it" in steps[user_step]
    assert any("click voice-1234" in s and "Create access key" in s for s in steps)


def test_no_step_names_a_policy_the_user_never_made_or_a_page_without_a_click() -> None:
    text = " ".join(storage_setup.console_steps("voice-1234", "Voice-Recordings-1234"))
    assert "voice-bucket" not in text
    assert "Back on the user page" not in text
    assert "Name it voice." not in text


def test_each_console_page_keeps_its_values_apart_for_a_copy_button() -> None:
    pages = storage_setup.console_pages("voice-1234", "Voice-Recordings-1234")
    assert [title for title, _ in pages] == ["Open the Amazon console", "Make the policy", "Make the user", "Make the access key", "Enter the key"]
    values = {value for _, lines in pages for _, value in lines if value}
    assert values == {storage_setup.CONSOLE_URL, "voice-1234", "Voice-Recordings-1234"}
    for _, lines in pages:
        for words, value in lines:
            assert (value is None) == ("{}" not in words), words


def test_the_service_is_named_in_the_waiting_and_storing_sentences() -> None:
    assert storage_setup.waiting_sentence("") == "Waiting for a response from Amazon…"
    assert storage_setup.provider_name("https://nbg1.your-objectstorage.com") == "Hetzner"
    assert storage_setup.provider_name("https://s3.eu-central-003.backblazeb2.com") == "Backblaze"
    assert storage_setup.provider_name("https://ams3.digitaloceanspaces.com") == "DigitalOcean"
    assert storage_setup.provider_name("https://minio.בית.example:9000") == "minio.בית.example"
    assert storage_setup.stores_files_sentence("") == (
        "Amazon stores files only, not notes' content. For full note syncing, be sure to configure sync between devices."
    )

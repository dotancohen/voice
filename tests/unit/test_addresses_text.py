"""The words for this device's address (LISTEN-4)."""

from __future__ import annotations

from src.core.addresses_text import address_words

CANDIDATES = "Only one of these addresses is correct; this device could not tell which. Another device tries each of them in turn."


def test_the_address_found_is_said_alone() -> None:
    assert address_words({"detected": True, "shown": ["https://192.168.1.23:8384"], "urls": ["https://192.168.1.23:8384", "https://10.0.0.5:8384"], "sentence": ""}) == "https://192.168.1.23:8384"


def test_candidates_are_said_with_the_sentence_that_only_one_is_correct() -> None:
    words = address_words({"detected": False, "shown": ["https://192.168.1.23:8384", "https://10.0.0.5:8384"], "urls": [], "sentence": CANDIDATES})
    assert words == f"https://192.168.1.23:8384, https://10.0.0.5:8384. {CANDIDATES}"


def test_no_address_is_said_in_words() -> None:
    assert address_words({"detected": False, "shown": [], "urls": [], "sentence": "No address on a local network was found. Is this device on a network?"}).startswith("No address")


def test_the_real_listener_answers_in_the_same_shape() -> None:
    from voicecore import listen_addresses

    found = listen_addresses(8384)
    assert set(found) == {"detected", "shown", "urls", "sentence"}
    assert all(url.endswith(":8384") for url in found["urls"])
    assert not any("127.0.0.1" in url for url in found["urls"])
    assert found["shown"] == found["urls"][: len(found["shown"])], "what is shown is tried first"
    assert address_words(found)

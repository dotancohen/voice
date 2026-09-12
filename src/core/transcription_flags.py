"""The five flags of a transcription.

They are flags rather than one state because any number of them can be true
at once: a transcription can be verified and cleaned, or verbatim and not yet
verified.

They are kept in the transcription's ``state`` field — a space-separated list
of words, each either set (``verified``) or explicitly not (``!verified``).
That field name is the one in the database and in the sync protocol, shared
with every installation that has already synced, so it stays as it is;
everything above the database calls them flags. Every application that
touches the field has to agree on the five words and on what they mean; the
same five lines appear in this application's user manual and in the Android
one, word for word.

The order is the life of a transcription: what came out of the service,
whether a person has checked it, and then the three ways it may have been
rewritten since.
"""

from __future__ import annotations

from typing import List, NamedTuple

ORIGINAL = "original"
VERIFIED = "verified"
VERBATIM = "verbatim"
CLEANED = "cleaned"
POLISHED = "polished"


class TranscriptionFlag(NamedTuple):
    """One of the things that can be said about a transcription."""

    name: str
    """The word written in the transcription's stored state field."""

    title: str
    """What the user reads."""

    description: str
    """What it means, in one line."""


ALL: List[TranscriptionFlag] = [
    TranscriptionFlag(
        ORIGINAL,
        "Original",
        "Unmodified transcription from the service",
    ),
    TranscriptionFlag(
        VERIFIED,
        "Verified",
        "User has verified the transcription is accurate",
    ),
    TranscriptionFlag(
        VERBATIM,
        "Verbatim",
        "Transcription includes filler words, false starts, etc.",
    ),
    TranscriptionFlag(
        CLEANED,
        "Cleaned",
        "Transcription has been cleaned up (remove filler words)",
    ),
    TranscriptionFlag(
        POLISHED,
        "Polished",
        "Transcription has been edited for readability",
    ),
]

DEFAULT_FLAGS = " ".join(f.name if f.name == ORIGINAL else f"!{f.name}" for f in ALL)
"""The flags a transcription is created with: original, and nothing else."""


def flag_words(flags: str) -> List[str]:
    """The words in a flag field, with the blanks dropped.

    Splitting an empty string yields one empty word, which would otherwise be
    written back out as a leading space.
    """
    return [word for word in flags.split(" ") if word.strip()]


def has_flag(flags: str, flag: str) -> bool:
    """Whether ``flag`` is set in the field ``flags``.

    A flag that is absent is not set: only the word itself counts, so
    ``verbatim`` never answers for ``verb``, and ``!verified`` is not
    ``verified``.
    """
    return flag in flag_words(flags)


def toggle_flag(flags: str, flag: str) -> str:
    """``flags`` with ``flag`` turned the other way round.

    Set becomes explicitly not set, not set becomes set, and a flag the field
    never mentioned is added as set. The other words keep their order.
    """
    words = flag_words(flags)
    negated = f"!{flag}"

    if flag in words:
        words.remove(flag)
        words.append(negated)
    elif negated in words:
        words.remove(negated)
        words.append(flag)
    else:
        words.append(flag)

    return " ".join(words)

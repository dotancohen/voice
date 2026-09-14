"""The words for where this device's listener can be reached (LISTEN-4): one
text for the Sync window, About, the code and the command line."""

from __future__ import annotations

from typing import Any, Dict


def address_words(addresses: Dict[str, Any]) -> str:
    """The address found through this machine's route; or, when it could not
    be told, every candidate followed by the sentence saying that only one of
    them is correct; or the sentence that no address was found."""
    shown = addresses.get("shown") or []
    if not shown:
        return addresses.get("sentence") or ""
    if addresses.get("detected"):
        return shown[0]
    return f"{', '.join(shown)}. {addresses.get('sentence', '')}".strip()

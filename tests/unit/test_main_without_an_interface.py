"""Starting Voice without naming an interface.

On 2026-09-13 ``python -m src.main`` crashed with "'Namespace' object has no
attribute 'config_dir'": when no interface is named, startup parses the
command line a second time with the default interface inserted, and that
second parse lost the account it had already resolved. Every other test
names an interface, so none took this path.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

import src.main as voice_main


def test_the_default_interface_starts_with_the_account_already_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "voice"
    monkeypatch.setenv("VOICE_CONFIG_DIR", str(root))
    monkeypatch.delenv("VOICE_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(sys, "argv", ["voice"])
    # The default interface is the GUI; what it is given is the question,
    # not whether a window opens
    monkeypatch.setattr(voice_main, "get_default_interface", lambda config_dir, root=None: "gui")
    started = {}

    def run_gui(config_dir, args):
        started["config_dir"] = config_dir
        started["config_root"] = args.config_root
        started["has_label"] = hasattr(args, "account_label")
        started["interface"] = args.interface
        return 0

    monkeypatch.setattr(voice_main, "run_gui", run_gui)
    handlers = list(logging.getLogger().handlers)
    try:
        with pytest.raises(SystemExit) as exit_:
            voice_main.main()
    finally:
        for handler in logging.getLogger().handlers[len(handlers):]:
            logging.getLogger().removeHandler(handler)
            handler.close()

    assert exit_.value.code == 0
    assert started["interface"] == "gui"
    assert started["config_root"] == root
    assert started["config_dir"] is not None and Path(started["config_dir"]).is_relative_to(root)
    assert started["has_label"]

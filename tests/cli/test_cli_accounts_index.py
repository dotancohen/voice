"""Several accounts on one installation (ACCT-6..ACCT-9), from the command line."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def run(root: Path, *args: str, account: str | None = None, env_account: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "VOICE_CONFIG_DIR": str(root)}
    env.pop("VOICE_ACCOUNT_ID", None)
    if env_account:
        env["VOICE_ACCOUNT_ID"] = env_account
    cmd = [sys.executable, "-m", "src.main"]
    if account:
        cmd += ["-a", account]
    cmd += ["cli", "--format", "json", *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def shown(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


@pytest.mark.cli
class TestAccountsOnOneInstallation:
    def test_a_first_run_makes_an_index_and_a_default_account(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        first = shown(run(root, "account", "show"))
        assert (root / "accounts.db").is_file()
        assert (root / "config.json").is_file(), "the machine's own file"
        assert (root / first["account_id"] / "notes.db").is_file()
        assert (root / first["account_id"] / "audio").is_dir()
        listed = shown(run(root, "account", "list"))
        assert [a["label"] for a in listed] == ["default"]
        assert listed[0]["is_default"] is True
        again = shown(run(root, "account", "show"))
        assert again["account_id"] == first["account_id"], "a second run opens the same account"

    def test_two_accounts_are_two_databases_and_two_audio_directories(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        me = shown(run(root, "account", "show"))
        created = shown(run(root, "account", "create", "--label", "sillyberry"))
        assert created["label"] == "sillyberry"
        assert created["account_id"] != me["account_id"]

        theirs = shown(run(root, "account", "show", account="sillyberry"))
        assert theirs["account_id"] == created["account_id"]
        assert theirs["directory"] == created["directory"]
        assert Path(theirs["directory"]).name == created["account_id"]
        assert shown(run(root, "account", "show"))["account_id"] == me["account_id"], "the default is unchanged"
        assert shown(run(root, "account", "show", env_account="sillyberry"))["account_id"] == created["account_id"]

        me_cfg = json.loads((root / me["account_id"] / "config.json").read_text())
        their_cfg = json.loads((root / created["account_id"] / "config.json").read_text())
        assert me_cfg["audiofile_directory"] != their_cfg["audiofile_directory"], "recordings are never shared"
        machine = json.loads((root / "config.json").read_text())
        assert me_cfg["this_device_id"] == their_cfg["this_device_id"] == machine["this_device_id"], "one device"

    def test_the_default_can_be_changed_and_a_label_must_be_unique(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        run(root, "account", "show")
        created = shown(run(root, "account", "create", "--label", "work"))
        duplicate = run(root, "account", "create", "--label", "work")
        assert duplicate.returncode == 1
        assert "already labelled" in duplicate.stderr

        switched = run(root, "account", "default", "work")
        assert switched.returncode == 0, switched.stderr
        assert shown(run(root, "account", "show"))["account_id"] == created["account_id"]
        unknown = run(root, "account", "show", account="nobody")
        assert unknown.returncode == 1
        assert "No account is called or numbered nobody" in unknown.stderr

    def test_a_directory_that_holds_one_database_is_the_account_itself(self, tmp_path: Path) -> None:
        root = tmp_path / "single"
        root.mkdir()
        from core.database import Database
        Database(root / "notes.db").close()
        (root / "config.json").write_text(json.dumps({"database_file": str(root / "notes.db")}))
        assert shown(run(root, "account", "show"))["directory"] == str(root)
        assert not (root / "accounts.db").exists(), "no index is made for a single directory"
        refused = run(root, "account", "show", account="x")
        assert refused.returncode == 1
        assert "cannot select" in refused.stderr

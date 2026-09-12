"""Settings that follow the user across devices.

Most of ``config.json`` is local (paths, ports, colours). A few values are
about the user rather than the machine and are stored in the versioned
``synced_settings`` table of the database so that every device shares them:

- ``transcription.preferred_languages`` (JSON list of ISO 639-1 codes)
- ``transcription.providers.<provider>.api_key`` (one per cloud provider)

The local config file acts as a cache of the synced value: on startup
:func:`reconcile_transcription_settings` copies synced values into the config
and seeds the database from the config when the database has none. To change a
synced value use :func:`set_synced_setting` (CLI: ``settings set``), which
writes both.

Concurrent changes on two devices are merged by voicecore like any other
field: the later value is kept and a conflict is flagged.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .config import Config
from .database import Database

logger = logging.getLogger(__name__)

KEY_PREFERRED_LANGUAGES = "transcription.preferred_languages"
PROVIDER_PREFIX = "transcription.providers."
API_KEY_SUFFIX = ".api_key"


def provider_api_key_setting(provider: str) -> str:
    """Synced setting key holding a provider's API key."""
    return f"{PROVIDER_PREFIX}{provider}{API_KEY_SUFFIX}"


def _parse_provider(key: str) -> Optional[str]:
    if key.startswith(PROVIDER_PREFIX) and key.endswith(API_KEY_SUFFIX):
        provider = key[len(PROVIDER_PREFIX):-len(API_KEY_SUFFIX)]
        return provider or None
    return None


def _parse_languages(value: Optional[str]) -> Optional[List[str]]:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        # Tolerate a plain comma-separated list typed by hand
        parsed = [v.strip() for v in value.split(",") if v.strip()]
    if not isinstance(parsed, list):
        return None
    return [str(v) for v in parsed]


def reconcile_transcription_settings(config: Config, db: Database) -> Dict[str, Any]:
    """Bring the local transcription config in line with the synced settings.

    Synced values win over the local file; a local value seeds the database
    only when the database has no value yet. Returns the effective config.
    """
    tcfg = config.get_transcription_config() or {}
    changed = False

    # Preferred languages
    local_langs = tcfg.get("preferred_languages")
    synced_langs = _parse_languages(db.get_setting(KEY_PREFERRED_LANGUAGES))
    if synced_langs is not None:
        if synced_langs != local_langs:
            tcfg["preferred_languages"] = synced_langs
            changed = True
    elif local_langs:
        db.set_setting(KEY_PREFERRED_LANGUAGES, json.dumps(local_langs))

    # Provider API keys: local first (seeding), then anything synced from elsewhere
    providers: Dict[str, Any] = tcfg.setdefault("providers", {})
    for provider, pcfg in list(providers.items()):
        if not isinstance(pcfg, dict):
            continue
        key = provider_api_key_setting(provider)
        synced = db.get_setting(key)
        local = pcfg.get("api_key")
        if synced is not None:
            if synced != local:
                pcfg["api_key"] = synced
                changed = True
        elif local:
            db.set_setting(key, local)

    for key, value in db.get_all_settings().items():
        provider = _parse_provider(key)
        if provider is None or value is None:
            continue
        pcfg = providers.get(provider)
        if not isinstance(pcfg, dict):
            providers[provider] = {"api_key": value}
            changed = True
        elif pcfg.get("api_key") != value:
            pcfg["api_key"] = value
            changed = True

    if changed:
        config.set_transcription_config(tcfg)
        logger.info("Transcription settings updated from synced settings")
    return tcfg


def set_synced_setting(config: Config, db: Database, key: str, value: str) -> None:
    """Set a synced setting and mirror it into the local config where relevant."""
    db.set_setting(key, value)
    if key == KEY_PREFERRED_LANGUAGES:
        langs = _parse_languages(value)
        if langs is None:
            raise ValueError("preferred_languages must be a JSON list of language codes")
        tcfg = config.get_transcription_config() or {}
        tcfg["preferred_languages"] = langs
        config.set_transcription_config(tcfg)
        return
    provider = _parse_provider(key)
    if provider:
        tcfg = config.get_transcription_config() or {}
        providers = tcfg.setdefault("providers", {})
        pcfg = providers.setdefault(provider, {})
        if isinstance(pcfg, dict):
            pcfg["api_key"] = value
        config.set_transcription_config(tcfg)

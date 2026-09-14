"""Deleting the files of recordings removed for good (FILE-15).

The core removes the rows and says which recordings went, each with the name
its file has on this device. Where this platform keeps recordings is the
application's business, and a file is found only by the name its row stored:
never by the recording's id.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

logger = logging.getLogger(__name__)


def remove_purged_files(purged: Iterable[Dict[str, str]], directory: Optional[Union[str, Path]]) -> List[Path]:
    """Delete the file of each purged recording from ``directory``; return the
    paths deleted. A recording whose row named no file, or whose file is not
    there, deletes nothing."""
    removed: List[Path] = []
    if not directory:
        return removed
    folder = Path(directory)
    for recording in purged:
        disk_name = recording.get("disk_name") or ""
        if not disk_name or Path(disk_name).name != disk_name:
            continue
        path = folder / disk_name
        if not path.is_file():
            continue
        try:
            path.unlink()
            removed.append(path)
        except OSError as e:
            logger.warning(f"Could not delete {path}: {e}")
    return removed

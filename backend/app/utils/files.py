"""Small file helpers shared by services."""
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("legal-ai.files")


def remove_quietly(path: Path) -> None:
    """Delete a file, but never let a failed delete hide the error being handled.

    This is for clean-up after something else went wrong. On Windows a file can
    be briefly locked by an antivirus scan, OneDrive or another process, and
    the user should still be told the real reason their upload was rejected.
    """
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not remove %s: %s", Path(path).name, exc)


def atomic_write_json(path: Path, data: Any, indent: Optional[int] = None) -> None:
    """Write JSON so a crash can never leave a half-written file behind.

    The data goes to a temporary file in the same folder first and is then
    swapped into place in one step. OSError is raised on failure; callers
    turn it into the right application error for their own context.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=indent)
        os.replace(tmp_name, path)
    except OSError:
        Path(tmp_name).unlink(missing_ok=True)
        raise

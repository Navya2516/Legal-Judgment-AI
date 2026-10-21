"""Saved analysis results (summary, provision explanations, continuation insights, translations): one JSON file each."""
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends

from app.config import Settings, get_settings
from app.utils.errors import StorageError
from app.utils.files import atomic_write_json

logger = logging.getLogger("legal-ai.results")

_DOC_ID = re.compile(r"^[a-f0-9]{32}$")
# A kind is "summary", "provisions" or "continuation", optionally with a language code for a
# translation: "summary.ta". Anything else is rejected, so a kind can never
# be used to reach another file on disk.
_KIND = re.compile(r"^(summary|provisions|continuation)(\.[a-z]{2})?$")


class ResultStore:
    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)

    def _path(self, doc_id: str, kind: str) -> Path:
        if not _DOC_ID.match(doc_id) or not _KIND.match(kind):
            raise ValueError("invalid result key")
        return self._dir / f"{doc_id}.{kind}.json"

    def save(self, doc_id: str, kind: str, data: dict[str, Any]) -> None:
        try:
            atomic_write_json(self._path(doc_id, kind), data)
        except OSError as exc:
            logger.error("Cannot save %s for %s: %s", kind, doc_id, exc)
            raise StorageError("The result could not be saved.") from exc

    def load(self, doc_id: str, kind: str) -> Optional[dict[str, Any]]:
        path = self._path(doc_id, kind)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.error("Cannot read %s for %s: %s", kind, doc_id, exc)
            raise StorageError("The saved result could not be read. Generate it again.") from exc

    def delete_all(self, doc_id: str) -> None:
        if not _DOC_ID.match(doc_id):
            raise ValueError("invalid result key")
        # Every saved result of this document, translations included.
        for path in self._dir.glob(f"{doc_id}.*.json"):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.error("Cannot delete %s: %s", path.name, exc)
                raise StorageError("Saved results could not be deleted.") from exc


def get_result_store(settings: Settings = Depends(get_settings)) -> ResultStore:
    return ResultStore(settings.results_path)

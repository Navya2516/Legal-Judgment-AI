"""Where extracted page text is kept: one JSON file per document.

Phase 4 (chunking and embeddings) reads its input from here.
"""
import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import Depends
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.schemas.documents import PageText
from app.utils.errors import StorageError
from app.utils.files import atomic_write_json

logger = logging.getLogger("legal-ai.pages")

_DOC_ID = re.compile(r"^[a-f0-9]{32}$")


class PageStore:
    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)

    def path_for(self, doc_id: str) -> Path:
        if not _DOC_ID.match(doc_id):  # defence in depth: never trust an id as a path
            raise ValueError("invalid document id")
        return self._directory / f"{doc_id}.json"

    def save(self, doc_id: str, pages: list[PageText]) -> None:
        payload: dict[str, Any] = {
            "document_id": doc_id,
            "page_count": len(pages),
            "pages": [page.model_dump(mode="json") for page in pages],
        }
        try:
            atomic_write_json(self.path_for(doc_id), payload)
        except OSError as exc:
            logger.error("Cannot save pages for %s: %s", doc_id, exc)
            raise StorageError("The extracted text could not be saved.") from exc

    def load(self, doc_id: str) -> list[PageText]:
        path = self.path_for(doc_id)
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return [PageText.model_validate(item) for item in payload["pages"]]
        except (OSError, ValueError, KeyError, ValidationError) as exc:
            logger.error("Cannot load pages for %s: %s", doc_id, exc)
            raise StorageError("The extracted text could not be read.") from exc

    def delete(self, doc_id: str) -> None:
        try:
            self.path_for(doc_id).unlink(missing_ok=True)
        except OSError as exc:
            logger.error("Cannot delete pages for %s: %s", doc_id, exc)
            raise StorageError("The extracted text could not be deleted.") from exc


def get_page_store(settings: Settings = Depends(get_settings)) -> PageStore:
    return PageStore(settings.extracted_path)

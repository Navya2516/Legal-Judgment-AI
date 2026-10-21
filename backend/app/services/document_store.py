"""A small JSON-file registry of uploaded documents.

It remembers each document's id, filename, status and page count. JSON is
enough for one user on one machine; if the project ever needs several
servers or many users, this class is the only place to swap for a database.
"""
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from app.config import get_settings
from app.schemas.documents import DocumentRecord
from app.utils.errors import StorageError
from app.utils.files import atomic_write_json

logger = logging.getLogger("legal-ai.store")

INTERRUPTED_MESSAGE = (
    "Processing was interrupted because the server restarted. "
    "Please upload the file again."
)


class DocumentStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()

    # ---- file access -------------------------------------------------
    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("registry root must be a JSON object")
            return data
        except (OSError, ValueError) as exc:
            logger.error("Cannot read registry %s: %s", self._path, exc)
            raise StorageError("The document registry could not be read.") from exc

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        try:
            atomic_write_json(self._path, data, indent=2)
        except OSError as exc:
            logger.error("Cannot write registry %s: %s", self._path, exc)
            raise StorageError("The document registry could not be saved.") from exc

    @staticmethod
    def _parse(raw: dict[str, Any]) -> DocumentRecord:
        try:
            return DocumentRecord.model_validate(raw)
        except ValidationError as exc:
            logger.error("Corrupt registry entry: %s", exc)
            raise StorageError("A document record is corrupted.") from exc

    # ---- public API --------------------------------------------------
    def list(self) -> list[DocumentRecord]:
        with self._lock:
            records = [self._parse(raw) for raw in self._load().values()]
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def get(self, doc_id: str) -> Optional[DocumentRecord]:
        with self._lock:
            raw = self._load().get(doc_id)
        return self._parse(raw) if raw is not None else None

    def add(
        self, filename: str, *, doc_id: Optional[str] = None, **fields: Any
    ) -> DocumentRecord:
        record = DocumentRecord(
            id=doc_id or uuid.uuid4().hex,
            filename=filename,
            created_at=datetime.now(timezone.utc),
            **fields,
        )
        with self._lock:
            data = self._load()
            data[record.id] = record.model_dump(mode="json")
            self._save(data)
        return record

    def update(self, doc_id: str, **fields: Any) -> Optional[DocumentRecord]:
        with self._lock:
            data = self._load()
            raw = data.get(doc_id)
            if raw is None:
                return None
            updated = self._parse({**raw, **fields})
            data[doc_id] = updated.model_dump(mode="json")
            self._save(data)
        return updated

    def delete(self, doc_id: str) -> bool:
        with self._lock:
            data = self._load()
            if doc_id not in data:
                return False
            del data[doc_id]
            self._save(data)
        return True

    def fail_interrupted(self) -> int:
        """Mark documents stuck in 'processing' as failed.

        Processing runs in the background, so a server restart kills it
        half-way. Called at startup so nothing is left "processing" forever.
        """
        with self._lock:
            data = self._load()
            count = 0
            for raw in data.values():
                if raw.get("status") == "processing":
                    raw["status"] = "failed"
                    raw["error"] = INTERRUPTED_MESSAGE
                    count += 1
                if raw.get("index_status") == "indexing":
                    raw["index_status"] = "failed"
                    raw["index_error"] = INTERRUPTED_MESSAGE
                    count += 1
            if count:
                self._save(data)
        return count


@lru_cache
def get_document_store() -> DocumentStore:
    return DocumentStore(get_settings().registry_path)

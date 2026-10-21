"""Record exactly what produced a result, so it can be reproduced or questioned."""
import importlib.metadata
import platform
import sys
from datetime import datetime, timezone

from app.config import Settings

PACKAGES = ["pymupdf", "sentence-transformers", "faiss-cpu", "numpy", "google-genai", "pydantic", "rapidocr-onnxruntime"]

# Settings that change results. The API key is never recorded.
SETTING_FIELDS = [
    "llm_provider", "gemini_model", "embedding_model", "chunk_size", "chunk_overlap", "top_k",
    "llm_max_context_chars", "llm_temperature", "llm_max_output_tokens", "gemini_thinking_level",
    "llm_retries", "llm_drop_unverified", "translation_batch_size", "ocr_enabled", "ocr_dpi",
]


def _version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def build_manifest(settings: Settings, *, command: str, seed: int, documents: list[dict]) -> dict:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": command,
        "seed": seed,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": {p: _version(p) for p in PACKAGES},
        "settings": {f: getattr(settings, f, None) for f in SETTING_FIELDS},
        "documents": documents,
    }

r"""TESTING ONLY. Starts the real backend with a scripted fake language model.

The fake model returns canned, obviously artificial text that quotes whatever
passage it is given. It exists so the whole app (upload, processing, summary,
translation, questions) can be exercised in a browser without an API key or
quota. Nothing it produces says anything about real model quality. Data lives
in a temporary folder that is deleted when the server stops.

    cd backend
    python ..\e2e\server.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import uvicorn  # noqa: E402

import app.main as main_module  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.routes.documents import get_ocr_factory  # noqa: E402
from app.services.document_store import DocumentStore, get_document_store  # noqa: E402
from app.services.embedder import get_embedder_factory  # noqa: E402
from app.services.llm import get_llm_factory  # noqa: E402
from tests.conftest import FakeEmbedder, FakeLlm, FakeOcr  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="jx-e2e-"))
settings = Settings(
    _env_file=None,
    upload_dir=str(tmp / "uploads"), extracted_dir=str(tmp / "extracted"),
    index_dir=str(tmp / "indexes"), results_dir=str(tmp / "results"),
    embedding_model="fake-hash-embedder", gemini_api_key="",
)
store = DocumentStore(tmp / "documents.json")
llm, embedder, ocr = FakeLlm(), FakeEmbedder(), FakeOcr()

app.dependency_overrides[get_document_store] = lambda: store
app.dependency_overrides[get_settings] = lambda: settings
app.dependency_overrides[get_ocr_factory] = lambda: (lambda: ocr)
app.dependency_overrides[get_embedder_factory] = lambda: (lambda: embedder)
app.dependency_overrides[get_llm_factory] = lambda: (lambda: llm)
main_module.settings = settings
main_module.get_document_store = lambda: store

if __name__ == "__main__":
    try:
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

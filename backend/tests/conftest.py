import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings, get_settings
from app.main import app
from app.routes.documents import get_ocr_factory
from app.services.document_store import DocumentStore, get_document_store
from app.services.embedder import get_embedder_factory
from app.services.index_store import IndexStore
from app.services.llm import get_llm_factory
from tests import pdf_factory


class FakeOcr:
    """Stands in for the real OCR engine: fast, and returns known text."""

    name = "fake"

    def __init__(self, text: str = "OCR TEXT FROM FAKE ENGINE for the scanned page."):
        self.text = text
        self.calls = 0

    def recognize(self, image: np.ndarray) -> str:
        assert image.ndim == 3 and image.shape[2] == 3
        self.calls += 1
        return self.text


class FakeEmbedder:
    """Deterministic bag-of-words embedder: texts sharing words get similar vectors.

    It lets the tests check the retrieval *logic* (ranking, pages, persistence)
    quickly and offline. It says nothing about the real model's quality, which
    is measured separately on real judgments.
    """

    name = "fake-hash-embedder"
    dim = 256

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        import re
        import zlib

        self.calls += 1
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                out[row, zlib.crc32(word.encode()) % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


class FakeLlm:
    """A stand-in for Gemini. Produces valid JSON that quotes the text it was given.

    Tests can queue exact replies with `replies`, or let it answer by itself.
    It records every call so tests can inspect the prompts.
    """

    name = "fake-llm"

    def __init__(self):
        self.calls = []
        self.replies = []

    def generate(self, *, system, prompt):
        self.calls.append({"system": system, "prompt": prompt})
        if self.replies:
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        return self._answer(prompt)

    @staticmethod
    def _quote(text, words=12):
        return " ".join(text.split()[:words])

    NATIVE_WORD = {"ta": "தமிழ்", "hi": "हिन्दी", "te": "తెలుగు", "ml": "മലയാളം", "kn": "ಕನ್ನಡ"}

    def _translate(self, prompt):
        """A fake translation: every word without a digit becomes a word in the target script."""
        import json
        import re

        code = re.search(r"\(code (\w+)\)", prompt).group(1)
        block = prompt.split("<items>")[1].split("</items>")[0]
        out = []
        for item_id, text in re.findall(r"^\[([A-Za-z0-9_.]+)\] (.*)$", block, re.M):
            words = [w if re.search(r"\d", w) else self.NATIVE_WORD[code] for w in text.split()]
            out.append({"id": item_id, "text": " ".join(words)})
        return json.dumps({"translations": out})

    def _answer(self, prompt):
        import json
        import re

        if "TRANSLATE_TASK" in prompt:
            return self._translate(prompt)
        if "ASK_TASK" in prompt:
            blocks = re.findall(r"\[Pages? (\d+)(?:-\d+)?\]\n(.*?)(?=\n\n\[Pages? |\n</judgment_text>)", prompt, re.S)
            page, text = blocks[0]
            return json.dumps({"answerable": True, "points": [
                {"text": "The judgment says this.", "pages": [int(page)], "quote": self._quote(text)}]})
        if "CONTINUATION_TASK" in prompt:
            blocks = re.findall(r"\[Pages? (\d+)(?:-\d+)?\]\n(.*?)(?=\n\n\[Pages? |\n</judgment_text>)", prompt, re.S)
            first_page, first_text = blocks[0]
            last_page, last_text = blocks[-1]
            return json.dumps({
                "disposition": {"label": "disposed_of", "text": "The case was disposed of.",
                                "pages": [int(last_page)], "quote": self._quote(last_text)},
                "directions": [{"text": "The court gave a direction.", "pages": [int(first_page)],
                                "quote": self._quote(first_text)}],
                "deadlines": [],
                "further_proceedings": [],
            })
        if "PROVISION_TASK" in prompt:
            notes = []
            for key, rest in re.findall(r"Provision: (.+?)\n((?:\[Page .*?(?:\n|$))+)", prompt):
                page, text = re.match(r"\[Page (\d+)\] (.*)", rest.splitlines()[0]).groups()
                notes.append({"key": key, "role_in_case": f"Discussed in the judgment ({key}).",
                              "pages": [int(page)], "quote": self._quote(text)})
            return json.dumps({"provisions": notes})
        blocks = re.findall(r"\[Pages? (\d+)(?:-\d+)?\]\n(.*?)(?=\n\n\[Pages? |\n</judgment_text>)", prompt, re.S)
        page, text = blocks[0]
        point = lambda label: [{"text": f"{label} point.", "pages": [int(page)], "quote": self._quote(text)}]
        return json.dumps({
            "case_title": "Test v. Test", "court": "Test Court", "date": None, "case_number": None,
            "plain_summary": point("Summary"), "facts": point("Fact"), "issues": point("Issue"),
            "holding": point("Holding"), "reasoning": point("Reason"), "final_order": point("Order"),
        })


@pytest.fixture
def fake_llm():
    return FakeLlm()


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture
def test_settings(tmp_path) -> Settings:
    """Settings that point every folder at a temporary directory."""
    return Settings(
        _env_file=None,
        upload_dir=str(tmp_path / "uploads"),
        extracted_dir=str(tmp_path / "extracted"),
        index_dir=str(tmp_path / "indexes"),
        results_dir=str(tmp_path / "results"),
        max_upload_mb=1,
        max_pages=50,
        ocr_min_chars=40,
        embedding_model="fake-hash-embedder",
        chunk_size=200,
        chunk_overlap=40,
        gemini_api_key="",
    )


@pytest.fixture
def store(tmp_path):
    """A document registry in a temporary folder, so tests never touch real data."""
    return DocumentStore(tmp_path / "documents.json")


@pytest.fixture
def fake_ocr():
    return FakeOcr()


@pytest.fixture
def client(store, test_settings, fake_ocr, fake_embedder, fake_llm, monkeypatch):
    app.dependency_overrides[get_document_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_ocr_factory] = lambda: (lambda: fake_ocr)
    app.dependency_overrides[get_embedder_factory] = lambda: (lambda: fake_embedder)
    app.dependency_overrides[get_llm_factory] = lambda: (lambda: fake_llm)
    monkeypatch.setattr(main_module, "settings", test_settings)
    monkeypatch.setattr(main_module, "get_document_store", lambda: store)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def text_pdf(tmp_path):
    return pdf_factory.make_text_pdf(tmp_path / "text.pdf")


@pytest.fixture
def scanned_pdf(tmp_path):
    return pdf_factory.make_scanned_pdf(tmp_path / "scan.pdf")


def upload(client, path, filename=None, content_type="application/pdf"):
    """POST a file to the upload endpoint."""
    with open(path, "rb") as handle:
        return client.post(
            "/api/v1/documents",
            files={"file": (filename or path.name, handle, content_type)},
        )

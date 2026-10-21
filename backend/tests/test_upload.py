"""Tests for the upload endpoint and the routes that read a processed document."""
import os
import sys
from pathlib import Path

import pytest

from app.main import app
from app.routes.documents import get_ocr_factory
from app.services.upload_service import validate_pdf
from tests import pdf_factory
from tests.conftest import upload

MISSING_ID = "0" * 32


def stored_files(test_settings):
    """Every file currently kept in the uploads and extracted-text folders."""
    found = []
    for folder in (test_settings.upload_path, test_settings.extracted_path):
        if folder.exists():
            found.extend(p.name for p in folder.iterdir())
    return sorted(found)


# ---- the happy path -----------------------------------------------------------
def test_upload_text_pdf_is_accepted_and_becomes_ready(client, text_pdf):
    response = upload(client, text_pdf)
    assert response.status_code == 202
    body = response.json()
    assert body["filename"] == "text.pdf"
    assert body["status"] == "processing"  # the immediate answer, before extraction
    assert body["page_count"] == 3
    assert body["size_bytes"] > 0
    assert response.headers["Location"] == f"/api/v1/documents/{body['id']}"

    record = client.get(f"/api/v1/documents/{body['id']}").json()
    assert record["status"] == "ready"
    assert record["pages_processed"] == 3
    assert record["char_count"] > 0
    assert record["ocr_pages"] == 0
    assert record["warnings"] == []
    assert record["error"] is None


def test_text_pdf_does_not_use_ocr(client, text_pdf, fake_ocr):
    upload(client, text_pdf)
    assert fake_ocr.calls == 0


def test_preview_has_page_markers_and_can_be_truncated(client, text_pdf):
    doc_id = upload(client, text_pdf).json()["id"]

    full = client.get(f"/api/v1/documents/{doc_id}/preview?chars=5000").json()
    assert full["truncated"] is False
    assert "[Page 1]" in full["preview"] and "[Page 3]" in full["preview"]
    # The PDF's own line breaks are kept ("Writ\nPetition"), so compare words only.
    assert "Writ Petition" in " ".join(full["preview"].split())
    assert full["page_count"] == 3

    short = client.get(f"/api/v1/documents/{doc_id}/preview?chars=200").json()
    assert short["truncated"] is True
    assert short["chars_returned"] <= 210


def test_pages_list_and_single_page(client, text_pdf):
    doc_id = upload(client, text_pdf).json()["id"]

    listing = client.get(f"/api/v1/documents/{doc_id}/pages").json()
    assert listing["total"] == 3
    assert [p["page_number"] for p in listing["pages"]] == [1, 2, 3]
    assert all(p["method"] == "text" for p in listing["pages"])
    assert "text" not in listing["pages"][0]  # the listing never carries the text

    page = client.get(f"/api/v1/documents/{doc_id}/pages/2").json()
    assert page["page_number"] == 2
    assert "Article 368" in page["text"]
    assert page["char_count"] == len(page["text"])


def test_page_outside_the_document_is_404(client, text_pdf):
    doc_id = upload(client, text_pdf).json()["id"]
    response = client.get(f"/api/v1/documents/{doc_id}/pages/99")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_page_zero_is_rejected(client, text_pdf):
    doc_id = upload(client, text_pdf).json()["id"]
    response = client.get(f"/api/v1/documents/{doc_id}/pages/0")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# ---- scanned documents -------------------------------------------------------
def test_scanned_pdf_is_read_with_ocr(client, scanned_pdf, fake_ocr, test_settings):
    test_settings.max_upload_mb = 40  # the generated 3-page scan is about 19 MB
    doc_id = upload(client, scanned_pdf).json()["id"]
    record = client.get(f"/api/v1/documents/{doc_id}").json()
    assert record["status"] == "ready"
    assert record["ocr_pages"] == 3
    assert fake_ocr.calls == 3
    assert any("OCR" in warning for warning in record["warnings"])

    page = client.get(f"/api/v1/documents/{doc_id}/pages/1").json()
    assert page["method"] == "ocr"


def test_scanned_pdf_without_ocr_fails_with_a_helpful_reason(
    client, scanned_pdf, test_settings
):
    test_settings.max_upload_mb = 40
    app.dependency_overrides[get_ocr_factory] = lambda: (lambda: None)
    doc_id = upload(client, scanned_pdf).json()["id"]

    record = client.get(f"/api/v1/documents/{doc_id}").json()
    assert record["status"] == "failed"
    assert "scanned" in record["error"]
    assert any("OCR is not available" in w for w in record["warnings"])

    response = client.get(f"/api/v1/documents/{doc_id}/preview")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "processing_failed"


def test_blank_pdf_fails_with_no_text_message(client, tmp_path):
    path = pdf_factory.make_blank_pdf(tmp_path / "blank.pdf")
    doc_id = upload(client, path).json()["id"]
    record = client.get(f"/api/v1/documents/{doc_id}").json()
    assert record["status"] == "failed"
    assert "No readable text" in record["error"]


# ---- documents that are not ready ---------------------------------------------
def test_text_of_a_document_still_processing_is_409(client, store):
    record = store.add("busy.pdf", status="processing")
    for suffix in ("preview", "pages", "pages/1"):
        response = client.get(f"/api/v1/documents/{record.id}/{suffix}")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "not_ready"


def test_text_routes_for_unknown_document_are_404(client):
    for suffix in ("preview", "pages", "pages/1"):
        response = client.get(f"/api/v1/documents/{MISSING_ID}/{suffix}")
        assert response.status_code == 404


# ---- rejected uploads ----------------------------------------------------------
def test_wrong_extension_is_rejected_with_415(client, test_settings, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    response = upload(client, path, content_type="text/plain")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file_type"
    assert client.get("/api/v1/documents").json()["total"] == 0
    assert stored_files(test_settings) == []


def test_renamed_non_pdf_is_rejected_and_not_kept(client, test_settings, tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_text("This is plain text, not a PDF.", encoding="utf-8")
    response = upload(client, path)
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "not_a_pdf"
    assert client.get("/api/v1/documents").json()["total"] == 0
    assert stored_files(test_settings) == []


def test_empty_file_is_rejected(client, test_settings, tmp_path):
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    response = upload(client, path)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_file"
    assert stored_files(test_settings) == []


def test_oversized_file_is_rejected_and_not_kept(client, test_settings, tmp_path):
    path = tmp_path / "huge.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10))  # limit is 1 MB in tests
    response = upload(client, path)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert stored_files(test_settings) == []


def test_corrupt_pdf_is_rejected_and_not_kept(client, test_settings, tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\nthis is not really a pdf body")
    response = upload(client, path)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_pdf"
    assert client.get("/api/v1/documents").json()["total"] == 0
    assert stored_files(test_settings) == []


def test_password_protected_pdf_is_rejected(client, test_settings, tmp_path):
    path = pdf_factory.make_encrypted_pdf(tmp_path / "locked.pdf")
    response = upload(client, path)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "encrypted_pdf"
    assert stored_files(test_settings) == []


def test_pdf_with_too_many_pages_is_rejected(client, test_settings, tmp_path):
    path = pdf_factory.make_text_pdf(tmp_path / "long.pdf", pages=["some text"] * 51)
    response = upload(client, path)  # the page limit is 50 in tests
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "too_many_pages"
    assert stored_files(test_settings) == []


# ---- Windows file locks ----------------------------------------------------------
# On Windows an open file cannot be deleted. PyMuPDF used to leave a corrupt
# file open while the error travelled up to the route, so the clean-up failed
# with PermissionError and the user saw a 500 instead of the real reason.
@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="inspects /proc, which only Linux has"
)
def test_rejecting_a_corrupt_pdf_leaves_no_file_handle_open(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\nthis is not really a pdf body")

    def open_handles():
        held = []
        for fd in os.listdir("/proc/self/fd"):
            try:
                held.append(os.readlink(f"/proc/self/fd/{fd}"))
            except OSError:
                pass
        return [target for target in held if target.endswith("broken.pdf")]

    try:
        validate_pdf(path, 50)
    except Exception:
        # The error is still travelling up, which is when the route cleans up.
        assert open_handles() == []
    else:
        pytest.fail("a corrupt PDF should have been rejected")


@pytest.mark.parametrize(
    "make_upload, status, code",
    [
        (lambda p: p.write_bytes(b"%PDF-1.4\nnot really a pdf"), 422, "invalid_pdf"),
        (lambda p: p.write_bytes(b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10)), 413, "file_too_large"),
    ],
    ids=["corrupt", "oversized"],
)
def test_failed_cleanup_never_hides_the_real_error(
    client, tmp_path, monkeypatch, make_upload, status, code
):
    """If the rejected file cannot be deleted (a lock, an antivirus scan,
    OneDrive syncing), the user must still be told why it was rejected."""
    path = tmp_path / "bad.pdf"
    make_upload(path)

    real_unlink = Path.unlink

    def locked_unlink(self, *args, **kwargs):
        if self.suffix == ".pdf" and self.parent.name == "uploads":
            raise PermissionError(32, "The process cannot access the file")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_unlink)
    response = upload(client, path)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_missing_file_field_is_a_validation_error(client):
    response = client.post("/api/v1/documents")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# ---- file names ------------------------------------------------------------------
@pytest.mark.parametrize(
    "sent, expected",
    [
        ("../../evil.pdf", "evil.pdf"),
        ("C:\\Users\\me\\judgment.pdf", "judgment.pdf"),
        ("தீர்ப்பு.pdf", "தீர்ப்பு.pdf"),
    ],
)
def test_filename_is_only_a_label_and_never_a_path(
    client, test_settings, text_pdf, sent, expected
):
    response = upload(client, text_pdf, filename=sent)
    assert response.status_code == 202
    body = response.json()
    assert body["filename"] == expected
    # On disk the PDF is named after the generated id, whatever was sent.
    assert f"{body['id']}.pdf" in stored_files(test_settings)
    assert all(
        name == f"{body['id']}.pdf" or name == f"{body['id']}.json"
        for name in stored_files(test_settings)
    )


# ---- deleting --------------------------------------------------------------------
def test_delete_removes_record_pdf_and_text(client, test_settings, text_pdf):
    doc_id = upload(client, text_pdf).json()["id"]
    assert sorted(stored_files(test_settings)) == [f"{doc_id}.json", f"{doc_id}.pdf"]

    assert client.delete(f"/api/v1/documents/{doc_id}").status_code == 204

    assert client.get(f"/api/v1/documents/{doc_id}").status_code == 404
    assert stored_files(test_settings) == []
    assert client.get("/api/v1/documents").json()["total"] == 0


def test_delete_unknown_document_is_404(client):
    response = client.delete(f"/api/v1/documents/{MISSING_ID}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_openapi_lists_the_upload_errors(client):
    spec = client.get("/openapi.json").json()
    responses = spec["paths"]["/api/v1/documents"]["post"]["responses"]
    assert {"202", "413", "415", "422", "500"} <= set(responses)

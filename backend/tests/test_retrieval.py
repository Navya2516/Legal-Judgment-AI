import pytest

from app.services.chunker import CLEANING_VERSION
from app.services.index_store import IndexMeta, IndexStore
from app.services.indexing import is_stale
from tests import pdf_factory
from tests.conftest import upload

PAGES = [
    "Facts. The appellant Ramesh purchased agricultural land in Madurai in 1998. "
    "The seller delivered possession but disputed the sale deed later.",
    "Issue. Whether the sale deed was valid when the registration fee was unpaid. "
    "The trial court held the sale deed invalid for want of registration.",
    "Reasoning. The High Court held that registration is mandatory under the "
    "Registration Act and that unregistered sale deeds cannot transfer title.",
    "Order. The appeal is dismissed with costs of Rs 5,000 payable by the appellant "
    "to the respondent within four weeks.",
]


@pytest.fixture
def doc(client, tmp_path):
    path = pdf_factory.make_text_pdf(tmp_path / "case.pdf", PAGES)
    response = upload(client, path)
    assert response.status_code == 202
    return response.json()["id"]


def test_upload_builds_index_in_background(client, doc):
    record = client.get(f"/api/v1/documents/{doc}").json()
    assert record["status"] == "ready"
    assert record["index_status"] == "ready"
    assert record["chunk_count"] >= 4


def test_index_info(client, doc):
    info = client.get(f"/api/v1/documents/{doc}/index").json()
    assert info["index_status"] == "ready"
    assert info["embedding_model"] == "fake-hash-embedder"
    assert info["embedding_dim"] == 256
    assert info["stale"] is False


def test_search_returns_relevant_page_first(client, doc):
    cases = {
        "registration fee unpaid sale deed invalid": {2},
        "appeal dismissed with costs": {4},
        "Ramesh purchased agricultural land Madurai": {1},
    }
    for query, expected_pages in cases.items():
        body = client.post(f"/api/v1/documents/{doc}/search", json={"query": query}).json()
        top = body["hits"][0]
        assert top["rank"] == 1
        assert set(range(top["chunk"]["page_start"], top["chunk"]["page_end"] + 1)) & expected_pages, query


def test_search_scores_are_ordered_and_bounded(client, doc):
    body = client.post(
        f"/api/v1/documents/{doc}/search", json={"query": "registration of sale deed", "top_k": 3}
    ).json()
    scores = [h["score"] for h in body["hits"]]
    assert len(scores) == 3
    assert scores == sorted(scores, reverse=True)
    assert all(-1.0001 <= s <= 1.0001 for s in scores)
    assert [h["rank"] for h in body["hits"]] == [1, 2, 3]


def test_top_k_larger_than_chunks_is_safe(client, doc):
    body = client.post(f"/api/v1/documents/{doc}/search", json={"query": "sale deed", "top_k": 20}).json()
    total = client.get(f"/api/v1/documents/{doc}/index").json()["chunk_count"]
    assert len(body["hits"]) == min(20, total)


def test_search_validation(client, doc):
    url = f"/api/v1/documents/{doc}/search"
    assert client.post(url, json={"query": "x"}).status_code == 422
    assert client.post(url, json={"query": "valid query", "top_k": 0}).status_code == 422
    assert client.post(url, json={"query": "valid query", "top_k": 99}).status_code == 422
    assert client.post(url, json={}).status_code == 422


def test_search_unknown_document_is_404(client):
    response = client.post(f"/api/v1/documents/{'0' * 32}/search", json={"query": "anything"})
    assert response.status_code == 404


def test_search_before_ready_is_409(client, store):
    record = store.add("x.pdf", status="processing")
    response = client.post(f"/api/v1/documents/{record.id}/search", json={"query": "anything"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_ready"


def test_search_without_index_is_409(client, store):
    record = store.add("x.pdf", status="ready")
    response = client.post(f"/api/v1/documents/{record.id}/search", json={"query": "anything"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "index_not_ready"


def test_chunks_are_browsable_with_paging(client, doc):
    first = client.get(f"/api/v1/documents/{doc}/chunks?limit=2").json()
    assert len(first["chunks"]) == 2 and first["total"] >= 4
    second = client.get(f"/api/v1/documents/{doc}/chunks?limit=2&offset=2").json()
    assert second["chunks"][0]["chunk_id"] == 2


def test_rebuild_index(client, doc, fake_embedder):
    calls = fake_embedder.calls
    response = client.post(f"/api/v1/documents/{doc}/index")
    assert response.status_code == 202
    assert fake_embedder.calls > calls
    assert client.get(f"/api/v1/documents/{doc}").json()["index_status"] == "ready"


def test_changed_settings_make_index_stale(client, doc, test_settings):
    test_settings.chunk_size = 500
    info = client.get(f"/api/v1/documents/{doc}/index").json()
    assert info["stale"] is True
    response = client.post(f"/api/v1/documents/{doc}/search", json={"query": "sale deed"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "index_stale"
    assert client.post(f"/api/v1/documents/{doc}/index").status_code == 202
    assert client.post(f"/api/v1/documents/{doc}/search", json={"query": "sale deed"}).status_code == 200


def test_embedding_failure_marks_index_failed_but_keeps_text(client, tmp_path):
    from app.main import app
    from app.services.embedder import get_embedder_factory

    def broken():
        raise RuntimeError("model download failed")

    app.dependency_overrides[get_embedder_factory] = lambda: broken
    path = pdf_factory.make_text_pdf(tmp_path / "case.pdf", PAGES)
    doc_id = upload(client, path).json()["id"]
    record = client.get(f"/api/v1/documents/{doc_id}").json()
    assert record["status"] == "ready"  # text extraction still succeeded
    assert record["index_status"] == "failed"
    assert "index" in record["index_error"].lower()
    response = client.post(f"/api/v1/documents/{doc_id}/search", json={"query": "sale deed"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "index_failed"
    assert client.get(f"/api/v1/documents/{doc_id}/pages").status_code == 200


def test_delete_removes_index_files(client, doc, test_settings):
    folder = test_settings.index_path
    assert any(folder.iterdir())
    assert client.delete(f"/api/v1/documents/{doc}").status_code == 204
    assert not any(folder.iterdir())


def test_index_survives_reload_from_disk(doc, test_settings):
    store = IndexStore(test_settings.index_path)
    loaded = store.load(doc)
    assert loaded.index.ntotal == len(loaded.chunks) == loaded.meta.chunk_count


def test_corrupt_index_gives_clean_error(client, doc, test_settings):
    (test_settings.index_path / f"{doc}.faiss").write_bytes(b"garbage")
    response = client.post(f"/api/v1/documents/{doc}/search", json={"query": "sale deed"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "storage_error"


def test_interrupted_indexing_is_marked_failed(store):
    record = store.add("x.pdf", status="ready", index_status="indexing")
    store.fail_interrupted()
    updated = store.get(record.id)
    assert updated.status == "ready" and updated.index_status == "failed"


def test_is_stale_detects_each_setting(test_settings):
    meta = IndexMeta(
        embedding_model=test_settings.embedding_model, embedding_dim=4,
        chunk_size=test_settings.chunk_size, chunk_overlap=test_settings.chunk_overlap,
        cleaning_version=CLEANING_VERSION, chunk_count=1,
    )
    assert not is_stale(meta, test_settings)
    assert is_stale(meta.model_copy(update={"embedding_model": "other"}), test_settings)
    assert is_stale(meta.model_copy(update={"chunk_overlap": 1}), test_settings)
    assert is_stale(meta.model_copy(update={"cleaning_version": 99}), test_settings)

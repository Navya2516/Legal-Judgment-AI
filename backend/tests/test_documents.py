MISSING_ID = "0" * 32


def test_list_is_empty_at_first(client):
    response = client.get("/api/v1/documents")
    assert response.status_code == 200
    assert response.json() == {"documents": [], "total": 0}


def test_get_existing_document(client, store):
    record = store.add("kesavananda.pdf")
    response = client.get(f"/api/v1/documents/{record.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == record.id
    assert body["filename"] == "kesavananda.pdf"
    assert body["status"] == "uploaded"


def test_list_returns_newest_first(client, store):
    first = store.add("first.pdf")
    second = store.add("second.pdf")
    body = client.get("/api/v1/documents").json()
    assert body["total"] == 2
    assert [doc["id"] for doc in body["documents"]] == [second.id, first.id]


def test_unknown_document_gives_consistent_404(client):
    response = client.get(f"/api/v1/documents/{MISSING_ID}")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert MISSING_ID in error["message"]


def test_malformed_id_is_rejected_with_422(client):
    response = client.get("/api/v1/documents/not-a-valid-id")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_route_uses_same_error_shape(client):
    response = client.get("/api/v1/nothing-here")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_404"


def test_corrupted_registry_returns_clean_500(client, store, tmp_path):
    (tmp_path / "documents.json").write_text("{ this is not json", encoding="utf-8")
    response = client.get("/api/v1/documents")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "storage_error"


def test_openapi_documents_the_real_error_shape(client):
    spec = client.get("/openapi.json").json()
    responses = spec["paths"]["/api/v1/documents/{doc_id}"]["get"]["responses"]
    for status in ("404", "422", "500"):
        schema = responses[status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorResponse")

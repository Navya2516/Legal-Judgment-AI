def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert isinstance(body["gemini_key_configured"], bool)
    assert "embedding_model" in body


def test_health_never_exposes_the_api_key(client):
    text = client.get("/health").text.lower()
    assert "api_key" not in text.replace("gemini_key_configured", "")
    assert "aiza" not in text


def test_every_response_has_a_request_id(client):
    response = client.get("/health")
    assert len(response.headers["X-Request-ID"]) == 12

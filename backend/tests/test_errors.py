from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.utils.errors import BadRequestError, register_exception_handlers


def _make_app() -> FastAPI:
    """A tiny separate app, so we can test error handling without touching the real one."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/bad")
    def bad():
        raise BadRequestError("That file is not a PDF.", details={"field": "file"})

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    return app


def test_app_error_keeps_its_status_code_and_details():
    response = TestClient(_make_app()).get("/bad")
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "bad_request"
    assert error["message"] == "That file is not a PDF."
    assert error["details"] == {"field": "file"}


def test_unexpected_error_hides_internal_details():
    client = TestClient(_make_app(), raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret internal detail" not in response.text

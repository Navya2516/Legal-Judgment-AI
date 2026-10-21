"""Application errors and the handlers that turn them into consistent JSON.

Every error response has the same shape, so the frontend needs only one
way to read errors:

    {"error": {"code": "not_found", "message": "...", "details": ...}}
"""
import logging
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("legal-ai.errors")


class AppError(Exception):
    """Base class for errors we raise on purpose."""

    status_code = 500
    code = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        code: Optional[str] = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class StorageError(AppError):
    status_code = 500
    code = "storage_error"


class ConflictError(AppError):
    """The request is fine, but the document is not in a state that allows it."""

    status_code = 409
    code = "conflict"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"


class UnsupportedMediaTypeError(AppError):
    status_code = 415
    code = "unsupported_file_type"


class UnprocessableFileError(AppError):
    """The upload is a PDF-shaped file we cannot use (corrupt, encrypted, ...)."""

    status_code = 422
    code = "invalid_pdf"


class LlmUnavailableError(AppError):
    """The language-model service failed or refused (502)."""

    status_code = 502
    code = "llm_unavailable"


class LlmNotConfiguredError(AppError):
    status_code = 503
    code = "llm_not_configured"


class LlmRateLimitedError(AppError):
    status_code = 429
    code = "llm_rate_limited"


def _error_body(code: str, message: str, details: Any = None) -> dict:
    body: dict = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"error": body}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("%s: %s", exc.code, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_body(
                "validation_error",
                "The request was not valid.",
                jsonable_encoder(exc.errors()),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(f"http_{exc.status_code}", str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        # The full traceback goes to the log; the user only sees a safe message.
        logger.exception("Unhandled error: %s", exc)
        return JSONResponse(
            status_code=500,
            content=_error_body(
                "internal_error", "Something went wrong on the server."
            ),
        )

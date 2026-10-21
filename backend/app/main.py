"""FastAPI entry point: wires together settings, middleware, errors and routes."""
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import analysis, ask, continuation, documents, meta, retrieval, system, translation
from app.services.document_store import get_document_store
from app.utils.errors import StorageError, register_exception_handlers
from app.utils.logging_config import setup_logging
from app.version import APP_VERSION

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger("legal-ai")


def _preload_embedder() -> None:
    """Load the embedding model in the background; failure only costs speed later."""
    try:
        from app.services.embedder import get_embedder

        warm_up = getattr(get_embedder(), "warm_up", None)
        if warm_up:
            warm_up()
            logger.info("Embedding model preloaded")
    except Exception:
        logger.exception("Could not preload the embedding model (it will load on first use)")


@asynccontextmanager
async def lifespan(_: FastAPI):
    for folder in (
        settings.upload_path,
        settings.extracted_path,
        settings.index_path,
        settings.results_path,
    ):
        folder.mkdir(parents=True, exist_ok=True)
    try:
        interrupted = get_document_store().fail_interrupted()
        if interrupted:
            logger.warning("Marked %d interrupted document(s) as failed", interrupted)
    except StorageError:
        logger.exception("Could not check for interrupted documents")
    if settings.embedding_preload:
        threading.Thread(target=_preload_embedder, daemon=True, name="embedder-preload").start()
    logger.info("Data directories ready (version %s)", APP_VERSION)
    yield


app = FastAPI(
    title="Multilingual Legal Judgment Explanation System",
    description=(
        "Evidence-grounded explanations of Indian court judgments. "
        "Educational information only, not legal advice."
    ),
    version=APP_VERSION,
    lifespan=lifespan,
)

register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Give every request an id, time it, and log one line per request."""
    request_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "%s %s -> %s (%.1f ms) [%s]",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        request_id,
    )
    return response


app.include_router(system.router)
app.include_router(meta.router)
app.include_router(documents.router)
app.include_router(retrieval.router)
app.include_router(analysis.router)
app.include_router(translation.router)
app.include_router(continuation.router)
app.include_router(ask.router)

"""System routes: confirm the server is alive and configured."""
from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.schemas.common import HealthResponse
from app.version import APP_VERSION

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Report that the server is running and which providers are configured.

    Only booleans are returned for secrets; the key itself is never exposed.
    """
    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        llm_provider=settings.llm_provider,
        gemini_key_configured=bool(settings.gemini_api_key),
        embedding_model=settings.embedding_model,
    )

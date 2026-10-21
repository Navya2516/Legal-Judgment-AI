"""Reference data the frontend needs: supported languages and the disclaimer."""
from fastapi import APIRouter

from app.constants import DISCLAIMER_TEXT
from app.schemas.meta import DisclaimerResponse, LanguageList
from app.services.languages import SUPPORTED_LANGUAGES

router = APIRouter(prefix="/api/v1", tags=["meta"])


@router.get("/languages", response_model=LanguageList)
def list_languages() -> LanguageList:
    """Languages available for explanations, with their native names."""
    return LanguageList(languages=list(SUPPORTED_LANGUAGES), default="en")


@router.get("/disclaimer", response_model=DisclaimerResponse)
def get_disclaimer() -> DisclaimerResponse:
    """The educational-use and not-legal-advice notice shown in the UI."""
    return DisclaimerResponse(disclaimer=DISCLAIMER_TEXT)

"""Central configuration. All settings come from environment variables / .env."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    # Load the embedding model in the background when the server starts, so the
    # first search or summary does not wait 30-60 seconds for it.
    embedding_preload: bool = False
    chunk_size: int = 800
    chunk_overlap: int = 150
    top_k: int = 5

    # Summaries: judgments up to this many characters are sent whole; longer
    # ones are summarised from passages chosen by retrieval (see README).
    llm_max_context_chars: int = 60000
    llm_timeout_seconds: int = 120
    llm_temperature: float = 0.2
    llm_max_output_tokens: int = 8192
    gemini_thinking_level: str = ""  # optional: minimal | low | medium | high (empty = model default)
    llm_retries: int = 2  # extra attempts when Gemini is briefly overloaded (503) or unreachable
    # Strict mode: also remove claims whose quote could not be found in the
    # judgment (status "cited"), keeping only word-for-word verified claims.
    llm_drop_unverified: bool = False

    # Translation: sentences sent to the model per call (Indian-language output is long).
    translation_batch_size: int = 12

    max_upload_mb: int = 25
    max_pages: int = 2000
    upload_dir: str = "data/uploads"
    extracted_dir: str = "data/extracted"
    index_dir: str = "data/indexes"
    results_dir: str = "data/results"

    # OCR for scanned pages. A page is sent to OCR only when it has fewer than
    # `ocr_min_chars` letters/digits of real text AND contains an image.
    ocr_enabled: bool = True
    ocr_dpi: int = 200
    ocr_min_chars: int = 40

    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def upload_path(self) -> Path:
        return BACKEND_DIR / self.upload_dir

    @property
    def extracted_path(self) -> Path:
        return BACKEND_DIR / self.extracted_dir

    @property
    def index_path(self) -> Path:
        return BACKEND_DIR / self.index_dir

    @property
    def results_path(self) -> Path:
        return BACKEND_DIR / self.results_dir

    @property
    def registry_path(self) -> Path:
        """JSON file that records every uploaded document and its status."""
        return BACKEND_DIR / "data" / "documents.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()

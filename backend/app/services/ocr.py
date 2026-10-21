"""OCR for scanned pages.

The rest of the app only knows the small `OcrEngine` interface, so the engine
behind it can be swapped (for example for Tesseract) without touching the
extractor. The default engine is RapidOCR, which installs with pip alone:
no separate program has to be installed on Windows.

RapidOCR's default models read English text. Judgments scanned in a regional
script would need a different recognition model.
"""
import logging
import threading
from functools import lru_cache
from typing import Optional, Protocol

import numpy as np

from app.config import get_settings

logger = logging.getLogger("legal-ai.ocr")


class OcrEngine(Protocol):
    name: str

    def recognize(self, image: np.ndarray) -> str:
        """Return the text found in a BGR image (height x width x 3 uint8)."""
        ...


class RapidOcrEngine:
    name = "rapidocr"

    def __init__(self) -> None:
        from rapidocr import RapidOCR  # imported here so the app runs without it

        self._engine = RapidOCR()
        self._lock = threading.Lock()  # OCR is CPU-heavy; run one page at a time

    def recognize(self, image: np.ndarray) -> str:
        with self._lock:
            result = self._engine(image)
        texts = getattr(result, "txts", None)
        if not texts:
            return ""
        return "\n".join(texts)


@lru_cache
def get_ocr_engine() -> Optional[OcrEngine]:
    """Load the OCR engine once; return None if it is disabled or not installed."""
    if not get_settings().ocr_enabled:
        logger.info("OCR is disabled by configuration")
        return None
    try:
        engine = RapidOcrEngine()
    except ImportError:
        logger.warning(
            "OCR engine not installed. Scanned pages will not be read. "
            "Install it with: pip install -r requirements-ocr.txt"
        )
        return None
    except Exception:
        logger.exception("OCR engine failed to start")
        return None
    logger.info("OCR engine ready: %s", engine.name)
    return engine

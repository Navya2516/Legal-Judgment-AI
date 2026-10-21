"""The language model (Gemini) behind a small interface.

Everything else in the app talks to `LlmClient`, so tests use a fake and the
provider can be swapped later. Errors are reduced to a few kinds the API can
explain to the user.
"""
import json
import logging
import re
import threading
import time
from typing import Callable, Optional, Protocol, Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.utils.errors import (
    LlmNotConfiguredError,
    LlmRateLimitedError,
    LlmUnavailableError,
)

logger = logging.getLogger("legal-ai.llm")


_RETRY_IN = re.compile(r"retry in ((?:\d+h)?(?:\d+m)?(?:\d+(?:\.\d+)?s)?)", re.I)


def _wait_text(raw: str) -> str:
    """'6h34m29.4s' -> 'about 6 h 34 min'; '28s' -> 'about 28 s'."""
    hours = re.search(r"(\d+)h", raw)
    minutes = re.search(r"(\d+)m", raw)
    seconds = re.search(r"(\d+)(?:\.\d+)?s", raw)
    parts = []
    if hours:
        parts.append(f"{int(hours.group(1))} h")
    if minutes:
        parts.append(f"{int(minutes.group(1))} min")
    if not parts and seconds:
        parts.append(f"{int(seconds.group(1))} s")
    return "about " + " ".join(parts) if parts else ""


def describe_rate_limit(error_text: str, model: str) -> str:
    """Say which Gemini limit was hit and when it resets, using what Google reported."""
    match = _RETRY_IN.search(error_text)
    wait = _wait_text(match.group(1)) if match and match.group(1) else ""
    if "PerDay" in error_text:
        limit = re.search(r"limit: (\d+)", error_text)
        count = f" ({limit.group(1)} requests a day)" if limit else ""
        return (
            f"The free daily limit for the model '{model}'{count} is used up. "
            + (f"Google says it resets in {wait}. " if wait else "")
            + "Failed and repeated requests count towards it. You can wait, or set GEMINI_MODEL in "
            "backend/.env to another model your key can use (run scripts\\list_gemini_models.py), "
            "then restart the server."
        )
    return (
        "The Gemini per-minute rate limit was reached. "
        + (f"Try again in {wait}." if wait else "Wait a minute and try again.")
    )

T = TypeVar("T", bound=BaseModel)


class LlmError(Exception):
    """kind: not_configured | auth | rate_limited | model_not_found | unavailable | bad_output"""

    def __init__(self, kind: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.retryable = retryable

    def to_app_error(self):
        if self.kind == "not_configured":
            return LlmNotConfiguredError(self.message)
        if self.kind == "rate_limited":
            return LlmRateLimitedError(self.message)
        if self.kind == "model_not_found":
            return LlmUnavailableError(self.message, code="llm_model_not_found")
        code = "llm_bad_output" if self.kind == "bad_output" else "llm_unavailable"
        return LlmUnavailableError(self.message, code=code)


class LlmClient(Protocol):
    name: str

    def generate(self, *, system: str, prompt: str) -> str:
        """Return the model's reply text (JSON text for our tasks)."""
        ...


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        temperature: float,
        max_output_tokens: int,
        timeout_seconds: int,
        retries: int = 2,
        thinking_level: str = "",
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = model
        self._thinking_level = (thinking_level or "").strip().lower()
        self._retries = max(0, retries)
        self._sleep = sleep
        self._api_key = api_key
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._timeout_ms = timeout_seconds * 1000
        self._client = None
        self._lock = threading.Lock()

    def _get_client(self):
        with self._lock:
            if self._client is None:
                from google import genai
                from google.genai import types

                self._client = genai.Client(
                    api_key=self._api_key,
                    http_options=types.HttpOptions(timeout=self._timeout_ms),
                )
        return self._client

    BACKOFF_SECONDS = (3.0, 8.0, 15.0)

    def generate(self, *, system: str, prompt: str) -> str:
        """One call, retried a couple of times when Gemini is briefly overloaded."""
        for attempt in range(self._retries + 1):
            try:
                return self._call_once(system, prompt)
            except LlmError as exc:
                if not exc.retryable or attempt >= self._retries:
                    raise
                wait = self.BACKOFF_SECONDS[min(attempt, len(self.BACKOFF_SECONDS) - 1)]
                logger.warning("Retrying Gemini in %.0fs (attempt %d failed: %s)", wait, attempt + 1, exc.message)
                self._sleep(wait)
        raise LlmError("unavailable", "The language model could not be reached.")  # not reached

    def _call_once(self, system: str, prompt: str) -> str:
        """One logical call. A reply cut off by the output limit is repeated once with a bigger limit."""
        budgets = [self._max_output_tokens]
        if self._max_output_tokens < self.TOKEN_CEILING:
            budgets.append(min(self._max_output_tokens * 2, self.TOKEN_CEILING))
        for index, budget in enumerate(budgets):
            response = self._request(system, prompt, budget)
            if self._finish_reason(response) != "MAX_TOKENS":
                break
            if index + 1 < len(budgets):
                logger.warning(
                    "Gemini reply was cut off at %d output tokens; repeating once with %d",
                    budget, budgets[index + 1],
                )
                continue
            raise LlmError(
                "bad_output",
                "The model's reply was cut off because it reached the output limit "
                f"({budget} tokens, which includes the model's own thinking). Raise LLM_MAX_OUTPUT_TOKENS "
                "in backend/.env, or lower GEMINI_THINKING_LEVEL, then restart the server.",
            )
        text = getattr(response, "text", None)
        if not text:
            raise LlmError(
                "bad_output", "The language model returned no text (it may have blocked the request)."
            )
        return text

    TOKEN_CEILING = 32768

    @staticmethod
    def _finish_reason(response) -> Optional[str]:
        candidates = getattr(response, "candidates", None)
        if not candidates:
            return None
        reason = getattr(candidates[0], "finish_reason", None)
        return getattr(reason, "name", None) or (str(reason) if reason is not None else None)

    def _request(self, system: str, prompt: str, max_output_tokens: int):
        from google.genai import errors, types

        settings = dict(
            system_instruction=system,
            temperature=self._temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
        )
        if self._thinking_level:
            settings["thinking_config"] = types.ThinkingConfig(thinking_level=self._thinking_level)
        config = types.GenerateContentConfig(**settings)
        try:
            response = self._get_client().models.generate_content(
                model=self.name, contents=prompt, config=config
            )
        except errors.APIError as exc:
            code = getattr(exc, "code", None)
            logger.warning("Gemini API error %s: %s", code, exc)
            if code in (401, 403) or "API key" in str(exc):
                raise LlmError(
                    "auth",
                    "The Gemini API key was rejected. Check GEMINI_API_KEY in backend/.env.",
                ) from exc
            if code == 404:
                raise LlmError(
                    "model_not_found",
                    f"Google says the model '{self.name}' is not available to your API key "
                    "(models are retired or limited to existing users over time). Set GEMINI_MODEL "
                    "in backend/.env to a current model and restart the server. To see which models "
                    "your key can use, run: python scripts\\list_gemini_models.py",
                ) from exc
            if code == 400 and self._thinking_level:
                raise LlmError(
                    "bad_output",
                    f"Google rejected the request, possibly because GEMINI_THINKING_LEVEL="
                    f"'{self._thinking_level}' is not supported by '{self.name}'. Remove that line "
                    "from backend/.env and restart the server.",
                ) from exc
            if code == 429:
                raise LlmError("rate_limited", describe_rate_limit(str(exc), self.name)) from exc
            if code in (500, 502, 503, 504):
                raise LlmError(
                    "unavailable",
                    "Gemini is busy or having a problem right now (a temporary error on Google's side). "
                    "Wait a minute and try again.",
                    retryable=True,
                ) from exc
            raise LlmError(
                "unavailable", "The language model service returned an error. Try again shortly."
            ) from exc
        except Exception as exc:  # network failures, timeouts
            logger.warning("Gemini call failed: %s", exc)
            raise LlmError(
                "unavailable",
                "The language model could not be reached (network problem or timeout). Try again.",
                retryable=True,
            ) from exc
        usage = getattr(response, "usage_metadata", None)
        logger.info(
            "Gemini finished: reason=%s output_tokens=%s thought_tokens=%s limit=%s",
            self._finish_reason(response),
            getattr(usage, "candidates_token_count", None),
            getattr(usage, "thoughts_token_count", None),
            max_output_tokens,
        )
        return response


_client: Optional[GeminiClient] = None
_client_key: tuple = ()
_client_lock = threading.Lock()


def get_llm() -> LlmClient:
    settings = get_settings()
    if settings.llm_provider != "gemini":
        raise LlmError("not_configured", f"LLM provider '{settings.llm_provider}' is not supported.")
    if not settings.gemini_api_key.strip():
        raise LlmError(
            "not_configured",
            "No Gemini API key is configured. Add GEMINI_API_KEY to backend/.env and restart the server.",
        )
    global _client, _client_key
    key = (
        settings.gemini_api_key,
        settings.gemini_model,
        settings.llm_temperature,
        settings.llm_max_output_tokens,
        settings.llm_timeout_seconds,
        settings.llm_retries,
        getattr(settings, "gemini_thinking_level", ""),
    )
    with _client_lock:
        if _client is None or _client_key != key:
            _client = GeminiClient(
                settings.gemini_api_key,
                settings.gemini_model,
                temperature=settings.llm_temperature,
                max_output_tokens=settings.llm_max_output_tokens,
                timeout_seconds=settings.llm_timeout_seconds,
                retries=settings.llm_retries,
                thinking_level=getattr(settings, "gemini_thinking_level", ""),
            )
            _client_key = key
        return _client


def get_llm_factory() -> Callable[[], LlmClient]:
    """A dependency, so tests can swap in a fake model."""
    return get_llm


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_json_reply(text: str) -> dict:
    cleaned = _FENCE.sub("", text.strip())
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def generate_validated(llm: LlmClient, *, system: str, prompt: str, model: Type[T]) -> T:
    """Call the model and validate its JSON. One automatic retry with the error."""
    reply = llm.generate(system=system, prompt=prompt)
    for attempt in (1, 2):
        try:
            return model.model_validate(parse_json_reply(reply))
        except (ValueError, ValidationError) as exc:
            logger.warning("Model reply was not valid (attempt %d): %s", attempt, str(exc)[:300])
            if attempt == 2:
                break
            reply = llm.generate(
                system=system,
                prompt=(
                    f"{prompt}\n\nYour previous reply could not be used ({str(exc)[:300]}). "
                    "Reply again with ONLY the corrected JSON object."
                ),
            )
    raise LlmError("bad_output", "The language model did not return a usable answer. Please try again.")

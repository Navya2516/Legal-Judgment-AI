import json

import pytest
from pydantic import BaseModel

from app.services import llm as llm_module
from app.services.llm import GeminiClient, LlmError, generate_validated, parse_json_reply


class Out(BaseModel):
    answer: str


class Scripted:
    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def generate(self, *, system, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def test_parse_json_reply_accepts_code_fences():
    assert parse_json_reply('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_reply_rejects_non_objects():
    with pytest.raises(ValueError):
        parse_json_reply("[1, 2]")


def test_generate_validated_retries_once_with_the_error():
    fake = Scripted(["nope", json.dumps({"answer": "ok"})])
    assert generate_validated(fake, system="s", prompt="p", model=Out).answer == "ok"
    assert "could not be used" in fake.prompts[1]


def test_generate_validated_gives_up_after_one_retry():
    fake = Scripted(["nope", '{"wrong": 1}'])
    with pytest.raises(LlmError) as info:
        generate_validated(fake, system="s", prompt="p", model=Out)
    assert info.value.kind == "bad_output"


def test_get_llm_without_key_says_not_configured(monkeypatch):
    class S:
        llm_provider = "gemini"
        gemini_api_key = "  "

    monkeypatch.setattr(llm_module, "get_settings", lambda: S())
    with pytest.raises(LlmError) as info:
        llm_module.get_llm()
    assert info.value.kind == "not_configured"
    assert "GEMINI_API_KEY" in info.value.message


# --- the Gemini wrapper, with a stubbed SDK client (no network) ---

genai_errors = pytest.importorskip("google.genai.errors")


class StubModels:
    """`outcome` is one result/exception, or a list used one per call (last one repeats)."""

    def __init__(self, outcome):
        self.outcomes = list(outcome) if isinstance(outcome, list) else [outcome]
        self.kwargs = None
        self.calls = 0

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class StubResponse:
    def __init__(self, text):
        self.text = text


def make_client(outcome, retries=0):
    client = GeminiClient(
        "key", "gemini-test", temperature=0.1, max_output_tokens=100, timeout_seconds=5,
        retries=retries, sleep=lambda seconds: client.slept.append(seconds),
    )
    client.slept = []
    models = StubModels(outcome)
    client._client = type("C", (), {"models": models})()
    return client, models


def test_gemini_success_sends_system_prompt_and_json_mode():
    client, models = make_client(StubResponse('{"a": 1}'))
    assert client.generate(system="SYS", prompt="PROMPT") == '{"a": 1}'
    assert models.kwargs["model"] == "gemini-test"
    assert models.kwargs["contents"] == "PROMPT"
    config = models.kwargs["config"]
    assert config.system_instruction == "SYS"
    assert config.response_mime_type == "application/json"
    assert config.temperature == 0.1


@pytest.mark.parametrize(
    "error,kind",
    [
        (genai_errors.ClientError(429, {"error": {"message": "quota"}}), "rate_limited"),
        (genai_errors.ClientError(403, {"error": {"message": "denied"}}), "auth"),
        (genai_errors.ClientError(400, {"error": {"message": "API key not valid"}}), "auth"),
        (genai_errors.ServerError(503, {"error": {"message": "overloaded"}}), "unavailable"),
        (TimeoutError("timed out"), "unavailable"),
    ],
)
def test_gemini_errors_are_mapped(error, kind):
    client, _ = make_client(error)
    with pytest.raises(LlmError) as info:
        client.generate(system="s", prompt="p")
    assert info.value.kind == kind


def test_gemini_empty_reply_is_bad_output():
    client, _ = make_client(StubResponse(""))
    with pytest.raises(LlmError) as info:
        client.generate(system="s", prompt="p")
    assert info.value.kind == "bad_output"


def test_gemini_retired_model_gives_actionable_error():
    client, _ = make_client(genai_errors.ClientError(404, {"error": {"message": "no longer available"}}))
    with pytest.raises(LlmError) as info:
        client.generate(system="s", prompt="p")
    assert info.value.kind == "model_not_found"
    assert "gemini-test" in info.value.message and "GEMINI_MODEL" in info.value.message
    assert info.value.to_app_error().code == "llm_model_not_found"


BUSY = genai_errors.ServerError(503, {"error": {"message": "high demand"}})


def test_temporary_503_is_retried_then_succeeds():
    client, models = make_client([BUSY, BUSY, StubResponse('{"a": 1}')], retries=2)
    assert client.generate(system="s", prompt="p") == '{"a": 1}'
    assert models.calls == 3 and client.slept == [3.0, 8.0]


def test_persistent_503_gives_up_with_a_friendly_message():
    client, models = make_client(BUSY, retries=2)
    with pytest.raises(LlmError) as info:
        client.generate(system="s", prompt="p")
    assert models.calls == 3
    assert info.value.kind == "unavailable" and "busy" in info.value.message


def test_network_errors_are_retried():
    client, models = make_client([OSError("reset"), StubResponse("{}")], retries=1)
    assert client.generate(system="s", prompt="p") == "{}"
    assert models.calls == 2


@pytest.mark.parametrize(
    "error",
    [
        genai_errors.ClientError(429, {"error": {"message": "quota"}}),
        genai_errors.ClientError(404, {"error": {"message": "gone"}}),
        genai_errors.ClientError(403, {"error": {"message": "denied"}}),
    ],
)
def test_client_errors_are_not_retried(error):
    client, models = make_client(error, retries=2)
    with pytest.raises(LlmError):
        client.generate(system="s", prompt="p")
    assert models.calls == 1 and client.slept == []


# ---------- 429 messages ----------
from app.services.llm import describe_rate_limit  # noqa: E402

DAILY = (
    "429 RESOURCE_EXHAUSTED. You exceeded your current quota. Quota exceeded for metric: "
    "generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash "
    "Please retry in 6h34m29.489806872s. quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"
)


def test_daily_quota_message_says_daily_and_when_it_resets():
    text = describe_rate_limit(DAILY, "gemini-3.8-flash")
    assert "daily limit" in text and "20 requests a day" in text
    assert "about 6 h 34 min" in text and "GEMINI_MODEL" in text


def test_per_minute_limit_message():
    text = describe_rate_limit("429 ... PerMinute ... Please retry in 28.4s.", "m")
    assert "per-minute" in text and "about 28 s" in text and "daily" not in text


def test_limit_message_without_details_still_useful():
    assert "Wait a minute" in describe_rate_limit("429 quota", "m")


# ---------- cut-off replies and thinking level ----------
class Cand:
    def __init__(self, name):
        self.finish_reason = type("R", (), {"name": name})()


class CutResponse:
    def __init__(self, text, reason):
        self.text = text
        self.candidates = [Cand(reason)]
        self.usage_metadata = type("U", (), {"candidates_token_count": 10, "thoughts_token_count": 90})()


def test_cut_off_reply_is_repeated_once_with_a_bigger_limit():
    client, models = make_client([CutResponse('{"a": "unterminated', "MAX_TOKENS"), CutResponse('{"a": 1}', "STOP")])
    assert client.generate(system="s", prompt="p") == '{"a": 1}'
    assert models.calls == 2
    assert models.kwargs["config"].max_output_tokens == 200  # 100 doubled


def test_still_cut_off_after_the_bigger_limit_gives_a_clear_error():
    client, models = make_client(CutResponse('{"a": "x', "MAX_TOKENS"))
    with pytest.raises(LlmError) as info:
        client.generate(system="s", prompt="p")
    assert models.calls == 2
    assert info.value.kind == "bad_output" and "cut off" in info.value.message and "LLM_MAX_OUTPUT_TOKENS" in info.value.message


def test_normal_finish_is_a_single_call():
    client, models = make_client(CutResponse('{"a": 1}', "STOP"))
    assert client.generate(system="s", prompt="p") == '{"a": 1}'
    assert models.calls == 1


def test_thinking_level_is_sent_only_when_set():
    client, models = make_client(StubResponse("{}"))
    client.generate(system="s", prompt="p")
    assert models.kwargs["config"].thinking_config is None
    client2 = GeminiClient("key", "m", temperature=0.1, max_output_tokens=100, timeout_seconds=5,
                           retries=0, thinking_level="Low")
    models2 = StubModels(StubResponse("{}"))
    client2._client = type("C", (), {"models": models2})()
    client2.generate(system="s", prompt="p")
    assert str(models2.kwargs["config"].thinking_config.thinking_level).lower().endswith("low")


def test_rejected_thinking_level_tells_the_user_what_to_remove():
    client = GeminiClient("key", "m", temperature=0.1, max_output_tokens=100, timeout_seconds=5,
                          retries=0, thinking_level="high")
    client._client = type("C", (), {"models": StubModels(genai_errors.ClientError(400, {"error": {"message": "bad"}}))})()
    with pytest.raises(LlmError) as info:
        client.generate(system="s", prompt="p")
    assert "GEMINI_THINKING_LEVEL" in info.value.message

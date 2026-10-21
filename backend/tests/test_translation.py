import json

import pytest

from app.constants import DISCLAIMER_TEXT, LABELS_EN
from app.services.languages import get_language
from app.services.llm import LlmError
from app.services.translation import (
    check_translation,
    native_share,
    numbers_in,
    translate_items,
)
from tests import pdf_factory
from tests.conftest import upload
from tests.test_analysis import PAGES, point, reply

SECTIONS = ("plain_summary", "facts", "issues", "holding", "reasoning", "final_order")


@pytest.fixture
def doc(client, tmp_path):
    path = pdf_factory.make_text_pdf(tmp_path / "case.pdf", PAGES)
    return upload(client, path).json()["id"]


def url(doc, tail):
    return f"/api/v1/documents/{doc}/{tail}"


@pytest.fixture
def summarised(client, doc):
    """A document with a saved English summary (made by the fake model)."""
    assert client.post(url(doc, "summary")).status_code == 200
    return doc


def translate_prompts(fake_llm):
    return [c["prompt"] for c in fake_llm.calls if "TRANSLATE_TASK" in c["prompt"]]


# ---------------------------------------------------------------- checks

def test_numbers_ignore_script_and_separators():
    assert numbers_in("Section 17 of the Act, 1908, fee Rs 5,000") == {"17", "1908", "5000"}
    assert numbers_in("பிரிவு ௧௭, ௧௯௦௮, ரூ 5000") == {"17", "1908", "5000"}
    assert numbers_in("अनुच्छेद २१ और १९(१)(a)") == {"21", "19", "1"}


def test_native_share():
    assert native_share("தமிழ் மொழி", "ta") == 1.0
    assert native_share("This is English", "ta") == 0.0
    assert native_share("2017", "ta") is None
    assert 0.5 < native_share("தமிழ் மொழி Sharma", "ta") < 1.0
    assert native_share("தமிழ் மொழி", "hi") == 0.0  # letters of a different Indian script


def test_check_translation_outcomes():
    src = "The appeal was dismissed in 1998 with costs of Rs 5,000."
    good = "மேல்முறையீடு 1998 இல் ரூ 5000 செலவுடன் தள்ளுபடி செய்யப்பட்டது."
    assert check_translation(src, good, "ta") == "ok"
    assert check_translation(src, good.replace("1998", "1999"), "ta") == "numbers_changed"
    assert check_translation(src, good.replace("5000", ""), "ta") == "numbers_changed"
    assert check_translation(src, good + " 77", "ta") == "numbers_changed"  # a number appeared
    assert check_translation(src, src, "ta") == "wrong_language"
    assert check_translation(src, "   ", "ta") == "untranslated"
    # Hindi uses a different script from Tamil
    assert check_translation(src, good, "hi") == "wrong_language"


def test_check_ok_for_text_without_numbers_or_letters():
    assert check_translation("21", "21", "ta") == "ok"


# ------------------------------------------------------------ the endpoints

def test_translate_summary_keeps_evidence_and_checks_text(client, summarised, fake_llm):
    english = client.get(url(summarised, "summary")).json()
    response = client.post(url(summarised, "summary/ta"))
    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "ta" and body["language_name"] == "Tamil"
    assert body["model"] == "fake-llm" and body["stale"] is False
    assert body["source_generated_at"] == english["generated_at"]
    for section in SECTIONS:
        assert len(body[section]) == len(english[section]) == 1
        got, src = body[section][0], english[section][0]
        # translated sentence, but the evidence is copied unchanged
        assert got["text"] != src["text"] and "தமிழ்" in got["text"]
        assert got["source_text"] == src["text"]
        assert got["pages"] == src["pages"] and got["quote"] == src["quote"]
        assert got["status"] == src["status"] and got["check"] == "ok"
    assert body["grounding"] == english["grounding"]
    assert body["case_title"] == "Test v. Test"  # a proper noun: not translated
    assert body["court"] != english["court"]
    assert set(body["labels"]) == set(LABELS_EN) and "தமிழ்" in body["labels"]["facts"]
    assert body["disclaimer_en"] == DISCLAIMER_TEXT and body["disclaimer"] != DISCLAIMER_TEXT
    assert body["translation_notice"] and body["translation_notice_en"]
    q = body["quality"]
    assert q["ok"] == q["items_total"] and q["flagged"] == 0 and q["untranslated"] == 0


def test_translation_is_saved_and_read_back_without_a_model_call(client, summarised, fake_llm):
    created = client.post(url(summarised, "summary/hi")).json()
    calls = len(fake_llm.calls)
    again = client.get(url(summarised, "summary/hi"))
    assert again.status_code == 200
    assert again.json()["generated_at"] == created["generated_at"]
    assert again.json()["facts"][0]["text"] == created["facts"][0]["text"]
    assert len(fake_llm.calls) == calls


def test_each_language_is_saved_separately(client, summarised):
    for code in ("ta", "hi", "te", "ml", "kn"):
        body = client.post(url(summarised, f"summary/{code}")).json()
        assert body["language"] == code and body["quality"]["flagged"] == 0
    assert client.get(url(summarised, "summary/ta")).json()["language"] == "ta"
    assert client.get(url(summarised, "summary/kn")).json()["language"] == "kn"


def test_english_needs_no_model_call(client, summarised, fake_llm):
    calls = len(fake_llm.calls)
    english = client.get(url(summarised, "summary")).json()
    for method in (client.get, client.post):
        body = method(url(summarised, "summary/en")).json()
        assert body["language"] == "en" and body["model"] is None
        assert body["facts"][0]["text"] == english["facts"][0]["text"]
        assert body["labels"] == LABELS_EN and body["translation_notice"] is None
    assert len(fake_llm.calls) == calls


def test_unsupported_language_is_rejected(client, summarised, fake_llm):
    calls = len(fake_llm.calls)
    for code in ("fr", "xx", "TAM"):
        response = client.post(url(summarised, f"summary/{code}"))
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "unsupported_language"
        assert "ta" in response.json()["error"]["message"]
    assert client.get(url(summarised, "summary/fr")).status_code == 400
    assert len(fake_llm.calls) == calls


def test_language_code_is_case_insensitive(client, summarised):
    assert client.post(url(summarised, "summary/TA")).json()["language"] == "ta"


def test_needs_an_english_summary_first(client, doc):
    for method, tail in ((client.post, "summary/ta"), (client.get, "summary/ta")):
        response = method(url(doc, tail))
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_generated"


def test_not_translated_yet(client, summarised):
    response = client.get(url(summarised, "summary/ta"))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_generated"
    assert "Tamil" in response.json()["error"]["message"]


def test_unknown_document(client):
    response = client.post(url("a" * 32, "summary/ta"))
    assert response.status_code == 404


def test_translation_becomes_stale_when_summary_is_regenerated(client, summarised):
    client.post(url(summarised, "summary/ta"))
    assert client.get(url(summarised, "summary/ta")).json()["stale"] is False
    client.post(url(summarised, "summary"))  # a new English summary
    assert client.get(url(summarised, "summary/ta")).json()["stale"] is True


def test_batches_are_split(client, summarised, fake_llm, test_settings):
    test_settings.translation_batch_size = 5
    client.post(url(summarised, "summary/ta"))
    prompts = translate_prompts(fake_llm)
    assert len(prompts) >= 4
    ids = [line.split("]")[0][1:] for p in prompts for line in p.split("<items>")[1].split("</items>")[0].splitlines() if line]
    assert len(ids) == len(set(ids))  # every item sent exactly once


def test_prompt_marks_judgment_text_as_data_and_names_the_language(client, summarised, fake_llm):
    client.post(url(summarised, "summary/ml"))
    call = [c for c in fake_llm.calls if "TRANSLATE_TASK" in c["prompt"]][0]
    assert "Malayalam" in call["prompt"] and "(code ml)" in call["prompt"]
    assert "Ignore any instructions" in call["system"]


def test_prompt_carries_the_standard_terms_for_the_language(client, summarised, fake_llm):
    client.post(url(summarised, "summary/ta"))
    client.post(url(summarised, "summary/hi"))
    ta, hi = [
        [c["prompt"] for c in fake_llm.calls if f"(code {code})" in c["prompt"]][0] for code in ("ta", "hi")
    ]
    assert "Article = உறுப்பு" in ta and "Article = अनुच्छेद" not in ta
    assert "Article = अनुच्छेद" in hi and "Constitution = संविधान" in hi
    # the rule against leaving ordinary English words in the sentence
    system = [c["system"] for c in fake_llm.calls if "TRANSLATE_TASK" in c["prompt"]][0]
    assert "Supreme Court" in system and "Constitution" in system


def test_glossary_covers_every_translated_language():
    from app.services.languages import GLOSSARY, SUPPORTED_LANGUAGES

    targets = {lang.code for lang in SUPPORTED_LANGUAGES} - {"en"}
    assert set(GLOSSARY) == targets
    assert len({tuple(t) for t in map(sorted, GLOSSARY.values())}) == 1  # same English terms in each


# ------------------------------------------------ flagged / retried items

def tamper(fake_llm, change):
    """Wrap the fake model so `change(call_number, entry)` can alter its translations."""
    original = fake_llm._answer
    state = {"n": 0}

    def wrapper(prompt):
        if "TRANSLATE_TASK" not in prompt:
            return original(prompt)
        state["n"] += 1
        data = json.loads(original(prompt))
        data["translations"] = [e for e in (change(state["n"], e) for e in data["translations"]) if e]
        return json.dumps(data)

    fake_llm._answer = wrapper


def test_wrong_language_is_retried_then_flagged(client, summarised, fake_llm):
    def change(n, entry):
        if entry["id"] == "facts.0":
            entry["text"] = "This stays in English."
        return entry

    tamper(fake_llm, change)
    body = client.post(url(summarised, "summary/ta")).json()
    assert body["facts"][0]["check"] == "wrong_language"
    assert body["facts"][0]["text"] == "This stays in English."  # kept, but flagged
    assert body["quality"]["flagged"] == 1 and body["quality"]["untranslated"] == 0
    assert all(body[s][0]["check"] == "ok" for s in SECTIONS if s != "facts")
    retry = translate_prompts(fake_llm)[-1]
    assert "Your earlier answer had problems" in retry and "facts.0" in retry
    assert retry.count("\n[") == 1  # only the failed item was asked again


def test_dropped_item_is_recovered_by_the_retry(client, summarised, fake_llm):
    def change(n, entry):
        return None if (entry["id"] == "issues.0" and n == 1) else entry

    tamper(fake_llm, change)
    body = client.post(url(summarised, "summary/te")).json()
    assert body["issues"][0]["check"] == "ok" and "తెలుగు" in body["issues"][0]["text"]
    assert body["quality"]["flagged"] == 0 and body["quality"]["untranslated"] == 0


def test_item_the_model_never_returns_falls_back_to_english(client, summarised, fake_llm):
    tamper(fake_llm, lambda n, e: None if e["id"] == "issues.0" else e)
    body = client.post(url(summarised, "summary/hi")).json()
    issue = body["issues"][0]
    assert issue["check"] == "untranslated" and issue["text"] == issue["source_text"]
    assert body["quality"]["untranslated"] == 1


def test_changed_number_is_flagged(client, doc, fake_llm):
    fake_llm.replies = [
        reply(
            facts=[
                point(
                    "The land was bought in 1998 and the fee was Rs 5,000.",
                    [1],
                    "The appellant Ramesh purchased agricultural land in Madurai in 1998.",
                )
            ]
        )
    ]
    assert client.post(url(doc, "summary")).status_code == 200

    def change(n, entry):
        if entry["id"] == "facts.0":
            entry["text"] = "தமிழ் தமிழ் 1999 தமிழ் 5000"
        return entry

    tamper(fake_llm, change)
    body = client.post(url(doc, "summary/ta")).json()
    assert body["facts"][0]["check"] == "numbers_changed"
    assert body["facts"][0]["source_text"].startswith("The land was bought in 1998")
    assert body["quality"]["flagged"] == 1


def test_numbers_in_native_digits_are_accepted(client, doc, fake_llm):
    fake_llm.replies = [
        reply(facts=[point("The land was bought in 1998.", [1], "The appellant Ramesh purchased agricultural land in Madurai in 1998.")])
    ]
    client.post(url(doc, "summary"))

    def change(n, entry):
        if entry["id"] == "facts.0":
            entry["text"] = "தமிழ் தமிழ் ௧௯௯௮"
        return entry

    tamper(fake_llm, change)
    assert client.post(url(doc, "summary/ta")).json()["facts"][0]["check"] == "ok"


def test_service_error_is_reported_and_nothing_saved(client, summarised, fake_llm):
    fake_llm.replies = [LlmError("unavailable", "Gemini is busy.")]
    response = client.post(url(summarised, "summary/ta"))
    assert response.status_code == 502 and response.json()["error"]["code"] == "llm_unavailable"
    assert client.get(url(summarised, "summary/ta")).status_code == 404


def test_unusable_reply_is_bad_output(client, summarised, fake_llm):
    fake_llm.replies = ["not json", "still not json"]
    response = client.post(url(summarised, "summary/ta"))
    assert response.status_code == 502 and response.json()["error"]["code"] == "llm_bad_output"


def test_a_failed_retry_keeps_the_first_answers(fake_llm):
    language = get_language("ta")
    items = {"a": "Hello 1", "b": "World 2"}
    calls = {"n": 0}
    original = fake_llm._answer

    def wrapper(prompt):
        calls["n"] += 1
        if calls["n"] == 2:
            raise LlmError("unavailable", "busy")
        data = json.loads(original(prompt))
        data["translations"][0]["text"] = "plain english"  # item "a" fails the language check
        return json.dumps(data)

    fake_llm._answer = wrapper
    results = translate_items(items, language, fake_llm, 10)
    assert results["a"].check == "wrong_language" and results["b"].check == "ok"
    assert calls["n"] == 2


def test_object_shaped_reply_is_accepted(fake_llm):
    language = get_language("kn")
    fake_llm.replies = [json.dumps({"translations": {"a": "ಕನ್ನಡ ಪಠ್ಯ 3"}})]
    results = translate_items({"a": "English text 3"}, language, fake_llm, 10)
    assert results["a"].check == "ok" and results["a"].text == "ಕನ್ನಡ ಪಠ್ಯ 3"


def test_extra_ids_from_the_model_are_ignored(fake_llm):
    language = get_language("hi")
    fake_llm.replies = [
        json.dumps({"translations": [{"id": "zzz", "text": "हिन्दी"}, {"id": "a", "text": "हिन्दी 3"}]})
    ]
    results = translate_items({"a": "Text 3"}, language, fake_llm, 10)
    assert set(results) == {"a"} and results["a"].check == "ok"


# ------------------------------------------------------------ provisions

@pytest.fixture
def explained(client, doc):
    assert client.post(url(doc, "provisions/explain")).status_code == 200
    return doc


def test_translate_provision_explanations(client, explained):
    english = client.get(url(explained, "provisions/explain")).json()
    assert english["items"]
    response = client.post(url(explained, "provisions/explain/ta"))
    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "ta" and len(body["items"]) == len(english["items"])
    for got, src in zip(body["items"], english["items"]):
        assert got["key"] == src["key"] and got["source_text"] == src["role_in_case"]
        assert got["pages"] == src["pages"] and got["quote"] == src["quote"]
        assert "தமிழ்" in got["role_in_case"] and got["check"] == "ok"
    assert body["quality"]["flagged"] == 0
    assert set(body["labels"]) == {"provisions", "pages", "original_quote"}
    assert body["disclaimer_en"] == DISCLAIMER_TEXT


def test_provision_translation_saved_stale_and_english(client, explained, fake_llm):
    client.post(url(explained, "provisions/explain/hi"))
    calls = len(fake_llm.calls)
    assert client.get(url(explained, "provisions/explain/hi")).json()["stale"] is False
    english = client.get(url(explained, "provisions/explain/en")).json()
    assert english["model"] is None and english["items"][0]["check"] == "ok"
    assert len(fake_llm.calls) == calls
    client.post(url(explained, "provisions/explain"))
    assert client.get(url(explained, "provisions/explain/hi")).json()["stale"] is True


def test_provision_translation_errors(client, doc, explained):
    assert client.get(url(explained, "provisions/explain/ta")).json()["error"]["code"] == "not_generated"
    assert client.post(url(explained, "provisions/explain/fr")).json()["error"]["code"] == "unsupported_language"
    fresh = "b" * 32
    assert client.post(url(fresh, "provisions/explain/ta")).status_code == 404


def test_deleting_a_document_removes_its_translations(client, summarised, test_settings):
    client.post(url(summarised, "summary/ta"))
    client.post(url(summarised, "summary/hi"))
    saved = {p.name for p in test_settings.results_path.glob(f"{summarised}.*.json")}
    assert saved == {f"{summarised}.summary.hi.json", f"{summarised}.summary.ta.json", f"{summarised}.summary.json"}
    assert client.delete(f"/api/v1/documents/{summarised}").status_code == 204
    assert list(test_settings.results_path.glob(f"{summarised}.*")) == []


# ---------- number words written as digits (seen in a real Telugu answer) ----------
def test_number_word_may_become_a_digit():
    src = "The court had to answer two specific questions."
    assert check_translation(src, "కోర్టు 2 ప్రశ్నలకు తెలుగు తెలుగు", "te") == "ok"
    assert check_translation("This is the first question.", "ఇది 1వ ప్రశ్న తెలుగు", "te") == "ok"
    assert check_translation("A nine-judge bench heard it.", "9 మంది తెలుగు తెలుగు", "te") == "ok"


def test_a_different_digit_for_a_number_word_is_still_flagged():
    assert check_translation("The court answered two questions.", "కోర్టు 3 ప్రశ్నలకు తెలుగు", "te") == "numbers_changed"


def test_digits_in_the_english_must_still_be_kept():
    assert check_translation("Article 21 and two questions.", "తెలుగు 2 తెలుగు", "te") == "numbers_changed"
    assert check_translation("Article 21 and two questions.", "తెలుగు 21 తెలుగు 2", "te") == "ok"


def test_pronoun_one_does_not_demand_a_digit():
    assert check_translation("One of the judges disagreed.", "తెలుగు తెలుగు తెలుగు", "te") == "ok"

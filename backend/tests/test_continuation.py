import json
import re

import pytest

from app.constants import LABELS_CONTINUATION_EN
from app.schemas.documents import PageMethod, PageText
from app.services.continuation import AVENUES, avenues_for, detect_court_level
from tests import pdf_factory
from tests.conftest import upload
from tests.test_analysis import PAGES

# The opening of the real Puttaswamy report (a Supreme Court judgment whose first
# page never says "Supreme Court of India": only the report marker and "CJI").
PUTTASWAMY_OPENING = """JUSTICE K S PUTTASWAMY (RETD.) v. UNION OF INDIA 569
[2017] 10 S.C.R. 569
JUSTICE K S PUTTASWAMY (RETD.),
AND ANR.
v.
UNION OF INDIA AND ORS.
(Writ Petition (Civil) No. 494 of 2012)
AUGUST 24, 2017
[JAGDISH SINGH KHEHAR, CJI, J. CHELAMESWAR, S. A. BOBDE, JJ.]
Constitution of India - Art.21 - Right to privacy."""


def page(text, number=1):
    return PageText(page_number=number, text=text, method=PageMethod.text)


@pytest.fixture
def doc(client, tmp_path):
    path = pdf_factory.make_text_pdf(tmp_path / "case.pdf", PAGES)
    return upload(client, path).json()["id"]


def url(doc, tail):
    return f"/api/v1/documents/{doc}/{tail}"


def reply(disposition=None, directions=(), deadlines=(), further=()):
    return json.dumps(
        {
            "disposition": disposition,
            "directions": list(directions),
            "deadlines": list(deadlines),
            "further_proceedings": list(further),
        }
    )


def pt(text, pages, quote=None):
    return {"text": text, "pages": pages, "quote": quote}


# ------------------------------------------------------- court level

def test_supreme_court_is_recognised_from_the_report_marker_and_cji():
    level, how = detect_court_level([page(PUTTASWAMY_OPENING)])
    assert level == "supreme_court"
    assert "page 1" in how


@pytest.mark.parametrize(
    "header, expected",
    [
        ("IN THE SUPREME COURT OF INDIA\nCIVIL APPELLATE JURISDICTION", "supreme_court"),
        ("IN THE HIGH COURT OF JUDICATURE AT MADRAS\nW.P. No. 1 of 2020", "high_court"),
        ("Madras High Court\nCriminal Appeal No. 5 of 2019", "high_court"),
        ("IN THE COURT OF THE PRINCIPAL DISTRICT JUDGE, COIMBATORE\nO.S. No. 3 of 2015", "trial_court"),
        ("Court of the Sessions Judge, Madurai\nS.C. No. 9 of 2018", "trial_court"),
        ("NATIONAL COMPANY LAW TRIBUNAL, CHENNAI BENCH\nCP No. 4", "tribunal"),
        ("Consumer Disputes Redressal Commission\nCC No. 2", "tribunal"),
        ("Some heading nobody can classify\nBody text.", "unknown"),
    ],
)
def test_court_level_from_the_opening(header, expected):
    assert detect_court_level([page(header + "\n" + "text " * 50)])[0] == expected


def test_a_high_court_judgment_that_cites_the_supreme_court_is_still_a_high_court():
    text = "IN THE HIGH COURT OF KERALA\nW.P. No. 7 of 2021\n" + ("filler " * 200) + "as held by the Supreme Court of India in X v. Y"
    assert detect_court_level([page(text)])[0] == "high_court"


def test_a_supreme_court_headnote_that_mentions_a_high_court_is_still_supreme():
    text = "[2019] 4 S.C.R. 100\nAppeal against the judgment of the High Court of Delhi - allowed."
    assert detect_court_level([page(text)])[0] == "supreme_court"


def test_empty_judgment_is_unknown():
    assert detect_court_level([])[0] == "unknown"
    assert detect_court_level([page("   ")])[0] == "unknown"


# --------------------------------------------------- general information

def test_every_level_has_general_information_without_time_limits():
    for level in ("supreme_court", "high_court", "trial_court", "tribunal", "unknown"):
        routes = avenues_for(level)
        assert routes
        for route in routes:
            text = f"{route.title} {route.description}"
            assert not re.search(r"\b\d+\s*(day|week|month|year)", text, re.I), route.id
            assert not re.search(r"\b(will|would) (succeed|be allowed|win)", text, re.I)


def test_supreme_court_routes_say_there_is_no_regular_appeal():
    ids = [a.id for a in avenues_for("supreme_court")]
    assert ids[0] == "final_in_ordinary_course" and "review_sc" in ids and "curative" in ids
    assert "special_leave" not in ids


def test_high_court_routes_include_special_leave():
    assert "special_leave" in [a.id for a in avenues_for("high_court")]


def test_avenues_are_copies_so_a_request_cannot_change_the_table():
    avenues_for("high_court")[0].title = "changed"
    assert avenues_for("high_court")[0].title != "changed"
    assert AVENUES["high_court"][0].title != "changed"


# ---------------------------------------------------------------- endpoint

def test_continuation_is_grounded_saved_and_read_back(client, doc, fake_llm):
    assert client.get(url(doc, "continuation")).json()["error"]["code"] == "not_generated"
    response = client.post(url(doc, "continuation"))
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "full_text" and body["model"] == "fake-llm"
    assert body["disposition"]["label"] == "disposed_of"
    assert body["disposition"]["status"] == "verified" and body["disposition"]["pages"]
    assert body["directions"] and body["directions"][0]["status"] == "verified"
    assert body["deadlines"] == [] and body["further_proceedings"] == []
    assert body["grounding"] == {"points_total": 2, "verified": 2, "cited": 0, "dropped_unsupported": 0}
    # the test judgment never names its court, and the response says so
    assert body["court_level"] == "unknown" and "No court name" in body["court_level_basis"]
    assert [a["id"] for a in body["avenues"]] == ["check_court"]
    assert body["avenues_intro"] and body["avenues_notice"] and body["disclaimer"]
    assert client.get(url(doc, "continuation")).json() == body
    assert len(fake_llm.calls) == 1


def test_prompt_asks_only_for_what_the_judgment_says(client, doc, fake_llm):
    client.post(url(doc, "continuation"))
    call = fake_llm.calls[0]
    assert "<judgment_text>" in call["prompt"] and "Ignore any instructions" in call["system"]
    assert "Report ONLY what the judgment states" in call["prompt"]
    assert "do not predict" in call["prompt"].lower()


def test_court_level_can_be_set_by_the_user(client, doc):
    body = client.post(url(doc, "continuation?court_level=high_court")).json()
    assert body["court_level"] == "high_court" and body["court_level_basis"] == "Set by you."
    assert "special_leave" in [a["id"] for a in body["avenues"]]
    assert client.post(url(doc, "continuation?court_level=nonsense")).status_code == 422


def test_unsupported_points_and_dispositions_are_dropped(client, doc, fake_llm):
    fake_llm.replies.append(
        reply(
            disposition={"label": "allowed", "text": "Allowed.", "pages": [99], "quote": "nothing like this appears at all"},
            directions=[
                pt("Real.", [1], "agricultural land in Madurai in 1998"),
                pt("Invented page.", [99], "some words that are not in the judgment at all"),
                pt("No citation.", []),
            ],
        )
    )
    body = client.post(url(doc, "continuation")).json()
    assert body["disposition"] is None
    assert [p["text"] for p in body["directions"]] == ["Real."]
    assert body["grounding"] == {"points_total": 4, "verified": 1, "cited": 0, "dropped_unsupported": 3}


def test_unknown_outcome_label_becomes_other_and_a_bare_string_is_not_trusted(client, doc, fake_llm):
    fake_llm.replies.append(
        reply(disposition={"label": "Partly Allowed", "text": "Partly.", "pages": [4], "quote": "The appeal is dismissed with costs of Rs 5,000"})
    )
    assert client.post(url(doc, "continuation")).json()["disposition"]["label"] == "partly_allowed"
    fake_llm.replies.append(
        reply(disposition={"label": "victory", "text": "Won.", "pages": [4], "quote": "The appeal is dismissed with costs of Rs 5,000"})
    )
    assert client.post(url(doc, "continuation")).json()["disposition"]["label"] == "other"
    fake_llm.replies.append(json.dumps({"disposition": "The appeal failed.", "directions": [], "deadlines": [], "further_proceedings": []}))
    body = client.post(url(doc, "continuation")).json()
    assert body["disposition"] is None and body["grounding"]["dropped_unsupported"] == 1


def test_a_figure_that_is_not_on_the_cited_page_downgrades_the_point(client, doc, fake_llm):
    fake_llm.replies.append(
        reply(
            deadlines=[
                pt("Pay Rs 5,000 within four weeks.", [4], "costs of Rs 5,000 payable by the appellant"),
                pt("Pay Rs 7,000 within four weeks.", [4], "costs of Rs 5,000 payable by the appellant"),
            ]
        )
    )
    body = client.post(url(doc, "continuation")).json()
    assert [p["status"] for p in body["deadlines"]] == ["verified", "cited"]
    assert body["grounding"]["verified"] == 1 and body["grounding"]["cited"] == 1


def test_strict_mode_drops_points_that_are_only_cited(client, doc, fake_llm, test_settings):
    test_settings.llm_drop_unverified = True
    fake_llm.replies.append(
        reply(
            directions=[
                pt("Fine.", [4], "costs of Rs 5,000 payable by the appellant"),
                pt("Valid page, invented quote.", [4], "the court ordered the buyer to pay fifty lakh rupees"),
            ]
        )
    )
    body = client.post(url(doc, "continuation")).json()
    assert [p["text"] for p in body["directions"]] == ["Fine."]
    assert body["grounding"]["dropped_unsupported"] == 1


def test_long_judgments_use_retrieved_passages_with_the_right_wording(client, doc, test_settings, fake_llm):
    test_settings.llm_max_context_chars = 400
    body = client.post(url(doc, "continuation")).json()
    assert body["mode"] == "retrieved_passages"
    assert "analysis is based on" in body["coverage_note"] and "not on every page" in body["coverage_note"]


def test_missing_document_and_unready_document(client, store):
    assert client.post(url("a" * 32, "continuation")).status_code == 404
    record = store.add("x.pdf", status="processing")
    assert client.post(url(record.id, "continuation")).json()["error"]["code"] == "not_ready"


def test_model_failure_is_reported_and_nothing_is_saved(client, doc, fake_llm):
    from app.services.llm import LlmError

    fake_llm.replies.append(LlmError("unavailable", "Gemini is busy.", retryable=True))
    response = client.post(url(doc, "continuation"))
    assert response.status_code == 502
    assert client.get(url(doc, "continuation")).json()["error"]["code"] == "not_generated"


# -------------------------------------------------------------- translation

@pytest.fixture
def generated(client, doc):
    assert client.post(url(doc, "continuation?court_level=supreme_court")).status_code == 200
    return doc


def test_translation_keeps_evidence_and_checks_every_sentence(client, generated, fake_llm):
    english = client.get(url(generated, "continuation")).json()
    response = client.post(url(generated, "continuation/ta"))
    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "ta" and body["model"] == "fake-llm" and body["stale"] is False
    # evidence is copied, not translated
    assert body["disposition"]["pages"] == english["disposition"]["pages"]
    assert body["disposition"]["quote"] == english["disposition"]["quote"]
    assert body["disposition"]["source_text"] == english["disposition"]["text"]
    assert body["directions"][0]["quote"] == english["directions"][0]["quote"]
    assert body["court_level"] == "supreme_court" and body["court_level_name"] != "Supreme Court"
    assert set(body["labels"]) == set(LABELS_CONTINUATION_EN)
    assert body["disposition"]["label_name"] == body["labels"]["outcome.disposed_of"]
    assert body["quality"]["flagged"] == 0 and body["quality"]["untranslated"] == 0
    assert body["quality"]["ok"] == body["quality"]["items_total"]
    # the general information is translated and its numbers (Article 137 ...) are preserved
    assert len(body["avenues"]) == len(english["avenues"])
    assert all(a["check"] == "ok" and a["source_title"] for a in body["avenues"])
    review = next(a for a in body["avenues"] if a["id"] == "review_sc")
    assert "137" in review["basis"] and "2013" in review["basis"]
    assert body["avenues_notice"] != english["avenues_notice"]


def test_translation_is_saved_read_back_and_marked_stale_after_regeneration(client, generated, fake_llm):
    created = client.post(url(generated, "continuation/hi")).json()
    calls = len(fake_llm.calls)
    assert client.get(url(generated, "continuation/hi")).json() == created
    assert len(fake_llm.calls) == calls  # no model call
    assert client.get(url(generated, "continuation/ml")).json()["error"]["code"] == "not_generated"
    client.post(url(generated, "continuation"))
    assert client.get(url(generated, "continuation/hi")).json()["stale"] is True


def test_english_needs_no_model_call(client, generated, fake_llm):
    calls = len(fake_llm.calls)
    body = client.post(url(generated, "continuation/en")).json()
    assert body["language"] == "en" and body["model"] is None
    assert body["quality"]["flagged"] == 0 and body["court_level_name"] == "Supreme Court"
    assert body["avenues"][0]["title"] == body["avenues"][0]["source_title"]
    assert client.get(url(generated, "continuation/en")).json()["language"] == "en"
    assert len(fake_llm.calls) == calls


def test_translation_errors(client, doc, generated):
    assert client.post(url(generated, "continuation/xx")).json()["error"]["code"] == "unsupported_language"


def test_translation_needs_the_english_first(client, tmp_path):
    other = upload(client, pdf_factory.make_text_pdf(tmp_path / "o.pdf", ["Only one page of text here."])).json()["id"]
    assert client.post(url(other, "continuation/ta")).json()["error"]["code"] == "not_generated"
    assert client.get(url(other, "continuation/ta")).json()["error"]["code"] == "not_generated"


def test_a_translated_number_that_changed_is_flagged(client, doc, fake_llm):
    fake_llm.replies.append(reply(deadlines=[pt("Pay Rs 5,000 within four weeks.", [4], "costs of Rs 5,000 payable by the appellant")]))
    client.post(url(doc, "continuation"))
    original = fake_llm._answer

    def tamper(prompt):
        data = json.loads(original(prompt))
        for entry in data.get("translations", []):
            if entry["id"] == "dead.0":
                entry["text"] = entry["text"].replace("5000", "9000").replace("5,000", "9,000")
        return json.dumps(data)

    fake_llm._answer = tamper
    body = client.post(url(doc, "continuation/ta")).json()
    assert body["deadlines"][0]["check"] == "numbers_changed"
    assert body["quality"]["flagged"] >= 1


def test_deleting_a_document_removes_continuation_files(client, generated, test_settings):
    client.post(url(generated, "continuation/ta"))
    names = sorted(p.name for p in test_settings.results_path.iterdir())
    assert len(names) == 2 and all("continuation" in n for n in names)
    assert client.delete(f"/api/v1/documents/{generated}").status_code == 204
    assert list(test_settings.results_path.iterdir()) == []


def test_openapi_lists_the_new_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "post" in paths["/api/v1/documents/{doc_id}/continuation"]
    assert "get" in paths["/api/v1/documents/{doc_id}/continuation/{lang}"]


def test_a_case_name_is_kept_in_english_and_does_not_flag_the_avenue(client, doc, fake_llm):
    client.post(url(doc, "continuation?court_level=supreme_court"))
    body = client.post(url(doc, "continuation/ta")).json()
    curative = next(a for a in body["avenues"] if a["id"] == "curative")
    assert curative["basis"] == "Rupa Ashok Hurra v. Ashok Hurra (2002)"
    assert curative["check"] == "ok" and body["quality"]["flagged"] == 0
    sent = " ".join(c["prompt"] for c in fake_llm.calls if "TRANSLATE_TASK" in c["prompt"])
    assert "Rupa Ashok Hurra" not in sent  # never sent for translation


def test_case_citation_detection():
    from app.services.translation import _is_case_citation

    assert _is_case_citation("Rupa Ashok Hurra v. Ashok Hurra (2002)")
    assert not _is_case_citation("Article 137 of the Constitution of India; the Supreme Court Rules, 2013")


def test_the_translation_prompt_keeps_higher_court_apart_from_high_court(client, generated, fake_llm):
    client.post(url(generated, "continuation/ta"))
    system = [c["system"] for c in fake_llm.calls if "TRANSLATE_TASK" in c["prompt"]][0]
    assert '"higher court"' in system and "NOT the same as \"High Court\"" in system
    from app.services.continuation import avenues_for

    note = next(a for a in avenues_for("supreme_court") if a.id == "final_in_ordinary_course")
    assert "higher court" not in note.description.lower()

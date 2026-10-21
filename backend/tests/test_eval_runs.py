"""Tests for collecting saved results, the human-audit sheets, and the question-answering run."""
import csv
import json

import pytest

from app.config import Settings
from app.services.llm import LlmError
from evaluation import ask_eval, audit, collect
from evaluation import gold as gold_mod
from evaluation.corpus import load_corpus
from evaluation.report import build_report
from evaluation.testing import HashEmbedder
from tests import pdf_factory
from tests.conftest import FakeLlm

DOC = "a" * 32


def _point(status, check=None, text="The court held this.", pages=(3,)):
    p = {"text": text, "pages": list(pages), "status": status, "quote": "the court held this on the page"}
    if check:
        p.update(check=check, source_text="English sentence.")
    return p


def test_collect_counts_and_does_not_double_count_translations(tmp_path):
    en = {"model": "m", "mode": "full_text", "pages_in_context": 5, "total_pages": 5,
          "plain_summary": [_point("verified"), _point("cited")], "facts": [_point("verified")],
          "grounding": {"points_total": 4, "verified": 2, "cited": 1, "dropped_unsupported": 1}}
    ta = {"model": "m", "plain_summary": [_point("verified", "ok"), _point("cited", "numbers_changed")],
          "facts": [_point("verified", "ok")], "quality": {"items_total": 3, "ok": 2, "flagged": 1, "untranslated": 0},
          "grounding": {"points_total": 4, "verified": 2, "cited": 1, "dropped_unsupported": 1}}
    (tmp_path / f"{DOC}.summary.json").write_text(json.dumps(en))
    (tmp_path / f"{DOC}.summary.ta.json").write_text(json.dumps(ta))
    (tmp_path / "notes.txt").write_text("ignored")
    rows = collect.collect_results(tmp_path, {DOC: "case.pdf"})
    assert {r["language"] for r in rows} == {"en", "ta"}
    s = collect.summarise_collected(rows)
    e = s["english_results"]
    assert e["points_shown"] == 3 and e["quote_checked_of_shown"]["k"] == 2
    assert e["removed_as_unsupported"]["k"] == 1 and e["claims_made_by_model"] == 4
    t = s["translated_results"]["translation_checks"]
    assert t["ok"]["k"] == 2 and t["numbers_changed"]["k"] == 1 and t["ok"]["n"] == 3
    assert "quote_checked_of_shown" not in s["translated_results"]


def test_collect_reports_an_unreadable_file(tmp_path):
    (tmp_path / f"{DOC}.summary.json").write_text("{not json")
    assert collect.collect_results(tmp_path)[0]["error"] == "unreadable"


def test_audit_evidence_sheet_roundtrip(tmp_path):
    result = {"holding": [_point("verified"), _point("cited")], "facts": [_point("verified")]}
    items = audit.evidence_items(result, document="case", source="summary", page_text=lambda p: "x " * 50 + "the court held this on the page " + "y " * 50)
    assert len(items) == 3 and all(i["label"] == "" for i in items)
    assert "the court held this" in items[0]["page_context"]
    sheet = tmp_path / "e.csv"
    assert audit.write_evidence_sheet(sheet, audit.sample_stratified(items, "auto_status", 5, seed=1)) == 3
    with pytest.raises(FileExistsError):
        audit.write_evidence_sheet(sheet, items)

    scored_before = audit.score_sheet(sheet, audit.EVIDENCE_LABELS, "auto_status")
    assert scored_before["labelled"] == 0 and scored_before["blank"] == 3  # nothing is invented

    rows = list(csv.DictReader(sheet.open(encoding="utf-8-sig")))
    labels = ["supported", "Not supported", "partly"]
    for r, lab in zip(rows, labels):
        r["label"] = lab
    rows[0]["label"] = "yes?"  # an invalid label is reported, not guessed
    with sheet.open("w", newline="", encoding="utf-8-sig") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    s = audit.score_sheet(sheet, audit.EVIDENCE_LABELS, "auto_status")
    assert s["labelled"] == 2 and len(s["invalid_labels"]) == 1
    assert s["overall"]["counts"]["partly"] + s["overall"]["counts"]["not_supported"] == 2


def test_audit_translation_items_and_second_reviewer(tmp_path):
    result = {"plain_summary": [_point("verified", "ok", text="தமிழ்"), _point("verified", "numbers_changed", text="தமிழ்")]}
    items = audit.translation_items(result, document="case", source="summary", language="ta")
    assert [i["auto_check"] for i in items] == ["ok", "numbers_changed"]
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    audit.write_translation_sheet(a, items)
    audit.write_translation_sheet(b, items)
    for path, labs in ((a, ["adequate", "major_error"]), (b, ["adequate", "minor_error"])):
        rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
        for r, lab in zip(rows, labs):
            r["label"] = lab
        with path.open("w", newline="", encoding="utf-8-sig") as h:
            w = csv.DictWriter(h, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    s = audit.score_sheet(a, audit.TRANSLATION_LABELS, "auto_check", second=b)
    assert s["by_auto_check"]["ok"]["adequate_only"]["k"] == 1
    assert s["by_auto_check"]["numbers_changed"]["adequate_only"]["k"] == 0
    assert s["by_language"]["ta"]["counts"]["adequate"] == 1
    assert s["second_reviewer"]["items_labelled_by_both"] == 2
    assert s["second_reviewer"]["agreement"]["k"] == 1


@pytest.fixture
def ask_setup(tmp_path):
    pages = [f"Page {i}. The sale deed was challenged and the court examined the registration fee in paragraph {i}. " * 4 for i in range(1, 9)]
    corpus = load_corpus(pdf_factory.make_text_pdf(tmp_path / "c.pdf", pages), Settings(_env_file=None))
    path = tmp_path / "c.questions.csv"
    gold_mod.write_template(path)
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    rows[0].update(answerable="yes", relevant_pages="1;2;3;4;5;6;7;8")
    rows[1].update(answerable="yes", relevant_pages="1;2;3;4;5;6;7;8")
    rows[2].update(answerable="no", relevant_pages="")
    with path.open("w", newline="", encoding="utf-8-sig") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return corpus, gold_mod.read_gold(path, corpus.page_count), tmp_path


def _run(setup, llm, **kw):
    corpus, g, tmp = setup
    return ask_eval.run_ask(corpus, g, settings=Settings(_env_file=None), llm=llm, embedder=HashEmbedder(),
                            cache_dir=tmp / "cache", index_dir=tmp / "idx", **kw)


def test_ask_run_scores_resumes_and_respects_the_budget(ask_setup):
    corpus, g, tmp = ask_setup
    plan = ask_eval.plan(corpus, g, tmp / "cache", "en")
    assert plan["to_ask"] == 3 and plan["already_cached"] == 0

    llm = ask_eval.CountingLlm(FakeLlm())
    first = _run(ask_setup, llm, max_calls=2)
    assert first["stopped"] and "budget" in first["stopped"] and llm.calls == 2

    resumed = ask_eval.CountingLlm(FakeLlm())
    _run(ask_setup, resumed, max_calls=10)
    assert resumed.calls == 1  # only the one question not yet cached is asked
    again = ask_eval.CountingLlm(FakeLlm())
    _run(ask_setup, again, max_calls=10)
    assert again.calls == 0

    s = ask_eval.score_ask(corpus, g, tmp / "cache", "en")
    assert s["questions_run"] == 3 and s["not_run"] == [] and s["models"] == ["fake-llm"]
    assert s["answered_rate"]["n"] == 2  # unanswerable question excluded here
    assert s["quote_checked"]["rate"] == 1.0 and s["point_on_gold_page"]["rate"] == 1.0
    # the fake model always answers, so on the unanswerable question it wrongly answered
    assert s["abstain_on_unanswerable"] == {"k": 0, "n": 1, "rate": 0.0, "ci95": s["abstain_on_unanswerable"]["ci95"]}


def test_ask_run_stops_on_rate_limit_and_keeps_finished_answers(ask_setup):
    corpus, g, tmp = ask_setup
    _run(ask_setup, ask_eval.CountingLlm(FakeLlm()), max_calls=1)  # one answer saved
    limited = FakeLlm()
    limited.replies = [LlmError("rate_limited", "daily limit reached", True)]
    info = _run(ask_setup, ask_eval.CountingLlm(limited), max_calls=10)
    assert "rate_limited" in info["stopped"]
    assert len(list((tmp / "cache").glob("*.json"))) == 1  # the earlier answer is kept


def test_report_is_built_and_marks_test_runs(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    assert "No results found" in build_report(run)
    manifest = {"created_at": "now", "python": "3", "platform": "x", "seed": 0, "packages": {"numpy": "1"},
                "settings": {"embedding_model": "e", "chunk_size": 800, "chunk_overlap": 150, "gemini_model": "g", "llm_temperature": 0.2}}
    summary = {m: {"mean": 0.5, "ci95": [0.1, 0.9]} for m in ("hit@1", "mrr")}
    (run / "retrieval.json").write_text(json.dumps({
        "manifest": manifest, "embedder": "fake-hash-embedder", "pooled_questions": 2,
        "per_document": [{"document": "d", "skipped_gold_rows": []}], "pooled": {"embedding": summary},
    }))
    text = build_report(run)
    assert "TEST RUN" in text and "| embedding |" in text and "do and do not show" in text


def test_report_warns_when_answers_come_from_several_models(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    rate = {"k": 1, "n": 2, "rate": 0.5, "ci95": [0.1, 0.9]}
    doc = {"document": "d", "language": "en", "models": ["m1", "m2"], "answered_rate": rate, "cites_gold_page": rate,
           "point_on_gold_page": rate, "quote_checked": rate, "abstain_on_unanswerable": rate,
           "seconds_per_question": {"mean": 1.0, "median": 1.0}, "not_run": []}
    (run / "ask-score.json").write_text(json.dumps({"model": "m1", "language": "en", "per_document": [doc]}))
    text = build_report(run)
    lines = text.splitlines()
    warn = next(i for i, l in enumerate(lines) if "more than one model" in l)
    table = next(i for i, l in enumerate(lines) if l.startswith("| Document | Answered"))
    assert warn < table


def test_report_uses_one_translation_audit_per_language(tmp_path):
    run = tmp_path / "run"
    run.mkdir()

    def rate(k, n):
        return {"k": k, "n": n, "rate": k / n, "ci95": [0.1, 0.9]}

    def audit_json(lang, counts, agree_k):
        n = sum(counts.values())
        return {"sheet": f"audit_translation_{lang}.csv", "rows": n, "labelled": n, "blank": 0,
                "overall": {"adequate_only": rate(counts["adequate"], n), "adequate_or_minor_error": rate(n - counts["major_error"], n), "counts": counts},
                "by_auto_check": {"ok": {"adequate_only": rate(counts["adequate"], n), "counts": counts}},
                "by_language": {lang: {"adequate_only": rate(counts["adequate"], n), "adequate_or_minor_error": rate(n - counts["major_error"], n)}},
                "second_reviewer": {"items_labelled_by_both": n, "agreement": rate(agree_k, n), "cohens_kappa": 0.4}}

    ta = audit_json("ta", {"adequate": 9, "minor_error": 1, "major_error": 0}, 8)
    hi = audit_json("hi", {"adequate": 5, "minor_error": 0, "major_error": 0}, 5)
    (run / "audit-translation-ta.json").write_text(json.dumps(ta))
    (run / "audit-translation-hi.json").write_text(json.dumps(hi))
    (run / "audit-translation.json").write_text(json.dumps(hi))  # whichever language was scored last
    text = build_report(run)
    assert "| ta | 10 | 9 | 1 | 0 |" in text and "| hi | 5 | 5 | 0 | 0 |" in text
    assert "14 adequate, 1 minor error, 0 major error of 15 items" in text
    (run / "audit-translation-ta.json").unlink()
    (run / "audit-translation-hi.json").unlink()
    assert "Sheet `audit_translation_hi.csv`" in build_report(run)  # falls back to the single file


def test_report_names_the_model_of_each_saved_result_and_warns_on_a_mix(tmp_path):
    run = tmp_path / "run"
    run.mkdir()

    def row(model, lang):
        return {"file": f"{model}.{lang}.json", "document_id": "a" * 32, "document": "d.pdf", "kind": "summary", "language": lang,
                "model": model, "generated_at": "t", "mode": "retrieved_passages", "pages_in_context": 5, "total_pages": 50,
                "points_shown": 3, "verified": 3, "cited": 0, "dropped_unsupported": 0, "claims_made": 3,
                "checks": {}, "translation_quality": None, "stale": None}

    rate = {"k": 3, "n": 3, "rate": 1.0, "ci95": [0.4, 1.0]}
    summary = {"english_results": {"results": 2, "points_shown": 6, "quote_checked_of_shown": rate, "claims_made_by_model": 6,
                                   "removed_as_unsupported": {"k": 0, "n": 6, "rate": 0.0, "ci95": [0.0, 0.4]}},
               "translated_results": {"results": 0, "points_shown": 0}}
    (run / "collect.json").write_text(json.dumps({"rows": [row("model-a", "en"), row("model-b", "en")], "summary": summary}))
    text = build_report(run)
    assert "more than one model (model-a, model-b)" in text
    assert "| d.pdf | summary | en | model-a |" in text and "| d.pdf | summary | en | model-b |" in text
    (run / "collect.json").write_text(json.dumps({"rows": [row("model-a", "en")], "summary": summary}))
    assert "more than one model" not in build_report(run)

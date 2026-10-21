"""Tests for the evaluation package's maths, gold files, baselines and verifier controls."""
import csv
import random

import pytest

from app.config import Settings
from evaluation import gold as gold_mod
from evaluation.bm25 import BM25, random_rank
from evaluation.corpus import load_corpus
from evaluation.retrieval_eval import evaluate_retrieval, score_ranking
from evaluation.stats import bootstrap_ci, cohens_kappa, proportion, wilson_interval
from evaluation.testing import HashEmbedder
from evaluation.verifier_eval import evaluate_verifier
from tests import pdf_factory


def test_wilson_known_values():
    lo, hi = wilson_interval(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = wilson_interval(5, 10)
    assert (lo, hi) == (pytest.approx(0.2366, abs=1e-3), pytest.approx(0.7634, abs=1e-3))
    assert wilson_interval(0, 0) is None
    assert proportion(0, 0)["rate"] is None


def test_bootstrap_is_reproducible_and_needs_two_values():
    values = [0, 1, 1, 0, 1, 1, 1, 0]
    assert bootstrap_ci(values, seed=3) == bootstrap_ci(values, seed=3)
    assert bootstrap_ci([1.0], seed=3) is None


def test_kappa():
    assert cohens_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert cohens_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
    assert cohens_kappa([], []) is None


@pytest.mark.parametrize("spec,expected", [("78", {78}), ("78;279-280", {78, 279, 280}), (" 3 , 5–7 ", {3, 5, 6, 7}), ("", set())])
def test_parse_pages(spec, expected):
    assert gold_mod.parse_pages(spec) == expected


@pytest.mark.parametrize("bad", ["abc", "0", "9-3", "1-500"])
def test_parse_pages_rejects_unclear_input(bad):
    with pytest.raises(ValueError):
        gold_mod.parse_pages(bad)


def test_pages_beyond_document_are_rejected():
    with pytest.raises(ValueError):
        gold_mod.parse_pages("40", page_count=30)


def test_gold_template_never_overwrites_labels(tmp_path):
    path = tmp_path / "a.questions.csv"
    gold_mod.write_template(path)
    with pytest.raises(FileExistsError):
        gold_mod.write_template(path)


def test_gold_reader_skips_unlabelled_and_inconsistent_rows(tmp_path):
    path = tmp_path / "doc.questions.csv"
    rows = [
        ("q1", "Facts?", "yes", "1;2"),
        ("q2", "Blank?", "", ""),
        ("q3", "Yes but no pages?", "yes", ""),
        ("q4", "No but pages?", "no", "3"),
        ("q5", "Not in the judgment?", "no", ""),
        ("q6", "Bad pages?", "yes", "x"),
    ]
    with path.open("w", newline="", encoding="utf-8") as h:
        w = csv.writer(h)
        w.writerow(gold_mod.FIELDS)
        for qid, q, a, p in rows:
            w.writerow([qid, q, a, p, ""])
    g = gold_mod.read_gold(path)
    assert [q.id for q in g.questions] == ["q1", "q5"]
    assert g.questions[0].relevant_pages == {1, 2} and g.questions[1].answerable is False
    assert len(g.skipped) == 4


def test_bm25_prefers_the_document_with_the_words():
    docs = ["the sale deed was not registered", "the appeal concerns a promotion and seniority", "costs of five thousand rupees"]
    assert BM25(docs).rank("seniority promotion")[0] == 1
    assert random_rank(10, 1) == random_rank(10, 1) and random_rank(10, 1) != random_rank(10, 2)


class _C:
    def __init__(self, a, b):
        self.page_start, self.page_end = a, b


def test_score_ranking_by_hand():
    chunks = [_C(1, 1), _C(2, 3), _C(5, 5), _C(9, 9)]
    s = score_ranking([3, 1, 2, 0], chunks, {2, 5, 9}, ks=[1, 2, 3])
    # ranked chunks cover: [9], [9,2,3], [9,2,3,5]
    assert s["hit@1"] == 1.0 and s["recall@1"] == pytest.approx(1 / 3)
    assert s["recall@2"] == pytest.approx(2 / 3) and s["recall@3"] == 1.0
    assert s["mrr"] == 1.0
    assert score_ranking([0], chunks, {9}, ks=[1])["mrr"] == 0.0


@pytest.fixture
def corpus(tmp_path):
    pages = [
        f"Page {i}. The court considered the {topic} in paragraph {i} and noted that decision number {i} "
        f"turned on the {topic} and nothing else, as counsel for the respondent argued at some length. " * 3
        for i, topic in enumerate(["sale deed", "seniority list", "pension rules", "land acquisition", "bail conditions", "tax assessment"] * 2, start=1)
    ]
    pdf = pdf_factory.make_text_pdf(tmp_path / "judg.pdf", pages)
    return load_corpus(pdf, Settings(_env_file=None))


def test_corpus_id_is_the_file_hash(corpus):
    assert len(corpus.doc_id) == 32 and corpus.doc_id == corpus.sha256[:32]
    assert corpus.page_count == 12 and corpus.chunks


def test_retrieval_eval_runs_and_beats_random_on_an_easy_case(corpus, tmp_path):
    path = tmp_path / "judg.questions.csv"
    gold_mod.write_template(path)
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    rows[0].update(question="Where is the seniority list discussed?", answerable="yes", relevant_pages="2;8")
    rows[1].update(question="What about pension rules?", answerable="yes", relevant_pages="3;9")
    rows[2].update(question="Who won the football match?", answerable="no", relevant_pages="")
    with path.open("w", newline="", encoding="utf-8-sig") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    g = gold_mod.read_gold(path, corpus.page_count)
    result = evaluate_retrieval(corpus, g, HashEmbedder(), seed=1)
    assert result["questions_scored"] == 2  # the unanswerable question is not scored for retrieval
    assert result["summary"]["embedding"]["recall@5"]["mean"] >= result["summary"]["random"]["recall@5"]["mean"]
    assert set(result["summary"]) == {"embedding", "bm25", "random"}


def test_verifier_controls_behave_as_designed(corpus):
    r = evaluate_verifier(corpus, samples=30, seed=2)
    c = r["controls"]
    assert c["exact"]["rate"] == 1.0
    assert c["surface_changes"]["rate"] == 1.0
    assert c["stray_margin_letter"]["rate"] == 1.0
    assert c["digit_changed"]["k"] == 0 and c["word_swapped"]["k"] == 0
    assert "other_document" not in c  # needs a second document
    assert c["wrong_page_claim"]["n"] == r["spans_sampled"]


def test_verifier_rejects_text_from_another_judgment(corpus, tmp_path):
    other_pdf = pdf_factory.make_text_pdf(tmp_path / "other.pdf", [
        f"Entirely different matter {i}: the zebra crossing regulations and the lighthouse keeper's pension were reviewed in chambers on day {i}, "
        "with reference to the harbour authority bylaws and the tidal register kept since the founding of the port. " * 3 for i in range(1, 8)])
    other = load_corpus(other_pdf, Settings(_env_file=None))
    r = evaluate_verifier(corpus, samples=20, seed=0, other=other)
    assert r["controls"]["other_document"]["k"] == 0 and r["controls"]["other_document"]["n"] > 0


def test_verifier_is_reproducible(corpus):
    a = evaluate_verifier(corpus, samples=15, seed=5)
    b = evaluate_verifier(corpus, samples=15, seed=5)
    assert a["controls"] == b["controls"]


def test_gold_check_catches_wrong_pages_and_missing_quotes(corpus, tmp_path):
    path = tmp_path / "judg.questions.csv"
    gold_mod.write_template(path)
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    quote = "turned on the seniority list and nothing else, as counsel for the respondent"  # pages 2 and 8
    rows[0].update(answerable="yes", relevant_pages="2", evidence_quote=quote)
    rows[1].update(answerable="yes", relevant_pages="5", evidence_quote=quote)  # wrong page
    rows[2].update(answerable="yes", relevant_pages="3", evidence_quote="words that appear nowhere in this judgment at all")
    rows[3].update(answerable="yes", relevant_pages="3", evidence_quote="")
    with path.open("w", newline="", encoding="utf-8-sig") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    g = gold_mod.read_gold(path, corpus.page_count)
    got = {r["id"]: r for r in gold_mod.check_gold(g, corpus.cleaned)}
    assert got["q01"]["status"] == "ok"
    assert got["q02"]["status"] == "wrong_pages" and 2 in got["q02"]["found_on"]
    assert got["q03"]["status"] == "not_found"
    assert got["q04"]["status"] == "no_quote"


def test_old_gold_files_without_the_quote_column_still_read(tmp_path):
    path = tmp_path / "old.questions.csv"
    path.write_text("id,question,answerable,relevant_pages,notes\nq1,Facts?,yes,3,\n", encoding="utf-8")
    assert gold_mod.read_gold(path).questions[0].evidence_quote == ""

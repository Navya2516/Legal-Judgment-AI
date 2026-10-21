"""Run the gold questions through the real question-answering service, and score it.

This uses the application's own `answer_question`, so the retrieval, prompt,
quote checking and translation are exactly what a user gets. It calls the real
model, and the free Gemini tier allows only about 20 requests a day per model,
so the run is built around that:

* `--dry-run` shows how many questions would be asked and how many are cached;
* every answer is saved the moment it arrives, so a run can be stopped and
  resumed, and nothing already answered is asked (or counted) twice;
* `--max-calls` stops before the budget is spent. Retries that happen inside the
  Gemini client also count against Google's quota but are invisible here, so
  keep a margin.

Scores (answerable questions only unless stated):
* answered_rate: share the system answered;
* cites_gold_page: of the answered ones, share where at least one cited page is
  a page the human marked as relevant;
* point_on_gold_page: of all answer sentences, share whose cited pages include a gold page;
* quote_checked: of all answer sentences, share whose quote was found on the page;
* abstain_on_unanswerable: for questions the judgment does not answer, share where the
  system correctly declined to answer.
"""
import json
import statistics
import time
from pathlib import Path
from typing import Optional

from app.config import Settings
from app.schemas.ask import AskResponse
from app.services.index_store import IndexMeta, IndexStore
from app.services.ask import answer_question
from app.services.chunker import CLEANING_VERSION
from app.services.languages import get_language
from app.services.llm import LlmClient, LlmError
from evaluation.corpus import Corpus
from evaluation.gold import GoldSet
from evaluation.stats import proportion

ASK_TOP_K = 6  # the same default as the /ask endpoint


class CountingLlm:
    """Wraps a model client: counts calls, times them, passes everything through."""

    def __init__(self, inner: LlmClient, min_gap: float = 0.0, sleep=time.sleep) -> None:
        self.inner = inner
        self.name = inner.name
        self.calls = 0
        self.seconds: list[float] = []
        self.min_gap = min_gap  # seconds between model calls, to stay under a per-minute limit
        self._sleep = sleep
        self._last_start: Optional[float] = None

    def generate(self, *, system: str, prompt: str) -> str:
        if self.min_gap and self._last_start is not None:
            wait = self.min_gap - (time.monotonic() - self._last_start)
            if wait > 0:
                self._sleep(wait)
        self.calls += 1
        start = self._last_start = time.monotonic()
        try:
            return self.inner.generate(system=system, prompt=prompt)
        finally:
            self.seconds.append(time.monotonic() - start)


def build_loaded_index(corpus: Corpus, embedder, directory: Path, settings: Settings):
    store = IndexStore(Path(directory))
    if not store.exists(corpus.doc_id):
        vectors = embedder.embed([c.text for c in corpus.chunks])
        meta = IndexMeta(
            embedding_model=embedder.name, embedding_dim=int(vectors.shape[1]),
            chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap,
            cleaning_version=CLEANING_VERSION, chunk_count=len(corpus.chunks),
        )
        store.save(corpus.doc_id, vectors, corpus.chunks, meta)
    return store.load(corpus.doc_id)


def plan(corpus: Corpus, gold: GoldSet, cache_dir: Path, lang: str) -> dict:
    todo, cached = [], []
    for q in gold.questions:
        (cached if _cache_path(cache_dir, corpus, q.id, lang).exists() else todo).append(q.id)
    return {
        "document": corpus.name, "language": lang, "questions": len(gold.questions),
        "already_cached": len(cached), "to_ask": len(todo),
        "minimum_model_calls": len(todo) * (1 if lang == "en" else 2),
        "note": "Retries and translation repairs can add calls. The free tier allows about 20 requests per day per model.",
    }


def _cache_path(cache_dir: Path, corpus: Corpus, qid: str, lang: str) -> Path:
    return Path(cache_dir) / f"{corpus.doc_id}.{qid}.{lang}.json"


def run_ask(
    corpus: Corpus, gold: GoldSet, *, settings: Settings, llm: CountingLlm, embedder,
    cache_dir: Path, index_dir: Path, lang: str = "en", max_calls: Optional[int] = None,
    minute_wait: float = 65.0, minute_retries: int = 3, sleep=time.sleep,
) -> dict:
    language = get_language(lang)
    if language is None:
        raise ValueError(f"unsupported language {lang!r}")
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    loaded = build_loaded_index(corpus, embedder, index_dir, settings)
    stopped: Optional[str] = None
    for q in gold.questions:
        path = _cache_path(cache_dir, corpus, q.id, lang)
        if path.exists():
            continue
        if max_calls is not None and llm.calls >= max_calls:
            stopped = f"stopped before {q.id}: the --max-calls budget of {max_calls} was reached"
            break
        started = time.monotonic()
        before = llm.calls
        response = None
        fatal = False
        waits = 0
        while True:
            try:
                response = answer_question(
                    corpus.doc_id, q.question, pages=corpus.pages, loaded=loaded, embedder=embedder,
                    llm=llm, settings=settings, language=language, top_k=ASK_TOP_K,
                    batch_size=settings.translation_batch_size,
                )
                break
            except LlmError as exc:
                # A per-minute limit clears on its own: wait and ask this question again.
                # A daily limit does not, so that (and other hard errors) still stops the run.
                if exc.kind == "rate_limited" and "per-minute" in exc.message and waits < minute_retries:
                    waits += 1
                    print(f"  per-minute limit reached at {q.id}; waiting {minute_wait:.0f}s (wait {waits}/{minute_retries})")
                    sleep(minute_wait)
                    continue
                stopped = f"stopped at {q.id}: model error ({exc.kind}): {exc.message[:200]}"
                fatal = exc.kind in {"rate_limited", "auth", "not_configured", "model_not_found"}
                break
        if response is None:
            if fatal:
                break
            continue  # a bad reply for one question should not end the run
        payload = {
            "question_id": q.id, "language": lang, "seconds": round(time.monotonic() - started, 2),
            "model_calls": llm.calls - before, "response": json.loads(response.model_dump_json()),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"stopped": stopped, "model_calls_this_run": llm.calls}


def score_ask(corpus: Corpus, gold: GoldSet, cache_dir: Path, lang: str = "en") -> dict:
    answered = on_gold = 0
    points_total = points_on_gold = points_verified = 0
    abstain_ok = unans_total = 0
    answerable_total = scored = 0
    seconds, calls, models = [], [], set()
    missing: list[str] = []
    per_question = []
    for q in gold.questions:
        path = _cache_path(cache_dir, corpus, q.id, lang)
        if not path.exists():
            missing.append(q.id)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        resp = AskResponse.model_validate(data["response"])
        models.add(resp.model)
        seconds.append(data.get("seconds", 0))
        calls.append(data.get("model_calls", 0))
        row = {"id": q.id, "answerable": q.answerable, "answered": resp.answered}
        if q.answerable:
            answerable_total += 1
            scored += 1
            if resp.answered:
                answered += 1
                cited = {p for pt in resp.answer for p in pt.pages}
                hit = bool(cited & q.relevant_pages)
                on_gold += hit
                row["cites_gold_page"] = hit
                for pt in resp.answer:
                    points_total += 1
                    points_on_gold += bool(set(pt.pages) & q.relevant_pages)
                    points_verified += pt.status == "verified"
        else:
            unans_total += 1
            abstain_ok += not resp.answered
        per_question.append(row)
    return {
        "document": corpus.name, "language": lang, "models": sorted(models),
        "questions_in_gold": len(gold.questions), "questions_run": len(per_question), "not_run": missing,
        "answered_rate": proportion(answered, answerable_total),
        "cites_gold_page": proportion(on_gold, answered),
        "point_on_gold_page": proportion(points_on_gold, points_total),
        "quote_checked": proportion(points_verified, points_total),
        "abstain_on_unanswerable": proportion(abstain_ok, unans_total),
        "seconds_per_question": {
            "mean": round(statistics.mean(seconds), 2) if seconds else None,
            "median": round(statistics.median(seconds), 2) if seconds else None,
        },
        "model_calls_per_question_mean": round(statistics.mean(calls), 2) if calls else None,
        "per_question": per_question,
    }

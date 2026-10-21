"""Does the search find the pages that answer a question?

For each gold question we rank the document's chunks and ask whether the top
chunks cover the pages the human marked as relevant. Three methods are run on
the same chunks and questions:

* embedding: the application's own search (MiniLM + cosine similarity);
* bm25: a plain keyword baseline;
* random: a seeded shuffle, the floor any method must beat.

Metrics, per question then averaged (unanswerable questions are not scored here):
* hit@k:    1 if any of the top-k chunks overlaps a relevant page;
* recall@k: share of the relevant pages that the top-k chunks cover;
* mrr:      1 / rank of the first chunk that overlaps a relevant page (0 if none in the list).
"""
import numpy as np

from evaluation.bm25 import BM25, random_rank
from evaluation.corpus import Corpus
from evaluation.gold import GoldSet
from evaluation.stats import bootstrap_ci, mean

KS = [1, 3, 5, 6, 10]


def _chunk_pages(chunk) -> set[int]:
    return set(range(chunk.page_start, chunk.page_end + 1))


def score_ranking(ranked_chunk_ids: list[int], chunks, relevant: set[int], ks=KS) -> dict:
    out: dict[str, float] = {}
    first = None
    for rank, cid in enumerate(ranked_chunk_ids, start=1):
        if _chunk_pages(chunks[cid]) & relevant:
            first = rank
            break
    out["mrr"] = (1.0 / first) if first else 0.0
    for k in ks:
        covered: set[int] = set()
        for cid in ranked_chunk_ids[:k]:
            covered |= _chunk_pages(chunks[cid])
        hit = covered & relevant
        out[f"hit@{k}"] = 1.0 if hit else 0.0
        out[f"recall@{k}"] = len(hit) / len(relevant)
    return out


def embedding_ranker(corpus: Corpus, embedder):
    """Rank chunks by cosine similarity, exactly as the app's FAISS inner-product index does."""
    vectors = np.ascontiguousarray(embedder.embed([c.text for c in corpus.chunks]), dtype=np.float32)

    def rank(question: str) -> list[int]:
        q = np.ascontiguousarray(embedder.embed([question]), dtype=np.float32)[0]
        scores = vectors @ q
        return sorted(range(len(scores)), key=lambda i: -float(scores[i]))

    return rank


def evaluate_retrieval(corpus: Corpus, gold: GoldSet, embedder, seed: int = 0, ks=KS) -> dict:
    """Per-method, per-question scores plus averages with bootstrap intervals for one document."""
    questions = [q for q in gold.questions if q.answerable]
    n_chunks = len(corpus.chunks)
    bm25 = BM25([c.text for c in corpus.chunks])
    emb = embedding_ranker(corpus, embedder)
    methods = {
        "embedding": lambda q, i: emb(q.question),
        "bm25": lambda q, i: bm25.rank(q.question),
        "random": lambda q, i: random_rank(n_chunks, seed * 100003 + i),
    }
    per_question: dict[str, list[dict]] = {m: [] for m in methods}
    for i, q in enumerate(questions):
        for name, ranker in methods.items():
            scores = score_ranking(ranker(q, i), corpus.chunks, q.relevant_pages, ks)
            per_question[name].append({"id": q.id, **scores})
    return {
        "document": corpus.name,
        "questions_scored": len(questions),
        "chunks": n_chunks,
        "per_question": per_question,
        "summary": {name: summarise(rows, seed) for name, rows in per_question.items()},
        "skipped_gold_rows": gold.skipped,
    }


def summarise(rows: list[dict], seed: int = 0) -> dict:
    if not rows:
        return {}
    metrics = [k for k in rows[0] if k != "id"]
    out = {}
    for m in metrics:
        values = [r[m] for r in rows]
        out[m] = {"mean": round(mean(values), 4), "ci95": bootstrap_ci(values, seed=seed)}
    return out

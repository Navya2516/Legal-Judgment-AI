r"""Command line for the evaluation. Run from the backend folder:

    python -m evaluation.run <command> [options]

Commands (each writes JSON into evaluation\runs\<run>\ ; --run names the folder, default "main"):

  gold-check      check every evidence_quote in the gold files against the judgment's pages
  find            search a phrase in the judgments and print the PDF page numbers (exact text search)
  gold-template   write a blank <pdf>.questions.csv for each PDF, for a person to fill in
  corpus          describe the PDFs (pages, characters, OCR pages, chunks)
  retrieval       score search against the gold questions (embedding vs BM25 vs random)
  verifier        stress-test the quote checker on text from the judgments (no model needed)
  collect         count what the app already saved (summaries, provisions, translations)
  ask-run         ask the gold questions with the real model (needs a Gemini key; uses quota)
  ask-score       score the saved answers of ask-run
  audit-sample    write a sheet for a human to label (evidence or translation)
  audit-score     score a filled-in sheet
  report          build report.md from everything in the run folder

Always give --pdfs a folder of judgments, and --gold a folder of <pdf name>.questions.csv files.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from app.config import get_settings
from evaluation import ask_eval, audit, collect, gold as gold_mod, manifest, report as report_mod
from evaluation import retrieval_eval, verifier_eval
from evaluation.corpus import find_pdfs, load_corpus
from evaluation.stats import bootstrap_ci, mean

EVAL_DIR = Path(__file__).resolve().parent
RUNS = EVAL_DIR / "runs"


def _run_dir(args) -> Path:
    path = RUNS / args.run
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save(args, name: str, payload: dict, docs: list[dict] | None = None) -> Path:
    payload = {
        "manifest": manifest.build_manifest(
            get_settings(), command=" ".join(sys.argv[1:]), seed=args.seed, documents=docs or []
        ),
        **payload,
    }
    path = _run_dir(args) / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Saved {path}")
    return path


def _embedder():
    if os.environ.get("EVAL_TEST_EMBEDDER") == "1":
        from evaluation.testing import HashEmbedder

        print("WARNING: using the stand-in test embedder. These numbers are NOT results.")
        return HashEmbedder()
    from app.services.embedder import get_embedder

    return get_embedder()


def _corpora(args, **kw):
    pdfs = find_pdfs(Path(args.pdfs))
    if not pdfs:
        sys.exit(f"No PDF files found in {args.pdfs}")
    settings = get_settings()
    ocr = None
    if getattr(args, "ocr", False):
        from app.services.ocr import get_ocr_engine as ocr
    out = []
    for pdf in pdfs:
        print(f"Reading {pdf.name} ...")
        out.append(load_corpus(pdf, settings, get_ocr_engine=ocr, **kw))
    return out


def _gold_for(corpus, args):
    path = Path(args.gold) / f"{corpus.name}.questions.csv"
    if not path.exists():
        print(f"  no gold file for {corpus.name} (expected {path}); skipped")
        return None
    g = gold_mod.read_gold(path, corpus.page_count)
    for reason in g.skipped:
        print(f"  gold {corpus.name}: {reason}")
    return g


def cmd_gold_template(args):
    pdfs = find_pdfs(Path(args.pdfs))
    if not pdfs:
        sys.exit(f"No PDF files found in {args.pdfs}")
    for pdf in pdfs:
        target = Path(args.gold) / f"{pdf.stem}.questions.csv"
        try:
            gold_mod.write_template(target)
            print(f"Wrote {target}")
        except FileExistsError as exc:
            print(exc)
    print("Now open each CSV in Excel, add questions about the case, and fill answerable (yes/no) and relevant_pages.")


def cmd_gold_check(args):
    bad = checked = unchecked = 0
    for corpus in _corpora(args):
        g = _gold_for(corpus, args)
        if not g:
            continue
        results = gold_mod.check_gold(g, corpus.cleaned)
        counts: dict[str, int] = {}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
            if r["status"] in ("wrong_pages", "not_found"):
                bad += 1
                where = f" (the quote is on page(s) {r['found_on']})" if r["found_on"] else " (the quote is not in this judgment: copy it again)"
                print(f"  {corpus.name} {r['id']}: {r['status']}{where}")
        checked += counts.get("ok", 0) + counts.get("wrong_pages", 0) + counts.get("not_found", 0)
        unchecked += counts.get("no_quote", 0)
        print(f"{corpus.name}: {counts or 'no fully labelled answerable rows yet'}")
    if checked == 0:
        print("Nothing was checked: no answerable row has both labels and an evidence_quote yet.")
        return 1
    if unchecked:
        print(f"{unchecked} answerable row(s) have no evidence_quote, so their pages are not checked.")
    print("All checked quotes are on the listed pages." if not bad else f"{bad} row(s) need fixing before you run retrieval.")
    return 1 if bad else 0


def cmd_find(args):
    from app.services.grounding import normalize

    needle = normalize(args.phrase)
    if len(needle) < 8:
        sys.exit("Type at least a few words so the search is meaningful.")
    for corpus in _corpora(args):
        hits = [p for p, t in corpus.cleaned.items() if needle in normalize(t)]
        shown = ", ".join(str(p) for p in hits[:40]) + (" ..." if len(hits) > 40 else "")
        print(f"{corpus.name}: {len(hits)} page(s): {shown or 'none'}")


def cmd_corpus(args):
    corpora = _corpora(args)
    docs = [c.describe() for c in corpora]
    for d in docs:
        print(f"  {d['name']}: {d['pages']} pages, {d['characters']:,} characters, {d['ocr_pages']} OCR, {d['empty_pages']} empty, {d['chunks']} chunks")
    _save(args, "corpus", {"documents": docs}, docs)


def cmd_retrieval(args):
    embedder = _embedder()
    per_doc, docs = [], []
    pooled_rows: dict[int, dict[str, list]] = {}
    for size in args.chunk_sizes:
        pooled_rows[size] = {"embedding": [], "bm25": [], "random": []}
        for corpus in _corpora(args, chunk_size=size):
            g = _gold_for(corpus, args)
            if not g or not any(q.answerable for q in g.questions):
                continue
            result = retrieval_eval.evaluate_retrieval(corpus, g, embedder, seed=args.seed)
            result["chunk_size"] = size
            per_doc.append(result)
            docs.append(corpus.describe())
            for m, rows in result["per_question"].items():
                pooled_rows[size][m].extend(rows)
            print(f"  {corpus.name} (chunk {size}): {result['questions_scored']} questions scored")
    if not per_doc:
        sys.exit("Nothing to score: no gold file has any fully labelled answerable question.")
    by_size = {
        str(size): {m: retrieval_eval.summarise(rows, args.seed) for m, rows in methods.items()}
        for size, methods in pooled_rows.items()
    }
    first = str(args.chunk_sizes[0])
    _save(args, "retrieval", {
        "embedder": embedder.name, "chunk_sizes": args.chunk_sizes, "per_document": per_doc,
        "pooled_questions": len(pooled_rows[args.chunk_sizes[0]]["embedding"]),
        "pooled": by_size[first], "pooled_by_chunk_size": by_size,
    }, docs)


def cmd_verifier(args):
    corpora = _corpora(args)
    per_doc = []
    for i, c in enumerate(corpora):
        other = corpora[(i + 1) % len(corpora)] if len(corpora) > 1 else None
        per_doc.append(verifier_eval.evaluate_verifier(c, samples=args.samples, seed=args.seed, other=other))
        print(f"  {c.name}: {per_doc[-1]['spans_sampled']} spans")
    _save(args, "verifier", {"per_document": per_doc}, [c.describe() for c in corpora])


def _names() -> dict[str, str]:
    from app.services.document_store import DocumentStore

    names = {}
    try:
        store = DocumentStore(get_settings().registry_path)
        for rec in store.list():
            names[rec.id] = rec.filename
    except Exception:
        pass
    return names


def cmd_collect(args):
    rows = collect.collect_results(Path(args.results_dir) if args.results_dir else get_settings().results_path, _names())
    summary = collect.summarise_collected(rows)
    print(f"{len(rows)} saved results read")
    _save(args, "collect", {"rows": rows, "summary": summary})


def _corpus_and_gold(args):
    for corpus in _corpora(args):
        g = _gold_for(corpus, args)
        if g and g.questions:
            yield corpus, g


def cmd_ask_run(args):
    settings = get_settings()
    run = _run_dir(args)
    cache, idx = run / "ask_cache", run / "indexes"
    pairs = list(_corpus_and_gold(args))
    if args.dry_run:
        for corpus, g in pairs:
            print(json.dumps(ask_eval.plan(corpus, g, cache, args.lang), indent=1))
        return
    from app.services.llm import get_llm

    llm = ask_eval.CountingLlm(get_llm(), min_gap=args.min_gap)
    embedder = _embedder()
    for corpus, g in pairs:
        info = ask_eval.run_ask(corpus, g, settings=settings, llm=llm, embedder=embedder,
                                cache_dir=cache, index_dir=idx, lang=args.lang, max_calls=args.max_calls)
        print(f"  {corpus.name}: {info}")
        if info["stopped"]:
            break
    print(f"Model calls made by this command: {llm.calls} (retries inside the Gemini client also count toward Google's quota).")


def cmd_ask_score(args):
    run = _run_dir(args)
    per_doc, model = [], None
    for corpus, g in _corpus_and_gold(args):
        per_doc.append(ask_eval.score_ask(corpus, g, run / "ask_cache", args.lang))
    for f in (run / "ask_cache").glob("*.json"):
        model = json.loads(f.read_text(encoding="utf-8"))["response"]["model"]
        break
    _save(args, "ask-score", {"language": args.lang, "model": model, "per_document": per_doc})


def cmd_audit_sample(args):
    settings = get_settings()
    out = Path(args.out)
    names = _names()
    if args.kind == "evidence":
        from app.services.chunker import clean_pages
        from app.services.page_store import PageStore

        store = PageStore(settings.extracted_path)
        items = []
        for row in collect.collect_results(settings.results_path, names):
            if row.get("language") != "en" or "error" in row:
                continue
            data = json.loads((settings.results_path / row["file"]).read_text(encoding="utf-8"))
            cleaned = clean_pages(store.load(row["document_id"]))
            items += audit.evidence_items(data, document=row["document"], source=row["kind"],
                                          page_text=lambda p, c=cleaned: c.get(p, ""))
        picked = audit.sample_stratified(items, "auto_status", args.per_stratum, args.seed)
        n = audit.write_evidence_sheet(out, picked)
    else:
        items = []
        for row in collect.collect_results(settings.results_path, names):
            if row.get("language") in (None, "en") or "error" in row or (args.language and row["language"] != args.language):
                continue
            data = json.loads((settings.results_path / row["file"]).read_text(encoding="utf-8"))
            items += audit.translation_items(data, document=row["document"], source=row["kind"], language=row["language"])
        picked = audit.sample_stratified(items, "auto_check", args.per_stratum, args.seed)
        n = audit.write_translation_sheet(out, picked)
    print(f"Wrote {n} items to {out}. Fill the label column (see evaluation/README.md), then run audit-score.")


def cmd_audit_score(args):
    labels = audit.EVIDENCE_LABELS if args.kind == "evidence" else audit.TRANSLATION_LABELS
    group = "auto_status" if args.kind == "evidence" else "auto_check"
    result = audit.score_sheet(Path(args.sheet), labels, group, Path(args.second) if args.second else None)
    print(f"{result['labelled']} labelled of {result['rows']} ({result['blank']} blank, {len(result['invalid_labels'])} invalid)")
    _save(args, f"audit-{args.kind}", result)


def cmd_report(args):
    run = _run_dir(args)
    text = report_mod.build_report(run)
    (run / "report.md").write_text(text, encoding="utf-8")
    print(f"Wrote {run / 'report.md'}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m evaluation.run", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp, pdfs=False, gold=False):
        sp.add_argument("--run", default="main", help="run folder name under evaluation/runs (default: main)")
        sp.add_argument("--seed", type=int, default=0)
        if pdfs:
            sp.add_argument("--pdfs", default=str(EVAL_DIR / "pdfs"), help="folder of judgment PDFs")
            sp.add_argument("--ocr", action="store_true", help="OCR scanned pages (slow)")
        if gold:
            sp.add_argument("--gold", default=str(EVAL_DIR / "gold"), help="folder of <pdf name>.questions.csv")

    sp = sub.add_parser("gold-template"); common(sp, True, True); sp.set_defaults(fn=cmd_gold_template)
    sp = sub.add_parser("gold-check"); common(sp, True, True); sp.set_defaults(fn=cmd_gold_check)
    sp = sub.add_parser("find"); common(sp, True); sp.add_argument("phrase"); sp.set_defaults(fn=cmd_find)
    sp = sub.add_parser("corpus"); common(sp, True); sp.set_defaults(fn=cmd_corpus)
    sp = sub.add_parser("retrieval"); common(sp, True, True)
    sp.add_argument("--chunk-sizes", type=int, nargs="+", default=[get_settings().chunk_size]); sp.set_defaults(fn=cmd_retrieval)
    sp = sub.add_parser("verifier"); common(sp, True)
    sp.add_argument("--samples", type=int, default=200); sp.set_defaults(fn=cmd_verifier)
    sp = sub.add_parser("collect"); common(sp)
    sp.add_argument("--results-dir", default=None); sp.set_defaults(fn=cmd_collect)
    sp = sub.add_parser("ask-run"); common(sp, True, True)
    sp.add_argument("--lang", default="en"); sp.add_argument("--max-calls", type=int, default=15)
    sp.add_argument("--min-gap", type=float, default=13.0,
                    help="seconds between model calls; 13 keeps under a 5-per-minute limit")
    sp.add_argument("--dry-run", action="store_true"); sp.set_defaults(fn=cmd_ask_run)
    sp = sub.add_parser("ask-score"); common(sp, True, True)
    sp.add_argument("--lang", default="en"); sp.set_defaults(fn=cmd_ask_score)
    sp = sub.add_parser("audit-sample"); common(sp)
    sp.add_argument("--kind", choices=["evidence", "translation"], required=True)
    sp.add_argument("--out", required=True, help="CSV to create (never overwrites an existing file)")
    sp.add_argument("--per-stratum", type=int, default=25)
    sp.add_argument("--language", default=None, help="translation sheets: only this language code")
    sp.set_defaults(fn=cmd_audit_sample)
    sp = sub.add_parser("audit-score"); common(sp)
    sp.add_argument("--kind", choices=["evidence", "translation"], required=True)
    sp.add_argument("--sheet", required=True); sp.add_argument("--second", default=None)
    sp.set_defaults(fn=cmd_audit_score)
    sp = sub.add_parser("report"); common(sp); sp.set_defaults(fn=cmd_report)

    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())

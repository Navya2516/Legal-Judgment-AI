"""Assemble run outputs into one Markdown report (paste-able into Word) and a JSON file."""
import json
from pathlib import Path

from evaluation.stats import fmt_rate, proportion
from evaluation.testing import is_test_name

LIMITS = """\
## What these numbers do and do not show

* Retrieval scores measure whether the top passages cover the pages a person marked as relevant. They depend on those labels and on how many questions were labelled; read the interval, not only the average.
* "Quote checked" means the quoted words were found on the cited page. It does not prove the sentence is a faithful paraphrase; the human audit estimates that.
* The checker stress test uses text cut from the judgment. It tests the checker, not how often the language model writes unsupported claims.
* Counts from saved results describe the runs that happened to be saved, not a random sample of model behaviour.
* Translation checks are automatic (numbers and script); they do not judge legal accuracy. Only a bilingual reviewer can.
* Cohen's kappa is unstable when almost every label is the same (for example nearly all "supported"): it can be near zero even when the reviewers agree on most items. Read it next to the raw agreement, and look at the items they disagreed on.
* The human audit covers sentences the quote checker had already accepted. It says nothing about claims removed as unsupported, or about answers the model declined to give.
* Seconds per question include the pause the evaluation inserts between model calls to stay under the free-tier limit, and any waiting for busy servers. Do not quote them as response time.\n* Retrieval scores count only the pages listed in the gold file. A passage that answers the question from a page not listed there counts as a miss, so on long judgments the scores can understate real retrieval quality.\n* A judgment uploaded twice appears twice in the saved-results counts. Check the Document column before reading a pooled figure as independent.\n* Results hold for the judgments, model version and settings listed above. They are not evidence about other courts, languages, models or documents.
"""


def _load(run: Path, name: str):
    path = run / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _translation_audits(run: Path) -> list:
    """Per-language audit results saved as audit-translation-<code>.json, in language order.

    Every audit-score run writes the same audit-translation.json, so a run folder that
    audited several languages keeps one copy per language under this naming.
    """
    found = []
    for path in sorted(Path(run).glob("audit-translation-*.json")):
        code = path.stem[len("audit-translation-"):]
        try:
            found.append((code, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return found


def _ci(d: dict) -> str:
    if not d or d.get("mean") is None:
        return "n/a"
    ci = d.get("ci95")
    return f"{d['mean']:.3f}" + (f" [{ci[0]:.3f}-{ci[1]:.3f}]" if ci else "")


def build_report(run: Path) -> str:
    run = Path(run)
    out: list[str] = []
    corpus = _load(run, "corpus")
    retrieval = _load(run, "retrieval")
    verifier = _load(run, "verifier")
    collected = _load(run, "collect")
    ask = _load(run, "ask-score")
    audits = {n: _load(run, n) for n in ("audit-evidence", "audit-translation")}

    manifests = [x["manifest"] for x in (corpus, retrieval, verifier, collected, ask) if x and "manifest" in x]
    test_only = bool(retrieval and is_test_name((retrieval.get("embedder") or "")))
    out.append(f"# Evaluation report: run `{run.name}`\n")
    if test_only:
        out += ["> **TEST RUN. A stand-in embedder was used, so these numbers are not results. Do not quote them.**\n"]
    if manifests:
        m = manifests[-1]
        s = m["settings"]
        out += [
            f"Created {m['created_at']} with Python {m['python']} on {m['platform']}.",
            f"Seed {m['seed']}. Embedding model `{s.get('embedding_model')}`; chunks {s.get('chunk_size')}/{s.get('chunk_overlap')} characters; language model setting `{s.get('gemini_model')}` when the last command ran (temperature {s.get('llm_temperature')}); each saved result and answer below names the model that actually wrote it.",
            "Packages: " + ", ".join(f"{k} {v}" for k, v in m["packages"].items()) + ".\n",
        ]
    if corpus:
        out += ["## Documents\n", "| Document | Pages | Characters | OCR pages | Empty pages | Chunks | SHA-256 (first 12) |", "|---|---|---|---|---|---|---|"]
        for d in corpus["documents"]:
            out.append(f"| {d['name']} | {d['pages']} | {d['characters']:,} | {d['ocr_pages']} | {d['empty_pages']} | {d['chunks']} | {d['sha256'][:12]} |")
        out.append("")
    if retrieval:
        out += ["## Retrieval\n", f"Embedder: `{retrieval.get('embedder')}`. Questions scored: {retrieval['pooled_questions']} across {len({d['document'] for d in retrieval['per_document']})} document(s). Mean per question with 95% bootstrap interval.\n"]
        metrics = ["hit@1", "hit@3", "hit@5", "hit@6", "hit@10", "recall@5", "recall@10", "mrr"]
        for size, pooled in (retrieval.get("pooled_by_chunk_size") or {"": retrieval["pooled"]}).items():
            if size:
                out.append(f"Chunk size {size} characters:\n")
            out += ["| Method | " + " | ".join(metrics) + " |", "|---|" + "---|" * len(metrics)]
            for method, summary in pooled.items():
                out.append(f"| {method} | " + " | ".join(_ci(summary.get(m)) for m in metrics) + " |")
            out.append("")
        seen_docs = set()
        for doc in retrieval["per_document"]:
            if doc["skipped_gold_rows"] and doc["document"] not in seen_docs:
                seen_docs.add(doc["document"])
                out.append(f"Skipped gold rows in {doc['document']} (fix the CSV): " + "; ".join(doc["skipped_gold_rows"]) + "\n")
    if verifier:
        out += ["## Quote-checker stress test\n", "Quotes cut or altered from the judgment text itself; the right outcome is known.\n", "| Document | Control | Rate | What the rate means |", "|---|---|---|---|"]
        for doc in verifier["per_document"]:
            for name, c in doc["controls"].items():
                out.append(f"| {doc['document']} | {name} | {fmt_rate(c)} | {c['expectation']} |")
                if "only_spans_found_on_one_page" in c:
                    u = c["only_spans_found_on_one_page"]
                    out.append(f"| {doc['document']} | {name} (spans on one page only) | {fmt_rate(u)} | same, excluding {c['spans_found_on_several_pages']} spans whose words also occur on other pages |")
        out.append("")
    if collected:
        out += ["## Saved results (no new model calls)\n"]
        e, t = collected["summary"]["english_results"], collected["summary"]["translated_results"]
        out.append(f"English results: {e['results']}. Points shown: {e['points_shown']}. Quote checked: {fmt_rate(e['quote_checked_of_shown'])}.")
        if e.get("removed_as_unsupported"):
            out.append(f"Claims removed because nothing supported them: {fmt_rate(e['removed_as_unsupported'])} of {e['claims_made_by_model']} claims made.")
        if t and t.get("translation_checks"):
            out.append("\nAutomatic translation checks:\n")
            out += ["| Check | Rate |", "|---|---|"] + [f"| {k} | {fmt_rate(v)} |" for k, v in t["translation_checks"].items()]
        used_models = sorted({r["model"] for r in collected["rows"] if r.get("model")})
        out.append("")
        if len(used_models) > 1:
            out += [f"> **Saved results came from more than one model ({', '.join(used_models)}). Do not pool them as one result; the table names the model of each.**", ""]
        out += ["| Document | Kind | Lang | Model | Mode | Pages seen | Shown | Quote checked | Page only | Removed |", "|---|---|---|---|---|---|---|---|---|---|"]
        for r in collected["rows"]:
            if "error" in r:
                continue
            seen = f"{r['pages_in_context']}/{r['total_pages']}" if r["pages_in_context"] is not None else "-"
            out.append(f"| {r['document']} | {r['kind']} | {r['language']} | {r.get('model') or '-'} | {r['mode'] or '-'} | {seen} | {r['points_shown']} | {r['verified']} | {r['cited']} | {r['dropped_unsupported'] if r['dropped_unsupported'] is not None else '-'} |")
        out.append("")
    if ask:
        out += ["## Question answering (real model)\n", f"Model `{ask.get('model')}`, language `{ask.get('language')}`.\n", "| Document | Answered (answerable) | Cites a gold page | Sentence on gold page | Sentence quote-checked | Declined when unanswerable | s/question | Not run |", "|---|---|---|---|---|---|---|---|"]
        used = sorted({m for d in ask["per_document"] for m in d.get("models", [])})
        if len(used) > 1:
            out.insert(len(out) - 3, f"> **Answers in this run came from more than one model ({', '.join(used)}). Do not pool them as one result.**\n")
        for d in ask["per_document"]:
            out.append(f"| {d['document']} | {fmt_rate(d['answered_rate'])} | {fmt_rate(d['cites_gold_page'])} | {fmt_rate(d['point_on_gold_page'])} | {fmt_rate(d['quote_checked'])} | {fmt_rate(d['abstain_on_unanswerable'])} | {d['seconds_per_question']['mean']} | {len(d['not_run'])} |")
        out.append("")
    ev, tr = audits["audit-evidence"], audits["audit-translation"]
    if ev:
        o = ev["overall"]
        out += ["## Human audit: does the page support the sentence?\n", f"Sheet `{Path(ev['sheet']).name}`: {ev['labelled']} labelled of {ev['rows']} ({ev['blank']} blank).", f"Supported: {fmt_rate(o['supported_only'])}. Supported or partly: {fmt_rate(o['supported_or_partly'])}."]
        for k, v in ev.get("by_auto_status", {}).items():
            out.append(f"* automatic status `{k}`: supported {fmt_rate(v['supported_only'])}; supported or partly {fmt_rate(v['supported_or_partly'])}")
        if ev.get("second_reviewer"):
            s = ev["second_reviewer"]
            out.append(f"\nSecond reviewer: {s['items_labelled_by_both']} items in common, agreement {fmt_rate(s['agreement'])}, Cohen's kappa {s['cohens_kappa']}.")
        out.append("")
    langs = _translation_audits(run)
    if langs:
        out += ["## Human audit: translation adequacy\n",
                "Each language was labelled on its own sheet. Rates below come from the first reviewer's labels; "
                "agreement compares the two reviewers on the same items.\n",
                "| Language | Items | Adequate | Minor error | Major error | Adequate rate | Reviewer agreement | Cohen's kappa |",
                "|---|---|---|---|---|---|---|---|"]
        total = {"adequate": 0, "minor_error": 0, "major_error": 0}
        for lang, a in langs:
            c = a["overall"]["counts"]
            for k in total:
                total[k] += c.get(k, 0)
            s2 = a.get("second_reviewer")
            agree = fmt_rate(s2["agreement"]) if s2 else "n/a (one reviewer)"
            kappa = s2["cohens_kappa"] if s2 and s2.get("cohens_kappa") is not None else "n/a"
            out.append(f"| {lang} | {a['labelled']} | {c.get('adequate', 0)} | {c.get('minor_error', 0)} | {c.get('major_error', 0)} | "
                       f"{fmt_rate(a['overall']['adequate_only'])} | {agree} | {kappa} |")
        n_all = sum(total.values())
        out += ["", f"All languages together: {total['adequate']} adequate, {total['minor_error']} minor error, "
                    f"{total['major_error']} major error of {n_all} items "
                    f"({fmt_rate(proportion(total['adequate'], n_all))} adequate). "
                    "Items from one language share a document, so the interval is optimistic.", ""]
        flagged = {}
        for lang, a in langs:
            for check, v in a.get("by_auto_check", {}).items():
                if check != "ok":
                    d = flagged.setdefault(check, [0, 0])
                    d[0] += v["counts"].get("adequate", 0)
                    d[1] += v["adequate_only"]["n"]
        for check, (ok, n) in flagged.items():
            out.append(f"* items the automatic check flagged as `{check}`: the reviewer rated {ok} of {n} adequate")
        out.append("")
    elif tr:
        o = tr["overall"]
        out += ["## Human audit: translation adequacy\n", f"Sheet `{Path(tr['sheet']).name}`: {tr['labelled']} labelled of {tr['rows']}.", f"Adequate: {fmt_rate(o['adequate_only'])}. Adequate or minor error: {fmt_rate(o['adequate_or_minor_error'])}."]
        for k, v in tr.get("by_language", {}).items():
            out.append(f"* {k}: adequate {fmt_rate(v['adequate_only'])}; no major error {fmt_rate(v['adequate_or_minor_error'])}")
        for k, v in tr.get("by_auto_check", {}).items():
            out.append(f"* automatic check `{k}`: adequate {fmt_rate(v['adequate_only'])}")
        out.append("")
    if len(out) <= 2:
        out.append("No results found in this run folder yet. Run the evaluation commands first (see evaluation/README.md).\n")
    out.append(LIMITS)
    return "\n".join(out)

"""Count what the application has already produced: no new model calls.

Reads the saved results (summary, provisions, continuation, and their
translations) and reports, per document, result kind and language:

* how many points the model wrote that survived, how many are quote-checked
  ("verified") and how many are page-only ("cited");
* how many claims were removed because nothing supported them;
* for translations, how the automatic checks came out (ok, numbers_changed,
  wrong_language, untranslated);
* how much of a long judgment the model actually saw.

"verified" means the quoted words were found on the cited page. It does not
prove the sentence is a faithful paraphrase; that is what the human audit is for.
"""
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterator, Optional

from evaluation.stats import proportion

_FILE = re.compile(r"^(?P<doc>[a-f0-9]{32})\.(?P<kind>summary|provisions|continuation)(?:\.(?P<lang>[a-z]{2}))?\.json$")
CHECKS = ["ok", "numbers_changed", "wrong_language", "untranslated"]


def iter_points(node: Any) -> Iterator[dict]:
    """Every evidence-bearing point in a result, wherever it sits in the JSON."""
    if isinstance(node, dict):
        if node.get("status") in {"verified", "cited"} and "pages" in node:
            yield node
        for value in node.values():
            yield from iter_points(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_points(value)


def collect_results(results_dir: Path, names: Optional[dict[str, str]] = None) -> list[dict]:
    names = names or {}
    rows: list[dict] = []
    for path in sorted(Path(results_dir).glob("*.json")):
        m = _FILE.match(path.name)
        if not m:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows.append({"file": path.name, "error": "unreadable"})
            continue
        points = list(iter_points(data))
        status = Counter(p["status"] for p in points)
        checks = Counter(p["check"] for p in points if "check" in p)
        grounding = data.get("grounding") or {}
        dropped = grounding.get("dropped_unsupported")
        seen, total = data.get("pages_in_context"), data.get("total_pages")
        rows.append(
            {
                "file": path.name,
                "document_id": m["doc"],
                "document": names.get(m["doc"], m["doc"][:8]),
                "kind": m["kind"],
                "language": m["lang"] or "en",
                "model": data.get("model"),
                "generated_at": data.get("generated_at"),
                "mode": data.get("mode"),
                "pages_in_context": seen,
                "total_pages": total,
                "points_shown": len(points),
                "verified": status["verified"],
                "cited": status["cited"],
                "dropped_unsupported": dropped,
                "claims_made": grounding.get("points_total"),
                "checks": {c: checks[c] for c in CHECKS if checks[c]},
                "translation_quality": data.get("quality"),
                "stale": data.get("stale"),
            }
        )
    return rows


def summarise_collected(rows: list[dict]) -> dict:
    """Pool the rows with Wilson intervals.

    Evidence statuses are pooled over the English results only: a translation
    copies the status of the English point it came from, so counting both
    would count the same evidence twice. Translation checks come from the
    translated results.
    """
    good = [r for r in rows if "error" not in r]

    def pool(selected: list[dict]) -> dict:
        shown = sum(r["points_shown"] for r in selected)
        verified = sum(r["verified"] for r in selected)
        made = sum(r["claims_made"] for r in selected if r["claims_made"] is not None)
        dropped = sum(r["dropped_unsupported"] for r in selected if r["dropped_unsupported"] is not None)
        check_total: Counter = Counter()
        for r in selected:
            check_total.update(r["checks"])
        translated = sum(check_total.values())
        out = {
            "results": len(selected),
            "points_shown": shown,
            "quote_checked_of_shown": proportion(verified, shown),
            "claims_made_by_model": made,
            "removed_as_unsupported": proportion(dropped, made) if made else None,
        }
        if translated:
            out["translation_checks"] = {c: proportion(check_total[c], translated) for c in CHECKS}
        return out

    by: dict[str, dict] = {}
    for key in sorted({(r["kind"], r["language"]) for r in good}):
        by[f"{key[0]}.{key[1]}"] = pool([r for r in good if (r["kind"], r["language"]) == key])
    english = [r for r in good if r["language"] == "en"]
    translated = [r for r in good if r["language"] != "en"]
    tr = pool(translated) if translated else None
    if tr:
        tr.pop("quote_checked_of_shown", None)
        tr.pop("claims_made_by_model", None)
        tr.pop("removed_as_unsupported", None)
    return {"english_results": pool(english), "translated_results": tr, "by_kind_and_language": by}

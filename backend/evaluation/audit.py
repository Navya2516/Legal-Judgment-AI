"""Human audit: does the page really support the sentence?

The automatic check only proves a quote exists on a page. Whether the sentence
is a fair statement of what the page says is a judgment a person must make, so
this module writes the sheets people fill in and scores them afterwards. It
never fills in a label itself.

Evidence audit (reviewer who reads English). For each sentence, read the quote
and the page text next to it, then write one label:
  supported      the page says what the sentence says
  partly         the page supports part of the sentence, or says it less strongly
  not_supported  the page does not say this, or says something different

Translation audit (reviewer fluent in the language). Compare the translated
sentence with the English sentence it came from:
  adequate       same meaning, correct legal terms
  minor_error    meaning kept, but a wrong or awkward word, or a small omission
  major_error    meaning changed, something added or lost that matters

Two reviewers on the same sheet allow a chance-corrected agreement figure
(Cohen's kappa), which a paper should report.
"""
import csv
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional

from evaluation.collect import iter_points
from evaluation.stats import cohens_kappa, proportion

EVIDENCE_LABELS = ["supported", "partly", "not_supported"]
TRANSLATION_LABELS = ["adequate", "minor_error", "major_error"]
EVIDENCE_FIELDS = [
    "item_id", "document", "source", "section", "auto_status", "pages", "claim", "quote", "page_context", "label", "notes",
]
TRANSLATION_FIELDS = [
    "item_id", "document", "source", "section", "language", "auto_check", "pages", "english", "translation", "label", "notes",
]
_WORD = re.compile(r"\w+", re.UNICODE)


def context_window(page_text: str, quote: Optional[str], width: int = 700) -> str:
    """Page text around where the quote starts, so the reviewer sees it in context."""
    flat = " ".join((page_text or "").split())
    words = _WORD.findall(quote or "")[:4]
    if len(words) >= 3:
        pattern = r"\W+".join(re.escape(w) for w in words)
        m = re.search(pattern, flat, re.IGNORECASE)
        if m:
            start = max(0, m.start() - width // 3)
            return flat[start : start + width]
    return flat[:width]


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path} already exists; it may hold someone's labels, so it was not overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _section_of(path_keys: list[str]) -> str:
    return path_keys[0] if path_keys else ""


def _walk(node, trail=()):
    """Like iter_points but remembers the top-level section each point sits in."""
    if isinstance(node, dict):
        if node.get("status") in {"verified", "cited"} and "pages" in node:
            yield (trail[0] if trail else ""), node
        for key, value in node.items():
            yield from _walk(value, trail + (key,))
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value, trail)


def evidence_items(result: dict, *, document: str, source: str, page_text: Callable[[int], str]) -> list[dict]:
    items = []
    for n, (section, p) in enumerate(_walk(result), start=1):
        claim = p.get("source_text") or p.get("text") or p.get("role_in_case") or ""
        if not claim:
            continue
        pages = p.get("pages") or []
        items.append(
            {
                "document": document, "source": source, "section": section,
                "auto_status": p["status"], "pages": ";".join(str(x) for x in pages),
                "claim": claim, "quote": p.get("quote") or "",
                "page_context": context_window(page_text(pages[0]) if pages else "", p.get("quote")),
                "label": "", "notes": "",
            }
        )
    return items


def translation_items(result: dict, *, document: str, source: str, language: str) -> list[dict]:
    items = []
    for section, p in _walk(result):
        if "check" not in p or not p.get("source_text"):
            continue
        text = p.get("text") or p.get("role_in_case")
        if not text:
            continue
        items.append(
            {
                "document": document, "source": source, "section": section, "language": language,
                "auto_check": p["check"], "pages": ";".join(str(x) for x in p.get("pages") or []),
                "english": p["source_text"], "translation": text, "label": "", "notes": "",
            }
        )
    return items


def sample_stratified(items: list[dict], key: str, per_stratum: int, seed: int) -> list[dict]:
    """Up to `per_stratum` items from each value of `key`, seeded, in a stable order."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        groups[it[key]].append(it)
    rng = random.Random(seed)
    chosen: list[dict] = []
    for value in sorted(groups):
        pool = groups[value]
        rng.shuffle(pool)
        chosen.extend(pool[:per_stratum])
    rng.shuffle(chosen)
    return chosen


def write_evidence_sheet(path: Path, items: list[dict]) -> int:
    rows = [{**it, "item_id": f"e{i:03d}"} for i, it in enumerate(items, start=1)]
    _write(path, EVIDENCE_FIELDS, rows)
    return len(rows)


def write_translation_sheet(path: Path, items: list[dict]) -> int:
    rows = [{**it, "item_id": f"t{i:03d}"} for i, it in enumerate(items, start=1)]
    _write(path, TRANSLATION_FIELDS, rows)
    return len(rows)


def _read(path: Path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _clean(label: str) -> str:
    return (label or "").strip().lower().replace(" ", "_").replace("-", "_")


def score_sheet(path: Path, labels: list[str], group_by: str, second: Optional[Path] = None) -> dict:
    """Score a filled-in sheet. Rows without a valid label are counted and left out."""
    rows = _read(path)
    labelled, blank, invalid = [], 0, []
    for r in rows:
        lab = _clean(r.get("label", ""))
        if not lab:
            blank += 1
        elif lab not in labels:
            invalid.append(f"{r.get('item_id')}: {r.get('label')!r}")
        else:
            labelled.append({**r, "label": lab})
    first_label = labels[0]
    top_two = set(labels[:2])
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in labelled:
        groups[r.get(group_by, "")].append(r)

    def rates(rs: list[dict]) -> dict:
        return {
            f"{first_label}_only": proportion(sum(r["label"] == first_label for r in rs), len(rs)),
            f"{labels[0]}_or_{labels[1]}": proportion(sum(r["label"] in top_two for r in rs), len(rs)),
            "counts": {l: sum(r["label"] == l for r in rs) for l in labels},
        }

    out = {
        "sheet": str(path), "rows": len(rows), "labelled": len(labelled), "blank": blank, "invalid_labels": invalid,
        "overall": rates(labelled),
        f"by_{group_by}": {k: rates(v) for k, v in sorted(groups.items())},
    }
    if "language" in (labelled[0] if labelled else {}):
        langs: dict[str, list[dict]] = defaultdict(list)
        for r in labelled:
            langs[r["language"]].append(r)
        out["by_language"] = {k: rates(v) for k, v in sorted(langs.items())}
    if second:
        other = {r["item_id"]: _clean(r.get("label", "")) for r in _read(second)}
        pairs = [(r["label"], other[r["item_id"]]) for r in labelled if other.get(r["item_id"]) in labels]
        out["second_reviewer"] = {
            "items_labelled_by_both": len(pairs),
            "agreement": proportion(sum(a == b for a, b in pairs), len(pairs)),
            "cohens_kappa": cohens_kappa([a for a, _ in pairs], [b for _, b in pairs]),
        }
    return out

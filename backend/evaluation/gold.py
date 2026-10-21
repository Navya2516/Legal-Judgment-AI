"""Gold questions: written and labelled by a person, never by this program.

One CSV per judgment, named <pdf stem>.questions.csv:

    id, question, answerable, relevant_pages, notes, evidence_quote

* answerable: yes or no. "no" means the judgment really does not answer it; the
  system should say so instead of guessing.
* relevant_pages: PDF page numbers (the numbers the viewer shows) holding the
  answer, as "78;279-280". Required for every "yes" row.

* evidence_quote (optional but strongly advised): a short exact quote, 8 to 25 words, copied
  from one of the relevant pages. `gold-check` searches for it and reports any row whose quote
  is not on a listed page, which catches wrong page numbers before they reach a result.

Rows that are not fully labelled are reported and skipped, never guessed.
"""
import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

FIELDS = ["id", "question", "answerable", "relevant_pages", "notes", "evidence_quote"]

# Generic starters that make sense for any judgment. The person adds questions
# that are specific to the case (a provision, a party, a date) and fills in
# answerable and relevant_pages for each one.
STARTER_QUESTIONS = [
    "What were the facts of the case?",
    "What were the main questions the court had to answer?",
    "What did the court finally decide?",
    "What reasons did the court give for its decision?",
    "What directions or orders did the court give?",
    "Which Articles or Sections did the court rely on?",
    "Who were the parties to the case?",
    "What happens next in this case?",
]

_RANGE = re.compile(r"^\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*$")


def parse_pages(spec: str, page_count: Optional[int] = None) -> set[int]:
    """'78;279-280' -> {78, 279, 280}. Raises ValueError on anything unclear."""
    pages: set[int] = set()
    for part in re.split(r"[;,]", spec or ""):
        if not part.strip():
            continue
        m = _RANGE.match(part)
        if not m:
            raise ValueError(f"cannot read page spec {part.strip()!r}")
        lo = int(m.group(1))
        hi = int(m.group(2) or lo)
        if lo < 1 or hi < lo or hi - lo > 50:
            raise ValueError(f"unreasonable page range {part.strip()!r}")
        pages.update(range(lo, hi + 1))
    if page_count is not None:
        outside = sorted(p for p in pages if p > page_count)
        if outside:
            raise ValueError(f"pages {outside} are beyond the document's {page_count} pages")
    return pages


@dataclass
class GoldQuestion:
    id: str
    question: str
    answerable: bool
    relevant_pages: set[int]
    notes: str = ""
    evidence_quote: str = ""


@dataclass
class GoldSet:
    doc: str
    questions: list[GoldQuestion] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # human-readable reasons


def write_template(path: Path, extra_questions: Optional[list[str]] = None) -> None:
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path} already exists; it may hold someone's labels, so it was not overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for i, q in enumerate(STARTER_QUESTIONS + (extra_questions or []), start=1):
            writer.writerow({"id": f"q{i:02d}", "question": q, "answerable": "", "relevant_pages": "", "notes": "", "evidence_quote": ""})


def read_gold(path: Path, page_count: Optional[int] = None) -> GoldSet:
    path = Path(path)
    gold = GoldSet(doc=path.name.replace(".questions.csv", ""))
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for n, row in enumerate(csv.DictReader(handle), start=2):
            qid = (row.get("id") or f"row{n}").strip()
            question = (row.get("question") or "").strip()
            if not question:
                continue
            answerable = (row.get("answerable") or "").strip().lower()
            if answerable not in {"yes", "no"}:
                gold.skipped.append(f"{qid}: answerable is blank (write yes or no)")
                continue
            try:
                pages = parse_pages(row.get("relevant_pages") or "", page_count)
            except ValueError as exc:
                gold.skipped.append(f"{qid}: {exc}")
                continue
            if answerable == "yes" and not pages:
                gold.skipped.append(f"{qid}: answerable is yes but relevant_pages is blank")
                continue
            if answerable == "no" and pages:
                gold.skipped.append(f"{qid}: answerable is no but relevant_pages is filled in")
                continue
            gold.questions.append(
                GoldQuestion(
                    qid, question, answerable == "yes", pages, (row.get("notes") or "").strip(),
                    (row.get("evidence_quote") or "").strip(),
                )
            )
    return gold


def check_gold(gold: GoldSet, cleaned: dict[int, str]) -> list[dict]:
    """Check each answerable row's evidence_quote against the judgment text.

    status: ok (quote is on a listed page), wrong_pages (quote exists, but not on a listed page;
    `found_on` says where), not_found (quote is nowhere in the judgment: copy it again) or
    no_quote (nothing to check; the pages rest on the labeller alone).
    """
    from app.services.grounding import PageTexts

    texts = PageTexts(cleaned)
    everywhere = set(cleaned)
    out = []
    for q in gold.questions:
        if not q.answerable:
            continue
        if not q.evidence_quote:
            out.append({"id": q.id, "status": "no_quote", "found_on": []})
            continue
        on_listed = texts.find_quote(q.evidence_quote, q.relevant_pages & everywhere)
        if on_listed:
            out.append({"id": q.id, "status": "ok", "found_on": on_listed})
            continue
        elsewhere = texts.find_quote(q.evidence_quote, everywhere)
        out.append({"id": q.id, "status": "wrong_pages" if elsewhere else "not_found", "found_on": elsewhere or []})
    return out

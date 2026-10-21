"""Find the statutory provisions a judgment refers to (Articles, Sections, Rules).

This is deliberately NOT done by the language model: a pattern search reads
every page, never skips one, and cannot invent a provision. The result is a
list of provisions with the pages they appear on and how often.

What it does not do: it does not know what a provision says. That is only
explained from the judgment's own words (see analysis service).
"""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

CONSTITUTION = "Constitution of India"

# Well-known abbreviations used in Indian judgments.
ACT_ABBREVIATIONS = {
    "IPC": "Indian Penal Code, 1860",
    "I.P.C": "Indian Penal Code, 1860",
    "CrPC": "Code of Criminal Procedure, 1973",
    "Cr.P.C": "Code of Criminal Procedure, 1973",
    "CPC": "Code of Civil Procedure, 1908",
    "C.P.C": "Code of Civil Procedure, 1908",
    "BNSS": "Bharatiya Nagarik Suraksha Sanhita, 2023",
    "BNS": "Bharatiya Nyaya Sanhita, 2023",
    "BSA": "Bharatiya Sakshya Adhiniyam, 2023",
    "NDPS": "Narcotic Drugs and Psychotropic Substances Act, 1985",
    "PMLA": "Prevention of Money Laundering Act, 2002",
    "UAPA": "Unlawful Activities (Prevention) Act, 1967",
    "POCSO": "Protection of Children from Sexual Offences Act, 2012",
    "IT Act": "Information Technology Act, 2000",
    "NI Act": "Negotiable Instruments Act, 1881",
    "RTI Act": "Right to Information Act, 2005",
}

_NUM = r"\d{1,4}(?:\s?-\s?[A-Z]|[A-Z]{1,2}(?![a-z]))?(?:\s?\(\s?(?!\d{4}\s?\))[0-9A-Za-z]{1,4}\s?\))*"
_LIST = rf"{_NUM}(?:\s*(?:,|and|&|or|to)\s*{_NUM})*"
_KIND = r"Articles?|Art\.|Sections?|Secs?\.|Ss?\.(?=\s?\d)|Rules?"
_MAIN = re.compile(rf"\b(?P<kind>{_KIND})\s*(?P<nums>{_LIST})", re.IGNORECASE)
_ORDER_RULE = re.compile(
    rf"\bOrder\s+(?P<order>[IVXL]{{1,6}}|\d{{1,3}})\s*,?\s*Rules?\s*(?P<nums>{_LIST})", re.IGNORECASE
)
_NUM_RE = re.compile(_NUM)

_ABBR_ALT = "|".join(re.escape(a) for a in sorted(ACT_ABBREVIATIONS, key=len, reverse=True))
_ABBR_NEXT = re.compile(rf"^\s*[,(]?\s*(?:of\s+(?:the\s+)?)?(?P<abbr>{_ABBR_ALT})\b\.?")
_CONSTITUTION = re.compile(r"\b(?:of|under|in)\s+(?:the\s+)?(?:Indian\s+)?Constitution(?:\s+of\s+India)?\b")
_TREATY = re.compile(
    r"\b(?:of|under)\s+the\s+(?P<name>(?:[A-Z][\w'’\-]*\s+){0,5}(?:Convention|Covenant|Declaration|Treaty|Charter)"
    r"(?:\s+(?:on|of)\s+(?:(?:[A-Z][\w]*|of|the|and)\s*){1,8})?)"
)
_ACT = re.compile(
    r"\b(?:of|under|in)\s+the\s+(?P<name>(?:(?:[A-Z(][^\s]*|of|and|for|the|to|in|on|other)\s+){1,14}?(?:Act|Code|Ordinance)(?:,?\s*\d{4})?)"
)
_ROMAN = re.compile(r"^[IVXL]+$")
# A bare "Article 8" next to one of these names is more likely that treaty than
# the Constitution. The label stays "assumed" because it rests on nearby words only.
NEARBY_TREATIES = [
    (re.compile(r"European Convention|\bECHR\b|Convention (?:for the Protection of )?(?:on )?Human Rights|Human Rights Act", re.I),
     "European Convention on Human Rights"),
    (re.compile(r"Universal Declaration|\bUDHR\b", re.I), "Universal Declaration of Human Rights"),
    (re.compile(r"\bICCPR\b|Covenant on Civil and Political Rights", re.I),
     "International Covenant on Civil and Political Rights"),
]
NEARBY_RADIUS = 160


@dataclass
class _Acc:
    kind: str
    number: str
    act: Optional[str]
    stated: int = 0
    assumed: int = 0
    pages: Counter = field(default_factory=Counter)
    variants: Counter = field(default_factory=Counter)
    first: Optional[tuple] = None


def _kind_name(raw: str) -> str:
    low = raw.lower().rstrip(".")
    if low.startswith("art"):
        return "article"
    if low.startswith("rule"):
        return "rule"
    return "section"


def _main_number(token: str) -> str:
    base = re.sub(r"\(.*", "", token).strip()
    return re.sub(r"\s*-\s*", "", base).replace(" ", "")


_NEXT_PROVISION = re.compile(
    r"\b(?:[Aa]rticles?|[Aa]rt\.|[Ss]ections?|[Ss]ecs?\.|Ss?\.(?=\s?\d)|[Rr]ules?|Order)\s*(?:\d|[IVXL]+\b)"
)


def _resolve_act(kind: str, ahead: str, before: str = "") -> tuple[Optional[str], Optional[str]]:
    """Returns (act, source) where source is "stated" or "assumed" or None.

    Only the text up to the next provision reference is examined, so an Act
    named for the next provision is never attached to this one.
    """
    cut = _NEXT_PROVISION.search(ahead)
    if cut:
        ahead = ahead[: cut.start()]
    m = _ABBR_NEXT.match(ahead)
    if m:
        return ACT_ABBREVIATIONS[m.group("abbr")], "stated"
    candidates = []
    c = _CONSTITUTION.search(ahead[:60])
    if c:
        candidates.append((c.start(), CONSTITUTION))
    t = _TREATY.search(ahead[:110])
    if t:
        candidates.append((t.start(), re.sub(r"\s+", " ", t.group("name")).strip()))
    a = _ACT.search(ahead[:130])
    if a:
        candidates.append((a.start(), re.sub(r"\s+", " ", a.group("name")).strip(" ,")))
    if candidates:
        return min(candidates)[1], "stated"
    if kind == "article":
        window = before[-NEARBY_RADIUS:] + " " + ahead[:NEARBY_RADIUS]
        for pattern, name in NEARBY_TREATIES:
            if pattern.search(window) and not _CONSTITUTION.search(window):
                return name, "assumed"
        # Most bare "Article N" in an Indian judgment means the Constitution, but
        # foreign texts (e.g. the European Convention) are also cited, so say
        # clearly that this is an assumption.
        return CONSTITUTION, "assumed"
    return None, None


def _snippet(text: str, start: int, end: int, radius: int = 110) -> str:
    return text[max(0, start - radius) : end + radius].strip()


def extract_provisions(cleaned_pages: dict[int, str]) -> list[dict]:
    """Return provisions sorted by number of mentions (most first).

    `cleaned_pages` is page number -> single-spaced page text.
    """
    found: dict[tuple, _Acc] = {}

    def add(kind, number, resolved, page, variant, text, start, end):
        act, source = resolved
        key = (kind, number, act)
        acc = found.get(key)
        if acc is None:
            acc = found[key] = _Acc(kind, number, act)
        acc.pages[page] += 1
        if source == "stated":
            acc.stated += 1
        elif source == "assumed":
            acc.assumed += 1
        if variant != number:
            acc.variants[variant] += 1
        if acc.first is None or page < acc.first[0]:
            acc.first = (page, _snippet(text, start, end))

    for page in sorted(cleaned_pages):
        text = cleaned_pages[page]
        consumed: list[tuple[int, int]] = []

        for m in _ORDER_RULE.finditer(text):
            consumed.append((m.start(), m.end()))
            act = _resolve_act("rule", text[m.end() :])
            order = m.group("order").upper()
            for token in _NUM_RE.findall(m.group("nums")):
                number = f"{order}/{_main_number(token)}"
                add("order_rule", number, act, page, number, text, m.start(), m.end())

        for m in _MAIN.finditer(text):
            if any(s <= m.start() < e for s, e in consumed):
                continue
            kind = _kind_name(m.group("kind"))
            act = _resolve_act(kind, text[m.end() :], text[max(0, m.start() - NEARBY_RADIUS) : m.start()])
            for token in _NUM_RE.findall(m.group("nums")):
                number = _main_number(token)
                if not number:
                    continue
                add(kind, number, act, page, re.sub(r"\s+", "", token), text, m.start(), m.end())

    out = []
    for acc in found.values():
        if acc.kind == "order_rule":
            order, rule = acc.number.split("/")
            label = f"Order {order} Rule {rule}"
        else:
            label = f"{acc.kind.capitalize()} {acc.number}"
        out.append(
            {
                "key": f"{label} ({acc.act})" if acc.act else label,
                "label": label,
                "kind": acc.kind,
                "number": acc.number,
                "act": acc.act,
                "act_basis": "stated" if acc.stated else ("assumed" if acc.assumed else None),
                "mentions": sum(acc.pages.values()),
                "pages": sorted(acc.pages),
                "variants": [v for v, _ in acc.variants.most_common(5)],
                "first_mention": {"page": acc.first[0], "text": acc.first[1]},
            }
        )
    out.sort(key=lambda d: (-d["mentions"], d["kind"], d["number"]))
    return out


def snippets_for(cleaned_pages: dict[int, str], provision: dict, limit: int = 3, radius: int = 260) -> list[tuple[int, str]]:
    """Up to `limit` text windows for a provision, spread across its pages."""
    pages = provision["pages"]
    if not pages:
        return []
    picks = sorted({pages[0], pages[len(pages) // 2], pages[-1]})[:limit]
    label = provision["label"]
    number = provision["number"].split("/")[-1]
    pattern = re.compile(rf"\b{re.escape(label.split()[0])}s?\.?\s*(?:[^.]{{0,40}}?\b){re.escape(number)}", re.IGNORECASE)
    out = []
    for page in picks:
        text = cleaned_pages.get(page, "")
        m = pattern.search(text)
        if m:
            out.append((page, _snippet(text, m.start(), m.end(), radius)))
    return out

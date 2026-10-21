"""Stress-test the quote checker on real judgment text. No model, no quota, no human labels.

The checker (app/services/grounding.py) decides whether a quote really appears
on a page. Here we hand it quotes whose truth we know, because we cut them out
of the judgment ourselves or altered them in a controlled way:

  exact              a real span, copied exactly                -> should be verified
  surface_changes    same span, different case / spacing / punctuation -> should be verified
  stray_margin_letter the span with a stray A-H letter inside, as extraction can leave -> should be verified
  wrong_page_claim   a real span cited with the wrong page      -> verified, page corrected to a page that has it
  word_swapped       one word replaced by another word from the judgment -> should NOT be verified
  digit_changed      one digit changed inside a number          -> should NOT be verified
  punctuation_collapsed  "3(1)" -> "31", "1.5" -> "15"         -> reported, not asserted: matching ignores punctuation
  other_document     a span from a different judgment          -> should NOT be verified

This tests the checker only. It says nothing about how often the language
model writes unsupported claims: that is measured from real model output
(collect, ask-run) and by a human audit (audit-sample / audit-score).
"""
import random
import re
from typing import Optional

from app.services.grounding import PageTexts, VERIFIED, check_claim, normalize
from evaluation.corpus import Corpus
from evaluation.stats import proportion

MIN_WORDS, MAX_WORDS = 10, 20
_DECIMAL = re.compile(r"\d[.,]\d")
_BRACKET = re.compile(r"\d\(\d+\)")
_WORD = re.compile(r"[A-Za-z]{4,}")


def _spans(corpus: Corpus, rng: random.Random, n: int) -> list[tuple[int, str]]:
    """Random word spans (page, text) taken from pages with enough text."""
    pages = [p for p, t in corpus.cleaned.items() if len(t.split()) >= MAX_WORDS + 5]
    out: list[tuple[int, str]] = []
    tries = 0
    while pages and len(out) < n and tries < n * 20:
        tries += 1
        page = rng.choice(pages)
        words = corpus.cleaned[page].split()
        length = rng.randint(MIN_WORDS, MAX_WORDS)
        start = rng.randrange(0, len(words) - length)
        text = " ".join(words[start : start + length])
        if len(normalize(text)) >= 30:
            out.append((page, text))
    return out


def _occurs(norm_pages: dict[int, str], needle: str) -> bool:
    """True if the text really is in the judgment: on one page, or across a page break.

    The quote checker also accepts text that runs over a page break, so an altered
    quote that happens to equal such text must not be counted as a wrong acceptance.
    """
    if any(needle in t for t in norm_pages.values()):
        return True
    for page, text in norm_pages.items():
        nxt = norm_pages.get(page + 1)
        if nxt is not None and needle in text[-len(needle):] + nxt[: len(needle)]:
            return True
    return False


def _swap_word(text: str, vocab: list[str], rng: random.Random) -> Optional[str]:
    matches = list(_WORD.finditer(text))
    if not matches or not vocab:
        return None
    m = rng.choice(matches)
    for _ in range(10):
        new = rng.choice(vocab)
        if new.lower() != m.group().lower():
            return text[: m.start()] + new + text[m.end():]
    return None


def _change_digit(text: str, rng: random.Random) -> Optional[str]:
    positions = [i for i, ch in enumerate(text) if ch.isdigit()]
    if not positions:
        return None
    i = rng.choice(positions)
    new = rng.choice([d for d in "0123456789" if d != text[i]])
    return text[:i] + new + text[i + 1:]


def _collapse_punctuation(text: str) -> Optional[str]:
    if _DECIMAL.search(text):
        return re.sub(r"(\d)[.,](\d)", r"\1\2", text)
    if _BRACKET.search(text):
        return re.sub(r"(\d)\((\d+)\)", r"\1\2", text)
    return None


def _surface_change(text: str, rng: random.Random) -> str:
    choice = rng.choice(["upper", "lower", "spaces", "strip_punct"])
    if choice == "upper":
        return text.upper()
    if choice == "lower":
        return text.lower()
    if choice == "spaces":
        return re.sub(r"\s+", "   ", text)
    return re.sub(r"[^\w\s]", "", text)


def _insert_margin_letter(text: str, rng: random.Random) -> str:
    words = text.split()
    words.insert(rng.randrange(2, len(words) - 1), rng.choice("ABCDEFGH"))
    return " ".join(words)


def evaluate_verifier(
    corpus: Corpus, *, samples: int = 200, seed: int = 0, other: Optional[Corpus] = None
) -> dict:
    rng = random.Random(f"{corpus.doc_id}:{seed}")
    texts = PageTexts(corpus.cleaned)
    allowed = set(corpus.cleaned)
    norm_pages = {p: normalize(t) for p, t in corpus.cleaned.items()}
    vocab = sorted({w for t in corpus.cleaned.values() for w in _WORD.findall(t)})
    spans = _spans(corpus, rng, samples)

    def verified(quote: str, claimed: list[int]):
        return check_claim(claimed, quote, texts, allowed)

    results: dict[str, dict] = {}

    def record(name: str, expectation: str, flags: list[bool], examples: list[str]) -> None:
        results[name] = {"expectation": expectation, **proportion(sum(flags), len(flags)), "examples_of_unexpected": examples[:5]}

    # 1 exact
    flags, ex = [], []
    for page, span in spans:
        c = verified(span, [page])
        ok = c.status == VERIFIED
        flags.append(ok)
        if not ok:
            ex.append(f"page {page}: {span[:160]}")
    record("exact", "verified (rate shown = verified)", flags, ex)

    # 2 surface changes
    flags, ex = [], []
    for page, span in spans:
        changed = _surface_change(span, rng)
        ok = verified(changed, [page]).status == VERIFIED
        flags.append(ok)
        if not ok:
            ex.append(f"page {page}: {changed[:160]}")
    record("surface_changes", "verified (rate shown = verified)", flags, ex)

    # 3 stray margin letter
    flags, ex = [], []
    for page, span in spans:
        changed = _insert_margin_letter(span, rng)
        ok = verified(changed, [page]).status == VERIFIED
        flags.append(ok)
        if not ok:
            ex.append(f"page {page}: {changed[:160]}")
    record("stray_margin_letter", "verified (rate shown = verified)", flags, ex)

    # 4 wrong claimed page: the checker should report a page where the words really are.
    # If the same words also occur on other pages, reporting one of those is not a failure of
    # the checker, so the rate is also given for spans that occur on exactly one page.
    flags, ex, unique_flags = [], [], []
    page_list = sorted(allowed)
    for page, span in spans:
        wrong = rng.choice([p for p in page_list if p != page] or [page])
        c = verified(span, [wrong])
        ok = c.status == VERIFIED and page in c.pages
        flags.append(ok)
        needle = normalize(span)
        if sum(needle in t for t in norm_pages.values()) == 1:
            unique_flags.append(ok)
        if not ok:
            ex.append(f"true page {page}, reported {c.pages}: {span[:120]}")
    record("wrong_page_claim", "verified on the true page (rate shown = true page reported)", flags, ex)
    results["wrong_page_claim"]["only_spans_found_on_one_page"] = proportion(sum(unique_flags), len(unique_flags))
    results["wrong_page_claim"]["spans_found_on_several_pages"] = len(flags) - len(unique_flags)

    # 5 word swapped (only cases whose altered text occurs nowhere in the judgment)
    flags, ex = [], []
    for page, span in spans:
        changed = _swap_word(span, vocab, rng)
        if not changed or _occurs(norm_pages, normalize(changed)):
            continue
        ok = verified(changed, [page]).status == VERIFIED
        flags.append(ok)
        if ok:
            ex.append(f"page {page}: {changed[:160]}")
    record("word_swapped", "NOT verified (rate shown = wrongly verified, should be 0)", flags, ex)

    # 6 digit changed
    flags, ex = [], []
    for page, span in spans:
        changed = _change_digit(span, rng)
        if not changed or _occurs(norm_pages, normalize(changed)):
            continue
        ok = verified(changed, [page]).status == VERIFIED
        flags.append(ok)
        if ok:
            ex.append(f"page {page}: {changed[:160]}")
    record("digit_changed", "NOT verified (rate shown = wrongly verified, should be 0)", flags, ex)

    # 7 punctuation collapsed (informational): spans with decimals or "3(1)" style numbers.
    # Look for such spans directly, since random spans rarely contain them.
    flags, ex = [], []
    candidates = []
    for page, text in corpus.cleaned.items():
        for m in list(_DECIMAL.finditer(text)) + list(_BRACKET.finditer(text)):
            words = text.split()
            idx = len(text[: m.start()].split())
            lo = max(0, idx - 6)
            candidates.append((page, " ".join(words[lo : lo + 14])))
    rng.shuffle(candidates)
    for page, span in candidates[:samples]:
        changed = _collapse_punctuation(span)
        if not changed or changed == span:
            continue
        accepted = verified(changed, [page]).status == VERIFIED
        flags.append(accepted)
        if accepted:
            ex.append(f"page {page}: {changed[:160]}")
    record(
        "punctuation_collapsed",
        "informational, by design: matching ignores punctuation, so '3(1)' and '31' match; rate shown = accepted",
        flags, ex,
    )
    results["punctuation_collapsed"]["spans_with_such_numbers_in_document"] = len(candidates)

    # 8 span from another judgment
    if other is not None and other.doc_id != corpus.doc_id:
        flags, ex = [], []
        for _, span in _spans(other, rng, samples):
            if _occurs(norm_pages, normalize(span)):
                continue
            ok = verified(span, [min(allowed)]).status == VERIFIED
            flags.append(ok)
            if ok:
                ex.append(span[:160])
        record("other_document", "NOT verified (rate shown = wrongly verified, should be 0)", flags, ex)

    return {
        "document": corpus.name,
        "spans_sampled": len(spans),
        "seed": seed,
        "controls": results,
        "note": "Tests the quote checker on text cut from the judgment. It is not a measure of how often the language model makes unsupported claims.",
    }

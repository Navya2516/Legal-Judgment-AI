"""Check that what the model claims is really in the judgment.

The model is asked to cite page numbers and to give a short word-for-word
quote for each claim. We never trust either:

* a cited page that was not part of the text the model was given is removed;
* a quote is searched for in the judgment text itself (ignoring case,
  punctuation and spacing). If it is found, the page(s) where it was found
  replace whatever the model said, so a citation is only ever a page where the
  words really appear;
* a claim with no valid page at all is "unsupported" and is not shown.

Stray margin letters (A to H) from law reports are ignored when matching, so an
extraction quirk does not turn a correct quote into a weaker "cited" claim.

Statuses: verified (quote found), cited (valid page, quote missing or not
found - weaker evidence), unsupported (nothing checkable).
"""
import re
from dataclasses import dataclass
from typing import Optional

MIN_QUOTE_ALNUM = 15  # shorter quotes are too easy to match by accident

VERIFIED = "verified"
CITED = "cited"
UNSUPPORTED = "unsupported"


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


@dataclass
class Checked:
    pages: list[int]
    status: str
    quote: Optional[str]


# Law reports print a column of margin letters (A to H) beside the text. Text
# extraction can leave them in the middle of a sentence ("... the right to C
# privacy ..."). They are not part of the judgment's words, so a quote that
# fails to match exactly gets a second try with them removed from both sides.
_MARGIN_TOKEN = re.compile(r"(?<!\S)[A-H](?!\S)")


def strip_margin_letters(text: str) -> str:
    return _MARGIN_TOKEN.sub(" ", text)


def _search(norm: dict[int, str], needle: str, allowed: set[int]) -> Optional[list[int]]:
    ordered = sorted(p for p in allowed if p in norm)
    for page in ordered:
        if needle in norm[page]:
            return [page]
    for page in ordered:  # a quote may run across a page break
        nxt = page + 1
        if nxt in allowed and nxt in norm:
            tail = norm[page][-len(needle):]
            joined = tail + norm[nxt][: len(needle)]
            at = joined.find(needle)
            if at != -1 and at < len(tail) < at + len(needle):
                return [page, nxt]
    return None


class PageTexts:
    """Normalised page text, built once per request."""

    def __init__(self, cleaned_pages: dict[int, str]) -> None:
        self._norm = {n: normalize(t) for n, t in cleaned_pages.items()}
        self._loose = {n: normalize(strip_margin_letters(t)) for n, t in cleaned_pages.items()}

    def find_quote(self, quote: str, allowed: set[int]) -> Optional[list[int]]:
        needle = normalize(quote)
        if len(needle) < MIN_QUOTE_ALNUM:
            return None
        found = _search(self._norm, needle, allowed)
        if found:
            return found
        loose = normalize(strip_margin_letters(quote))
        if len(loose) >= MIN_QUOTE_ALNUM:
            return _search(self._loose, loose, allowed)
        return None


def check_claim(
    pages: list[int], quote: Optional[str], texts: PageTexts, allowed: set[int]
) -> Checked:
    valid = sorted({p for p in pages if p in allowed})
    clean_quote = quote.strip() if quote and quote.strip() else None
    if clean_quote:
        found = texts.find_quote(clean_quote, allowed)
        if found:
            return Checked(found, VERIFIED, clean_quote)
    if valid:
        return Checked(valid, CITED, clean_quote if clean_quote else None)
    return Checked([], UNSUPPORTED, clean_quote)

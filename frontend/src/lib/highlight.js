// Find a quoted passage inside a page of text so the page viewer can mark it.
// Page text and quotes can differ in spacing, line breaks and stray margin
// letters (A–H) from law reports, so matching is done on letters and digits only
// and mapped back to positions in the original text.

const MARGIN = /(?<!\S)[A-H](?!\S)/g;

function squash(text) {
  let flat = "";
  const map = [];
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i].toLowerCase();
    if (/[a-z0-9]/.test(ch)) {
      flat += ch;
      map.push(i);
    }
  }
  return { flat, map };
}

export function findQuote(pageText, quote) {
  if (!pageText || !quote) return null;
  const direct = locate(pageText, squash(quote).flat);
  if (direct) return direct;
  // Second try: ignore stray margin letters on both sides.
  const blank = (m) => " ".repeat(m.length);
  return locate(pageText.replace(MARGIN, blank), squash(quote.replace(MARGIN, blank)).flat);
}

function locate(pageText, needle) {
  if (needle.length < 15) return null;
  const { flat, map } = squash(pageText);
  const at = flat.indexOf(needle);
  if (at === -1) return null;
  return { start: map[at], end: map[at + needle.length - 1] + 1 };
}

// Split text into [{text, marked}] for rendering.
export function splitByMatch(text, match) {
  if (!match) return [{ text, marked: false }];
  return [
    { text: text.slice(0, match.start), marked: false },
    { text: text.slice(match.start, match.end), marked: true },
    { text: text.slice(match.end), marked: false },
  ].filter((part) => part.text.length > 0);
}

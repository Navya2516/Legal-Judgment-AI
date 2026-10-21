import { describe, expect, it } from "vitest";
import { formatPages, formatBytes, shortName } from "../src/lib/format";
import { findQuote, splitByMatch } from "../src/lib/highlight";
import { parseHash, hrefFor } from "../src/hooks/useRoute";
import { explainError } from "../src/lib/errors";

describe("formatPages", () => {
  it("joins runs", () => expect(formatPages([5, 3, 4, 9])).toBe("3–5, 9"));
  it("handles one and none", () => {
    expect(formatPages([142])).toBe("142");
    expect(formatPages([])).toBe("");
  });
});

describe("format helpers", () => {
  it("formats sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });
  it("shortens long names", () => expect(shortName("a".repeat(100), 10)).toHaveLength(10));
});

describe("findQuote", () => {
  const page = "The right to privacy is an intrinsic part of the right to life\nand personal liberty under Article 21.";
  it("finds a quote across a line break and different case", () => {
    const m = findQuote(page, "right to privacy is an intrinsic part of the RIGHT TO LIFE and personal liberty");
    expect(m).not.toBeNull();
    expect(page.slice(m.start, m.end)).toMatch(/^right to privacy/);
    expect(page.slice(m.start, m.end)).toMatch(/personal liberty$/);
  });
  it("ignores stray margin letters in the page", () => {
    const withLetters = "the right to C privacy is an intrinsic part of the right to life";
    expect(findQuote(withLetters, "the right to privacy is an intrinsic part of the right to life")).not.toBeNull();
  });
  it("returns null when absent or too short", () => {
    expect(findQuote(page, "completely different words that are not here")).toBeNull();
    expect(findQuote(page, "Article")).toBeNull();
    expect(findQuote("", "anything long enough to count here")).toBeNull();
  });
  it("splits text around a match", () => {
    expect(splitByMatch("abcdef", { start: 2, end: 4 })).toEqual([
      { text: "ab", marked: false }, { text: "cd", marked: true }, { text: "ef", marked: false },
    ]);
    expect(splitByMatch("abc", null)).toEqual([{ text: "abc", marked: false }]);
  });
});

describe("routes", () => {
  it("parses document routes and tabs", () => {
    expect(parseHash("#/doc/abcdef1234567890/ask")).toEqual({ name: "doc", id: "abcdef1234567890", tab: "ask" });
    expect(parseHash("#/doc/abcdef1234567890")).toMatchObject({ tab: "summary" });
    expect(parseHash("#/doc/abcdef1234567890/nonsense")).toMatchObject({ tab: "summary" });
  });
  it("falls back to home for anything odd", () => {
    expect(parseHash("")).toEqual({ name: "home" });
    expect(parseHash("#/doc/../../etc")).toEqual({ name: "home" });
    expect(parseHash("#/doc/x")).toEqual({ name: "home" });
  });
  it("builds hrefs", () => expect(hrefFor({ name: "doc", id: "abcdef1234567890", tab: "next" })).toBe("#/doc/abcdef1234567890/next"));
});

describe("explainError", () => {
  it("gives actionable text for known codes", () => {
    expect(explainError({ code: "network" }).body).toMatch(/backend/);
    expect(explainError({ code: "llm_not_configured" }).body).toMatch(/GEMINI_API_KEY/);
    expect(explainError({ code: "llm_rate_limited" }).retry).toBe(true);
    const daily = explainError({ code: "llm_rate_limited", message: "The free daily limit for the model 'm' is used up. Google says it resets in about 6 h 34 min." });
    expect(daily.body).toMatch(/resets in about 6 h 34 min/);
    expect(daily.retry).toBe(false);
  });
  it("falls back to the server's message", () => {
    expect(explainError({ code: "weird", message: "Boom" }).body).toBe("Boom");
  });
});

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import EvidenceRow from "../src/components/EvidenceRow";
import ErrorBox from "../src/components/ErrorBox";
import SummaryPanel from "../src/components/SummaryPanel";
import AskPanel from "../src/components/AskPanel";
import Gate from "../src/components/Gate";
import ProcessingSteps from "../src/components/ProcessingSteps";

const point = (over = {}) => ({
  text: "The court held that privacy is a fundamental right.", sourceText: "The court held that privacy is a fundamental right.",
  pages: [142], status: "verified", quote: "the right to privacy is protected as an intrinsic part of the right to life", check: "ok", ...over,
});

beforeEach(() => {
  window.matchMedia = (q) => ({ matches: true, media: q, addEventListener() {}, removeEventListener() {} });
});
afterEach(() => vi.restoreAllMocks());

describe("EvidenceRow", () => {
  it("shows the text, status, page and quote, and opens the page", async () => {
    const onOpenPage = vi.fn();
    render(<EvidenceRow {...point()} onOpenPage={onOpenPage} lang="en" />);
    expect(screen.getByText(/privacy is a fundamental right/)).toBeInTheDocument();
    expect(screen.getByText(/Quote checked/)).toBeInTheDocument();
    expect(screen.getByText(/intrinsic part of the right to life/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Open page 142/ }));
    expect(onOpenPage).toHaveBeenCalledWith(142, point().quote);
  });
  it("marks page-only evidence honestly", () => {
    render(<EvidenceRow {...point({ status: "cited", quote: null })} lang="en" />);
    expect(screen.getByText(/Page only/)).toBeInTheDocument();
    expect(screen.getByText(/No exact words were quoted/)).toBeInTheDocument();
  });
  it("flags a translation whose numbers changed and offers the English", async () => {
    render(<EvidenceRow {...point({ text: "தமிழ் 20", check: "numbers_changed", sourceText: "English 21" })} translated lang="ta" />);
    expect(screen.getByRole("note")).toHaveTextContent(/number/i);
    await userEvent.click(screen.getByText(/Show the English sentence/));
    expect(screen.getByText("English 21")).toBeVisible();
  });
  it("folds the evidence on narrow screens", async () => {
    window.matchMedia = (q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} });
    render(<EvidenceRow {...point()} lang="en" />);
    expect(screen.queryByText(/Quote checked/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Show evidence/ }));
    expect(screen.getByText(/Quote checked/)).toBeInTheDocument();
  });
});

describe("ErrorBox", () => {
  it("explains and offers retry", async () => {
    const retry = vi.fn();
    render(<ErrorBox error={{ code: "llm_rate_limited", message: "x", status: 429 }} onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/usage limit/);
    await userEvent.click(screen.getByRole("button", { name: /Try again/ }));
    expect(retry).toHaveBeenCalled();
  });
  it("renders nothing without an error", () => {
    const { container } = render(<ErrorBox error={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("Gate", () => {
  const base = { status: "ready", busy: null, error: null, actionError: null, generate: vi.fn(), translate: vi.fn(), reload: vi.fn() };
  const props = { lang: "en", languageName: "English", noun: "summary", generateLabel: "Write the summary", translateLabel: "Translate", intro: "Intro text" };
  it("invites generation when nothing exists", async () => {
    const generate = vi.fn();
    render(<Gate {...props} analysis={{ ...base, status: "missing", generate }}>content</Gate>);
    await userEvent.click(screen.getByRole("button", { name: "Write the summary" }));
    expect(generate).toHaveBeenCalled();
    expect(screen.queryByText("content")).toBeNull();
  });
  it("offers translation when only English exists", () => {
    render(<Gate {...props} lang="ta" languageName="Tamil" analysis={{ ...base, status: "needs_translation" }}>content</Gate>);
    expect(screen.getByText(/not in Tamil yet/)).toBeInTheDocument();
  });
  it("shows progress while the model works", () => {
    render(<Gate {...props} analysis={{ ...base, busy: "generating" }}>content</Gate>);
    expect(screen.getByRole("status")).toHaveTextContent(/writing the summary/);
  });
  it("shows an error with retry", () => {
    render(<Gate {...props} analysis={{ ...base, status: "error", error: { code: "network" } }}>content</Gate>);
    expect(screen.getByRole("alert")).toHaveTextContent(/Can't reach the server/);
  });
  it("renders content when ready", () => {
    render(<Gate {...props} analysis={base}>content</Gate>);
    expect(screen.getByText("content")).toBeInTheDocument();
  });
});

describe("SummaryPanel", () => {
  const data = {
    language: "en", labels: { plain_summary: "Plain summary", facts: "Facts", holding: "Holding (what the court decided)" },
    case_title: "Test v. Test", court: "Supreme Court", date: "2017", case_number: null, coverage_note: "Built from 40 pages.",
    plain_summary: [point()], facts: [], issues: [], holding: [point({ text: "Held privacy is protected." })], reasoning: [], final_order: [],
    grounding: { points_total: 3, verified: 2, cited: 0, dropped_unsupported: 1 }, disclaimer: "Not legal advice.",
  };
  it("renders only sections with points, with the grounding line and notes", () => {
    render(<SummaryPanel data={data} onOpenPage={() => {}} />);
    expect(screen.getByRole("heading", { name: "Test v. Test" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Plain summary" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Facts" })).toBeNull();
    expect(screen.getByText(/Built from 40 pages/)).toBeInTheDocument();
    expect(screen.getByText(/1 removed because nothing/)).toBeInTheDocument();
    expect(screen.getByText("Not legal advice.")).toBeInTheDocument();
  });
});

describe("ProcessingSteps", () => {
  it("shows page progress", () => {
    render(<ProcessingSteps doc={{ status: "processing", index_status: "none", page_count: 10, pages_processed: 4, ocr_pages: 0 }} />);
    expect(screen.getByText(/4 of 10 pages/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
  });
  it("shows the failed index step", () => {
    render(<ProcessingSteps doc={{ status: "ready", index_status: "failed", page_count: 10, pages_processed: 10, ocr_pages: 0 }} />);
    expect(screen.getByText(/could not finish/)).toBeInTheDocument();
  });
});

describe("AskPanel", () => {
  function mockAsk(response) {
    globalThis.fetch = vi.fn(() => Promise.resolve(new Response(JSON.stringify(response), { status: 200, headers: { "Content-Type": "application/json" } })));
  }
  const answer = {
    document_id: "d", question: "Why?", language: "en", language_name: "English", answered: true, message: null,
    answer: [{ text: "Because the court said so.", source_text: "Because the court said so.", pages: [3], status: "verified", quote: "the court said so on this very point", check: "ok" }],
    passages: [{ pages: [3], score: 0.81, excerpt: "An excerpt from the judgment." }],
    grounding: { points_total: 1, verified: 1, cited: 0, dropped_unsupported: 0 }, disclaimer: "Not legal advice.", translation_notice: null,
  };
  it("asks, shows a cited answer and the passages searched", async () => {
    mockAsk(answer);
    render(<AskPanel docId="abcdef1234567890" lang="en" languageName="English" ready onOpenPage={() => {}} />);
    await userEvent.type(screen.getByLabelText("Your question"), "Why did the court decide this?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Because the court said so.")).toBeInTheDocument();
    expect(screen.getByText(/Passages searched \(1\)/)).toBeInTheDocument();
    const body = JSON.parse(globalThis.fetch.mock.calls[0][1].body);
    expect(body).toMatchObject({ question: "Why did the court decide this?", lang: "en" });
    expect(screen.getByLabelText("Your question")).toHaveValue("");
  });
  it("says so when the judgment does not answer", async () => {
    mockAsk({ ...answer, answered: false, answer: [], message: "Not clearly answered." });
    render(<AskPanel docId="abcdef1234567890" lang="en" languageName="English" ready onOpenPage={() => {}} />);
    await userEvent.type(screen.getByLabelText("Your question"), "What is the weather?");
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByText(/does not clearly answer this/)).toBeInTheDocument();
    expect(screen.getByText("Not clearly answered.")).toBeInTheDocument();
    expect(screen.getByText(/model found nothing/)).toBeInTheDocument();
  });
  it("tells apart removed sentences from a model that found nothing", async () => {
    mockAsk({ ...answer, answered: false, answer: [], message: "Not clearly answered.",
      grounding: { points_total: 2, verified: 0, cited: 0, dropped_unsupported: 2 } });
    render(<AskPanel docId="abcdef1234567890" lang="en" languageName="English" ready onOpenPage={() => {}} />);
    await userEvent.type(screen.getByLabelText("Your question"), "What did the court decide?");
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByText(/2 written sentence\(s\) were removed/)).toBeInTheDocument();
  });
  it("shows an error and lets the user retry", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ error: { code: "llm_rate_limited", message: "busy" } }), { status: 429 })));
    render(<AskPanel docId="abcdef1234567890" lang="en" languageName="English" ready onOpenPage={() => {}} />);
    await userEvent.type(screen.getByLabelText("Your question"), "Why did the court decide this?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/usage limit/);
    await waitFor(() => expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument());
  });
  it("blocks asking until the index is ready", () => {
    render(<AskPanel docId="abcdef1234567890" lang="en" languageName="English" ready={false} onOpenPage={() => {}} />);
    expect(screen.getByText(/not available yet/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Your question")).toBeNull();
  });
  it("does not send a too-short question", async () => {
    globalThis.fetch = vi.fn();
    render(<AskPanel docId="abcdef1234567890" lang="en" languageName="English" ready onOpenPage={() => {}} />);
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });
});

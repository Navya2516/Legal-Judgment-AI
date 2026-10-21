import { formatPages } from "../lib/format";

const STATUS = {
  verified: { label: "Quote checked", icon: "✓", tone: "ok", help: "The quoted words were found on the cited page of the judgment." },
  cited: { label: "Page only", icon: "!", tone: "warn", help: "The page is real, but the exact quoted words could not be matched. Read the page to confirm." },
};

const CHECK_TEXT = {
  numbers_changed: "A number in this translation differs from the English. Compare with the English sentence.",
  wrong_language: "This sentence may not be fully in the chosen language.",
  untranslated: "This sentence could not be translated, so the English is shown.",
};

export function StatusBadge({ status }) {
  const info = STATUS[status] || STATUS.cited;
  return (
    <span className={`badge badge-${info.tone}`} title={info.help}>
      <span aria-hidden="true">{info.icon}</span> {info.label}
    </span>
  );
}

// The "margin note" of a point: where it comes from, and the judgment's own words.
export default function EvidenceNote({ pages, status, quote, onOpenPage }) {
  return (
    <div className="evidence">
      <div className="evidence-head">
        <StatusBadge status={status} />
        <span className="evidence-pages">
          {pages.length > 1 ? "Pages" : "Page"}{" "}
          {pages.map((page, index) => (
            <span key={page}>
              {index > 0 && ", "}
              <button type="button" className="pagelink" onClick={() => onOpenPage?.(page, quote)}
                aria-label={`Open page ${page} of the judgment`}>
                {page}
              </button>
            </span>
          ))}
        </span>
      </div>
      {quote ? (
        <blockquote className="evidence-quote" lang="en">
          {quote}
        </blockquote>
      ) : (
        <p className="evidence-none">No exact words were quoted for this point.</p>
      )}
      <span className="visually-hidden">Pages {formatPages(pages)}</span>
    </div>
  );
}

export function CheckNotice({ check }) {
  if (!check || check === "ok" || !CHECK_TEXT[check]) return null;
  return <p className="check-notice" role="note">{CHECK_TEXT[check]}</p>;
}

import { useState } from "react";
import EvidenceNote, { CheckNotice } from "./EvidenceNote";
import { useMediaQuery } from "../hooks/useMediaQuery";

/**
 * One point of an explanation with its evidence in the margin.
 * Wide screens: the text sits in the left column and the evidence in a ruled
 * margin column on the right, like marginal notes in a law report.
 * Narrow screens: the evidence folds under the text behind a button.
 */
export default function EvidenceRow({
  text, sourceText, pages, status, quote, check, translated = false, heading, onOpenPage, lang,
}) {
  const wide = useMediaQuery("(min-width: 62rem)");
  const [open, setOpen] = useState(false);
  const showEnglish = translated && sourceText && sourceText !== text;
  return (
    <article className="leaf-row">
      <div className="leaf-text">
        {heading && <h4 className="leaf-heading">{heading}</h4>}
        <p lang={lang} className="point-text">{text}</p>
        <CheckNotice check={check} />
        {showEnglish && (
          <details className="english-original">
            <summary>Show the English sentence</summary>
            <p lang="en">{sourceText}</p>
          </details>
        )}
        {!wide && (
          <>
            <button type="button" className="btn btn-link" aria-expanded={open} onClick={() => setOpen(!open)}>
              {open ? "Hide evidence" : `Show evidence (page ${pages.join(", ")})`}
            </button>
            {open && <EvidenceNote pages={pages} status={status} quote={quote} onOpenPage={onOpenPage} />}
          </>
        )}
      </div>
      {wide && (
        <aside className="leaf-margin" aria-label="Evidence from the judgment">
          <EvidenceNote pages={pages} status={status} quote={quote} onOpenPage={onOpenPage} />
        </aside>
      )}
    </article>
  );
}

export function LeafHead({ children, id }) {
  return (
    <div className="leaf-row leaf-row-head">
      <div className="leaf-text">
        <h3 className="leaf-title" id={id}>{children}</h3>
      </div>
      <div className="leaf-margin leaf-margin-empty" aria-hidden="true" />
    </div>
  );
}

export function LeafNote({ children, tone = "info" }) {
  return (
    <div className="leaf-row">
      <div className="leaf-text">
        <div className={`notice notice-${tone}`}>{children}</div>
      </div>
      <div className="leaf-margin leaf-margin-empty" aria-hidden="true" />
    </div>
  );
}

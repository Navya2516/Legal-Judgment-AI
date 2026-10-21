import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { findQuote, splitByMatch } from "../lib/highlight";
import ErrorBox from "./ErrorBox";
import Spinner from "./Spinner";

// Pages do not change once extracted, so fetched pages are kept for the session.
const cache = new Map();

export default function PageViewer({ docId, page, quote, total, onClose, onChange }) {
  const [state, setState] = useState({ loading: true, text: "", error: null });
  const [attempt, setAttempt] = useState(0);
  const closeRef = useRef(null);
  const lastFocus = useRef(null);

  useEffect(() => {
    lastFocus.current = document.activeElement;
    closeRef.current?.focus();
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      lastFocus.current?.focus?.();
    };
  }, [onClose]);

  useEffect(() => {
    const key = `${docId}:${page}`;
    if (cache.has(key)) {
      setState({ loading: false, text: cache.get(key), error: null });
      return undefined;
    }
    const controller = new AbortController();
    setState({ loading: true, text: "", error: null });
    api.getPage(docId, page, { signal: controller.signal })
      .then((body) => {
        cache.set(key, body.text);
        setState({ loading: false, text: body.text, error: null });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setState({ loading: false, text: "", error });
      });
    return () => controller.abort();
  }, [docId, page, attempt]);

  const match = findQuote(state.text, quote);
  const parts = splitByMatch(state.text, match);

  return (
    <div className="viewer-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <section className="viewer" role="dialog" aria-modal="true" aria-labelledby="viewer-title">
        <header className="viewer-head">
          <h2 id="viewer-title">Page {page}{total ? ` of ${total}` : ""}</h2>
          <div className="viewer-nav">
            <button type="button" className="btn btn-quiet" disabled={page <= 1} onClick={() => onChange(page - 1)}>Previous</button>
            <button type="button" className="btn btn-quiet" disabled={total ? page >= total : false} onClick={() => onChange(page + 1)}>Next</button>
            <button type="button" className="btn" ref={closeRef} onClick={onClose}>Close</button>
          </div>
        </header>
        <div className="viewer-body">
          {state.loading && <Spinner label="Loading the page…" />}
          <ErrorBox error={state.error} onRetry={() => setAttempt((n) => n + 1)} />
          {!state.loading && !state.error && (
            <>
              {quote && (
                <p className="viewer-note">
                  {match
                    ? "The highlighted words are the quote used as evidence."
                    : "The quoted words are not highlighted here. They may be split across lines or sit on a neighbouring page."}
                </p>
              )}
              {state.text.trim() ? (
                <pre className="viewer-text" lang="en">
                  {parts.map((part, i) => (part.marked ? <mark key={i}>{part.text}</mark> : <span key={i}>{part.text}</span>))}
                </pre>
              ) : (
                <p className="empty-line">No text could be read from this page (it may be blank or an image).</p>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  );
}

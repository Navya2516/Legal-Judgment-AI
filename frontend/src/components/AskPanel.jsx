import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import ErrorBox from "./ErrorBox";
import EvidenceRow from "./EvidenceRow";
import Spinner from "./Spinner";
import { formatPages } from "../lib/format";

const SUGGESTIONS = [
  "What did the court finally decide?",
  "What were the main questions the court had to answer?",
  "Which Articles or Sections did the court rely on?",
  "What were the facts of the case?",
];

function Passages({ passages, onOpenPage }) {
  if (!passages?.length) return null;
  return (
    <details className="passages">
      <summary>Passages searched ({passages.length})</summary>
      <ol>
        {passages.map((p, i) => (
          <li key={i}>
            <button type="button" className="pagelink" onClick={() => onOpenPage(p.pages[0], null)}>page {formatPages(p.pages)}</button>
            <span className="passage-score"> relevance {p.score.toFixed(2)}</span>
            <p lang="en">{p.excerpt}</p>
          </li>
        ))}
      </ol>
    </details>
  );
}

function Answer({ turn, onOpenPage, onRetry }) {
  if (turn.pending) {
    return <div className="turn-answer"><Spinner label="Searching the judgment and writing an answer…" /></div>;
  }
  if (turn.error) {
    return <div className="turn-answer"><ErrorBox error={turn.error} onRetry={onRetry} compact /></div>;
  }
  const r = turn.response;
  return (
    <div className="turn-answer">
      {r.answered ? (
        <div className="leaf">
          {r.answer.map((p, i) => (
            <EvidenceRow key={i} {...p} translated={r.language !== "en"} lang={r.language} onOpenPage={onOpenPage} />
          ))}
        </div>
      ) : (
        <div className="notice notice-info">
          <p className="notice-title">The judgment does not clearly answer this</p>
          <p>{r.message}</p>
          <p className="notice-meta">
            {r.grounding.dropped_unsupported > 0
              ? `${r.grounding.dropped_unsupported} written sentence(s) were removed because no page of the judgment supported them.`
              : "The model found nothing in the searched passages to answer with."}
          </p>
        </div>
      )}
      {r.translation_notice && <p className="grounding-line" lang={r.language}>{r.translation_notice}</p>}
      <Passages passages={r.passages} onOpenPage={onOpenPage} />
      <p className="grounding-line" lang={r.language}>{r.disclaimer}</p>
    </div>
  );
}

export default function AskPanel({ docId, lang, languageName, ready, onOpenPage }) {
  const [turns, setTurns] = useState([]);
  const [text, setText] = useState("");
  const endRef = useRef(null);
  const busy = turns.some((t) => t.pending);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [turns.length]);

  async function send(question) {
    const q = question.trim();
    if (q.length < 3 || busy) return;
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setTurns((old) => [...old, { id, question: q, lang, pending: true }]);
    setText("");
    try {
      const response = await api.ask(docId, { question: q, lang });
      setTurns((old) => old.map((t) => (t.id === id ? { ...t, pending: false, response } : t)));
    } catch (error) {
      setTurns((old) => old.map((t) => (t.id === id ? { ...t, pending: false, error } : t)));
    }
  }

  function retry(turn) {
    setTurns((old) => old.filter((t) => t.id !== turn.id));
    send(turn.question);
  }

  function onKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send(text);
    }
  }

  if (!ready) {
    return (
      <div className="empty-state">
        <h3 className="empty-title">Questions are not available yet</h3>
        <p className="empty-help">Answers are found by searching the judgment, and its search index is not ready. Open this page again in a moment, or rebuild the index from the backend.</p>
      </div>
    );
  }

  return (
    <div className="ask">
      <div className="ask-intro">
        <p>Ask about anything in this judgment. Answers use only passages found in it, quote its exact words, and say so when it does not answer.
          {lang !== "en" && <> Answers are written in {languageName}; the quoted evidence stays in English.</>}</p>
        <p className="note-inline">Questions and answers are not saved. They disappear when you leave this page.</p>
      </div>
      <div className="transcript" aria-live="polite">
        {turns.length === 0 && (
          <div className="suggestions">
            <p className="suggest-title">Try one of these</p>
            <ul>
              {SUGGESTIONS.map((s) => (
                <li key={s}><button type="button" className="btn btn-quiet" onClick={() => send(s)} disabled={busy}>{s}</button></li>
              ))}
            </ul>
          </div>
        )}
        {turns.map((turn) => (
          <div className="turn" key={turn.id}>
            <p className="turn-question"><span className="visually-hidden">You asked: </span>{turn.question}</p>
            <Answer turn={turn} onOpenPage={onOpenPage} onRetry={() => retry(turn)} />
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(text); }}>
        <label htmlFor="question">Your question</label>
        <textarea id="question" rows={2} maxLength={500} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKeyDown}
          placeholder="For example: Why did the court dismiss the appeal?" />
        <div className="composer-foot">
          <span className="note-inline">{text.length}/500 · Enter to send, Shift+Enter for a new line</span>
          <button type="submit" className="btn btn-primary" disabled={busy || text.trim().length < 3}>{busy ? "Working…" : "Ask"}</button>
        </div>
      </form>
    </div>
  );
}

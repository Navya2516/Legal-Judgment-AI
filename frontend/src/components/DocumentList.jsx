import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { navigate } from "../hooks/useRoute";
import { formatBytes, formatDate, shortName } from "../lib/format";
import ErrorBox from "./ErrorBox";
import Spinner from "./Spinner";

const STATUS_TEXT = { uploaded: "Waiting", processing: "Reading", ready: "Ready", failed: "Failed" };

export default function DocumentList({ refreshKey }) {
  const [state, setState] = useState({ loading: true, docs: [], error: null });
  const [confirm, setConfirm] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const load = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }));
    api.listDocuments()
      .then((body) => setState({ loading: false, docs: body.documents, error: null }))
      .catch((error) => setState({ loading: false, docs: [], error }));
  }, []);

  useEffect(load, [load, refreshKey]);

  async function remove(id) {
    setDeleteError(null);
    try {
      await api.deleteDocument(id);
      setConfirm(null);
      load();
    } catch (error) {
      setDeleteError(error);
    }
  }

  return (
    <section className="doclist" aria-labelledby="doclist-title">
      <h2 id="doclist-title">Your judgments</h2>
      {state.loading && <Spinner label="Loading…" />}
      <ErrorBox error={state.error} onRetry={load} />
      <ErrorBox error={deleteError} compact />
      {!state.loading && !state.error && state.docs.length === 0 && (
        <p className="empty-line">Nothing uploaded yet. Upload a judgment above to begin.</p>
      )}
      {state.docs.length > 0 && (
        <ul className="docs">
          {state.docs.map((d) => (
            <li key={d.id} className="doc">
              <div className="doc-main">
                <p className="doc-name" title={d.filename}>{shortName(d.filename)}</p>
                <p className="doc-meta">
                  {d.page_count ? `${d.page_count} pages` : "pages unknown"} · {formatBytes(d.size_bytes)} · {formatDate(d.created_at)}
                </p>
              </div>
              <span className={`chip chip-${d.status}`}>{STATUS_TEXT[d.status] || d.status}</span>
              <div className="doc-actions">
                {d.status !== "failed" && (
                  <button type="button" className="btn btn-quiet" onClick={() => navigate({ name: "doc", id: d.id, tab: "summary" })}>
                    Open<span className="visually-hidden"> {d.filename}</span>
                  </button>
                )}
                {confirm === d.id ? (
                  <>
                    <button type="button" className="btn btn-danger" onClick={() => remove(d.id)}>Delete for good</button>
                    <button type="button" className="btn btn-quiet" onClick={() => setConfirm(null)}>Keep</button>
                  </>
                ) : (
                  <button type="button" className="btn btn-quiet" onClick={() => setConfirm(d.id)}>
                    Delete<span className="visually-hidden"> {d.filename}</span>
                  </button>
                )}
              </div>
              {d.status === "failed" && <p className="doc-error">{d.error}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

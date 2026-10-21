import { useCallback, useState } from "react";
import { api } from "../api/client";
import { TABS, hrefFor, navigate } from "../hooks/useRoute";
import { isBusy, useDocument } from "../hooks/useDocument";
import { formatDate, shortName } from "../lib/format";
import AskPanel from "./AskPanel";
import ContinuationPanel from "./ContinuationPanel";
import ErrorBox from "./ErrorBox";
import PageViewer from "./PageViewer";
import ProcessingSteps from "./ProcessingSteps";
import ProvisionsPanel from "./ProvisionsPanel";
import Spinner from "./Spinner";
import SummaryPanel from "./SummaryPanel";
import Gate from "./Gate";
import { useAnalysis } from "../hooks/useAnalysis";

function SummaryTab({ docId, lang, languageName, onOpenPage }) {
  const analysis = useAnalysis("summary", docId, lang);
  return (
    <Gate analysis={analysis} lang={lang} languageName={languageName} noun="summary"
      generateLabel="Write the summary" translateLabel={`Translate into ${languageName}`}
      intro="The summary covers the facts, the questions the court decided, its reasoning and the final order. Every point is linked to a page and quotes the judgment's own words. This calls the language model and can take up to a minute.">
      {analysis.data && <SummaryPanel data={analysis.data} onOpenPage={onOpenPage} />}
    </Gate>
  );
}

function DeleteSection({ doc }) {
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState(null);
  async function remove() {
    try {
      await api.deleteDocument(doc.id);
      navigate({ name: "home" });
    } catch (e) {
      setError(e);
    }
  }
  return (
    <section className="data-section" aria-labelledby="data-title">
      <h2 id="data-title">Your copy of this judgment</h2>
      <p>The PDF, its extracted text, the search index and every saved summary are stored on the backend's machine. Deleting removes all of them.</p>
      <ErrorBox error={error} compact />
      {confirm ? (
        <div className="row-actions">
          <button type="button" className="btn btn-danger" onClick={remove}>Delete for good</button>
          <button type="button" className="btn btn-quiet" onClick={() => setConfirm(false)}>Keep it</button>
        </div>
      ) : (
        <button type="button" className="btn btn-quiet" onClick={() => setConfirm(true)}>Delete this judgment</button>
      )}
    </section>
  );
}

export default function Workspace({ docId, tab, lang, languages }) {
  const { doc, error, loading } = useDocument(docId);
  const [viewer, setViewer] = useState(null);
  const language = languages.find((l) => l.code === lang) || languages[0];
  const openPage = useCallback((page, quote) => setViewer({ page, quote }), []);

  if (loading) return <div className="page-pad"><Spinner label="Opening the judgment…" /></div>;
  if (!doc) {
    return (
      <div className="page-pad">
        <ErrorBox error={error} />
        <a className="btn" href="#/">Back to your judgments</a>
      </div>
    );
  }

  const header = (
    <header className="doc-head">
      <p className="crumb"><a href="#/">Your judgments</a></p>
      <h1 className="doc-title" title={doc.filename}>{shortName(doc.filename, 90)}</h1>
      <p className="doc-meta">{doc.page_count} pages · added {formatDate(doc.created_at)}</p>
    </header>
  );

  if (doc.status === "failed") {
    return (
      <div className="page-pad">
        {header}
        <div className="notice notice-error" role="alert"><p className="notice-title">This file could not be read</p><p>{doc.error}</p></div>
        <DeleteSection doc={doc} />
      </div>
    );
  }
  if (isBusy(doc)) {
    return <div className="page-pad">{header}<ProcessingSteps doc={doc} /></div>;
  }

  return (
    <div className="workspace">
      <div className="page-pad">{header}</div>
      <nav className="tabs" aria-label="Sections of this judgment">
        {TABS.map((t) => (
          <a key={t.id} href={hrefFor({ name: "doc", id: docId, tab: t.id })} aria-current={t.id === tab ? "page" : undefined} className="tab">
            {t.label}
          </a>
        ))}
      </nav>
      {doc.warnings?.length > 0 && (
        <div className="page-pad"><div className="notice notice-warn"><ul>{doc.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></div></div>
      )}
      {doc.index_status === "failed" && (
        <div className="page-pad"><div className="notice notice-warn">The search index failed to build ({doc.index_error}). Summaries of short judgments still work; questions do not.</div></div>
      )}
      <div className="sheet" id="panel" lang={lang === "en" ? "en" : undefined}>
        {tab === "summary" && <SummaryTab docId={docId} lang={lang} languageName={language.name} onOpenPage={openPage} />}
        {tab === "provisions" && <ProvisionsPanel docId={docId} lang={lang} languageName={language.name} onOpenPage={openPage} />}
        {tab === "next" && <ContinuationPanel docId={docId} lang={lang} languageName={language.name} onOpenPage={openPage} />}
        {tab === "ask" && <AskPanel docId={docId} lang={lang} languageName={language.name} ready={doc.index_status === "ready"} onOpenPage={openPage} />}
      </div>
      <div className="page-pad"><DeleteSection doc={doc} /></div>
      {viewer && (
        <PageViewer docId={docId} page={viewer.page} quote={viewer.quote} total={doc.page_count}
          onClose={() => setViewer(null)} onChange={(page) => setViewer({ page, quote: null })} />
      )}
    </div>
  );
}

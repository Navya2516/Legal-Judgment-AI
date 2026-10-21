function Step({ state, title, detail }) {
  const mark = state === "done" ? "✓" : state === "active" ? "…" : state === "failed" ? "✕" : "";
  return (
    <li className={`step step-${state}`} aria-current={state === "active" ? "step" : undefined}>
      <span className="step-mark" aria-hidden="true">{mark}</span>
      <span>
        <span className="step-title">{title}</span>
        {detail && <span className="step-detail"> {detail}</span>}
      </span>
    </li>
  );
}

export default function ProcessingSteps({ doc }) {
  const failed = doc.status === "failed";
  const reading = doc.status === "uploaded" || doc.status === "processing";
  const indexing = doc.status === "ready" && doc.index_status === "indexing";
  const total = doc.page_count || 0;
  const percent = total ? Math.round((doc.pages_processed / total) * 100) : 0;
  return (
    <div className="processing">
      <ol className="steps">
        <Step state="done" title="File received and checked" />
        <Step
          state={failed ? "failed" : reading ? "active" : "done"}
          title="Reading the pages"
          detail={reading && total ? `${doc.pages_processed} of ${total} pages` : doc.ocr_pages ? `${doc.ocr_pages} scanned pages read with OCR` : ""}
        />
        <Step
          state={failed ? "pending" : indexing ? "active" : reading ? "pending" : doc.index_status === "failed" ? "failed" : "done"}
          title="Preparing the judgment for search"
          detail={doc.index_status === "failed" ? "could not finish" : ""}
        />
      </ol>
      {reading && total > 0 && (
        <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label="Pages read">
          <div className="progress-fill" style={{ width: `${percent}%` }} />
        </div>
      )}
      {reading && <p className="empty-help">Scanned pages take longer because each one is read by OCR. You can leave this page open.</p>}
    </div>
  );
}

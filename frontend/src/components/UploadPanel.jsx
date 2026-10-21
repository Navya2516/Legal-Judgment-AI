import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { useDocument, isBusy } from "../hooks/useDocument";
import { navigate } from "../hooks/useRoute";
import ErrorBox from "./ErrorBox";
import ProcessingSteps from "./ProcessingSteps";
import Spinner from "./Spinner";
import { formatBytes } from "../lib/format";

export default function UploadPanel({ onUploaded }) {
  const [phase, setPhase] = useState("idle"); // idle | uploading | processing
  const [file, setFile] = useState(null);
  const [error, setError] = useState(null);
  const [docId, setDocId] = useState(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);
  const { doc, error: pollError } = useDocument(docId);

  useEffect(() => {
    if (doc && doc.status === "ready" && !isBusy(doc)) {
      onUploaded?.();
      navigate({ name: "doc", id: doc.id, tab: "summary" });
    }
  }, [doc, onUploaded]);

  async function start(chosen) {
    setError(null);
    if (!chosen) return;
    if (!/\.pdf$/i.test(chosen.name)) {
      setError({ code: "unsupported_file_type", message: "Only PDF files can be uploaded. Choose a .pdf file." });
      return;
    }
    if (chosen.size === 0) {
      setError({ code: "invalid_pdf", message: "That file is empty." });
      return;
    }
    setFile(chosen);
    setPhase("uploading");
    try {
      const record = await api.uploadDocument(chosen);
      setDocId(record.id);
      setPhase("processing");
    } catch (e) {
      setError(e);
      setPhase("idle");
    }
  }

  function reset() {
    setPhase("idle");
    setFile(null);
    setDocId(null);
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  if (phase !== "idle") {
    const failed = doc?.status === "failed";
    return (
      <section className="upload upload-active" aria-labelledby="upload-title">
        <h2 id="upload-title" className="upload-title">{file?.name}</h2>
        <p className="upload-sub">{formatBytes(file?.size)}</p>
        {phase === "uploading" && <Spinner label="Uploading and checking the file…" />}
        {phase === "processing" && doc && <ProcessingSteps doc={doc} />}
        {phase === "processing" && !doc && <Spinner label="Starting…" />}
        {doc?.warnings?.length > 0 && (
          <div className="notice notice-warn"><ul>{doc.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></div>
        )}
        {failed && (
          <div className="notice notice-error" role="alert">
            <p className="notice-title">This file could not be read</p>
            <p>{doc.error || "Text could not be extracted from it."}</p>
          </div>
        )}
        {pollError && !doc && <ErrorBox error={pollError} />}
        {(failed || pollError) && <button type="button" className="btn" onClick={reset}>Choose another file</button>}
      </section>
    );
  }

  return (
    <section className="upload" aria-labelledby="upload-title">
      <h2 id="upload-title" className="upload-title">Upload a judgment</h2>
      <div
        className={`dropzone${dragging ? " dropzone-over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); start(e.dataTransfer.files?.[0]); }}
      >
        <p className="dropzone-main">Drop a PDF here</p>
        <p className="dropzone-sub">or</p>
        <label className="btn btn-primary" htmlFor="pdf-input">Choose a PDF file</label>
        <input id="pdf-input" ref={inputRef} className="visually-hidden-input" type="file" accept="application/pdf,.pdf"
          onChange={(e) => start(e.target.files?.[0])} />
      </div>
      <p className="upload-help">Text PDFs and scanned PDFs both work. Your file is stored only in the backend's data folder on your own machine and you can delete it at any time.</p>
      <ErrorBox error={error} />
    </section>
  );
}

import { explainError } from "../lib/errors";

export default function ErrorBox({ error, onRetry, compact = false }) {
  if (!error) return null;
  const info = explainError(error);
  return (
    <div className={`notice notice-error${compact ? " notice-compact" : ""}`} role="alert">
      <p className="notice-title">{info.title}</p>
      <p>{info.body}</p>
      {error.code && error.code !== "network" && (
        <p className="notice-meta">Reference: {error.code}{error.status ? ` (${error.status})` : ""}</p>
      )}
      {info.retry && onRetry && (
        <button type="button" className="btn btn-quiet" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

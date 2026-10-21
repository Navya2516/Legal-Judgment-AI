import ErrorBox from "./ErrorBox";
import Spinner from "./Spinner";

/**
 * Shows the right thing for a result that may not exist yet: a loading line,
 * an error, an invitation to generate or translate it, or (when ready) its content.
 */
export default function Gate({
  analysis, lang, languageName, noun, generateLabel, translateLabel, intro, options, children,
}) {
  const { status, busy, error, actionError } = analysis;

  if (busy) {
    return (
      <div className="empty-state" aria-live="polite">
        <Spinner label={busy === "translating" ? `Translating into ${languageName}…` : `Reading the judgment and writing the ${noun}…`} />
        <p className="empty-help">
          This can take up to a minute. The result is saved when it finishes, so nothing is lost if you wait here.
        </p>
      </div>
    );
  }
  if (status === "loading") {
    return <div className="empty-state"><Spinner label={`Loading the ${noun}…`} /></div>;
  }
  if (status === "error") {
    return <ErrorBox error={error} onRetry={analysis.reload} />;
  }
  if (status === "missing" || status === "needs_translation") {
    const translating = status === "needs_translation";
    return (
      <div className="empty-state">
        <h3 className="empty-title">
          {translating ? `The ${noun} is not in ${languageName} yet` : `No ${noun} yet`}
        </h3>
        <p className="empty-help">{translating ? `The English ${noun} exists. Translating it is a separate step with its own checks.` : intro}</p>
        {options}
        <ErrorBox error={actionError} onRetry={translating ? analysis.translate : () => analysis.generate()} />
        <button type="button" className="btn btn-primary" onClick={() => (translating ? analysis.translate() : analysis.generate())}>
          {translating ? translateLabel : generateLabel}
        </button>
      </div>
    );
  }
  return (
    <>
      {actionError && <ErrorBox error={actionError} onRetry={() => analysis.generate()} />}
      {children}
    </>
  );
}

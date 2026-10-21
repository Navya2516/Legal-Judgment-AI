import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { useAnalysis } from "../hooks/useAnalysis";
import { formatPages } from "../lib/format";
import ErrorBox from "./ErrorBox";
import EvidenceRow, { LeafHead, LeafNote } from "./EvidenceRow";
import Gate from "./Gate";
import Spinner from "./Spinner";
import { GroundingLine, TranslationNotes } from "./SummaryPanel";

function ProvisionList({ docId, onOpenPage }) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [filter, setFilter] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setState({ loading: true, data: null, error: null });
    api.listProvisions(docId, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((error) => !controller.signal.aborted && setState({ loading: false, data: null, error }));
    return () => controller.abort();
  }, [docId, attempt]);

  const rows = useMemo(() => {
    const all = state.data?.provisions || [];
    const needle = filter.trim().toLowerCase();
    return needle ? all.filter((p) => `${p.key} ${p.label} ${p.act || ""}`.toLowerCase().includes(needle)) : all;
  }, [state.data, filter]);

  if (state.loading) return <div className="empty-state"><Spinner label="Finding the provisions…" /></div>;
  if (state.error) return <ErrorBox error={state.error} onRetry={() => setAttempt((n) => n + 1)} />;
  if (!state.data.provisions.length) {
    return <div className="empty-state"><h3 className="empty-title">No Articles or Sections found</h3><p className="empty-help">The text of this judgment does not mention any provision in a form this tool recognises.</p></div>;
  }
  const visible = showAll || filter ? rows : rows.slice(0, 12);
  return (
    <div className="provision-list">
      <div className="provision-tools">
        <label htmlFor="prov-filter">Filter by name</label>
        <input id="prov-filter" type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="for example Article 21" />
        <span className="provision-count">{rows.length} of {state.data.total}</span>
      </div>
      <div className="table-wrap">
        <table>
          <caption className="visually-hidden">Articles, Sections and Rules mentioned in the judgment</caption>
          <thead>
            <tr><th scope="col">Provision</th><th scope="col" className="num">Mentions</th><th scope="col" className="num">Pages</th><th scope="col">First mention</th></tr>
          </thead>
          <tbody>
            {visible.map((p) => (
              <tr key={p.key}>
                <th scope="row" lang="en">
                  {p.key}
                  {p.act_basis === "assumed" && <span className="note-inline" title="The judgment writes only the Article number, so the Constitution is assumed."> (Constitution assumed)</span>}
                </th>
                <td className="num">{p.mentions}</td>
                <td className="num">{p.page_count}</td>
                <td><button type="button" className="pagelink" onClick={() => onOpenPage(p.first_mention.page, null)}>page {p.first_mention.page}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!showAll && !filter && rows.length > 12 && (
        <button type="button" className="btn btn-quiet" onClick={() => setShowAll(true)}>Show all {rows.length}</button>
      )}
      <p className="grounding-line">{state.data.note}</p>
    </div>
  );
}

export default function ProvisionsPanel({ docId, lang, languageName, onOpenPage }) {
  const analysis = useAnalysis("explanations", docId, lang);
  const [topN, setTopN] = useState(8);
  const options = (
    <div className="field-inline">
      <label htmlFor="topn">Explain the most-mentioned</label>
      <select id="topn" value={topN} onChange={(e) => setTopN(Number(e.target.value))}>
        {[5, 8, 12].map((n) => <option key={n} value={n}>{n} provisions</option>)}
      </select>
    </div>
  );
  const gate = { ...analysis, generate: () => analysis.generate({ topN }) };
  const data = analysis.data;
  return (
    <div className="leaf">
      <LeafHead id="explained">What the judgment does with each provision</LeafHead>
      <Gate analysis={gate} lang={lang} languageName={languageName} noun="provision explanations"
        generateLabel="Explain the provisions" translateLabel={`Translate into ${languageName}`}
        intro="Each explanation says what role the provision plays in this judgment and cites the page. This calls the language model and can take up to a minute."
        options={options}>
        {data && (
          <>
            <TranslationNotes data={data} />
            {data.items.length === 0 && <LeafNote>No explanation could be supported by the judgment text.</LeafNote>}
            {data.items.map((item) => (
              <EvidenceRow key={item.key} heading={<span lang="en">{item.key}</span>} text={item.role_in_case}
                sourceText={item.source_text} pages={item.pages} status={item.status} quote={item.quote}
                check={item.check} translated={data.language !== "en"} lang={data.language} onOpenPage={onOpenPage} />
            ))}
            <LeafNote><GroundingLine grounding={data.grounding} /></LeafNote>
            <LeafNote tone="muted">{data.disclaimer}</LeafNote>
          </>
        )}
      </Gate>
      <div className="section-break" />
      <LeafHead id="all-provisions">Every provision found in the text</LeafHead>
      <div className="leaf-row">
        <div className="leaf-text"><ProvisionList docId={docId} onOpenPage={onOpenPage} /></div>
        <div className="leaf-margin leaf-margin-empty" aria-hidden="true" />
      </div>
    </div>
  );
}

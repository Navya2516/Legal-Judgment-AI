import { useState } from "react";
import { useAnalysis } from "../hooks/useAnalysis";
import EvidenceRow, { LeafHead, LeafNote } from "./EvidenceRow";
import Gate from "./Gate";
import { GroundingLine, TranslationNotes } from "./SummaryPanel";

const COURT_OPTIONS = [
  ["", "Detect automatically"],
  ["supreme_court", "Supreme Court"],
  ["high_court", "High Court"],
  ["trial_court", "Trial or district-level court"],
  ["tribunal", "Tribunal or commission"],
];

function CourtSelect({ value, onChange }) {
  return (
    <div className="field-inline">
      <label htmlFor="court-level">Court that gave the judgment</label>
      <select id="court-level" value={value} onChange={(e) => onChange(e.target.value)}>
        {COURT_OPTIONS.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
      </select>
    </div>
  );
}

function Points({ title, id, points, empty, lang, translated, onOpenPage }) {
  return (
    <section aria-labelledby={id}>
      <LeafHead id={id}>{title}</LeafHead>
      {points.length === 0 && <LeafNote tone="muted">{empty}</LeafNote>}
      {points.map((p, i) => (
        <EvidenceRow key={i} {...p} translated={translated} lang={lang} onOpenPage={onOpenPage} />
      ))}
    </section>
  );
}

export default function ContinuationPanel({ docId, lang, languageName, onOpenPage }) {
  const analysis = useAnalysis("continuation", docId, lang);
  const [court, setCourt] = useState("");
  const gate = { ...analysis, generate: () => analysis.generate({ courtLevel: court || undefined }) };
  const data = analysis.data;
  const translated = data && data.language !== "en";
  const labels = data?.labels || {};
  const none = "Nothing of this kind is stated in the passages that were reviewed.";
  return (
    <div className="leaf">
      <Gate analysis={gate} lang={lang} languageName={languageName} noun="next-steps insights"
        generateLabel="Find what happens next" translateLabel={`Translate into ${languageName}`}
        intro="This reads how the court disposed of the case, what it ordered and any dates it set. It calls the language model and can take up to a minute."
        options={<CourtSelect value={court} onChange={setCourt} />}>
        {data && (
          <>
            <LeafNote>
              <strong>{labels.court_level || "Court"}:</strong> <span lang={lang}>{data.court_level_name}</span>
              <span className="note-inline"> — {data.court_level_basis}</span>
            </LeafNote>
            {data.coverage_note && <LeafNote tone="warn">{data.coverage_note}</LeafNote>}
            <TranslationNotes data={data} />
            <section aria-labelledby="c-disposition">
              <LeafHead id="c-disposition">{labels.disposition || "How the court disposed of the case"}</LeafHead>
              {data.disposition ? (
                <EvidenceRow heading={<span className="outcome" lang={lang}>{data.disposition.label_name}</span>}
                  {...data.disposition} text={data.disposition.text} translated={translated} lang={lang} onOpenPage={onOpenPage} />
              ) : <LeafNote tone="muted">The judgment passages reviewed do not state how the case was disposed of.</LeafNote>}
            </section>
            <Points id="c-directions" title={labels.directions || "What the court ordered"} points={data.directions} empty={none} lang={lang} translated={translated} onOpenPage={onOpenPage} />
            <Points id="c-deadlines" title={labels.deadlines || "Time limits and dates stated in the judgment"} points={data.deadlines} empty={none} lang={lang} translated={translated} onOpenPage={onOpenPage} />
            <Points id="c-further" title={labels.further_proceedings || "What happens next in this case"} points={data.further_proceedings} empty={none} lang={lang} translated={translated} onOpenPage={onOpenPage} />
            <LeafNote><GroundingLine grounding={data.grounding} /></LeafNote>

            <section className="avenues" aria-labelledby="c-avenues">
              <LeafHead id="c-avenues">{labels.avenues || "General information"}</LeafHead>
              <LeafNote tone="general"><span lang={lang}>{data.avenues_intro}</span></LeafNote>
              <div className="leaf-row">
                <div className="leaf-text">
                  <ul className="avenue-list">
                    {data.avenues.map((a) => (
                      <li key={a.id}>
                        <h4 lang={lang}>{a.title}</h4>
                        <p lang={lang}>{a.description}</p>
                        {a.basis && <p className="note-inline" lang="en">{a.basis}</p>}
                        {translated && a.source_description !== a.description && (
                          <details className="english-original"><summary>Show the English text</summary><p lang="en"><strong>{a.source_title}.</strong> {a.source_description}</p></details>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="leaf-margin leaf-margin-empty" aria-hidden="true" />
              </div>
              <LeafNote tone="general"><span lang={lang}>{data.avenues_notice}</span></LeafNote>
            </section>
            <LeafNote tone="muted">{data.disclaimer}</LeafNote>
            <div className="leaf-row"><div className="leaf-text">
              <details className="rerun">
                <summary>Court level wrong? Run it again</summary>
                <CourtSelect value={court} onChange={setCourt} />
                <button type="button" className="btn btn-quiet" onClick={() => gate.generate()}>Run again</button>
              </details>
            </div><div className="leaf-margin leaf-margin-empty" aria-hidden="true" /></div>
          </>
        )}
      </Gate>
    </div>
  );
}

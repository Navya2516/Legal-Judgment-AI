import EvidenceRow, { LeafHead, LeafNote } from "./EvidenceRow";
import { StatusBadge } from "./EvidenceNote";

export const SUMMARY_SECTIONS = ["plain_summary", "facts", "issues", "holding", "reasoning", "final_order"];

export function GroundingLine({ grounding }) {
  if (!grounding) return null;
  return (
    <p className="grounding-line">
      {grounding.points_total} points written · {grounding.verified} quote checked · {grounding.cited} page only ·{" "}
      {grounding.dropped_unsupported} removed because nothing in the judgment supported them
    </p>
  );
}

export function TranslationNotes({ data, language }) {
  if (!data || data.language === "en") return null;
  return (
    <>
      {data.stale && (
        <LeafNote tone="warn">The English text was regenerated after this translation was made. Translate again to match it.</LeafNote>
      )}
      {data.translation_notice && <LeafNote>{data.translation_notice}</LeafNote>}
      {data.quality && data.quality.flagged + data.quality.untranslated > 0 && (
        <LeafNote tone="warn">
          {data.quality.ok} of {data.quality.items_total} sentences passed the automatic checks.{" "}
          {data.quality.flagged} are flagged and {data.quality.untranslated} were left in English. Flagged sentences are marked below.
        </LeafNote>
      )}
    </>
  );
}

export default function SummaryPanel({ data, onOpenPage }) {
  const labels = data.labels || {};
  const lang = data.language;
  const translated = lang !== "en";
  const anyPoints = SUMMARY_SECTIONS.some((s) => data[s]?.length);
  const meta = [data.court, data.date, data.case_number].filter(Boolean);
  return (
    <div className="leaf">
      <div className="leaf-row">
        <div className="leaf-text case-head">
          <h2 className="case-title" lang="en">{data.case_title || "Untitled judgment"}</h2>
          {meta.length > 0 && <p className="case-meta" lang={lang}>{meta.join(" · ")}</p>}
          <p className="legend-inline">
            <StatusBadge status="verified" /> the quoted words were found on that page. <StatusBadge status="cited" /> the page is real but the words were not matched. Neither guarantees a perfect paraphrase, so read the page.
          </p>
        </div>
        <div className="leaf-margin leaf-margin-empty" aria-hidden="true" />
      </div>
      {data.coverage_note && <LeafNote tone="warn">{data.coverage_note}</LeafNote>}
      <TranslationNotes data={data} />
      {!anyPoints && <LeafNote>The summary has no points that the judgment text supports.</LeafNote>}
      {SUMMARY_SECTIONS.filter((s) => data[s]?.length).map((section) => (
        <section key={section} aria-labelledby={`sec-${section}`}>
          <LeafHead id={`sec-${section}`}>{labels[section] || section}</LeafHead>
          {data[section].map((point, index) => (
            <EvidenceRow key={`${section}-${index}`} {...point} translated={translated} lang={lang} onOpenPage={onOpenPage} />
          ))}
        </section>
      ))}
      <LeafNote><GroundingLine grounding={data.grounding} /></LeafNote>
      <LeafNote tone="muted">{data.disclaimer}</LeafNote>
    </div>
  );
}

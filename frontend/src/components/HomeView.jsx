import { useState } from "react";
import DocumentList from "./DocumentList";
import { StatusBadge } from "./EvidenceNote";
import UploadPanel from "./UploadPanel";

export default function HomeView() {
  const [refresh, setRefresh] = useState(0);
  return (
    <div className="home">
      <section className="hero">
        <div className="hero-copy">
          <h1>Understand a court judgment in your own language</h1>
          <p className="hero-lead">
            Upload a judgment PDF. You get a plain-language summary, the laws it relies on, what happens next in the case, and answers to your questions in English, Tamil, Hindi, Telugu, Malayalam or Kannada.
          </p>
          <div className="how">
            <h2>How each point is checked</h2>
            <p>Every point names the page it came from and quotes the judgment's own words. The server then looks for those exact words on that page.</p>
            <ul>
              <li><StatusBadge status="verified" /> the quoted words were found on the page.</li>
              <li><StatusBadge status="cited" /> the page is real, but the words were not matched. Read the page.</li>
            </ul>
            <p className="how-limit">A checked quote proves the words exist on that page. It cannot prove that the plain-language sentence is a perfect paraphrase, so use it as a guide to the judgment, not a replacement for it.</p>
          </div>
        </div>
        <UploadPanel onUploaded={() => setRefresh((n) => n + 1)} />
      </section>
      <DocumentList refreshKey={refresh} />
    </div>
  );
}

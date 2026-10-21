import { useEffect, useState } from "react";
import { api } from "../api/client";

const FALLBACK =
  "This system provides educational explanations of court judgments. It is not legal advice. Automated summaries and translations can contain mistakes, so check important details against the original judgment and consult a qualified advocate before taking any legal step.";

export default function Footer() {
  const [text, setText] = useState(FALLBACK);
  useEffect(() => {
    let live = true;
    api.disclaimer().then((b) => live && b?.disclaimer && setText(b.disclaimer)).catch(() => {});
    return () => { live = false; };
  }, []);
  return (
    <footer className="footer">
      <div className="footer-inner">
        <p className="footer-title">Educational information, not legal advice</p>
        <p>{text}</p>
      </div>
    </footer>
  );
}

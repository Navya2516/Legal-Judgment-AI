import LanguagePicker from "./LanguagePicker";

export default function Header({ languages, lang, onLang }) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <a className="brand" href="#/">
          <span className="brand-mark" aria-hidden="true" />
          <span>
            <span className="brand-name">Judgment Explainer</span>
            <span className="brand-sub">Indian court judgments in plain language</span>
          </span>
        </a>
        <nav className="topnav" aria-label="Main">
          <a href="#/">Your judgments</a>
        </nav>
        <LanguagePicker languages={languages} value={lang} onChange={onLang} />
      </div>
    </header>
  );
}

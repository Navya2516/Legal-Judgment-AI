import { useEffect, useMemo, useState } from "react";
import { api } from "./api/client";
import { useRoute } from "./hooks/useRoute";
import { FALLBACK_LANGUAGES, loadLanguage, saveLanguage } from "./lib/languages";
import Footer from "./components/Footer";
import Header from "./components/Header";
import HomeView from "./components/HomeView";
import Workspace from "./components/Workspace";

export default function App() {
  const route = useRoute();
  const [languages, setLanguages] = useState(FALLBACK_LANGUAGES);
  const [lang, setLang] = useState(() => loadLanguage(FALLBACK_LANGUAGES.map((l) => l.code)));

  useEffect(() => {
    let live = true;
    api.languages()
      .then((body) => {
        if (live && body?.languages?.length) setLanguages(body.languages);
      })
      .catch(() => {}); // the built-in list is the same six languages
    return () => { live = false; };
  }, []);

  const codes = useMemo(() => languages.map((l) => l.code), [languages]);
  const active = codes.includes(lang) ? lang : "en";
  const choose = (code) => {
    setLang(code);
    saveLanguage(code);
  };

  return (
    <>
      <a className="skip-link" href="#main">Skip to the content</a>
      <Header languages={languages} lang={active} onLang={choose} />
      <main id="main" className="main">
        {route.name === "doc" ? (
          <Workspace key={route.id} docId={route.id} tab={route.tab} lang={active} languages={languages} />
        ) : (
          <HomeView />
        )}
      </main>
      <Footer />
    </>
  );
}

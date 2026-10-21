import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";

// How each kind of result is read, generated (English) and translated.
const KINDS = {
  summary: {
    read: (id, lang) => api.readSummary(id, lang),
    generate: (id) => api.generateSummary(id),
    translate: (id, lang) => api.translateSummary(id, lang),
  },
  explanations: {
    read: (id, lang) => api.readExplanations(id, lang),
    generate: (id, opts) => api.generateExplanations(id, opts?.topN ?? 8),
    translate: (id, lang) => api.translateExplanations(id, lang),
  },
  continuation: {
    read: (id, lang) => api.readContinuation(id, lang),
    generate: (id, opts) => api.generateContinuation(id, opts?.courtLevel),
    translate: (id, lang) => api.translateContinuation(id, lang),
  },
};

/**
 * status:
 *   loading            looking for a saved result (no model call)
 *   ready              data is available in the chosen language
 *   missing            nothing has been generated yet (English first)
 *   needs_translation  English exists, this language has not been made yet
 *   error              the saved result could not be read
 * busy: null | "generating" | "translating"   (a model call is running)
 * actionError: the last generate/translate failure, if any
 */
export function useAnalysis(kind, docId, lang) {
  const config = KINDS[kind];
  const [view, setView] = useState({ status: "loading", data: null, error: null });
  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState(null);
  const token = useRef(0);

  const load = useCallback(async () => {
    const mine = ++token.current;
    setView({ status: "loading", data: null, error: null });
    setActionError(null);
    try {
      const data = await config.read(docId, lang);
      if (mine === token.current) setView({ status: "ready", data, error: null });
    } catch (error) {
      if (mine !== token.current) return;
      if (error.code !== "not_generated") {
        setView({ status: "error", data: null, error });
        return;
      }
      if (lang === "en") {
        setView({ status: "missing", data: null, error: null });
        return;
      }
      try {
        await config.read(docId, "en"); // does the English exist?
        if (mine === token.current) setView({ status: "needs_translation", data: null, error: null });
      } catch (inner) {
        if (mine !== token.current) return;
        if (inner.code === "not_generated") setView({ status: "missing", data: null, error: null });
        else setView({ status: "error", data: null, error: inner });
      }
    }
  }, [config, docId, lang]);

  useEffect(() => {
    load();
    return () => {
      token.current += 1; // ignore answers that arrive after leaving
    };
  }, [load]);

  const run = useCallback(
    async (steps) => {
      const mine = token.current;
      setActionError(null);
      try {
        for (const step of steps) {
          setBusy(step.busy);
          await step.call();
          if (mine !== token.current) return;
        }
        const data = await config.read(docId, lang);
        if (mine === token.current) setView({ status: "ready", data, error: null });
      } catch (error) {
        if (mine !== token.current) return;
        setActionError(error);
        // English may have been saved even though the translation failed: re-check.
        if (lang !== "en" && view.status === "missing") {
          try {
            await config.read(docId, "en");
            setView({ status: "needs_translation", data: null, error: null });
          } catch {
            /* stay on "missing" */
          }
        }
      } finally {
        if (mine === token.current) setBusy(null);
      }
    },
    [config, docId, lang, view.status]
  );

  // Generate the English result, then translate it when another language is chosen.
  const generate = useCallback(
    (opts) => {
      const steps = [{ busy: "generating", call: () => config.generate(docId, opts) }];
      if (lang !== "en") steps.push({ busy: "translating", call: () => config.translate(docId, lang) });
      return run(steps);
    },
    [config, docId, lang, run]
  );

  const translate = useCallback(
    () => run([{ busy: "translating", call: () => config.translate(docId, lang) }]),
    [config, docId, lang, run]
  );

  return { ...view, busy, actionError, generate, translate, reload: load };
}

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";

const POLL_MS = 1500;

export function isBusy(doc) {
  return !!doc && (doc.status === "uploaded" || doc.status === "processing" || doc.index_status === "indexing");
}

// Loads one document and keeps refreshing it while it is still being processed.
export function useDocument(id) {
  const [state, setState] = useState({ doc: null, error: null, loading: !!id });
  const timer = useRef(null);
  const alive = useRef(true);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const doc = await api.getDocument(id);
      if (!alive.current) return;
      setState({ doc, error: null, loading: false });
      if (isBusy(doc)) timer.current = setTimeout(load, POLL_MS);
    } catch (error) {
      if (!alive.current) return;
      // A brief network blip while polling should not throw away what we already show.
      setState((old) => ({ doc: old.doc, error, loading: false }));
      if (error.code === "network" || error.code === "timeout") timer.current = setTimeout(load, POLL_MS * 3);
    }
  }, [id]);

  useEffect(() => {
    alive.current = true;
    setState({ doc: null, error: null, loading: !!id });
    load();
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
    };
  }, [id, load]);

  return { ...state, reload: load };
}

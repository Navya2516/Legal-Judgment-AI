// One small wrapper around fetch. Every backend error has the same shape:
//   { "error": { "code": "...", "message": "...", "details": ... } }
// so the rest of the app only ever deals with ApiError.

export const API_BASE = (import.meta.env?.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

const DEFAULT_TIMEOUT_MS = 5 * 60 * 1000; // model calls can take a minute or more

export class ApiError extends Error {
  constructor({ status = 0, code = "unknown", message = "Something went wrong.", details = null }) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function withQuery(path, query) {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

export async function request(path, { method = "GET", json, form, query, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  const controller = new AbortController();
  const onAbort = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", onAbort, { once: true });
  }
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const init = { method, signal: controller.signal, headers: {} };
  if (json !== undefined) {
    init.body = JSON.stringify(json);
    init.headers["Content-Type"] = "application/json";
  } else if (form) {
    init.body = form; // the browser sets the multipart boundary
  }

  let response;
  try {
    response = await fetch(`${API_BASE}${withQuery(path, query)}`, init);
  } catch (error) {
    if (timedOut) {
      throw new ApiError({ code: "timeout", message: "The server took too long to answer." });
    }
    if (signal?.aborted) throw error; // the caller cancelled on purpose
    throw new ApiError({ code: "network", message: "Could not reach the server." });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }

  if (response.status === 204) return null;
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const err = body?.error;
    throw new ApiError({
      status: response.status,
      code: err?.code || `http_${response.status}`,
      message: err?.message || `The server answered with an error (${response.status}).`,
      details: err?.details ?? null,
    });
  }
  return body;
}

const docs = (id) => `/api/v1/documents/${encodeURIComponent(id)}`;

export const api = {
  health: (o) => request("/health", o),
  languages: (o) => request("/api/v1/languages", o),
  disclaimer: (o) => request("/api/v1/disclaimer", o),

  listDocuments: (o) => request("/api/v1/documents", o),
  getDocument: (id, o) => request(docs(id), o),
  deleteDocument: (id, o) => request(docs(id), { ...o, method: "DELETE" }),
  uploadDocument(file, o) {
    const form = new FormData();
    form.append("file", file, file.name);
    return request("/api/v1/documents", { ...o, method: "POST", form });
  },
  getPage: (id, n, o) => request(`${docs(id)}/pages/${n}`, o),

  // Summary: English is generated first, other languages are translated from it.
  generateSummary: (id, o) => request(`${docs(id)}/summary`, { ...o, method: "POST" }),
  readSummary: (id, lang, o) => request(`${docs(id)}/summary/${lang}`, o),
  translateSummary: (id, lang, o) => request(`${docs(id)}/summary/${lang}`, { ...o, method: "POST" }),

  listProvisions: (id, o) => request(`${docs(id)}/provisions`, { ...o, query: { limit: 200 } }),
  generateExplanations: (id, topN, o) =>
    request(`${docs(id)}/provisions/explain`, { ...o, method: "POST", json: { top_n: topN } }),
  readExplanations: (id, lang, o) => request(`${docs(id)}/provisions/explain/${lang}`, o),
  translateExplanations: (id, lang, o) =>
    request(`${docs(id)}/provisions/explain/${lang}`, { ...o, method: "POST" }),

  generateContinuation: (id, courtLevel, o) =>
    request(`${docs(id)}/continuation`, { ...o, method: "POST", query: { court_level: courtLevel } }),
  readContinuation: (id, lang, o) => request(`${docs(id)}/continuation/${lang}`, o),
  translateContinuation: (id, lang, o) =>
    request(`${docs(id)}/continuation/${lang}`, { ...o, method: "POST" }),

  ask: (id, { question, lang, topK = 6 }, o) =>
    request(`${docs(id)}/ask`, { ...o, method: "POST", json: { question, lang, top_k: topK } }),
};

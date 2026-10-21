import { API_BASE } from "../api/client";

// Turn a backend error into a sentence that says what happened and what to do.
export function explainError(error) {
  const code = error?.code;
  switch (code) {
    case "network":
      return {
        title: "Can't reach the server",
        body: `The app could not connect to the backend at ${API_BASE}. Start the backend (uvicorn) and try again.`,
        retry: true,
      };
    case "timeout":
      return { title: "The server took too long", body: "The request timed out. The model may be busy. Try again in a moment.", retry: true };
    case "llm_not_configured":
      return {
        title: "The Gemini API key is not set",
        body: "Add GEMINI_API_KEY to backend/.env, then restart the backend.",
        retry: false,
      };
    case "llm_rate_limited":
      return {
        title: "The model's usage limit was reached",
        // The backend says which limit was hit (daily or per-minute) and when it resets.
        body: error.message || "Wait a minute or two, then try again. Free Gemini keys have daily and per-minute limits.",
        retry: !/daily limit/.test(error.message || ""),
      };
    case "llm_unavailable":
      return { title: "The language model is busy or unreachable", body: "This is usually temporary. Try again shortly.", retry: true };
    case "llm_model_not_found":
      return {
        title: "The configured model name was not found",
        body: "Set GEMINI_MODEL in backend/.env to a model your key can use (run scripts/list_gemini_models.py), then restart the backend.",
        retry: false,
      };
    case "llm_bad_output":
      return { title: "The model's reply could not be used", body: "This sometimes happens. Try again.", retry: true };
    case "index_not_ready":
    case "index_failed":
    case "index_stale":
      return { title: "The search index is not ready", body: error.message, retry: true };
    case "file_too_large":
    case "unsupported_file_type":
    case "invalid_pdf":
      return { title: "This file can't be used", body: error.message, retry: false };
    case "not_found":
      return { title: "Not found", body: error.message || "This judgment no longer exists.", retry: false };
    case "validation_error":
      return { title: "The request was not valid", body: "Check what you entered and try again.", retry: false };
    default:
      return { title: "Something went wrong", body: error?.message || "Try again.", retry: true };
  }
}

// Used until (or if) the backend's /languages answers. Same six languages.
export const FALLBACK_LANGUAGES = [
  { code: "en", name: "English", native_name: "English" },
  { code: "ta", name: "Tamil", native_name: "தமிழ்" },
  { code: "hi", name: "Hindi", native_name: "हिन्दी" },
  { code: "te", name: "Telugu", native_name: "తెలుగు" },
  { code: "ml", name: "Malayalam", native_name: "മലയാളം" },
  { code: "kn", name: "Kannada", native_name: "ಕನ್ನಡ" },
];

const KEY = "jx.language";

// A language choice is a harmless per-viewer convenience, so it may be remembered.
// Storage can be blocked or empty, so every access is guarded.
export function loadLanguage(codes) {
  try {
    const saved = window.localStorage.getItem(KEY);
    if (saved && codes.includes(saved)) return saved;
  } catch {
    /* storage unavailable */
  }
  return "en";
}

export function saveLanguage(code) {
  try {
    window.localStorage.setItem(KEY, code);
  } catch {
    /* storage unavailable */
  }
}

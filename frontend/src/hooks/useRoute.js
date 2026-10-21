import { useEffect, useState } from "react";

export const TABS = [
  { id: "summary", label: "Summary" },
  { id: "provisions", label: "Legal provisions" },
  { id: "next", label: "What happens next" },
  { id: "ask", label: "Ask a question" },
];

export function parseHash(hash) {
  const parts = (hash || "").replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "doc" && parts[1] && /^[A-Za-z0-9_-]{8,64}$/.test(parts[1])) {
    const tab = TABS.some((t) => t.id === parts[2]) ? parts[2] : "summary";
    return { name: "doc", id: parts[1], tab };
  }
  return { name: "home" };
}

export function hrefFor(route) {
  return route.name === "doc" ? `#/doc/${route.id}/${route.tab || "summary"}` : "#/";
}

export function navigate(route) {
  window.location.hash = hrefFor(route);
}

export function useRoute() {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

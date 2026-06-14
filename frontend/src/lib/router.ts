import type { View } from "../types";

// A tiny hand-rolled router over the History API. The app has effectively two
// routes, the landing page and a chat, so this stays lighter than pulling in a
// router dependency. The URL is the source of truth for which view is shown:
//   /            -> home (hero + sections)
//   /chat        -> a fresh, unsaved chat (no conversation id yet)
//   /chat/:id    -> an existing conversation
// Deep links and reloads work because the deploy serves index.html for unknown
// paths (frontend/wrangler.jsonc: not_found_handling = single-page-application).

export type Route = { view: View; conversationId: number | null };

export function getRoute(): Route {
  if (typeof window === "undefined") return { view: "home", conversationId: null };
  const path = window.location.pathname;
  const match = path.match(/^\/chat\/(\d+)\/?$/);
  if (match) return { view: "chat", conversationId: Number(match[1]) };
  if (path === "/chat" || path === "/chat/") return { view: "chat", conversationId: null };
  return { view: "home", conversationId: null };
}

// Push (or replace) a path without reloading. A no-op when the path is already
// current and we are not explicitly replacing, so re-entering the same route
// (e.g. opening the conversation already in the URL) does not stack duplicates.
export function navigate(path: string, opts?: { replace?: boolean }): void {
  if (typeof window === "undefined") return;
  if (window.location.pathname === path && !opts?.replace) return;
  if (opts?.replace) window.history.replaceState({}, "", path);
  else window.history.pushState({}, "", path);
}

// Subscribe to back/forward (and the phone back gesture). Returns an unsubscribe.
export function onPopState(cb: (route: Route) => void): () => void {
  const handler = () => cb(getRoute());
  window.addEventListener("popstate", handler);
  return () => window.removeEventListener("popstate", handler);
}

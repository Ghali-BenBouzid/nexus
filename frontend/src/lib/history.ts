// Browser-persisted query history, shell-style: submitted prompts are kept in
// localStorage (oldest first, most recent last) so the input can recall them
// with ArrowUp/ArrowDown. Entries are de-duplicated, re-running a prompt moves
// it to the most-recent slot rather than piling up.
//
// The list is scoped per browser AND per demo user in live mode, so switching
// accounts on a shared machine doesn't mix histories. In simulated mode there are
// no accounts, so a single shared key is used.
import { useCallback, useState } from "react";

import { currentUserKey } from "./api";
import { LIVE_MODE } from "./research";

const BASE_KEY = "nexus-query-history";
const MAX = 50;

function storageKey(): string {
  return LIVE_MODE ? `${BASE_KEY}:${currentUserKey()}` : BASE_KEY;
}

export function loadHistory(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey()) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function rememberQuery(prompt: string): string[] {
  const trimmed = prompt.trim();
  if (!trimmed) return loadHistory();
  // drop any prior copy, then append so the newest is always last
  const next = [...loadHistory().filter((p) => p !== trimmed), trimmed].slice(-MAX);
  try {
    localStorage.setItem(storageKey(), JSON.stringify(next));
  } catch {
    // private mode / quota: history is best-effort, never block a submit
  }
  return next;
}

export function useQueryHistory() {
  const [history, setHistory] = useState<string[]>(loadHistory);
  const remember = useCallback((prompt: string) => setHistory(rememberQuery(prompt)), []);
  return { history, remember };
}

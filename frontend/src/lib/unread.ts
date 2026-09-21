// Which reports the user has actually read. A report is unread until it is
// opened, and unread again when a refresh gives it new content, so the marker in
// the Outputs list means "there is something here you have not seen" and nothing
// else. Status is a separate thing and is said in words.
//
// `completedAt` is the content's version: the backend moves it whenever the
// report is rewritten, so nothing new is needed to know that what was read has
// since changed.
import type { Output } from "../types";

// Output id -> the completedAt the user read. null covers a report opened while
// it was still running, which has no completedAt yet.
export type Seen = Record<number, string | null>;

const KEY = "nexus-seen-outputs";
// Enough to cover any plausible demo account, and small enough that the entry
// never grows without bound.
const KEEP = 200;

export function isUnread(output: Output, seen: Seen): boolean {
  // A report that is still working, or that failed, has nothing to read yet.
  if (output.status !== "complete") return false;
  return !(output.id in seen) || seen[output.id] !== output.completedAt;
}

export function unreadCount(outputs: Output[], seen: Seen): number {
  return outputs.filter((o) => isUnread(o, seen)).length;
}

export function markSeen(seen: Seen, output: Output): Seen {
  const next: Seen = { ...seen, [output.id]: output.completedAt };
  const ids = Object.keys(next);
  if (ids.length <= KEEP) return next;
  // Oldest ids first: they are the backend's query ids, so they sort by age.
  for (const id of ids.map(Number).sort((a, b) => a - b).slice(0, ids.length - KEEP)) {
    delete next[id];
  }
  return next;
}

// Read state is a per-viewer convenience, so it lives in this browser and a
// failure to read or write it is not worth a thought.
export function loadSeen(): Seen {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Seen) : {};
  } catch {
    return {};
  }
}

export function saveSeen(seen: Seen): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(seen));
  } catch {
    // A full or blocked store costs the user a dot, not their work.
  }
}

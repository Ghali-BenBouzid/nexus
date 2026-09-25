// How hard the supervisor thinks before it answers, picked in the composer and
// sent with every message. A per-viewer preference like the language: read when
// a message is sent, remembered in this browser only. Deep runs and fact checks
// keep their own effort on the server whatever this says.

// Two levels: below high the supervisor had too little thought to cite what it
// found. "max" leaves the model at its own ceiling.
export type Effort = "high" | "max";

export const EFFORTS: Effort[] = ["high", "max"];

const STORAGE_KEY = "nexus-effort";

function stored(): Effort {
  try {
    const v = localStorage.getItem(STORAGE_KEY) as Effort | null;
    // Anything else, such as a level that no longer exists, reads as the default.
    return v && EFFORTS.includes(v) ? v : "high";
  } catch {
    return "high";
  }
}

let current: Effort = stored();

export const getEffort = (): Effort => current;

export function setEffort(next: Effort): void {
  current = next;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* private window: kept for this page only */
  }
}

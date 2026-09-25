// How hard the supervisor thinks before it answers, picked in the composer and
// sent with every message. A per-viewer preference like the language: read when
// a message is sent, remembered in this browser only. Deep runs and fact checks
// keep their own effort on the server whatever this says.

export type Effort = "low" | "medium" | "high" | "xhigh";

export const EFFORTS: Effort[] = ["low", "medium", "high", "xhigh"];

const STORAGE_KEY = "nexus-effort";

function stored(): Effort {
  try {
    const v = localStorage.getItem(STORAGE_KEY) as Effort | null;
    return v && EFFORTS.includes(v) ? v : "medium";
  } catch {
    return "medium";
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

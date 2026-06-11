// Dispatches a research run to either the simulated engine (default) or the real
// backend (VITE_LIVE_MODE=true). The UI calls runResearch and reacts to the
// callbacks; it doesn't care which engine is behind them.
import type { Outcome, Result, Status, TimelineEvent } from "../types";
import { runLiveResearch } from "./api";
import { pickRun, toTimeline } from "./simulatedEngine";

export const LIVE_MODE = import.meta.env.VITE_LIVE_MODE === "true";

export type ResearchCallbacks = {
  onEvent: (e: TimelineEvent) => void;
  onStatus: (s: Status) => void;
  isCancelled: () => boolean;
};

export type ResearchOutcome = { result: Result; outcome: Outcome; error?: string };

const EMPTY_RESULT: Result = { report: "", sources: [], consulted: [], gaps: [] };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// Returns null if the run was cancelled (a newer run superseded it).
export function runResearch(
  prompt: string,
  cb: ResearchCallbacks,
): Promise<ResearchOutcome | null> {
  return LIVE_MODE ? runLiveResearch(prompt, cb) : runSimulated(prompt, cb);
}

async function runSimulated(
  prompt: string,
  cb: ResearchCallbacks,
): Promise<ResearchOutcome | null> {
  const { timeline, result } = toTimeline(pickRun(prompt));

  // Easter eggs to exercise the honest states: a prompt starting with "fail"
  // or "empty" forces that outcome.
  let outcome: Outcome = "ok";
  const p = prompt.toLowerCase();
  if (/^fail\b/.test(p)) outcome = "failed";
  else if (/^empty\b/.test(p)) outcome = "empty";

  cb.onStatus("running");
  for (const e of timeline) {
    await sleep(e.delay);
    if (cb.isCancelled()) return null;
    // A failed run dies partway through the writer.
    if (outcome === "failed" && e.kind === "writer" && e.state === "done") {
      return {
        result,
        outcome: "failed",
        error:
          "The writer agent lost its connection to the model provider (502). " +
          "Re-running usually clears it.",
      };
    }
    cb.onEvent(e);
  }
  if (cb.isCancelled()) return null;
  if (outcome === "empty") return { result: EMPTY_RESULT, outcome: "empty" };
  return { result, outcome: "ok" };
}

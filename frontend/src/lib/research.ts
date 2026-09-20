// Dispatches a research run to either the simulated engine (default) or the real
// backend (VITE_LIVE_MODE=true, with an invite). The UI calls runResearch and
// reacts to the callbacks; it doesn't care which engine is behind them.
import type { Outcome, Result, Status, TimelineEvent } from "../types";
import { hasInvite, runLiveResearch } from "./api";
import { pickRun, toTimeline } from "./simulatedEngine";

export const LIVE_MODE = import.meta.env.VITE_LIVE_MODE === "true";

// Live research needs a live build AND an invite. In a live build the app asks a
// visitor without one for a demo account before any run starts, so the simulated
// engine only serves builds without VITE_LIVE_MODE. Re-read on use, since an
// expired invite is dropped mid-session.
export const isLive = (): boolean => LIVE_MODE && hasInvite();

export type ResearchCallbacks = {
  onEvent: (e: TimelineEvent) => void;
  onStatus: (s: Status) => void;
  isCancelled: () => boolean;
  // Live mode only: the backend query id, as soon as the run is submitted, so the
  // turn can later refresh or cancel it. The simulated engine never calls it.
  onQueryId?: (id: number) => void;
  // Live mode only: the conversation this run belongs to (a new one on the first
  // message, the existing one on follow-ups), so the app can persist it.
  onConversation?: (id: number) => void;
  // Live mode only: the run's title, when it has one.
  onTitle?: (title: string) => void;
  // Live mode only: seconds since the backend job last showed signs of life, so
  // the progress bar can warn when a run looks stuck.
  onHeartbeat?: (secondsSince: number | null) => void;
  // Live mode only: the reply as it is written, one chunk at a time.
  onToken?: (text: string) => void;
  // Live mode only: the model's thinking while it works, same chunk at a time.
  // It is a scratchpad, not an answer: show it as provisional.
  onThought?: (text: string) => void;
};

export type ResearchOutcome = {
  result: Result;
  outcome: Outcome;
  title?: string;
  error?: string;
  // What the turn produced: the answer, and the follow-ups offered under it.
  reply?: string;
};

const EMPTY_RESULT: Result = { report: "", sources: [], consulted: [], gaps: [] };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// Returns null if the run was cancelled (a newer run superseded it).
// `conversationId` is the live-mode thread to append to (null = start a new one).
export function runResearch(
  prompt: string,
  cb: ResearchCallbacks,
  conversationId?: number | null,
  documentIds: number[] = [],
): Promise<ResearchOutcome | null> {
  return isLive()
    ? runLiveResearch(prompt, cb, conversationId ?? null, documentIds)
    : runSimulated(prompt, cb);
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
  if (outcome === "empty") return { result: EMPTY_RESULT, outcome: "empty", reply: "" };
  // The simulated run answers in the thread like a real one: its canned report
  // is the answer, and its sources are what the citations point at.
  return { result, outcome: "ok", reply: result.report };
}

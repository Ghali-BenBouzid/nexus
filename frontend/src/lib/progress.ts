// Turns a run's agent events into what the progress bar shows: the current stage,
// one row per researcher and when the latest step began. Pure, so the bar can
// re-derive it on every clock tick, and it is tested on its own.
import type { TimelineEvent } from "../types";

// What a researcher (or the run) is doing right now, and since when (the
// performance.now() instant its event reached the UI).
export type Activity =
  | { kind: "thinking"; at: number | null }
  | { kind: "search"; text: string; at: number | null }
  | { kind: "read"; domain: string; at: number | null }
  | { kind: "document"; text: string; at: number | null };

export type ResearcherOutcome = "running" | "found" | "empty" | "failed";

export type ResearcherRow = {
  index: number;
  question: string;
  outcome: ResearcherOutcome;
  activity: Activity | null; // only while running
};

export type Stage =
  | "starting"
  | "planning"
  | "researching"
  | "writing"
  | "answering"
  | "done";

// A run the turn started in the background, which finishes on its own.
export type StartedRun = { run: "deep_research" | "fact_check"; text: string };

export type Progress = {
  stage: Stage;
  planSize: number | null;
  researchers: ResearcherRow[]; // in plan order
  total: number; // researchers the plan asked for
  active: number; // researchers still working
  // The latest event is the supervisor, planner or writer calling the model.
  thinking: boolean;
  latest: Activity | null; // the most recent researcher activity
  lastAt: number | null; // when the latest event arrived
  // Background runs this turn kicked off; their own progress lives in Outputs.
  started: StartedRun[];
};

export function summarize(events: TimelineEvent[]): Progress {
  let stage: Stage = "starting";
  let planSize: number | null = null;
  let total = 0;
  let thinking = false;
  let latest: Activity | null = null;
  let lastAt: number | null = null;
  const started: StartedRun[] = [];
  const rows = new Map<number, ResearcherRow>();

  const row = (index: number, question = ""): ResearcherRow => {
    let r = rows.get(index);
    if (!r) {
      r = { index, question, outcome: "running", activity: null };
      rows.set(index, r);
    }
    if (question) r.question = question;
    return r;
  };
  const act = (index: number | undefined, activity: Activity) => {
    latest = activity;
    if (index != null) row(index).activity = activity;
  };

  for (const e of events) {
    const at = e.at ?? null;
    if (at != null) lastAt = at;
    thinking = false;
    switch (e.kind) {
      case "planner":
        stage = "planning";
        break;
      case "plan":
        planSize = e.items.length;
        total = Math.max(total, planSize);
        break;
      case "thinking":
        if (e.agent === "researcher") {
          act(e.index, { kind: "thinking", at });
          break;
        }
        if (e.agent === "planner") stage = "planning";
        if (e.agent === "writer") stage = "writing";
        if (e.agent === "supervisor" && stage !== "starting") stage = "answering";
        thinking = true;
        break;
      case "researcher":
        stage = "researching";
        if (e.state === "start") {
          total = Math.max(total, e.total);
          row(e.index, e.question);
        } else {
          const r = row(e.index, e.question);
          r.outcome = e.outcome;
          r.activity = null;
        }
        break;
      case "tool":
        if (e.action === "search") act(e.index, { kind: "search", text: e.text, at });
        else if (e.action === "read") act(e.index, { kind: "read", domain: e.domain, at });
        else if (e.action === "document") act(undefined, { kind: "document", text: e.text, at });
        break;
      case "started":
        started.push({ run: e.run, text: e.text });
        break;
      case "writer":
        stage = e.state === "done" ? "done" : "writing";
        break;
    }
  }

  const researchers = [...rows.values()].sort((a, b) => a.index - b.index);
  const active = researchers.filter((r) => r.outcome === "running").length;
  return { stage, planSize, researchers, total, active, thinking, latest, lastAt, started };
}

// How a run that is no longer live ended; null while it runs.
export type Ended = "stopped" | "failed" | null;

export type Mark = "run" | "ok" | "warn" | "stop";

// One row of the expanded list. ``cut``: the step was still going when the run
// ended, so it never finished.
export type Step =
  | { kind: "understanding"; mark: Mark; cut: boolean }
  | { kind: "plan"; mark: Mark; cut: boolean; size: number | null }
  | { kind: "researcher"; mark: Mark; cut: boolean; row: ResearcherRow }
  | { kind: "started"; mark: Mark; cut: boolean; run: StartedRun }
  | { kind: "write"; mark: Mark; cut: boolean };

// The main steps of a run, for the expanded bar. Only a live run has a running
// step: once it ends, whatever was still going shows how it ended instead of a
// spinner and a timer that would keep counting.
export function steps(p: Progress, ended: Ended): Step[] {
  const settle = (mark: Mark) => {
    const cut = mark === "run" && ended !== null;
    return { mark: cut ? (ended === "stopped" ? "stop" : "warn") : mark, cut } as const;
  };
  const list: Step[] = [];
  if (p.stage === "starting" && ended === null) list.push({ kind: "understanding", ...settle("run") });
  if (p.stage !== "starting" || p.planSize != null) {
    const planned = p.planSize != null || p.stage !== "planning";
    list.push({ kind: "plan", size: p.planSize, ...settle(planned ? "ok" : "run") });
  }
  for (const row of p.researchers) {
    const mark = row.outcome === "running" ? "run" : row.outcome === "found" ? "ok" : "warn";
    list.push({ kind: "researcher", row, ...settle(mark) });
  }
  for (const run of p.started) {
    // It is off on its own by the time the turn ends, so it is never "running"
    // here: the Outputs panel is where its progress lives.
    list.push({ kind: "started", run, ...settle("ok") });
  }
  if (p.stage === "writing" || p.stage === "done") {
    list.push({ kind: "write", ...settle(p.stage === "done" ? "ok" : "run") });
  }
  return list;
}

// The one sentence the collapsed activity row shows while a run works. Events
// give short, already-finished strings, so they win. The model's thinking is a
// scratchpad streaming in a token at a time, so its tail is usually half a
// sentence: only a finished one is worth putting on a line that a reader scans.
export type Headline =
  | { kind: "activity"; activity: Activity }
  | { kind: "researcher"; question: string }
  | { kind: "thought"; text: string }
  | { kind: "stage" };

export function headline(p: Progress, thinking: string): Headline {
  // A finished read or search only describes the run while research is live;
  // afterwards the latest activity is stale and the stage is the truth.
  if (p.stage === "researching" && p.active > 0) {
    if (p.latest && p.latest.kind !== "thinking") return { kind: "activity", activity: p.latest };
    const live = p.researchers.filter((r) => r.outcome === "running");
    // With several at once, no single question speaks for the run: the stage
    // line ("3 of 5 researchers") does.
    if (live.length === 1) return { kind: "researcher", question: live[0].question };
  }
  const thought = lastSentence(thinking);
  if (thought) return { kind: "thought", text: thought };
  return { kind: "stage" };
}

const TERMINATOR = /[.!?…]$/;

// The last finished sentence of a streaming scratchpad, or null while the first
// one is still being written. Long sentences are cut to one line's worth.
export function lastSentence(text: string, max = 90): string | null {
  const parts = text
    .split(/(?<=[.!?…])\s+|\n+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (parts.length === 0) return null;
  const last = parts[parts.length - 1];
  const done = TERMINATOR.test(last) ? last : parts.length > 1 ? parts[parts.length - 2] : null;
  if (!done) return null;
  return done.length > max ? done.slice(0, max - 1).trimEnd() + "…" : done;
}

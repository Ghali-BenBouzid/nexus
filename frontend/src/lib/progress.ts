// Turns a run's agent events into what the progress bar shows: the current stage,
// one row per researcher and when the latest step began. Pure, so the bar can
// re-derive it on every clock tick, and it is tested on its own.
import type { TimelineEvent } from "../types";

// What a researcher (or the run) is doing right now, and since when (the
// performance.now() instant its event reached the UI).
export type Activity =
  | { kind: "thinking"; at: number | null }
  | { kind: "search"; text: string; at: number | null }
  | { kind: "read"; domain: string; at: number | null };

export type ResearcherOutcome = "running" | "found" | "empty" | "failed";

export type ResearcherRow = {
  index: number;
  question: string;
  outcome: ResearcherOutcome;
  activity: Activity | null; // only while running
};

export type Stage = "starting" | "planning" | "researching" | "writing" | "done";

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
};

export function summarize(events: TimelineEvent[]): Progress {
  let stage: Stage = "starting";
  let planSize: number | null = null;
  let total = 0;
  let thinking = false;
  let latest: Activity | null = null;
  let lastAt: number | null = null;
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
        break;
      case "writer":
        stage = e.state === "done" ? "done" : "writing";
        break;
    }
  }

  const researchers = [...rows.values()].sort((a, b) => a.index - b.index);
  const active = researchers.filter((r) => r.outcome === "running").length;
  return { stage, planSize, researchers, total, active, thinking, latest, lastAt };
}

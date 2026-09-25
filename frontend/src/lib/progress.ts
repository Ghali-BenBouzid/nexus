// Turns a run's agent events into what the progress bar shows: the current stage,
// one row per researcher and when the latest step began. Pure, so the bar can
// re-derive it on every clock tick, and it is tested on its own.
import type { Source, TimelineEvent } from "../types";

// What a researcher (or the run) is doing right now, and since when (the
// performance.now() instant its event reached the UI).
export type Activity =
  | { kind: "thinking"; at: number | null }
  | { kind: "search"; text: string; at: number | null }
  | { kind: "read"; domain: string; at: number | null }
  | { kind: "document"; text: string; at: number | null }
  | { kind: "steer"; at: number | null }
  | { kind: "claims"; at: number | null };

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
  // Keyed by team as well as number: two research calls can run at once.
  const rows = new Map<string, ResearcherRow>();
  let team = "";

  const row = (index: number, question = ""): ResearcherRow => {
    let r = rows.get(`${team}:${index}`);
    if (!r) {
      r = { index, question, outcome: "running", activity: null };
      rows.set(`${team}:${index}`, r);
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
    team = ("team" in e && e.team) || "";
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
        else if (e.action === "steer") act(undefined, { kind: "steer", at });
        else if (e.action === "claims") act(undefined, { kind: "claims", at });
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

// How a run that is no longer live ended; null while it runs. "done" matters as
// much as the other two: a run that answered finished every step it took, even
// the ones no event ever closed, and a finished run must not show a spinner.
export type Ended = "stopped" | "failed" | "done" | null;

export type Mark = "run" | "ok" | "warn" | "stop";

type Row =
  | { kind: "understanding" }
  | { kind: "think"; step: number; title: string | null }
  | { kind: "search"; text: string }
  | { kind: "read"; domain: string }
  | { kind: "document"; text: string }
  | { kind: "steer" }
  | { kind: "research"; team: string; question: string }
  | { kind: "plan"; team: string; size: number | null; sub: boolean }
  | { kind: "researcher"; team: string; row: ResearcherRow; sub: boolean }
  | { kind: "started"; run: StartedRun }
  | { kind: "write"; done: boolean };

// One row of the expanded feed. ``cut``: the step was still going when the run
// ended, so it never finished. ``sub``: it belongs to the research team above it.
export type Step = { mark: Mark; cut: boolean } & Row;

const isSub = (r: Row) => "sub" in r && r.sub;

// Everything the run did, in the order it did it: each stretch of thinking
// under the title a small model gave it, each search, page and file it read,
// and each research team with its plan and researchers right under it. Only a
// live run has a running step; once it ends, whatever was still going shows
// how it ended instead.
export function timeline(events: TimelineEvent[], ended: Ended): Step[] {
  const rows: Row[] = [];
  // Two research calls can run at once, each numbering its researchers from 1,
  // so a team's rows are found by its id: the id of the call that sent it.
  // Events stored before teams had ids fall back to the latest team.
  let teams = 0;
  let current = "";
  const teamOf = (e: object) => ("team" in e && typeof e.team === "string" ? e.team : current);

  // Where a team's next row goes: under its own step, after what is already
  // there. A row with no team step above it (older runs) goes at the end.
  const slot = (team: string): { at: number; sub: boolean } => {
    const head = rows.findIndex((r) => r.kind === "research" && r.team === team);
    if (head < 0) return { at: rows.length, sub: false };
    let at = head + 1;
    while (at < rows.length && isSub(rows[at])) at++;
    return { at, sub: true };
  };
  const plan = (team: string) => {
    const found = rows.find((r) => r.kind === "plan" && r.team === team);
    if (found?.kind === "plan") return found;
    const { at, sub } = slot(team);
    const made: Row & { kind: "plan" } = { kind: "plan", team, size: null, sub };
    rows.splice(at, 0, made);
    return made;
  };
  const researcher = (team: string, index: number, question = ""): ResearcherRow => {
    const found = rows.find((r) => r.kind === "researcher" && r.team === team && r.row.index === index);
    if (found?.kind === "researcher") {
      if (question) found.row.question = question;
      return found.row;
    }
    const row: ResearcherRow = { index, question, outcome: "running", activity: null };
    const { sub, at: end } = slot(team);
    let at = end;
    // Researchers start in parallel and in any order; they are listed by number.
    while (at > 0) {
      const prev = rows[at - 1];
      if (prev.kind !== "researcher" || prev.team !== team || prev.row.index < index) break;
      at--;
    }
    rows.splice(at, 0, { kind: "researcher", team, row, sub });
    return row;
  };

  for (const e of events) {
    const at = e.at ?? null;
    switch (e.kind) {
      case "step":
        rows.push({ kind: "think", step: e.step, title: null });
        break;
      case "step_title":
        for (const r of rows) if (r.kind === "think" && r.step === e.step) r.title = e.title;
        break;
      case "thinking":
        if (e.agent === "researcher" && e.index != null) {
          researcher(teamOf(e), e.index).activity = { kind: "thinking", at };
        }
        break;
      case "tool":
        if (e.action === "research") {
          current = e.team ?? `team-${++teams}`;
          rows.push({ kind: "research", team: current, question: e.text });
        } else if ("index" in e && e.index != null) {
          // A researcher's own search or read is that row's state, not a step.
          const r = researcher(teamOf(e), e.index);
          if (e.action === "search") r.activity = { kind: "search", text: e.text, at };
          if (e.action === "read") r.activity = { kind: "read", domain: e.domain, at };
        } else if (e.action === "search") rows.push({ kind: "search", text: e.text });
        else if (e.action === "read") rows.push({ kind: "read", domain: e.domain });
        else if (e.action === "document") rows.push({ kind: "document", text: e.text });
        else if (e.action === "steer") rows.push({ kind: "steer" });
        break;
      case "planner":
        plan(teamOf(e));
        break;
      case "plan":
        plan(teamOf(e)).size = e.items.length;
        break;
      case "researcher": {
        const r = researcher(teamOf(e), e.index, e.question);
        if (e.state === "done") {
          r.outcome = e.outcome;
          r.activity = null;
        }
        break;
      }
      case "started":
        rows.push({ kind: "started", run: { run: e.run, text: e.text } });
        break;
      case "writer": {
        const write = rows.find((r) => r.kind === "write");
        if (write?.kind === "write") write.done ||= e.state === "done";
        else rows.push({ kind: "write", done: e.state === "done" });
        break;
      }
    }
  }

  const settle = (mark: Mark): { mark: Mark; cut: boolean } => {
    if (mark !== "run" || ended === null) return { mark, cut: false };
    // The run answered, so whatever was still marked running did finish; only a
    // run that was cut short leaves a step unfinished.
    if (ended === "done") return { mark: "ok", cut: false };
    return { mark: ended === "stopped" ? "stop" : "warn", cut: true };
  };

  // Before the model has said anything, the one thing happening is reading the
  // request. Shown on a finished run too, where it settles as done.
  if (rows.length === 0) return [{ kind: "understanding", ...settle("run") }];

  let lastTop = rows.length - 1;
  while (lastTop > 0 && isSub(rows[lastTop])) lastTop--;
  return rows.map((r, i): Step => {
    if (r.kind === "researcher") {
      const failed = r.row.outcome === "empty" || r.row.outcome === "failed";
      return { ...r, ...settle(r.row.outcome === "running" ? "run" : failed ? "warn" : "ok") };
    }
    // A step is running while nothing has come after it; a team while any of
    // its researchers still is; a plan until it has its size; the writer until
    // it says it is done.
    let live = i === lastTop;
    if (r.kind === "research") {
      live ||= rows.some((o) => o.kind === "researcher" && o.team === r.team && o.row.outcome === "running");
    }
    if (r.kind === "plan") live = r.size == null;
    if (r.kind === "write") live = !r.done;
    if (r.kind === "started") live = false;
    return { ...r, ...settle(live ? "run" : "ok") };
  });
}

// The one sentence the collapsed activity row shows while a run works: what the
// latest step is doing, in the most specific words available. With several
// researchers at once, no single question speaks for the run, and the stage
// line ("3 of 5 researchers") does.
export type Headline =
  | { kind: "activity"; activity: Activity }
  | { kind: "researcher"; question: string }
  | { kind: "step"; step: Step }
  | { kind: "stage" };

export function headline(p: Progress, items: Step[]): Headline {
  if (p.stage === "researching" && p.active > 0) {
    if (p.latest && p.latest.kind !== "thinking") return { kind: "activity", activity: p.latest };
    const live = p.researchers.filter((r) => r.outcome === "running");
    if (live.length === 1) return { kind: "researcher", question: live[0].question };
    return { kind: "stage" };
  }
  const tops = items.filter((s) => !isSub(s));
  const step = tops[tops.length - 1];
  if (step && step.kind !== "understanding") return { kind: "step", step };
  return { kind: "stage" };
}

// One round of the supervisor's work, and what it said at the end of it. A turn
// reads like a conversation: the work, a part of the reply, more work, the next
// part, and so on down to the answer. `at` is when its words arrived: where the
// round ended and the next began.
export type Round = { events: TimelineEvent[]; said: string | null; at: number | null };

export function rounds(events: TimelineEvent[]): Round[] {
  const out: Round[] = [{ events: [], said: null, at: null }];
  // A step is named after it ends, often once the words after it are out, and
  // the name belongs with the step, not with whatever round is going by then.
  const home = new Map<number, TimelineEvent[]>();
  for (const e of events) {
    const round = out[out.length - 1];
    if (e.kind === "said") {
      round.said = e.text;
      round.at = e.at ?? null;
      out.push({ events: [], said: null, at: null });
      continue;
    }
    if (e.kind === "step") home.set(e.step, round.events);
    (e.kind === "step_title" ? (home.get(e.step) ?? round.events) : round.events).push(e);
  }
  return out;
}

// Every source the reply can cite so far, where [n] finds it: at n - 1. The
// numbers are the ones the reply uses while it is written; the stored reply is
// renumbered, and cites the turn's final source list instead.
export function liveSources(events: TimelineEvent[]): Source[] {
  const out: Source[] = [];
  for (const e of events) {
    if (e.kind === "sources") e.items.forEach((s, i) => (out[e.first - 1 + i] = s));
  }
  return out;
}

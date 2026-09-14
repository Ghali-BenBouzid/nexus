import { useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import { summarize, type Activity, type Progress, type ResearcherRow } from "../lib/progress";
import type { Turn } from "../types";

// Seconds without a heartbeat before the bar warns that the run may be stuck. The
// job beats every 10 s, so this tolerates a few slow or missed beats.
const STALE_AFTER = 45;

const clock = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

const since = (at: number | null, now: number) => (at == null ? null : (now - at) / 1000);

function activityText(a: Activity, now: number): string {
  if (a.kind === "search") return t.progress.searching(a.text);
  if (a.kind === "read") return t.progress.readingPage(a.domain);
  const s = since(a.at, now);
  return s == null ? t.progress.thinking : `${t.progress.thinking} ${clock(s)}`;
}

// The bar's one line: the stage the run is in.
function headline(p: Progress, turn: Turn): string {
  if (turn.status === "awaiting_plan") return t.progress.planReady(turn.plan?.length ?? p.planSize ?? 0);
  if (turn.status === "complete") {
    return p.researchers.length > 0 ? t.progress.researched(p.researchers.length) : t.progress.ready;
  }
  if (turn.stopped) return t.progress.stopped;
  if (turn.status === "failed") return t.progress.failed;
  switch (p.stage) {
    case "starting":
      return t.progress.understanding;
    case "planning":
      return t.progress.planning;
    case "researching":
      return p.active > 0 ? t.progress.researching(p.active, p.total) : t.progress.researchDone;
    case "writing":
      return t.progress.writing;
    case "done":
      return t.progress.ready;
  }
}

// What is happening inside that stage right now, so a long step reads as work.
function detail(p: Progress, now: number): string | null {
  if (p.stage === "researching" && p.active > 0 && p.latest) return activityText(p.latest, now);
  const s = since(p.lastAt, now);
  if (p.thinking) return s == null ? t.progress.thinking : `${t.progress.thinking} ${clock(s)}`;
  return null;
}

function heartbeatAge(turn: Turn, now: number): number | null {
  if (turn.heartbeatAge == null || turn.heartbeatSeenAt == null) return null;
  return turn.heartbeatAge + (now - turn.heartbeatSeenAt) / 1000;
}

type Mark = "run" | "ok" | "warn";

function Step({ mark, children, state }: { mark: Mark; children: React.ReactNode; state?: string | null }) {
  return (
    <li className={"pb-step " + mark}>
      <span className="pb-mark" aria-hidden="true">
        {mark === "run" ? <span className="spin" /> : mark === "ok" ? I.check : I.warn}
      </span>
      <span className="pb-step-text">{children}</span>
      {state && <span className="pb-step-state">{state}</span>}
    </li>
  );
}

function researcherState(r: ResearcherRow, now: number): string {
  if (r.outcome === "found") return t.progress.found;
  if (r.outcome === "empty") return t.progress.empty;
  if (r.outcome === "failed") return t.progress.couldNot;
  return r.activity ? activityText(r.activity, now) : t.progress.starting;
}

// A run's progress as one line that changes with each stage, like a chat app's
// "thinking" row. Collapsed by default; expanding it lists the main steps.
export function ProgressBar({ turn, now }: { turn: Turn; now: number }) {
  const [open, setOpen] = useState(false);
  const p = summarize(turn.events);
  const running = turn.status === "running" || turn.status === "pending";
  const elapsed = ((turn.endedAt ?? now) - turn.startedAt) / 1000;

  const age = running ? heartbeatAge(turn, now) : null;
  const stale = age != null && age > STALE_AFTER;
  const label = headline(p, turn);
  const sub = stale ? t.progress.stale(clock(age)) : running ? detail(p, now) : null;

  const icon = running ? <span className="spin" /> : turn.status === "complete" ? I.check : turn.stopped ? I.stop : I.warn;
  const planDone = p.planSize != null || p.stage === "researching" || p.stage === "writing" || p.stage === "done";

  return (
    <div className={"pb" + (open ? " open" : "") + (stale ? " stale" : "")}>
      <button type="button" className="pb-bar" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className={"pb-icon" + (running ? " live" : "")} aria-hidden="true">{icon}</span>
        <span className="pb-head" aria-live="polite">
          {/* Keyed by the text, so each new stage fades in instead of swapping. */}
          <span key={label} className={"pb-label" + (running && !stale ? " live" : "")}>{label}</span>
          {sub && <span key={sub.split(" ")[0]} className="pb-detail">{sub}</span>}
        </span>
        <span className="pb-time">{clock(elapsed)}</span>
        <span className="pb-chevron" aria-hidden="true">{I.arrowDown}</span>
      </button>

      {open && (
        <ol className="pb-steps">
          {p.stage === "starting" && running && <Step mark="run">{t.progress.understanding}</Step>}
          {(p.stage !== "starting" || p.planSize != null) && (
            <Step mark={planDone ? "ok" : "run"}>
              {p.planSize != null ? t.progress.planned(p.planSize) : t.progress.planning}
            </Step>
          )}
          {p.researchers.map((r) => (
            <Step key={r.index} mark={r.outcome === "running" ? "run" : r.outcome === "found" ? "ok" : "warn"} state={researcherState(r, now)}>
              <span className="pb-num">{r.index}</span>
              {r.question}
            </Step>
          ))}
          {(p.stage === "writing" || p.stage === "done") && (
            <Step mark={p.stage === "done" ? "ok" : "run"} state={p.stage === "writing" ? detail(p, now) : null}>
              {p.stage === "done" ? t.progress.written : t.progress.writing}
            </Step>
          )}
        </ol>
      )}
    </div>
  );
}

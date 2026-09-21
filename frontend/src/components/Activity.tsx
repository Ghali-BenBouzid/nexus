import { useEffect, useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import {
  headline,
  steps,
  summarize,
  type Activity as Act,
  type Headline,
  type Mark,
  type Progress,
  type ResearcherRow,
  type Step as StepRow,
} from "../lib/progress";
import type { Turn } from "../types";

// Seconds without a heartbeat before the row warns that the run may be stuck. The
// job beats every 10 s, so this tolerates a few slow or missed beats.
const STALE_AFTER = 45;

const clock = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

// How long a finished run took, read as a duration rather than as a stopwatch.
const brief = (seconds: number) => {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
};

const since = (at: number | null, now: number) => (at == null ? null : (now - at) / 1000);

function activityText(a: Act, now: number): string {
  if (a.kind === "search") return t.progress.searching(a.text);
  if (a.kind === "read") return t.progress.readingPage(a.domain);
  if (a.kind === "document") return t.progress.readingDocument(a.text);
  const s = since(a.at, now);
  return s == null ? t.progress.thinking : `${t.progress.thinking} ${clock(s)}`;
}

// The stage a run is in, for when nothing more specific is happening.
function stageText(p: Progress, turn: Turn): string {
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
    case "answering":
      return t.progress.answering;
    default:
      return t.progress.answered;
  }
}

function headlineText(h: Headline, p: Progress, turn: Turn, now: number): string {
  switch (h.kind) {
    case "activity":
      return activityText(h.activity, now);
    case "researcher":
      return h.question;
    case "thought":
      return h.text;
    case "stage":
      return stageText(p, turn);
  }
}

function heartbeatAge(turn: Turn, now: number): number | null {
  if (turn.heartbeatAge == null || turn.heartbeatSeenAt == null) return null;
  return turn.heartbeatAge + (now - turn.heartbeatSeenAt) / 1000;
}

const MARKS: Record<Mark, React.ReactNode> = { run: <span className="spin" />, ok: I.check, warn: I.warn, stop: I.stop };

function Step({ mark, children, state }: { mark: Mark; children: React.ReactNode; state?: string | null }) {
  return (
    // Prefixed modifiers: a bare "run" collides with the page-level .run class.
    <li className={"act-step act-step-" + mark}>
      <span className="act-mark" aria-hidden="true">{MARKS[mark]}</span>
      <span className="act-step-text">{children}</span>
      {state && <span className="act-step-state">{state}</span>}
    </li>
  );
}

function researcherState(r: ResearcherRow, now: number): string {
  if (r.outcome === "found") return t.progress.found;
  if (r.outcome === "empty") return t.progress.empty;
  if (r.outcome === "failed") return t.progress.couldNot;
  return r.activity ? activityText(r.activity, now) : t.progress.starting;
}

function StepItem({ step, now, stopped }: { step: StepRow; now: number; stopped: boolean }) {
  // A step the run ended in the middle of says so, and nothing about it ticks.
  const cut = step.cut ? (stopped ? t.progress.stoppedHere : t.progress.unfinished) : null;
  switch (step.kind) {
    case "understanding":
      return <Step mark={step.mark}>{t.progress.understanding}</Step>;
    case "plan":
      return (
        <Step mark={step.mark} state={cut}>
          {step.size != null ? t.progress.planned(step.size) : t.progress.planning}
        </Step>
      );
    case "researcher":
      return (
        <Step mark={step.mark} state={cut ?? researcherState(step.row, now)}>
          <span className="act-num">{step.row.index}</span>
          {step.row.question}
        </Step>
      );
    case "started":
      return (
        <Step mark={step.mark} state={t.progress.inOutputs}>
          {step.run.run === "deep_research"
            ? t.progress.deepStarted(step.run.text)
            : t.progress.factCheckStarted(step.run.text)}
        </Step>
      );
    case "write":
      return (
        <Step mark={step.mark} state={cut}>
          {step.mark === "ok" ? t.progress.written : t.progress.writing}
        </Step>
      );
  }
}

// How long a headline holds before another may replace it. Thinking streams a
// finished sentence every few hundred milliseconds, and a line that rewrites
// itself that fast reads as flicker rather than as progress. Something new
// actually starting (a search, a page, a researcher) is worth cutting in for,
// but it still gets a floor so six parallel researchers cannot strobe the row.
const DWELL_MS = 1100;
const DWELL_URGENT_MS = 350;

function useCalmLabel(label: string, urgent: boolean): string {
  const [shown, setShown] = useState(label);
  const shownAt = useRef(0);

  useEffect(() => {
    if (label === shown) return;
    const floor = urgent ? DWELL_URGENT_MS : DWELL_MS;
    const wait = Math.max(0, floor - (Date.now() - shownAt.current));
    const id = setTimeout(() => {
      shownAt.current = Date.now();
      setShown(label);
    }, wait);
    return () => clearTimeout(id);
  }, [label, shown, urgent]);

  return shown;
}

// Everything a turn did before it answered, as the one inline row a chat app
// shows: what it is doing right now, how long it has taken, and a chevron onto
// the thinking behind it and the steps it took. The model's thinking is not a
// separate disclosure, because to a reader it is not a separate thing.
export function Activity({ turn, now }: { turn: Turn; now: number }) {
  // Folded away until asked for. The row says what is happening; the thinking
  // behind it is there for whoever wants it, not pushed at everyone.
  const [open, setOpen] = useState(false);
  const p = summarize(turn.events);
  const running = turn.status === "running" || turn.status === "pending";
  const elapsed = ((turn.endedAt ?? now) - turn.startedAt) / 1000;
  const thinking = (turn.thinking ?? "").trim();

  const age = running ? heartbeatAge(turn, now) : null;
  const stale = age != null && age > STALE_AFTER;

  // While the run works, the row says what it is doing, in the most specific
  // words available. Once it has answered, it says what it cost: the work is
  // still there to inspect, but it stops competing with the answer for the eye.
  const settled = !running && turn.status === "complete";
  const head = headline(p, thinking);
  const next = stale
    ? t.progress.stale(clock(age!))
    : settled
      ? [t.progress.thoughtFor(brief(elapsed))]
          .concat(p.researchers.length > 0 ? t.progress.researched(p.researchers.length) : [])
          .join(" · ")
      : headlineText(head, p, turn, now);
  // A search starting, a page opening, a researcher taking over, or the run
  // ending: those are events. One thought giving way to the next is not.
  const urgent = !running || head.kind === "activity" || head.kind === "researcher";
  const label = useCalmLabel(next, urgent);

  const rows = steps(
    p,
    running ? null : turn.stopped ? "stopped" : turn.status === "failed" ? "failed" : "done",
  );

  return (
    <div
      className={"act" + (open ? " open" : "") + (running ? " live" : "") + (stale ? " stale" : "")}
      onClick={(e) => e.stopPropagation()}
    >
      <button type="button" className="act-bar" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {running && !stale && (
          <span className="act-dots" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
        )}
        {(stale || (!running && !settled)) && (
          <span className="act-icon" aria-hidden="true">{turn.stopped ? I.stop : I.warn}</span>
        )}
        {/* Keyed by the text, so each new stage fades in instead of swapping. */}
        <span key={label} className="act-label" aria-live="polite">{label}</span>
        {running && <span className="act-time">{clock(elapsed)}</span>}
        <span className="act-chevron" aria-hidden="true">{I.chevron}</span>
      </button>

      {open && (thinking || rows.length > 0) && (
        <div className="act-body">
          {/* The thinking first: it is the narrative, the steps are the receipt. */}
          {thinking && <div className="act-think">{thinking}</div>}
          {rows.length > 0 && (
            <ol className="act-steps">
              {rows.map((step) => (
                <StepItem
                  key={
                    step.kind === "researcher"
                      ? `r${step.row.index}`
                      : step.kind === "started"
                        ? `s${step.run.run}${step.run.text}`
                        : step.kind
                  }
                  step={step}
                  now={now}
                  stopped={!!turn.stopped}
                />
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}

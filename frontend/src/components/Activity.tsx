import { useEffect, useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import {
  headline,
  summarize,
  timeline,
  type Activity as Act,
  type Headline,
  type Mark,
  type Progress,
  type ResearcherRow,
  type Step as StepRow,
} from "../lib/progress";
import type { Turn } from "../types";

// Seconds without a single frame from the run before the row warns that it may
// be stuck. The job beats every 5 s and the stream sends a keep-alive after 15 s
// of quiet, so silence this long means nothing is on the other end.
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
  if (a.kind === "steer") return t.progress.steering;
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

// What a step says, in the feed and on the collapsed row alike.
function stepText(step: StepRow): string {
  switch (step.kind) {
    case "understanding":
      return t.progress.understanding;
    case "think":
      return step.title ?? t.progress.think;
    case "search":
      return t.progress.searchStep(step.text);
    case "read":
      return t.progress.readStep(step.domain);
    case "document":
      return t.progress.documentStep(step.text);
    case "steer":
      return t.progress.steerStep;
    case "research":
      return t.progress.researchStep(step.question);
    case "plan":
      return step.size != null ? t.progress.planned(step.size) : t.progress.planning;
    case "researcher":
      return step.row.question;
    case "started":
      return step.run.run === "deep_research"
        ? t.progress.deepStarted(step.run.text)
        : t.progress.factCheckStarted(step.run.text);
    case "write":
      return step.mark === "ok" ? t.progress.written : t.progress.writing;
  }
}

function headlineText(h: Headline, p: Progress, turn: Turn, now: number): string {
  switch (h.kind) {
    case "activity":
      return activityText(h.activity, now);
    case "researcher":
      return h.question;
    case "step":
      return stepText(h.step);
    case "stage":
      return stageText(p, turn);
  }
}

function heartbeatAge(turn: Turn, now: number): number | null {
  if (turn.heartbeatAge == null || turn.heartbeatSeenAt == null) return null;
  return turn.heartbeatAge + (now - turn.heartbeatSeenAt) / 1000;
}

const MARKS: Record<Mark, React.ReactNode> = { run: <span className="spin" />, ok: I.check, warn: I.warn, stop: I.stop };

function Step({
  mark,
  children,
  state,
  sub,
}: {
  mark: Mark;
  children: React.ReactNode;
  state?: string | null;
  sub?: boolean;
}) {
  return (
    // Prefixed modifiers: a bare "run" collides with the page-level .run class.
    <li className={"act-step act-step-" + mark + (sub ? " act-step-sub" : "")}>
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
    case "researcher":
      return (
        <Step mark={step.mark} sub={step.sub} state={cut ?? researcherState(step.row, now)}>
          <span className="act-num">{step.row.index}</span>
          {step.row.question}
        </Step>
      );
    case "started":
      return (
        <Step mark={step.mark} state={t.progress.inOutputs}>
          {stepText(step)}
        </Step>
      );
    default:
      return (
        <Step mark={step.mark} sub={step.kind === "plan" && step.sub} state={cut}>
          {stepText(step)}
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
// every step it took, in order. Its thinking shows as those steps' titles,
// never as the scratchpad itself.
export function Activity({ turn, now }: { turn: Turn; now: number }) {
  // Open while the run works, so its steps can be followed as they happen;
  // folded once it has answered, so they stop competing with the answer. A
  // reader who opens or closes it has decided, and that sticks.
  const [chosen, setChosen] = useState<boolean | null>(null);
  const p = summarize(turn.events);
  const running = turn.status === "running" || turn.status === "pending";
  const open = chosen ?? running;
  const elapsed = ((turn.endedAt ?? now) - turn.startedAt) / 1000;

  const age = running ? heartbeatAge(turn, now) : null;
  const stale = age != null && age > STALE_AFTER;

  const rows = timeline(
    turn.events,
    running ? null : turn.stopped ? "stopped" : turn.status === "failed" ? "failed" : "done",
  );
  const counted = rows.filter((r) => r.kind !== "understanding" && !("sub" in r && r.sub)).length;

  // While the run works, the row says what it is doing, in the most specific
  // words available. Once it has answered, it says what it cost: the work is
  // still there to inspect, but it stops competing with the answer for the eye.
  const settled = !running && turn.status === "complete";
  const head = headline(p, rows);
  const next = stale
    ? t.progress.stale(clock(age!))
    : settled
      ? [t.progress.thoughtFor(brief(elapsed))]
          .concat(counted > 0 ? t.progress.stepCount(counted) : [])
          .join(" · ")
      : headlineText(head, p, turn, now);
  // A step starting or the run ending is an event worth cutting in for; a
  // thought being renamed is not.
  const urgent = !running || head.kind !== "step" || head.step.kind !== "think";
  const label = useCalmLabel(next, urgent);

  return (
    <div
      className={"act" + (open ? " open" : "") + (running ? " live" : "") + (stale ? " stale" : "")}
      onClick={(e) => e.stopPropagation()}
    >
      <button type="button" className="act-bar" onClick={() => setChosen(!open)} aria-expanded={open}>
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

      {open && rows.length > 0 && (
        <div className="act-body">
          <ol className="act-steps">
            {rows.map((step, i) => (
              <StepItem key={i} step={step} now={now} stopped={!!turn.stopped} />
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

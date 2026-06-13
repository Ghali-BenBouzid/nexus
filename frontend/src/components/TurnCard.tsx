import { useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import type { Turn } from "../types";
import { AgentFeed } from "./AgentFeed";
import { Markdown } from "./Markdown";
import { NexusMark } from "./NexusLogo";

const noop = () => {};

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

type TurnCardProps = {
  turn: Turn;
  now: number;
  feedTag: string;
  inSplit: boolean;
  focused?: boolean;
  onSelect?: () => void; // split: focus this turn's report in the side panel
  onOpenReport: () => void; // open/reveal the report (switches to split in thread mode)
  onRerun: (query: string) => void;
  onConfirmPlan: (turn: Turn) => void;
  onRevisePlan: (turn: Turn, feedback: string) => void;
  onDiscardPlan: (turn: Turn) => void;
};

// One conversation turn rendered as chat: the user's query as a bubble, and the
// agent's live activity log AS the assistant's reply. The finished report is not
// shown here, it opens in the side panel (a "Report ready" card links to it).
export function TurnCard({ turn, now, feedTag, inSplit, focused, onSelect, onOpenReport, onRerun, onConfirmPlan, onRevisePlan, onDiscardPlan }: TurnCardProps) {
  const [revising, setRevising] = useState(false);
  const [feedback, setFeedback] = useState("");
  const awaitingPlan = turn.status === "awaiting_plan";
  const running = turn.status === "running" || turn.status === "pending";
  const elapsed = ((turn.endedAt ?? now) - turn.startedAt) / 1000;

  const hasReport = turn.status === "complete" && turn.outcome === "ok" && !!turn.result;
  const isEmpty = turn.status === "complete" && turn.outcome === "empty";
  const isFailed = !turn.stopped && (turn.status === "failed" || turn.outcome === "failed");

  // While the plan awaits confirmation the proposed sub-questions live only in the
  // confirm card below; suppress the duplicate "plan" feed event until the user
  // acts, after which it rejoins the timeline like any other event.
  const feedEvents = awaitingPlan ? turn.events.filter((e) => e.kind !== "plan") : turn.events;
  const hasActivity = feedEvents.length > 0;

  return (
    <div className={"msg-turn" + (focused && inSplit ? " focused" : "")} onClick={inSplit ? onSelect : undefined}>
      <div className="msg-row user">
        <div className="bubble-user">{turn.query}</div>
      </div>

      <div className="msg-row assistant">
        <div className="assistant-reply">
          <div className="reply-agent"><span className="reply-mark"><NexusMark size={18} /></span>{t.turn.brand}</div>

          {turn.reply != null && (
            <div className="reply-text">
              <Markdown text={turn.reply} onCite={noop} activeCite={null} />
            </div>
          )}

          {turn.reply == null && running && !hasActivity && (
            <div className="reply-thinking">
              <span className="spin" />{t.turn.planning}
            </div>
          )}

          {hasActivity && (
            <div className="activity-reply">
              <AgentFeed events={feedEvents} status={turn.status} compact tag={feedTag} />
            </div>
          )}

          {/* The plan-confirmation prompt sits at the bottom of the timeline, like a
              new message, and is the only place the proposed sub-questions appear
              until the user acts. */}
          {awaitingPlan && turn.plan && (
            <div className="plan-confirm" onClick={(e) => e.stopPropagation()}>
              <div className="plan-head">{t.turn.planTitle}</div>
              <ol className="plan-list">
                {turn.plan.map((q, i) => <li key={i}>{q}</li>)}
              </ol>
              {!revising ? (
                <div className="plan-actions">
                  <button className="btn btn-primary" onClick={() => onConfirmPlan(turn)}>{t.turn.confirmPlan}</button>
                  <button className="btn btn-ghost" onClick={() => setRevising(true)}>{t.turn.revisePlan}</button>
                  <button className="btn btn-ghost plan-discard" onClick={() => onDiscardPlan(turn)}>{t.turn.discardPlan}</button>
                </div>
              ) : (
                <div className="plan-revise">
                  <textarea
                    className="plan-feedback"
                    value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                    placeholder={t.turn.revisePlaceholder}
                    rows={2}
                  />
                  <div className="plan-actions">
                    <button className="btn btn-primary" onClick={() => { onRevisePlan(turn, feedback); setRevising(false); setFeedback(""); }}>{t.turn.sendRevision}</button>
                    <button className="btn btn-ghost" onClick={() => setRevising(false)}>{t.turn.cancelRevision}</button>
                  </div>
                </div>
              )}
            </div>
          )}

          {turn.reply == null && !awaitingPlan && (running || elapsed > 0.2) && (
            <div className="reply-status">
              {running ? t.turn.researching : turn.stopped ? t.turn.stopped : t.turn.done} · {fmt(elapsed)}
            </div>
          )}

          {hasReport && (
            <button className={"report-ready" + (inSplit && focused ? " active" : "")} onClick={(e) => { e.stopPropagation(); onOpenReport(); }}>
              <span className="rr-ic">{I.doc}</span>
              <span className="rr-main">
                <span className="rr-title">{t.turn.reportReady}</span>
                <span className="rr-sub">
                  {t.count.sources(turn.result!.sources.length)}
                  {turn.result!.gaps.length > 0 ? ` · ${t.count.gaps(turn.result!.gaps.length)}` : ""} ·{" "}
                  {inSplit ? t.turn.viewInPanel : t.turn.openReport}
                </span>
              </span>
              <span className="rr-arrow">→</span>
            </button>
          )}

          {isEmpty && (
            <div className="reply-note">
              {t.turn.emptyNote}
              <button className="linkish" onClick={() => onRerun(turn.query)}>{t.turn.tryRewording}</button>
            </div>
          )}
          {turn.stopped && (
            <div className="reply-note">
              {t.turn.stoppedNote}
              <button className="linkish" onClick={() => onRerun(turn.query)}>{t.turn.rerun}</button>
            </div>
          )}
          {isFailed && (
            <div className="reply-error">
              <div className="re-title">{t.turn.runFailed}</div>
              <div className="re-msg">{turn.error || t.turn.defaultError}</div>
              <button className="linkish" onClick={() => onRerun(turn.query)}>{t.turn.tryAgain}</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

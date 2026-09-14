import { useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import type { Turn } from "../types";
import { Markdown } from "./Markdown";
import { NexusMark } from "./NexusLogo";
import { ProgressBar } from "./ProgressBar";

const noop = () => {};

type TurnCardProps = {
  turn: Turn;
  now: number;
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
// run's progress bar AS the assistant's reply. The finished report is not shown
// here, it opens in the side panel (a "Report ready" card links to it).
export function TurnCard({ turn, now, inSplit, focused, onSelect, onOpenReport, onRerun, onConfirmPlan, onRevisePlan, onDiscardPlan }: TurnCardProps) {
  const [revising, setRevising] = useState(false);
  const [feedback, setFeedback] = useState("");
  const awaitingPlan = turn.status === "awaiting_plan";
  const running = turn.status === "running" || turn.status === "pending";

  const hasReport = turn.status === "complete" && turn.outcome === "ok" && !!turn.result;
  const isEmpty = turn.status === "complete" && turn.outcome === "empty";
  const isFailed = !turn.stopped && (turn.status === "failed" || turn.outcome === "failed");
  const hasActivity = turn.events.length > 0;

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

          {turn.reply == null && (running || hasActivity) && <ProgressBar turn={turn} now={now} />}

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

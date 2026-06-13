import { I } from "../icons";
import { t } from "../lib/i18n";
import type { Turn } from "../types";
import { AgentFeed } from "./AgentFeed";
import { NexusMark } from "./NexusLogo";

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
};

// One conversation turn rendered as chat: the user's query as a bubble, and the
// agent's live activity log AS the assistant's reply. The finished report is not
// shown here, it opens in the side panel (a "Report ready" card links to it).
export function TurnCard({ turn, now, feedTag, inSplit, focused, onSelect, onOpenReport, onRerun }: TurnCardProps) {
  const running = turn.status === "running" || turn.status === "pending";
  const elapsed = ((turn.endedAt ?? now) - turn.startedAt) / 1000;

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

          {running && !hasActivity && (
            <div className="reply-thinking">
              <span className="spin" />{t.turn.planning}
            </div>
          )}

          {hasActivity && (
            <div className="activity-reply">
              <AgentFeed events={turn.events} status={turn.status} compact tag={feedTag} />
            </div>
          )}

          {(running || elapsed > 0.2) && (
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

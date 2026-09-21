import { useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import type { Turn } from "../types";
import { Markdown } from "./Markdown";
import { Activity } from "./Activity";
import { FileTile } from "./FileTile";
import { SourceList, useScrollToCite } from "./Sources";

type TurnCardProps = {
  turn: Turn;
  now: number;
  inSplit: boolean;
  focused?: boolean;
  onSelect?: () => void; // split: focus this turn in the side panel
  onRerun: (query: string) => void;
};

// One conversation turn rendered as chat: the user's question, the run's live
// progress while it works, and then the answer itself. A turn produces an answer,
// not a document: the reports in the Outputs panel come from background runs.
export function TurnCard({
  turn,
  now,
  inSplit,
  focused,
  onSelect,
  onRerun,
}: TurnCardProps) {
  const [showSources, setShowSources] = useState(false);
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const [citeSeq, setCiteSeq] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const running = turn.status === "running" || turn.status === "pending";

  // The stored reply once there is one, what has streamed in until then. The
  // stored one always wins: a retried call can leave streamed text behind that
  // the model never actually sent.
  const answer = turn.reply ?? turn.streamed ?? "";
  const streaming = running && !turn.reply && !!turn.streamed;
  const thinking = (turn.thinking ?? "").trim();
  const sources = turn.result?.sources ?? [];
  const isEmpty = turn.status === "complete" && !answer.trim() && sources.length === 0;
  const isFailed = !turn.stopped && (turn.status === "failed" || turn.outcome === "failed");
  const hasActivity = turn.events.length > 0;

  // Clicking a [n] in the answer opens the source list, highlights that source
  // and moves the view to it. The seq is what lets the same citation be clicked
  // twice and still bring its source back after scrolling away.
  const onCite = (n: number) => {
    setShowSources(true);
    setActiveCite(n);
    setCiteSeq((k) => k + 1);
  };
  useScrollToCite(listRef, showSources ? activeCite : null, citeSeq);

  return (
    <div
      className={"msg-turn" + (focused && inSplit ? " focused" : "")}
      onClick={inSplit ? onSelect : undefined}
    >
      {/* The files sent with this message, above the words they came with and
          outside the bubble: they were attached to the message, not said in it,
          and the thread should read the way the composer looked when it was sent. */}
      {(turn.attachments?.length ?? 0) > 0 && (
        <div className="msg-row user">
          <div className="bubble-files">
            {turn.attachments!.map((doc) => (
              <FileTile key={doc.id} name={doc.filename} bytes={doc.sizeBytes} />
            ))}
          </div>
        </div>
      )}
      <div className="msg-row user">
        <div className="bubble-user">{turn.query}</div>
      </div>

      <div className="msg-row assistant">
        <div className="assistant-reply">
          {/* The live feed stays above the answer once it lands, so the work is
              still inspectable after the fact. */}
          {(running || hasActivity || thinking) && <Activity turn={turn} now={now} />}

          {answer.trim() && (
            <div className={"reply-text" + (streaming ? " streaming" : "")}>
              <Markdown text={answer} onCite={onCite} activeCite={activeCite} />
            </div>
          )}

          {sources.length > 0 && (
            <div className="reply-sources" onClick={(e) => e.stopPropagation()}>
              <button
                type="button"
                className="src-toggle"
                onClick={() => setShowSources((open) => !open)}
                aria-expanded={showSources}
              >
                <span className="src-chev" aria-hidden="true">{I.chevron}</span>
                <span className="src-label">{t.artifact.sourcesHead}</span>
                <span className="src-cnt">{t.artifact.cited(sources.length)}</span>
              </button>
              {showSources && (
                <SourceList
                  sources={sources}
                  activeCite={activeCite}
                  onPick={onCite}
                  listRef={listRef}
                />
              )}
            </div>
          )}

          {isEmpty && (
            <div className="reply-note">
              {t.turn.emptyNote}
              <button className="linkish" onClick={() => onRerun(turn.query)}>
                {t.turn.tryRewording}
              </button>
            </div>
          )}
          {turn.stopped && (
            <div className="reply-note">
              {t.turn.stoppedNote}
              <button className="linkish" onClick={() => onRerun(turn.query)}>
                {t.turn.rerun}
              </button>
            </div>
          )}
          {isFailed && (
            <div className="reply-error">
              <div className="re-title">{t.turn.runFailed}</div>
              <div className="re-msg">{turn.error || t.turn.defaultError}</div>
              <button className="linkish" onClick={() => onRerun(turn.query)}>
                {t.turn.tryAgain}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}


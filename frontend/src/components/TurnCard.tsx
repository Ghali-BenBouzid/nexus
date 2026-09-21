import { useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import type { Turn } from "../types";
import { Markdown } from "./Markdown";
import { ProgressBar } from "./ProgressBar";
import { SourceList } from "./Sources";

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

  // Clicking a [n] in the answer opens the source list and highlights that source.
  const onCite = (n: number) => {
    setShowSources(true);
    setActiveCite(n);
  };

  return (
    <div
      className={"msg-turn" + (focused && inSplit ? " focused" : "")}
      onClick={inSplit ? onSelect : undefined}
    >
      <div className="msg-row user">
        <div className="bubble-user">
          {/* The files sent with this message, above the words they came with,
              so the thread reads the way it looked when it was sent. */}
          {(turn.attachments?.length ?? 0) > 0 && (
            <div className="bubble-files">
              {turn.attachments!.map((doc) => (
                <span key={doc.id} className="bubble-file">
                  {I.doc}
                  {doc.filename}
                </span>
              ))}
            </div>
          )}
          {turn.query}
        </div>
      </div>

      <div className="msg-row assistant">
        <div className="assistant-reply">
          {/* The live feed stays above the answer once it lands, so the work is
              still inspectable after the fact. */}
          {(running || hasActivity) && <ProgressBar turn={turn} now={now} />}

          {/* The model's thinking, while it is the only thing happening. It is
              a scratchpad and often blunt, so it reads as provisional and is
              folded away by default once the answer starts arriving. */}
          {thinking && (
            <Thinking text={thinking} live={running && !answer.trim()} />
          )}

          {answer.trim() && (
            <div className={"reply-text" + (streaming ? " streaming" : "")}>
              <Markdown text={answer} onCite={onCite} activeCite={activeCite} />
            </div>
          )}

          {sources.length > 0 && (
            <div className="reply-sources" onClick={(e) => e.stopPropagation()}>
              <button
                className={"sources-toggle" + (showSources ? " open" : "")}
                onClick={() => setShowSources((open) => !open)}
                aria-expanded={showSources}
              >
                {I.link}
                {t.turn.sourcesUsed(sources.length)}
                <span className="sources-chevron">{showSources ? "−" : "+"}</span>
              </button>
              {showSources && (
                <SourceList
                  sources={sources}
                  activeCite={activeCite}
                  onPick={setActiveCite}
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

// The model's thinking. It opens itself while it is the only thing happening,
// because that stretch is most of the wait, and closes itself once the answer
// starts. Either way one click always wins: the moment the reader touches it,
// their choice is the one that holds for the rest of the turn.
function Thinking({ text, live }: { text: string; live: boolean }) {
  const [choice, setChoice] = useState<boolean | null>(null);
  const shown = choice ?? live;
  return (
    <div className="thinking" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        className={"thinking-toggle" + (shown ? " open" : "")}
        onClick={() => setChoice(!shown)}
        aria-expanded={shown}
      >
        <span className="thinking-chevron" aria-hidden="true">
          {I.chevron}
        </span>
        {live ? t.turn.thinkingLive : t.turn.thinkingDone}
      </button>
      {shown && <div className="thinking-text">{text}</div>}
    </div>
  );
}

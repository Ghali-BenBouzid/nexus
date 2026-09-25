import { Fragment, useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import { liveSources, rounds, timeline } from "../lib/progress";
import { stored } from "../lib/uploads";
import type { Doc, Turn } from "../types";
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
  onPreview?: (doc: Doc) => void;
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
  onPreview,
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
  const sources = turn.result?.sources ?? [];
  // A turn that only asked has no words of its own, and is not empty: its
  // questions are in the panel, then in the answer card below it.
  const isEmpty =
    turn.status === "complete" && !answer.trim() && sources.length === 0 && !turn.ask?.length;
  const isFailed = !turn.stopped && (turn.status === "failed" || turn.outcome === "failed");
  const hasActivity = turn.events.length > 0;
  // Running a message again sends its words again. A message that was only a
  // file has none, and one stopped before it was sent lost its files with it:
  // offering to run either again only led to "attach the document first".
  const canRerun = !turn.unsent && !!turn.query.trim();

  // The reply as it was written: a round of work, the part of the reply that
  // came after it, and so on down to the answer. The stored parts line up with
  // the rounds once the turn is done, and stand in for what each round said. A
  // turn that failed has no parts, only what it said before it failed; one
  // whose parts do not line up reads as a single round and a single reply.
  let rs = rounds(turn.events);
  const aligned = !turn.parts || turn.parts.length === rs.length;
  if (!aligned) rs = [{ events: turn.events, said: null, at: null }];
  const parts = aligned ? turn.parts : undefined;
  // Until the reply is stored, it cites by the numbers it was written with,
  // and the sources those numbers name have been arriving along with it. A
  // turn that failed never got its stored reply, so it keeps them too.
  const cites = turn.parts || turn.reply ? sources : liveSources(turn.events);
  const lastRound = rs.length - 1;

  // Clicking a [n] in the answer opens the source list, highlights that source
  // and moves the view to it. The seq is what lets the same citation be clicked
  // twice and still bring its source back after scrolling away.
  const onCite = (n: number) => {
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
              <FileTile
                key={doc.id}
                name={doc.filename}
                bytes={doc.sizeBytes}
                state={doc.state}
                error={doc.error}
                onOpen={onPreview && stored(doc) ? () => onPreview(doc) : undefined}
              />
            ))}
          </div>
        </div>
      )}
      {/* A message that was only a file has no words to put in a bubble: the
          file above is the whole message, the way it is anywhere else. */}
      {/* Answers from the question panel read as what they are: each question
          and what was chosen, not the plain text the supervisor was sent. */}
      {turn.answers?.length ? (
        <div className="msg-row user">
          <dl className="bubble-answers">
            {turn.answers.map((pair, i) => (
              <div className="ba-pair" key={i}>
                <dt>{pair.question}</dt>
                <dd className={pair.answer == null ? "skipped" : undefined}>
                  {pair.answer ?? t.ask.skipped}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : (
        turn.query.trim() && (
          <div className="msg-row user">
            <div className="bubble-user">{turn.query}</div>
          </div>
        )
      )}

      <div className="msg-row assistant">
        <div className="assistant-reply">
          {/* Each round of work stays above the words that followed it once
              they land, so the work is still inspectable after the fact. */}
          {rs.map((round, i) => {
            const last = i === lastRound;
            const text = last ? (parts?.[i] ?? answer) : (parts?.[i] ?? round.said ?? "");
            // With one round, the row is there from the start, as the sign the
            // turn is working. Between parts, a round shows once it has done
            // something: words straight after words need nothing between them.
            const chip =
              rs.length === 1
                ? running || hasActivity
                : timeline(round.events, "done").some((s) => s.kind !== "understanding");
            return (
              <Fragment key={i}>
                {chip && (
                  <Activity
                    turn={turn}
                    events={round.events}
                    from={i === 0 ? turn.startedAt : (rs[i - 1].at ?? turn.startedAt)}
                    to={last ? null : round.at}
                    last={last}
                    now={now}
                  />
                )}
                {text.trim() && (
                  <div className={"reply-text" + (last && streaming ? " streaming" : "")}>
                    <Markdown text={text} onCite={onCite} sources={cites} />
                  </div>
                )}
              </Fragment>
            );
          })}

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
              {canRerun && (
                <button className="linkish" onClick={() => onRerun(turn.query)}>
                  {t.turn.tryRewording}
                </button>
              )}
            </div>
          )}
          {turn.stopped && (
            <div className="reply-note">
              {t.turn.stoppedNote}
              {canRerun && (
                <button className="linkish" onClick={() => onRerun(turn.query)}>
                  {t.turn.rerun}
                </button>
              )}
            </div>
          )}
          {isFailed && (
            <div className="reply-error">
              <div className="re-title">{t.turn.runFailed}</div>
              <div className="re-msg">{turn.error || t.turn.defaultError}</div>
              {canRerun && (
                <button className="linkish" onClick={() => onRerun(turn.query)}>
                  {t.turn.tryAgain}
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}


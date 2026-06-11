import { Fragment, useRef, useState } from "react";

import { I } from "../icons";
import type { Outcome, Result, Status, TimelineEvent } from "../types";
import { AgentFeed } from "./AgentFeed";
import { Markdown } from "./Markdown";
import { GapsCard, SourcesPanel, StateCard } from "./SourcesPanel";

type RunScreenProps = {
  query: string;
  status: Status;
  events: TimelineEvent[];
  result: Result | null;
  outcome: Outcome;
  error: string | null;
  elapsed: number;
  feedTag: string;
  onBack: () => void;
  onNew: () => void;
};

export function RunScreen({
  query,
  status,
  events,
  result,
  outcome,
  error,
  elapsed,
  feedTag,
  onBack,
  onNew,
}: RunScreenProps) {
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const [showActivity, setShowActivity] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const onCite = (n: number) => {
    setActiveCite(n);
    const c = listRef.current;
    if (c) {
      const el = c.querySelector<HTMLElement>(`[data-n="${n}"]`);
      if (el) c.scrollTop += el.getBoundingClientRect().top - c.getBoundingClientRect().top - 8;
    }
  };

  const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const statusLabel = status === "complete" ? "complete" : status === "failed" ? "failed" : "running";

  const isComplete = status === "complete" && outcome === "ok";
  const isFailed = status === "failed" || outcome === "failed";
  const isEmpty = status === "complete" && outcome === "empty";

  return (
    <main className="run">
      <div className="wrap">
        <div className="run-head">
          <button className="run-back" onClick={onBack} title="Back" aria-label="Back">{I.arrowLeft}</button>
          <div className="run-q">
            <div className="eyebrow">Research query</div>
            <h1>{query}</h1>
          </div>
          <div className={"run-status " + statusLabel}>
            <span className="sd" />{statusLabel}<span className="elapsed">· {fmt(elapsed)}</span>
          </div>
        </div>

        {(status === "running" || status === "pending") && (
          <AgentFeed events={events} status={status} tag={feedTag} />
        )}

        {isComplete && result && (
          <Fragment>
            <button className="btn btn-ghost" style={{ marginBottom: 8 }} onClick={() => setShowActivity((s) => !s)}>
              {I.feed}{showActivity ? "Hide" : "Show"} agent activity · {events.length} steps
            </button>
            {showActivity && (
              <div style={{ marginBottom: 18 }}>
                <AgentFeed events={events} status="complete" compact tag={feedTag} />
              </div>
            )}

            <div className="report-grid">
              <div>
                <article className="report">
                  <Markdown text={result.report} onCite={onCite} activeCite={activeCite} />
                  <div className="report-foot">
                    <button className="btn btn-primary" onClick={onNew}>New research</button>
                    <button className="btn btn-ghost" onClick={() => navigator.clipboard?.writeText(result.report)}>Copy report</button>
                    <button className="btn btn-ghost" onClick={onNew}>Re-run</button>
                  </div>
                </article>
              </div>
              <div className="src-panel-col" style={{ display: "grid", gap: 16 }}>
                <SourcesPanel result={result} activeCite={activeCite} onPick={onCite} listRef={listRef} />
                <GapsCard gaps={result.gaps} />
              </div>
            </div>
          </Fragment>
        )}

        {isEmpty && <StateCard kind="empty" onRetry={onBack} />}
        {isFailed && <StateCard kind="failed" error={error} onRetry={onBack} />}
      </div>
    </main>
  );
}

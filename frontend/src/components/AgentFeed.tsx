import { Fragment, useEffect, useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import type { Status, TimelineEvent } from "../types";

function FeedEvent({ e, isLast, running }: { e: TimelineEvent; isLast: boolean; running: boolean }) {
  const liveCaret = running && isLast;
  const Caret = liveCaret ? <span className="caret" /> : null;

  if (e.kind === "planner") {
    return (
      <div className="ev">
        <div className="ev-rail"><span className={"ev-dot accent" + (liveCaret ? " pulse" : "")} /><span className="ev-line" /></div>
        <div className="ev-body">
          <div className="ev-title"><span className="role">{t.feed.planner}</span>{e.title}{Caret}</div>
          <div className="ev-sub">{e.sub}</div>
        </div>
      </div>
    );
  }
  if (e.kind === "plan") {
    return (
      <div className="ev">
        <div className="ev-rail"><span className="ev-dot accent" /><span className="ev-line" /></div>
        <div className="ev-body">
          <div className="ev-title">{t.feed.plan(e.items.length)}</div>
          <div className="plan-card">
            {e.items.map((q, i) => (
              <div className="pq" key={i}><span className="pn">{i + 1}</span><span>{q}</span></div>
            ))}
          </div>
        </div>
      </div>
    );
  }
  if (e.kind === "researcher" && e.state === "start") {
    return (
      <div className="ev">
        <div className="ev-rail"><span className={"ev-dot accent" + (liveCaret ? " pulse" : "")} /><span className="ev-line" /></div>
        <div className="ev-body">
          <div className="ev-title"><span className="role">{t.feed.researcher} {e.index}/{e.total}</span>{e.question}{Caret}</div>
        </div>
      </div>
    );
  }
  if (e.kind === "tool") {
    const isErr = e.action === "error";
    return (
      <div className={"ev tool" + (isErr ? " err" : "")}>
        <div className="ev-rail"><span className={"ev-dot " + (isErr ? "warn" : "")} /><span className="ev-line" /></div>
        <div className="ev-body">
          <div className="tool-line">
            {e.action === "search" && (
              <Fragment><span className="tk">{t.feed.search}</span><span>"{e.text}"</span></Fragment>
            )}
            {e.action === "read" && (
              <Fragment><span className="tk">{t.feed.read}</span><span className="dom">{e.domain}</span><span>· {e.title}</span></Fragment>
            )}
            {isErr && (
              <Fragment><span style={{ display: "inline-flex", width: 14, height: 14 }}>{I.warn}</span><span>{e.text}</span></Fragment>
            )}
            {liveCaret && Caret}
          </div>
        </div>
      </div>
    );
  }
  if (e.kind === "researcher" && e.state === "done") {
    return (
      <div className="ev">
        <div className="ev-rail"><span className="ev-dot ok" /><span className="ev-line" /></div>
        <div className="ev-body">
          <div className="ev-title" style={{ fontWeight: 500 }}>{t.feed.researcherDone(e.index)}</div>
          <div className="ev-sub">{e.sub}</div>
        </div>
      </div>
    );
  }
  if (e.kind === "writer") {
    const done = e.state === "done";
    return (
      <div className="ev">
        <div className="ev-rail"><span className={"ev-dot " + (done ? "ok" : "accent") + (liveCaret ? " pulse" : "")} />{!isLast && <span className="ev-line" />}</div>
        <div className="ev-body">
          <div className="ev-title"><span className="role">{t.feed.writer}</span>{e.title}{Caret}</div>
          <div className="ev-sub">{e.sub}</div>
        </div>
      </div>
    );
  }
  return null;
}

type AgentFeedProps = {
  events: TimelineEvent[];
  status: Status;
  compact?: boolean;
  tag: string;
};

export function AgentFeed({ events, status, compact, tag }: AgentFeedProps) {
  const ref = useRef<HTMLDivElement>(null);
  // The timeline is open by default (this is a demo of the live workflow) but can
  // be collapsed to keep a long thread tidy.
  const [open, setOpen] = useState(true);
  useEffect(() => {
    if (ref.current && !compact && open) ref.current.scrollTop = ref.current.scrollHeight;
  }, [events, compact, open]);
  const running = status === "running" || status === "pending";
  return (
    <div className="feed-shell">
      <button
        type="button"
        className={"feed-bar" + (open ? "" : " collapsed")}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="feed-bar-main">
          <span className="feed-chevron">{I.arrowDown}</span>
          <span>{t.feed.activity}</span>
          {!open && events.length > 0 && (
            <span className="feed-count">{t.feed.steps(events.length)}</span>
          )}
        </span>
        {!compact && <span className="demo-tag"><span className="pip" />{tag}</span>}
      </button>
      {open && (
        <div className="feed" ref={ref} style={compact ? { maxHeight: "none" } : undefined}>
          {events.map((e, i) => (
            <FeedEvent key={e.id} e={e} isLast={i === events.length - 1} running={running} />
          ))}
        </div>
      )}
    </div>
  );
}

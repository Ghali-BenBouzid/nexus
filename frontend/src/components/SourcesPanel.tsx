import { useState, type RefObject } from "react";

import { I } from "../icons";
import type { Result } from "../types";

type SourcesPanelProps = {
  result: Result;
  activeCite: number | null;
  onPick: (n: number) => void;
  listRef: RefObject<HTMLDivElement>;
};

const stripScheme = (url: string) => url.replace(/^https?:\/\//, "");

export function SourcesPanel({ result, activeCite, onPick, listRef }: SourcesPanelProps) {
  const [prov, setProv] = useState(false);
  return (
    <div className="src-panel">
      <div className="src-card">
        <div className="src-card-head">
          <h4>Sources</h4>
          <span className="cnt">
            {result.sources.length} cited{prov ? ` · ${result.consulted.length} consulted` : ""}
          </span>
        </div>
        <div className="src-list" ref={listRef}>
          {result.sources.map((s, i) => {
            const n = i + 1;
            return (
              <a
                key={n}
                className={"src-item" + (activeCite === n ? " active" : "")}
                data-n={n}
                href={s.url}
                target="_blank"
                rel="noreferrer"
                onClick={() => onPick(n)}
              >
                <span className="sn">{n}</span>
                <div>
                  <div className="st">{s.title}</div>
                  <div className="su">{stripScheme(s.url)}</div>
                </div>
              </a>
            );
          })}
          {prov &&
            result.consulted.map((s, i) => (
              <a key={"c" + i} className="src-item consulted" href={s.url} target="_blank" rel="noreferrer">
                <span className="sn">·</span>
                <div>
                  <div className="st">{s.title}</div>
                  <div className="su">{stripScheme(s.url)}</div>
                </div>
              </a>
            ))}
        </div>
        <div className="prov-toggle" onClick={() => setProv((p) => !p)}>
          <span className={"switch" + (prov ? " on" : "")} />
          Show everything consulted
        </div>
      </div>
    </div>
  );
}

export function GapsCard({ gaps }: { gaps: string[] }) {
  if (!gaps || !gaps.length) return null;
  return (
    <div className="gaps-card">
      <h4>
        <span style={{ display: "inline-flex", width: 17, height: 17 }}>{I.warn}</span>
        Gaps · {gaps.length} unanswered
      </h4>
      <ul>
        {gaps.map((g, i) => (
          <li key={i}>{g}</li>
        ))}
      </ul>
    </div>
  );
}

type StateCardProps = { kind: "empty" | "failed"; error?: string | null; onRetry: () => void };

export function StateCard({ kind, error, onRetry }: StateCardProps) {
  if (kind === "failed") {
    return (
      <div className="state-card failed">
        <div className="sic">{I.warn}</div>
        <h3>This run failed</h3>
        <p>{error || "A system error stopped the research before it finished. No report was produced."}</p>
        <button className="btn btn-primary" onClick={onRetry}>Try again</button>
      </div>
    );
  }
  return (
    <div className="state-card empty">
      <div className="sic">{I.empty}</div>
      <h3>No sources found</h3>
      <p>The agents ran successfully but couldn't find evidence to answer this question. That's a valid result. Try rewording it, or narrowing the scope.</p>
      <button className="btn btn-primary" onClick={onRetry}>Edit & retry</button>
    </div>
  );
}

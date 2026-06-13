import { useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import type { Result, Turn } from "../types";
import { Markdown } from "./Markdown";

const stripScheme = (url: string) => url.replace(/^https?:\/\//, "").replace(/^www\./, "");

// The redesigned sources block: a calm, numbered list that reads as part of the
// report rather than a panel bolted on. Citation numbers double as anchors the
// in-report [n] markers scroll to and highlight.
function Sources({
  result,
  activeCite,
  onPick,
  listRef,
}: {
  result: Result;
  activeCite: number | null;
  onPick: (n: number) => void;
  listRef: React.RefObject<HTMLDivElement>;
}) {
  const [prov, setProv] = useState(false);
  if (result.sources.length === 0 && result.consulted.length === 0) return null;

  return (
    <section className="art-sources">
      <div className="art-sources-head">
        <h3>{t.artifact.sourcesHead}</h3>
        <span className="art-sources-cnt">{t.artifact.cited(result.sources.length)}</span>
      </div>
      <div className="art-src-list" ref={listRef}>
        {result.sources.map((s, i) => {
          const n = i + 1;
          return (
            <a
              key={n}
              className={"art-src" + (activeCite === n ? " active" : "")}
              data-n={n}
              href={s.url}
              target="_blank"
              rel="noreferrer"
              onClick={() => onPick(n)}
            >
              <span className="art-src-n">{n}</span>
              <span className="art-src-main">
                <span className="art-src-title">{s.title}</span>
                <span className="art-src-url">{stripScheme(s.url)}{I.ext}</span>
              </span>
            </a>
          );
        })}
        {prov &&
          result.consulted.map((s, i) => (
            <a key={"c" + i} className="art-src consulted" href={s.url} target="_blank" rel="noreferrer">
              <span className="art-src-n">·</span>
              <span className="art-src-main">
                <span className="art-src-title">{s.title}</span>
                <span className="art-src-url">{stripScheme(s.url)}</span>
              </span>
            </a>
          ))}
      </div>
      {result.consulted.length > 0 && (
        <button className="art-prov" onClick={() => setProv((p) => !p)}>
          <span className={"switch" + (prov ? " on" : "")} />
          {t.artifact.showConsulted(result.consulted.length)}
        </button>
      )}
    </section>
  );
}

type ArtifactProps = {
  turn: Turn;
  onRefresh: (turn: Turn) => void;
  onBack?: () => void; // return to the artifact list (reader view)
  onClose?: () => void; // collapse the whole panel
};

// The output panel: the rendered report and its sources, presented as a single
// coherent document (the chat thread carries the live agent activity instead).
export function Artifact({ turn, onRefresh, onBack, onClose }: ArtifactProps) {
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const result = turn.result;

  const onCite = (n: number) => {
    setActiveCite(n);
    const c = listRef.current;
    if (c) {
      const el = c.querySelector<HTMLElement>(`[data-n="${n}"]`);
      if (el) c.scrollTop += el.getBoundingClientRect().top - c.getBoundingClientRect().top - 8;
    }
  };

  if (!result || (!result.report.trim() && result.sources.length === 0)) {
    const msg = turn.status === "failed"
      ? t.artifact.emptyFailed
      : turn.status === "complete"
        ? t.artifact.emptyNoCite
        : t.artifact.emptyPending;
    if (!onBack && !onClose) return <div className="art-empty">{msg}</div>;
    return (
      <div className="artifact">
        <div className="art-head">
          <div className="art-head-title">
            {onBack && (
              <button className="icon-btn" title={t.artifact.back} onClick={onBack}>{I.arrowLeft}</button>
            )}
            {I.doc}<span>{t.artifact.report}</span>
          </div>
          {onClose && (
            <div className="art-head-actions">
              <button className="icon-btn" title={t.artifact.closePanel} onClick={onClose}>{I.arrowRight}</button>
            </div>
          )}
        </div>
        <div className="art-empty">{msg}</div>
      </div>
    );
  }

  return (
    <div className="artifact">
      <div className="art-head">
        <div className="art-head-title">
          {onBack && (
            <button className="icon-btn" title={t.artifact.back} onClick={onBack}>{I.arrowLeft}</button>
          )}
          {I.doc}<span>{t.artifact.report}</span>
        </div>
        <div className="art-head-actions">
          <button className="icon-btn" title={t.artifact.copy} onClick={() => navigator.clipboard?.writeText(result.report)}>
            {I.copy}
          </button>
          <button className="icon-btn" title={t.artifact.refresh} onClick={() => onRefresh(turn)}>
            {I.refresh}
          </button>
          {onClose && (
            <button className="icon-btn" title={t.artifact.closePanel} onClick={onClose}>{I.arrowRight}</button>
          )}
        </div>
      </div>
      <div className="art-body">
        <div className="art-q">{turn.query}</div>
        <article className="report">
          <Markdown text={result.report} onCite={onCite} activeCite={activeCite} />
        </article>
        <Sources result={result} activeCite={activeCite} onPick={onCite} listRef={listRef} />
        {result.gaps.length > 0 && (
          <section className="art-gaps">
            <h3>{I.warn}{t.artifact.unanswered(result.gaps.length)}</h3>
            <ul>
              {result.gaps.map((g, i) => (
                <li key={i}>{g}</li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}

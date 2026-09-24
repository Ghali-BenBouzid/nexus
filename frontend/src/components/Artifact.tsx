import { useEffect, useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import type { Result, Status } from "../types";
import { domainOf } from "../lib/favicon";
import { Favicon } from "./Favicon";
import { Markdown } from "./Markdown";
import { useScrollToCite } from "./Sources";

const stripScheme = (url: string) => url.replace(/^https?:\/\//, "").replace(/^www\./, "");

// The sources behind a report. Folded away by default: the report is what the
// reader came for, and a citation opens this on its own when one is clicked.
// A flat, numbered list rather than a stack of cards, so it reads as the back
// matter of a document instead of as a separate widget.
function Sources({
  result,
  activeCite,
  onPick,
  open,
  onToggle,
  listRef,
}: {
  result: Result;
  activeCite: number | null;
  onPick: (n: number) => void;
  open: boolean;
  onToggle: () => void;
  listRef: React.RefObject<HTMLDivElement>;
}) {
  // Everything the run opened, not just what survived into the report.
  const [all, setAll] = useState(false);
  const consulted = result.consulted.length;
  const total = result.sources.length + consulted;
  if (result.sources.length === 0 && consulted === 0) return null;

  return (
    <section className={"art-sources" + (open ? " open" : "")}>
      <div className="art-sources-head">
        <button type="button" className="src-toggle" onClick={onToggle} aria-expanded={open}>
          <span className="src-chev" aria-hidden="true">{I.chevron}</span>
          <span className="src-label">{t.artifact.sourcesHead}</span>
          <span className="src-cnt">{t.artifact.cited(result.sources.length)}</span>
        </button>
        {/* The scope control sits in the header, so widening the list never
            moves the control that widened it. */}
        {open && consulted > 0 && (
          <button type="button" className="art-scope" onClick={() => setAll((a) => !a)}>
            {all ? t.artifact.onlyCited(result.sources.length) : t.artifact.allConsulted(total)}
          </button>
        )}
      </div>

      {open && (
        <div className="src-list" ref={listRef}>
          {result.sources.map((s, i) => {
            const n = i + 1;
            return (
              <a
                key={n}
                className={"src-row" + (activeCite === n ? " active" : "")}
                data-n={n}
                href={s.url}
                target="_blank"
                rel="noreferrer"
                onClick={() => onPick(n)}
              >
                <span className="src-n">{n}</span>
                <span className="src-main">
                  <span className="src-where">
                    <Favicon url={s.url} size={14} />
                    {domainOf(s.url)}
                  </span>
                  <span className="src-title">{s.title}</span>
                  <span className="src-url">{stripScheme(s.url)}{I.ext}</span>
                </span>
              </a>
            );
          })}
          {all &&
            result.consulted.map((s, i) => (
              <a key={"c" + i} className="src-row consulted" href={s.url} target="_blank" rel="noreferrer">
                <span className="src-n" aria-hidden="true">·</span>
                <span className="src-main">
                  <span className="src-where">
                    <Favicon url={s.url} size={14} />
                    {domainOf(s.url)}
                  </span>
                  <span className="src-title">{s.title}</span>
                  <span className="src-url">{stripScheme(s.url)}{I.ext}</span>
                </span>
              </a>
            ))}
        </div>
      )}
    </section>
  );
}

type ArtifactProps = {
  title: string;
  status: Status;
  error?: string | null;
  result: Result | null;
  onRefresh: () => void;
  onBack?: () => void; // return to the outputs list (reader view)
  onClose?: () => void; // collapse the whole panel
  isMobile?: boolean; // mobile: one X that closes the drawn-up report back to the list
};

// The reader: one report and its sources, presented as a single coherent
// document. Its own chrome, because a report outlives the turn that asked for
// it and is read on its own.
// Copying leaves nothing on screen to show it worked, so the button says so
// itself for a moment: the icon turns into a check and a small "Copied" shows.
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = () => {
    navigator.clipboard
      ?.writeText(text)
      .then(() => {
        setCopied(true);
        window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => setCopied(false), 1600);
      })
      .catch(() => {});
  };

  return (
    <button
      className={"icon-btn copy-btn" + (copied ? " done" : "")}
      title={t.artifact.copy}
      aria-label={t.artifact.copy}
      onClick={copy}
    >
      {copied ? I.check : I.copy}
      {copied && (
        <span className="copied" role="status">
          {t.artifact.copied}
        </span>
      )}
    </button>
  );
}

export function Artifact({
  title,
  status,
  error,
  result,
  onRefresh,
  onBack,
  onClose,
  isMobile,
}: ArtifactProps) {
  const [activeCite, setActiveCite] = useState<number | null>(null);
  // Folded away until asked for, either by the header or by a citation.
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const [citeSeq, setCiteSeq] = useState(0);
  const onCite = (n: number) => {
    setActiveCite(n);
    setCiteSeq((k) => k + 1);
  };
  useScrollToCite(listRef, sourcesOpen ? activeCite : null, citeSeq);

  if (!result || (!result.report.trim() && result.sources.length === 0)) {
    const msg =
      status === "failed"
        ? error || t.artifact.emptyFailed
        : status === "complete"
          ? t.artifact.emptyNoCite
          : t.artifact.emptyPending;
    if (!onBack && !onClose) return <div className="art-empty">{msg}</div>;
    return (
      <div className="artifact">
        <div className="art-head">
          <div className="art-head-title">
            {onBack && !isMobile && (
              <button className="icon-btn" title={t.artifact.back} onClick={onBack}>{I.arrowLeft}</button>
            )}
            {I.doc}<span>{t.artifact.report}</span>
          </div>
          <div className="art-head-actions">
            {!isMobile && onClose && (
              <button className="icon-btn" title={t.artifact.closePanel} onClick={onClose}>{I.arrowRight}</button>
            )}
            {isMobile && (
              <button className="icon-btn" title={t.artifact.closePanel} onClick={onBack ?? onClose}>{I.close}</button>
            )}
          </div>
        </div>
        <div className="art-empty">{msg}</div>
      </div>
    );
  }

  return (
    <div className="artifact">
      <div className="art-head">
        <div className="art-head-title">
          {onBack && !isMobile && (
            <button className="icon-btn" title={t.artifact.back} onClick={onBack}>{I.arrowLeft}</button>
          )}
          {I.doc}<span>{title}</span>
        </div>
        <div className="art-head-actions">
          <CopyButton text={result.report} />
          <button className="icon-btn" title={t.artifact.refresh} onClick={onRefresh}>
            {I.refresh}
          </button>
          {!isMobile && onClose && (
            <button className="icon-btn" title={t.artifact.closePanel} onClick={onClose}>{I.arrowRight}</button>
          )}
          {isMobile && (
            <button className="icon-btn" title={t.artifact.closePanel} onClick={onBack ?? onClose}>{I.close}</button>
          )}
        </div>
      </div>
      <div className="art-body">
        <article className="report">
          <Markdown text={result.report} onCite={onCite} sources={result.sources} />
        </article>
        <Sources
          result={result}
          activeCite={activeCite}
          onPick={onCite}
          open={sourcesOpen}
          onToggle={() => setSourcesOpen((o) => !o)}
          listRef={listRef}
        />
      </div>
    </div>
  );
}

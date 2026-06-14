import { I } from "../icons";
import { t } from "../lib/i18n";
import type { Turn } from "../types";
import { Artifact } from "./Artifact";

type ArtifactPanelProps = {
  turns: Turn[];
  width: number; // set by the resize divider
  selectedId: number | null; // which artifact is open in the reader (null = list)
  onSelect: (id: number | null) => void;
  onClose: () => void; // collapse the whole panel
  onRefresh: (turn: Turn) => void; // re-sync the open report from the backend
  isMobile?: boolean; // mobile: list is a top sheet, report a bottom sheet
};

// A turn becomes a readable artifact once it carries a result with something to
// show (a report body or at least one source). Running/empty turns are skipped.
export function isArtifactTurn(t: Turn): boolean {
  return !!t.result && (t.result.report.trim().length > 0 || t.result.sources.length > 0);
}

function meta(turn: Turn): string {
  if (!turn.result) return t.history.status(turn.status);
  const n = turn.result.sources.length;
  const gaps = turn.result.gaps.length;
  return `${t.count.sources(n)}${gaps > 0 ? ` · ${t.count.gaps(gaps)}` : ""}`;
}

// The right-hand output panel as an artifact browser: a list of every report the
// conversation has produced (newest first), and a reader for the chosen one. The
// reader's back/close chevrons live in the Artifact header, so there is no second
// title bar stacked on top of the report.
export function ArtifactPanel({ turns, width, selectedId, onSelect, onClose, onRefresh, isMobile }: ArtifactPanelProps) {
  const artifacts = turns.filter(isArtifactTurn);
  const selected = selectedId != null ? artifacts.find((t) => t.id === selectedId) : undefined;
  // On mobile the width is set by CSS (full-bleed sheets), not the resize divider.
  const style = isMobile ? undefined : { width };

  if (selected) {
    return (
      <aside className="artifact-panel artifact-panel--reader" style={style}>
        <Artifact turn={selected} onRefresh={onRefresh} onBack={() => onSelect(null)} onClose={onClose} isMobile={isMobile} />
      </aside>
    );
  }

  // Newest first, so the latest report sits at the top of the list.
  const ordered = [...artifacts].reverse();

  return (
    <aside className="artifact-panel artifact-panel--list" style={style}>
      <div className="ch-head">
        <span className="ch-title">{I.doc}{t.artifact.title}</span>
        {/* Mobile has no close button here: the top-right corner button toggles
            the list (and highlights while open). Desktop keeps the chevron. */}
        {!isMobile && (
          <button className="icon-btn" onClick={onClose} aria-label={t.artifact.closePanel} title={t.artifact.closePanel}>
            {I.arrowRight}
          </button>
        )}
      </div>
      <div className="ch-body">
        {ordered.length === 0 && <div className="drawer-empty">{t.artifact.noReports}</div>}
        {ordered.map((t) => (
          <button key={t.id} className="hist-item" onClick={() => onSelect(t.id)}>
            <span className={"hist-dot " + t.status} />
            <div className="hist-main">
              <div className="hist-q">{t.title ?? t.query}</div>
              <div className="hist-meta">{meta(t)}</div>
            </div>
          </button>
        ))}
      </div>
    </aside>
  );
}

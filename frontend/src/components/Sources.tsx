import { useEffect, type RefObject } from "react";

import { I } from "../icons";
import { domainOf } from "../lib/favicon";
import { Favicon } from "./Favicon";
import type { Source } from "../types";

const stripScheme = (url: string) => url.replace(/^https?:\/\//, "").replace(/^www\./, "");

// Move the view to the source a citation points at, once the row is actually
// there. A click on [n] while the sources are folded opens the list in the same
// update, so the row only exists after React has committed: a scroll attempted
// any earlier finds nothing and silently does nothing. `seq` rather than the
// number itself, so clicking the same citation twice still brings it back into
// view after the reader has scrolled away.
export function useScrollToCite(
  listRef: RefObject<HTMLElement> | undefined,
  n: number | null,
  seq: number,
) {
  useEffect(() => {
    if (n == null || !listRef) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-n="${n}"]`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    // `seq` is the trigger; it is deliberately not read in the body.
  }, [n, seq, listRef]);
}

// The numbered sources behind a piece of text, shared by the chat answer and the
// report reader: one look for a citation wherever it appears.
export function SourceList({
  sources,
  activeCite,
  onPick,
  listRef,
}: {
  sources: Source[];
  activeCite: number | null;
  onPick: (n: number) => void;
  listRef?: RefObject<HTMLDivElement>;
}) {
  return (
    <div className="src-list" ref={listRef}>
      {sources.map((source, i) => {
        const n = i + 1;
        return (
          <a
            key={n}
            className={"src-row" + (activeCite === n ? " active" : "")}
            data-n={n}
            href={source.url}
            target="_blank"
            rel="noreferrer"
            onClick={() => onPick(n)}
          >
            <span className="src-n">{n}</span>
            <span className="src-main">
              <span className="src-where">
                <Favicon url={source.url} size={14} />
                {domainOf(source.url)}
              </span>
              <span className="src-title">{source.title}</span>
              <span className="src-url">{stripScheme(source.url)}{I.ext}</span>
            </span>
          </a>
        );
      })}
    </div>
  );
}

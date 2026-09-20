import type { RefObject } from "react";

import type { Source } from "../types";

const stripScheme = (url: string) => url.replace(/^https?:\/\//, "");

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
            className={"src-item" + (activeCite === n ? " active" : "")}
            data-n={n}
            href={source.url}
            target="_blank"
            rel="noreferrer"
            onClick={() => onPick(n)}
          >
            <span className="sn">{n}</span>
            <div>
              <div className="st">{source.title}</div>
              <div className="su">{stripScheme(source.url)}</div>
            </div>
          </a>
        );
      })}
    </div>
  );
}

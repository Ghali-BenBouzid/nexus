import { Fragment, type ReactNode } from "react";

type CiteProps = { onCite: (n: number) => void; activeCite: number | null };

// Split a string on [n] tokens, rendering each as a clickable superscript.
function citeNodes(str: string, kp: string, { onCite, activeCite }: CiteProps): ReactNode[] {
  return str.split(/(\[\d+\])/g).map((p, i) => {
    const m = p.match(/^\[(\d+)\]$/);
    if (m) {
      const n = +m[1];
      return (
        <sup
          key={kp + "c" + i}
          className={"cite" + (activeCite === n ? " active" : "")}
          onClick={() => onCite(n)}
        >
          [{n}]
        </sup>
      );
    }
    return <Fragment key={kp + "t" + i}>{p}</Fragment>;
  });
}

// Inline pass: **bold** + [n] citations.
function inline(str: string, kp: string, cp: CiteProps): ReactNode[] {
  return str.split(/(\*\*[^*]+\*\*)/g).map((s, i) => {
    const b = s.match(/^\*\*([^*]+)\*\*$/);
    if (b) return <strong key={kp + "b" + i}>{citeNodes(b[1], kp + "b" + i, cp)}</strong>;
    return <Fragment key={kp + "s" + i}>{citeNodes(s, kp + "s" + i, cp)}</Fragment>;
  });
}

type MarkdownProps = { text: string; onCite: (n: number) => void; activeCite: number | null };

// Markdown subset: ## h2, ### h3, > blockquote, - lists, **bold**, [n] citations.
export function Markdown({ text, onCite, activeCite }: MarkdownProps) {
  const cp: CiteProps = { onCite, activeCite };
  const blocks = text.trim().split(/\n\n+/);
  return (
    <div className="doc">
      {blocks.map((blk, bi) => {
        if (blk.startsWith("## ")) return <h2 key={bi}>{inline(blk.slice(3), "h" + bi, cp)}</h2>;
        if (blk.startsWith("### ")) return <h3 key={bi}>{inline(blk.slice(4), "h" + bi, cp)}</h3>;
        if (blk.startsWith("> ")) return <blockquote key={bi}>{inline(blk.slice(2), "q" + bi, cp)}</blockquote>;
        if (blk.split("\n").every((l) => l.startsWith("- "))) {
          return (
            <ul key={bi}>
              {blk.split("\n").map((l, li) => (
                <li key={li}>{inline(l.slice(2), "l" + bi + li, cp)}</li>
              ))}
            </ul>
          );
        }
        return <p key={bi}>{inline(blk, "p" + bi, cp)}</p>;
      })}
    </div>
  );
}

import { Children, Fragment, type ReactNode, useRef } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { resolve, slug } from "../lib/slug";

type CiteProps = { onCite: (n: number) => void; activeCite: number | null };

// Split a string on [n] tokens, rendering each as a clickable superscript that
// scrolls to (and highlights) its source. Citations are ours, not real markdown:
// "[1]" has no matching link-reference definition, so remark passes it through as
// literal text and we turn it into a citation here.
function citeNodes(str: string, kp: string, { onCite, activeCite }: CiteProps): ReactNode[] {
  return str.split(/(\[\d+\])/g).map((p, i) => {
    const m = p.match(/^\[(\d+)\]$/);
    if (m) {
      const n = +m[1];
      return (
        <sup
          key={kp + "c" + i}
          className={"cite" + (activeCite === n ? " active" : "")}
          role="button"
          tabIndex={0}
          aria-label={`Jump to source ${n}`}
          title={`Jump to source ${n}`}
          onClick={() => onCite(n)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onCite(n);
            }
          }}
        >
          [{n}]
        </sup>
      );
    }
    return <Fragment key={kp + "t" + i}>{p}</Fragment>;
  });
}

// Walk an element's children and turn citation tokens inside any string child
// into clickable citations. Nested elements (bold, links, ...) pass through and
// are handled by their own component override, so citations work at any depth.
function withCites(children: ReactNode, cp: CiteProps): ReactNode {
  return Children.map(children, (child, i) =>
    typeof child === "string" ? citeNodes(child, "k" + i, cp) : child,
  );
}

// A heading's anchor, from whatever nodes make up its text.
function anchor(node: ReactNode): string {
  return slug(text(node));
}

function text(node: ReactNode): string {
  return Children.toArray(node)
    .map((child) => {
      if (typeof child === "string" || typeof child === "number") return String(child);
      if (child && typeof child === "object" && "props" in child) {
        return text((child.props as { children?: ReactNode }).children);
      }
      return "";
    })
    .join("");
}

// Jump to a section of this document. A link that resolves to nothing does
// nothing, rather than scrolling somewhere arbitrary.
// ponytail: scoped to the first .doc on the page, which is the one report or
// answer a jump link can appear in.
function jumpTo(target: string, root: HTMLElement | null): void {
  const headings = Array.from(root?.querySelectorAll<HTMLElement>("[id]") ?? []);
  const id = resolve(target, headings.map((h) => h.id));
  if (id) {
    headings.find((h) => h.id === id)?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  }
}

type MarkdownProps = { text: string; onCite: (n: number) => void; activeCite: number | null };

// Full Markdown via react-markdown + GFM (tables, lists, code, etc.), with our
// [n] citations layered on top. Tables get a scroll wrapper so a wide comparison
// never overflows the report column.
export function Markdown({ text, onCite, activeCite }: MarkdownProps) {
  const doc = useRef<HTMLDivElement>(null);
  const cp: CiteProps = { onCite, activeCite };
  const kids = (children: ReactNode) => withCites(children, cp);

  const components: Components = {
    // Reports start at ## in the data; demote any stray h1 so the hierarchy holds.
    // Every heading carries its anchor, so a report can link to its own sections.
    h1: ({ children }) => <h2 id={anchor(children)}>{kids(children)}</h2>,
    h2: ({ children }) => <h2 id={anchor(children)}>{kids(children)}</h2>,
    h3: ({ children }) => <h3 id={anchor(children)}>{kids(children)}</h3>,
    h4: ({ children }) => <h4 id={anchor(children)}>{kids(children)}</h4>,
    p: ({ children }) => <p>{kids(children)}</p>,
    li: ({ children }) => <li>{kids(children)}</li>,
    strong: ({ children }) => <strong>{kids(children)}</strong>,
    em: ({ children }) => <em>{kids(children)}</em>,
    blockquote: ({ children }) => <blockquote>{kids(children)}</blockquote>,
    th: ({ children }) => <th>{kids(children)}</th>,
    td: ({ children }) => <td>{kids(children)}</td>,
    // A link into this same document scrolls; only a real one leaves the page.
    a: ({ href, children }) =>
      href?.startsWith("#") ? (
        <a
          href={href}
          className="jump"
          onClick={(e) => {
            e.preventDefault();
            jumpTo(href, doc.current);
          }}
        >
          {kids(children)}
        </a>
      ) : (
        <a href={href} target="_blank" rel="noreferrer">
          {kids(children)}
        </a>
      ),
    // Code is verbatim: never reinterpret tokens inside it as citations.
    table: ({ children }) => (
      <div className="md-table">
        <table>{children}</table>
      </div>
    ),
  };

  return (
    <div className="doc" ref={doc}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

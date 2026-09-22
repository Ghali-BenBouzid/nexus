import { Children, Fragment, type ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { I } from "../icons";
import { t } from "../lib/i18n";
import { segments } from "../lib/cites";
import { domainOf } from "../lib/favicon";
import { Favicon } from "./Favicon";
import { resolve, slug } from "../lib/slug";
import type { Source } from "../types";

type CiteProps = {
  onCite: (n: number) => void;
  activeCite: number | null;
  // What the numbers point at, so a citation can name its sources where it
  // stands. Index n - 1 is source [n]; an out-of-range number shows as a bare
  // number, because code numbers the sources and a stray one points nowhere.
  sources: Source[];
};

const stripScheme = (url: string) => url.replace(/^https?:\/\//, "").replace(/^www\./, "");

// How wide the open list is allowed to get, and how much room it needs under
// the chip before it flips above instead.
const POP_W = 340;
const POP_MIN_H = 180;

// Adjacent citations are one act of sourcing, so they are read as one: a claim
// backed by four pages is a claim with four receipts, not four separate marks
// in the prose. The group collapses to a single chip and opens to the list,
// which is the only way a reader checks a source they actually doubt.
function CiteGroup({ ns, sources, onCite, activeCite }: CiteProps & { ns: number[] }) {
  // Each offset is measured from the edge it is pinned to, so the panel grows
  // away from the chip rather than back over it.
  const [at, setAt] = useState<{
    x: number;
    y: number;
    fromRight: boolean;
    fromBottom: boolean;
  } | null>(null);
  const chip = useRef<HTMLButtonElement>(null);
  const open = at !== null;

  // In a portal, positioned against the viewport, because the list has to
  // escape whatever is around it: a report body scrolls and a wide table
  // scrolls sideways, and both would clip a panel drawn inside them.
  useEffect(() => {
    if (!open) return;
    const close = () => setAt(null);
    const away = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!chip.current?.contains(target) && !(target as HTMLElement).closest?.(".cites-pop")) {
        close();
      }
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    // Fixed to the viewport, so it cannot follow the text it belongs to: it
    // closes rather than drifting away from the sentence it came from.
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  const toggle = () => {
    if (open) return setAt(null);
    const box = chip.current?.getBoundingClientRect();
    if (!box) return;
    // Hung from whichever side keeps it on screen. A citation sits at the end
    // of its sentence, so the right edge is the usual case, not the rare one.
    const fromRight = box.left + POP_W > window.innerWidth - 12;
    // Below unless there is no room, in which case it opens upward from the
    // chip's top edge rather than down off the bottom of the window.
    const fromBottom = window.innerHeight - box.bottom < POP_MIN_H;
    setAt({
      x: fromRight ? window.innerWidth - box.right : box.left,
      y: fromBottom ? window.innerHeight - box.top + 6 : box.bottom + 6,
      fromRight,
      fromBottom,
    });
  };

  const lit = ns.some((n) => n === activeCite);
  const label = t.cites.label(ns.length);
  // Which of the group's sources the panel is showing. It resets whenever the
  // panel closes, so reopening a citation always starts at its first source.
  const [page, setPage] = useState(0);
  useEffect(() => {
    if (!open) setPage(0);
  }, [open]);
  const first = sources[ns[0] - 1];
  const shown = sources[ns[page] - 1];

  return (
    <>
      <button
        ref={chip}
        type="button"
        className={"cites-chip" + (open || lit ? " active" : "")}
        onClick={toggle}
        aria-expanded={open}
        aria-label={label}
        title={label}
      >
        {first ? (
          <>
            <Favicon url={first.url} size={13} />
            <span className="cites-domain">{domainOf(first.url)}</span>
          </>
        ) : (
          <span className="cites-domain">{ns[0]}</span>
        )}
        {ns.length > 1 && <span className="cites-more">+{ns.length - 1}</span>}
      </button>
      {at &&
        createPortal(
          <div
            className="cites-pop"
            style={{
              [at.fromRight ? "right" : "left"]: at.x,
              [at.fromBottom ? "bottom" : "top"]: at.y,
            }}
          >
            <div className="cites-pop-head">
              {ns.length > 1 && (
                <div className="cites-pager">
                  <button
                    type="button"
                    className="cites-arrow"
                    onClick={() => setPage((i) => (i - 1 + ns.length) % ns.length)}
                    aria-label={t.cites.prev}
                  >
                    {I.arrowLeft}
                  </button>
                  <span className="cites-count">{page + 1}/{ns.length}</span>
                  <button
                    type="button"
                    className="cites-arrow"
                    onClick={() => setPage((i) => (i + 1) % ns.length)}
                    aria-label={t.cites.next}
                  >
                    {I.arrowRight}
                  </button>
                </div>
              )}
              <span className="cites-pop-label">
                <span className="cites-stack" aria-hidden="true">
                  {ns.slice(0, 3).map((n) =>
                    sources[n - 1] ? <Favicon key={n} url={sources[n - 1].url} size={14} /> : null,
                  )}
                </span>
                {label}
              </span>
            </div>
            {shown ? (
              <a
                className="cites-card"
                href={shown.url}
                target="_blank"
                rel="noreferrer"
                onClick={() => {
                  onCite(ns[page]);
                  setAt(null);
                }}
              >
                <span className="cites-card-top">
                  <Favicon url={shown.url} size={16} />
                  <span className="cites-domain">{domainOf(shown.url)}</span>
                </span>
                <span className="cites-title">{shown.title}</span>
                <span className="cites-url">{stripScheme(shown.url)}{I.ext}</span>
              </a>
            ) : (
              <div className="cites-card missing">{t.cites.missing}</div>
            )}
          </div>,
          document.body,
        )}
    </>
  );
}

// Split a string into prose and citation groups, rendering each group as one
// chip. Citations are ours, not real markdown: "[1]" has no matching link
// definition, so remark passes it through as literal text and it is turned
// into a citation here.
function citeNodes(str: string, kp: string, cp: CiteProps): ReactNode[] {
  return segments(str).map((part, i) =>
    "ns" in part ? (
      <CiteGroup key={kp + "c" + i} ns={part.ns} {...cp} />
    ) : (
      <Fragment key={kp + "t" + i}>{part.text}</Fragment>
    ),
  );
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

type MarkdownProps = {
  text: string;
  onCite: (n: number) => void;
  activeCite: number | null;
  sources?: Source[];
};

// Full Markdown via react-markdown + GFM (tables, lists, code, etc.), with our
// [n] citations layered on top. Tables get a scroll wrapper so a wide comparison
// never overflows the report column.
export function Markdown({ text, onCite, activeCite, sources = [] }: MarkdownProps) {
  const doc = useRef<HTMLDivElement>(null);
  const cp: CiteProps = { onCite, activeCite, sources };
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

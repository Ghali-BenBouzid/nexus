import { lazy, Suspense, useEffect, useRef, useState } from "react";

import { I } from "../icons";
import { fetchDocumentFile } from "../lib/api";
import { t } from "../lib/i18n";
import { prettyText, previewKind } from "../lib/preview";
import { Markdown } from "./Markdown";

const PdfPages = lazy(() => import("./PdfPages"));

// What to open: a document the server has, or a file still sitting in the
// composer. A staged file is already a blob, so it opens without a round trip.
export type PreviewTarget = {
  name: string;
  bytes?: number;
  file?: File;
  docId?: number;
};

type Loaded =
  | { status: "loading" }
  | { status: "failed"; error: string }
  | { status: "ready"; url: string; blob: Blob; text?: string; html?: string };

const noCite = () => {};

const kb = (bytes: number) =>
  bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;

// A converted Word file is HTML we did not write, so it renders in a sandbox
// with nothing allowed but opening links: no script in it can run, whatever the
// file contains. The page's own colours are handed in, since a sandboxed frame
// inherits nothing from the page around it.
function docxFrame(html: string): string {
  const css = getComputedStyle(document.body);
  const v = (name: string) => css.getPropertyValue(name).trim();
  // The same font stylesheet the page loaded, so the frame sets type in the
  // family the page is using rather than falling back to the system's.
  const fonts = document.querySelector<HTMLLinkElement>('link[href*="fonts.googleapis.com/css"]');
  const fontLink = fonts ? `<link rel="stylesheet" href="${fonts.href}">` : "";
  return `<!doctype html><html><head><meta charset="utf-8"><base target="_blank">${fontLink}
<style>
  body { margin: 0; padding: 28px 34px 48px; font: 15px/1.65 ${v("--font-sans")};
    color: ${v("--fg")}; background: ${v("--surface-solid")}; }
  a { color: ${v("--accent")}; }
  img { max-width: 100%; height: auto; }
  table { border-collapse: collapse; margin: 12px 0; }
  td, th { border: 1px solid ${v("--line-strong")}; padding: 6px 9px; vertical-align: top; }
  td > p, th > p { margin: 0; }
  td > p + p, th > p + p { margin-top: 6px; }
  h1, h2, h3 { line-height: 1.3; }
</style></head><body>${html}</body></html>`;
}

// The file itself, over everything, as large as the window allows. Every kind
// reads the same way: pages or prose in one scrolling card, with our header and
// nobody else's toolbar. The text formats get the renderer the answers use.
export function DocPreview({ target, onClose }: { target: PreviewTarget; onClose: () => void }) {
  const kind = previewKind(target.name);
  const [loaded, setLoaded] = useState<Loaded>({ status: "loading" });
  const closeBtn = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let dead = false;
    let url: string | null = null;
    setLoaded({ status: "loading" });
    (async () => {
      try {
        const raw = target.file ?? (await fetchDocumentFile(target.docId!));
        if (dead) return;
        // Whatever type the upload was stored under, a .pdf is handed to the
        // viewer as one; an octet-stream would be downloaded instead of shown.
        const blob = kind === "pdf" ? new Blob([raw], { type: "application/pdf" }) : raw;
        url = URL.createObjectURL(blob);
        if (kind === "docx") {
          const mammoth = await import("mammoth");
          const { value } = await mammoth.convertToHtml({ arrayBuffer: await raw.arrayBuffer() });
          if (!dead) setLoaded({ status: "ready", url, blob, html: value });
        } else if (kind === "markdown" || kind === "text") {
          const text = await raw.text();
          if (!dead) setLoaded({ status: "ready", url, blob, text: prettyText(target.name, text) });
        } else {
          setLoaded({ status: "ready", url, blob });
        }
      } catch (err) {
        if (!dead) {
          setLoaded({ status: "failed", error: err instanceof Error ? err.message : t.preview.failed });
        }
      }
    })();
    return () => {
      dead = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [target, kind]);

  // Read through a ref: the app re-renders on every streamed token, and a fresh
  // onClose each time would re-run this and yank focus back to the button.
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    closeBtn.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close.current();
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);

  const url = loaded.status === "ready" ? loaded.url : null;

  let body;
  if (loaded.status === "loading") {
    body = (
      <div className="pv-state">
        <span className="spin" />
        {t.preview.loading}
      </div>
    );
  } else if (loaded.status === "failed") {
    body = <div className="pv-state bad">{loaded.error}</div>;
  } else if (kind === "pdf") {
    const wait = (
      <div className="pv-state">
        <span className="spin" />
        {t.preview.loading}
      </div>
    );
    body = (
      <Suspense fallback={wait}>
        <PdfPages data={loaded.blob} />
      </Suspense>
    );
  } else if (loaded.html != null) {
    body = (
      <iframe
        className="pv-frame"
        sandbox="allow-popups allow-popups-to-escape-sandbox"
        srcDoc={docxFrame(loaded.html)}
        title={target.name}
      />
    );
  } else if (kind === "markdown") {
    body = (
      <div className="pv-scroll pv-doc">
        <Markdown text={loaded.text ?? ""} onCite={noCite} />
      </div>
    );
  } else if (kind === "text") {
    body = (
      <div className="pv-scroll">
        <pre className="pv-text">{loaded.text}</pre>
      </div>
    );
  } else {
    body = <div className="pv-state">{t.preview.none}</div>;
  }

  return (
    <div className="pv-veil" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="pv-card" role="dialog" aria-modal="true" aria-label={target.name}>
        <div className="pv-head">
          <span className="pv-ic" aria-hidden="true">{I.doc}</span>
          <div className="pv-title">
            <span className="pv-name">{target.name}</span>
            {target.bytes != null && <span className="pv-meta">{kb(target.bytes)}</span>}
          </div>
          {url && (
            <>
              <a className="icon-btn" href={url} target="_blank" rel="noreferrer" aria-label={t.preview.newTab} title={t.preview.newTab}>
                {I.ext}
              </a>
              <a className="icon-btn" href={url} download={target.name} aria-label={t.preview.download} title={t.preview.download}>
                {I.download}
              </a>
            </>
          )}
          <button ref={closeBtn} type="button" className="icon-btn" onClick={onClose} aria-label={t.preview.close} title={t.preview.close}>
            {I.close}
          </button>
        </div>
        <div className="pv-body">{body}</div>
      </div>
    </div>
  );
}

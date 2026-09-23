import { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

import { t } from "../lib/i18n";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

// A PDF drawn as pages, in the same card and the same scroll as every other
// file, instead of the browser's viewer with its own toolbar nested inside
// ours. This module is only ever imported lazily, so pdf.js costs nothing
// until someone opens a PDF.
export default function PdfPages({ data }: { data: Blob }) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let dead = false;
    let task: ReturnType<typeof pdfjs.getDocument> | null = null;
    (async () => {
      task = pdfjs.getDocument({ data: new Uint8Array(await data.arrayBuffer()) });
      const loaded = await task.promise;
      if (!dead) setDoc(loaded);
    })().catch(() => !dead && setFailed(true));
    return () => {
      dead = true;
      task?.destroy();
    };
  }, [data]);

  if (failed) return <div className="pv-state bad">{t.preview.failed}</div>;
  if (!doc) {
    return (
      <div className="pv-state">
        <span className="spin" />
        {t.preview.loading}
      </div>
    );
  }
  return (
    <div className="pv-scroll pv-pdf">
      {Array.from({ length: doc.numPages }, (_, i) => (
        <PdfPage key={i} doc={doc} n={i + 1} />
      ))}
    </div>
  );
}

// One page, drawn when it comes near the view rather than all at once: a long
// report would otherwise rasterize hundreds of pages nobody scrolled to.
function PdfPage({ doc, n }: { doc: PDFDocumentProxy; n: number }) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  // Held at A4 until the page says otherwise, so the scrollbar is roughly
  // right before anything has been drawn.
  const [ratio, setRatio] = useState(1.414);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    let task: RenderTask | null = null;
    let started = false;
    const io = new IntersectionObserver(
      async ([entry]) => {
        if (!entry.isIntersecting || started) return;
        started = true;
        io.disconnect();
        const page = await doc.getPage(n);
        const base = page.getViewport({ scale: 1 });
        setRatio(base.height / base.width);
        // ponytail: drawn once at the width it opened at. A window resized
        // while reading gets a scaled bitmap; redraw on resize if that shows.
        const scale = (el.clientWidth / base.width) * (window.devicePixelRatio || 1);
        const viewport = page.getViewport({ scale });
        const c = canvas.current;
        if (!c) return;
        c.width = Math.floor(viewport.width);
        c.height = Math.floor(viewport.height);
        task = page.render({ canvas: c, viewport });
        await task.promise.catch(() => {});
      },
      // Measured against the card's own scroll, and a screen ahead of it.
      { root: el.closest(".pv-scroll"), rootMargin: "100% 0px" },
    );
    io.observe(el);
    return () => {
      io.disconnect();
      task?.cancel();
    };
  }, [doc, n]);

  return (
    <div ref={box} className="pv-page" style={{ aspectRatio: `1 / ${ratio}` }}>
      <canvas ref={canvas} aria-label={`${n} / ${doc.numPages}`} />
    </div>
  );
}

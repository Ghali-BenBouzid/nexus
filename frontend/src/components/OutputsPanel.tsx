import { useEffect, useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import { stored, UPLOAD_ACCEPT } from "../lib/uploads";
import { elapsed, when } from "../lib/when";
import type { Doc, Output, Result } from "../types";
import { Artifact } from "./Artifact";

type OutputsPanelProps = {
  outputs: Output[];
  documents: Doc[];
  width: number; // set by the resize divider
  openId: number | null; // which report is open in the reader (null = the list)
  openResult: Result | null; // its body, once loaded
  onOpen: (id: number | null) => void;
  unread: Set<number>; // finished reports not opened since they last changed

  onClose: () => void; // collapse the whole panel
  onRefresh: (id: number) => void;
  onUpload: (file: File) => void;
  onRemove: (doc: Doc) => void;
  onFactCheck: (doc: Doc) => void;
  onPreview: (doc: Doc) => void;
  uploadError?: string | null;
  isMobile?: boolean;
  // The quick tour points here when the panel is open; at the fab when it is not.
  tourAnchor?: boolean;
};

const kb = (bytes: number) =>
  bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;

function docMeta(doc: Doc): string {
  if (doc.state === "uploading") return t.uploads.uploading;
  if (doc.state === "reading") return t.uploads.reading;
  if (doc.state === "failed") return doc.error ?? t.uploads.failedFile;
  // Size and length, and nothing about how the text was got out. Whether a page
  // came back through OCR is our problem, not something to hand the reader.
  const parts = [kb(doc.sizeBytes)];
  if (doc.pages) parts.push(t.uploads.pages(doc.pages));
  // Truncation stays: it is not how the file was read but how much of it was,
  // and it is the reason an answer can miss what is in the last chapter.
  if (doc.truncated) parts.push(t.uploads.truncated);
  return parts.join(" · ");
}

const isWorking = (output: Output) => output.status === "pending" || output.status === "running";

// What the run is, and when: how long it has been working while it runs, and
// when it finished once it has.
function outputMeta(output: Output, now: Date): React.ReactNode {
  const kind = output.kind === "fact_check" ? t.artifact.fact_check : t.artifact.deep_research;
  // Each part wraps as a whole, so a narrow panel never leaves "AM" alone on a line.
  const parts = isWorking(output)
    ? [kind, t.artifact.workingFor(elapsed(output.createdAt, now))]
    : [
        kind,
        ...(output.status === "failed" ? [t.artifact.failed] : []),
        when(output.completedAt ?? output.createdAt, now),
      ];
  const last = parts.length - 1;
  return parts.map((part, i) => (
    <span key={i}>
      <span className="nowrap">
        {part}
        {i < last && " ·"}
      </span>
      {i < last && " "}
    </span>
  ));
}

// The panel's clock: every second while a run is working, so its timer ticks,
// and every half minute otherwise, which is enough for "5 minutes ago".
function useNow(fast: boolean): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), fast ? 1_000 : 30_000);
    return () => clearInterval(id);
  }, [fast]);
  return now;
}

// The right-hand panel: what this account has produced (deep research reports and
// fact checks, wherever they were started) and what it has attached. Two lists,
// because a report is something the agents made and a file is something the user
// brought, and mixing them reads as a dump.
export function OutputsPanel({
  outputs,
  documents,
  width,
  openId,
  openResult,
  onOpen,
  unread,
  onClose,
  onRefresh,
  onUpload,
  onRemove,
  onFactCheck,
  onPreview,
  uploadError,
  isMobile,
  tourAnchor,
}: OutputsPanelProps) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const now = useNow(outputs.some(isWorking));
  const style = isMobile ? undefined : { width };
  const open = openId != null ? outputs.find((o) => o.id === openId) : undefined;

  if (open) {
    return (
      <aside className="artifact-panel artifact-panel--reader" style={style} data-tour={tourAnchor ? "outputs" : undefined}>
        <Artifact
          title={open.title}
          status={open.status}
          error={open.error}
          result={openResult}
          onRefresh={() => onRefresh(open.id)}
          onBack={() => onOpen(null)}
          onClose={onClose}
          isMobile={isMobile}
        />
      </aside>
    );
  }

  return (
    <aside className="artifact-panel artifact-panel--list" style={style} data-tour={tourAnchor ? "outputs" : undefined}>
      <div className="ch-head">
        <span className="ap-title">{t.artifact.title}</span>
        {/* Mobile has no close button here: the top-right corner button toggles
            the panel (and highlights while open). Desktop keeps the chevron. */}
        {!isMobile && (
          <button
            className="icon-btn"
            onClick={onClose}
            aria-label={t.artifact.closePanel}
            title={t.artifact.closePanel}
          >
            {I.arrowRight}
          </button>
        )}
      </div>

      <div className="ch-body">
        {outputs.length === 0 && <div className="drawer-empty">{t.artifact.noReports}</div>}
        {outputs.map((output) => {
          const ready = output.status === "complete";
          const isNew = unread.has(output.id);
          return (
            <button
              key={output.id}
              className={"hist-item with-dot" + (isNew ? " unread" : "")}
              data-tour={`output-${output.id}`}
              onClick={() => ready && onOpen(output.id)}
              disabled={!ready}
            >
              {/* The dot means one thing only: there is something here you have
                  not read. How the run went is said in words underneath. */}
              <span className="hist-dot" aria-hidden="true" />
              <div className="hist-main">
                <div className="hist-q">{output.title}</div>
                <div
                  className={"hist-meta " + output.status}
                  title={new Date(output.completedAt ?? output.createdAt).toLocaleString()}
                >
                  {!ready && output.status !== "failed" && <span className="spin" />}
                  {outputMeta(output, now)}
                </div>
              </div>
            </button>
          );
        })}

        <div className="uploads">
          <div className="uploads-head">
            <span className="ap-subtitle">{t.uploads.title}</span>
            <button
              className="icon-btn"
              onClick={() => fileInput.current?.click()}
              aria-label={t.uploads.add}
              title={t.uploads.add}
            >
              {I.paperclip}
            </button>
          </div>
          <input
            ref={fileInput}
            type="file"
            className="visually-hidden"
            accept={UPLOAD_ACCEPT}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onUpload(file);
              e.target.value = ""; // so the same file can be picked again
            }}
          />
          {uploadError && <div className="uploads-error">{uploadError}</div>}
          {documents.length === 0 && !uploadError && (
            <div className="drawer-empty">{t.uploads.empty}</div>
          )}
          {documents.map((doc) => (
            <div key={doc.id} className="upload-item" data-state={doc.state}>
              <span className="upload-ic">
                {doc.state === "uploading" || doc.state === "reading" ? (
                  <span className="spin" />
                ) : (
                  I.doc
                )}
              </span>
              {/* The name opens the file. Nothing to open until the server has
                  it, so a file on its way up is plain text. */}
              <button
                type="button"
                className="upload-main"
                onClick={() => onPreview(doc)}
                disabled={!stored(doc)}
                aria-label={t.preview.open(doc.filename)}
              >
                <div className="upload-name">{doc.filename}</div>
                <div className="upload-meta">{docMeta(doc)}</div>
              </button>
              <div className="upload-actions">
                {/* Nothing to check until the server has the file. One still
                    being read can be asked about: the turn waits for it. */}
                {stored(doc) && doc.state !== "failed" && (
                  <button
                    className="icon-btn"
                    onClick={() => onFactCheck(doc)}
                    aria-label={t.uploads.factCheck}
                    title={t.uploads.factCheck}
                  >
                    {I.clipboardCheck}
                  </button>
                )}
                {confirming === doc.id ? (
                  <button
                    className="icon-btn danger"
                    onClick={() => {
                      setConfirming(null);
                      onRemove(doc);
                    }}
                    aria-label={t.uploads.remove}
                    title={t.uploads.remove}
                  >
                    {I.check}
                  </button>
                ) : (
                  <button
                    className="icon-btn"
                    onClick={() => setConfirming(doc.id)}
                    aria-label={t.uploads.remove}
                    title={t.uploads.remove}
                  >
                    {I.trash}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}

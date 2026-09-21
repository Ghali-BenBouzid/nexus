import { useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
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
  uploadError?: string | null;
  isMobile?: boolean;
};

const kb = (bytes: number) =>
  bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;

function docMeta(doc: Doc): string {
  const parts = [kb(doc.sizeBytes)];
  if (doc.pages) parts.push(t.uploads.pages(doc.pages));
  if (doc.ocr) parts.push(t.uploads.ocr);
  if (doc.truncated) parts.push(t.uploads.truncated);
  return parts.join(" · ");
}

function outputMeta(output: Output): string {
  const kind = output.kind === "fact_check" ? t.artifact.fact_check : t.artifact.deep_research;
  if (output.status === "failed") return `${kind} · ${t.artifact.failed}`;
  if (output.status !== "complete") return `${kind} · ${t.artifact.running}`;
  return kind;
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
  uploadError,
  isMobile,
}: OutputsPanelProps) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const style = isMobile ? undefined : { width };
  const open = openId != null ? outputs.find((o) => o.id === openId) : undefined;

  if (open) {
    return (
      <aside className="artifact-panel artifact-panel--reader" style={style}>
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
    <aside className="artifact-panel artifact-panel--list" style={style}>
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
              onClick={() => ready && onOpen(output.id)}
              disabled={!ready}
            >
              {/* The dot means one thing only: there is something here you have
                  not read. How the run went is said in words underneath. */}
              <span className="hist-dot" aria-hidden="true" />
              <div className="hist-main">
                <div className="hist-q">{output.title}</div>
                <div className={"hist-meta " + output.status}>
                  {!ready && output.status !== "failed" && <span className="spin" />}
                  {outputMeta(output)}
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
            accept=".pdf,.docx,.doc,.txt,.md"
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
            <div key={doc.id} className="upload-item">
              <span className="upload-ic">{I.doc}</span>
              <div className="upload-main">
                <div className="upload-name">{doc.filename}</div>
                <div className="upload-meta">{docMeta(doc)}</div>
              </div>
              <div className="upload-actions">
                <button
                  className="icon-btn"
                  onClick={() => onFactCheck(doc)}
                  aria-label={t.uploads.factCheck}
                  title={t.uploads.factCheck}
                >
                  {I.shield}
                </button>
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

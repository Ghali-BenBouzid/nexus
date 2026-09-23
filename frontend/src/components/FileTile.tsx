import { I } from "../icons";
import { t } from "../lib/i18n";

// The extension, as the badge every file manager puts on a document. Falls back
// to "FILE" for something without one, rather than showing an empty badge.
function kindOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  const ext = dot > 0 ? filename.slice(dot + 1) : "";
  return (ext || "file").toUpperCase().slice(0, 4);
}

const kb = (bytes: number) =>
  bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;

// An attached document, as a tile rather than as a chip. A file is a thing with
// a shape, so it gets one: a page, a format badge and its name. We render no
// thumbnail because nothing here has ever opened the file to make one, and a
// fake preview would claim more than we know. The ruled lines say "a document"
// without pretending to show its contents.
export function FileTile({
  name,
  bytes,
  meta,
  state,
  error,
  onRemove,
}: {
  name: string;
  bytes?: number;
  // How far the file has got. A tile appears the instant a file is picked, so
  // it has to be able to say "still reading this" and "this one did not work"
  // as well as it says how big the file is.
  state?: "uploading" | "failed";
  error?: string;
  // Anything already known about the file (pages, OCR, truncation). Falls back
  // to the size when there is nothing more interesting to say.
  meta?: string;
  onRemove?: () => void;
}) {
  return (
    <div className="ftile" data-state={state} title={error ?? name}>
      <div className="ftile-page" aria-hidden="true">
        <span className="ftile-lines" />
        <span className="ftile-kind">{kindOf(name)}</span>
      </div>
      <div className="ftile-foot">
        <span className="ftile-name">{name}</span>
        <span className="ftile-meta">
          {state === "uploading" && <span className="spin" aria-hidden="true" />}
          {state === "uploading"
            ? t.uploads.reading
            : state === "failed"
              ? t.uploads.failedFile
              : (meta ?? (bytes != null ? kb(bytes) : ""))}
        </span>
      </div>
      {onRemove && (
        <button
          type="button"
          className="ftile-x"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          aria-label={t.uploads.remove}
          title={t.uploads.remove}
        >
          {I.close}
        </button>
      )}
    </div>
  );
}

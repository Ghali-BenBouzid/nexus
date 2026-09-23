import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { I } from "../icons";
import { t } from "../lib/i18n";
import { useQueryHistory } from "../lib/history";
import { UPLOAD_ACCEPT, dragHasFiles, isSupported } from "../lib/uploads";
import type { Mode } from "../types";
import { ModePicker } from "./ModePicker";
import { FileTile } from "./FileTile";

type PromptBarProps = {
  onSubmit: (prompt: string) => void;
  // Files picked but not sent yet. They ride along with the next message, the
  // way an attachment does anywhere else, rather than needing a chat to exist
  // first. Leaving these out hides the attach button (the hero has no chat to
  // attach to yet).
  staged?: File[];
  onAttach?: (files: File[]) => void;
  onUnstage?: (index: number) => void;
  onPreview?: (file: File) => void;
  attachError?: string | null;
  placeholder?: string;
  autoFocus?: boolean;
  // The composer variant (pinned in the conversation) hides the verbose hint row.
  // "hero" = the big landing input; "composer" = the chat-style pinned bar.
  variant?: "hero" | "composer";
  // While a run is in flight the submit button becomes a stop button and new
  // submissions are blocked until the current run is stopped or finishes.
  running?: boolean;
  onStop?: () => void;
  // What sending does. Leaving `onMode` out hides the control entirely, which is
  // what the demo build does: there is no background run to start without a key.
  mode?: Mode;
  onMode?: (next: Mode) => void;
};

// How long a passing notice stays up, fade included.
const NOTICE_MS = 2200;

// Dropping a file on the page attaches it. The listeners are on the window
// rather than on the bar, because the whole window is what people aim at: a
// drop target the size of the composer is one most people miss. Only one prompt
// bar is mounted at a time (the hero or the chat), so this stays a single
// target.
function useFileDrop(onFiles: ((files: File[]) => void) | undefined) {
  const [over, setOver] = useState(false);
  // Dragging across a child fires leave on the parent, so depth is counted
  // rather than trusted: the veil lifts when the drag has truly left.
  const depth = useRef(0);
  // The bar re-renders on every keystroke and the caller passes a fresh arrow
  // each time, so the listeners read the callback through a ref instead of
  // being torn down and rebound as you type.
  const sink = useRef(onFiles);
  sink.current = onFiles;
  const armed = !!onFiles;

  useEffect(() => {
    if (!armed) return;
    const enter = (e: DragEvent) => {
      if (!dragHasFiles(e.dataTransfer)) return;
      depth.current += 1;
      setOver(true);
    };
    const over_ = (e: DragEvent) => {
      if (!dragHasFiles(e.dataTransfer)) return;
      // Without this the browser opens the file instead of handing it over.
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    };
    const leave = () => {
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setOver(false);
    };
    const drop = (e: DragEvent) => {
      if (!dragHasFiles(e.dataTransfer)) return;
      e.preventDefault();
      depth.current = 0;
      setOver(false);
      sink.current?.(Array.from(e.dataTransfer?.files ?? []));
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragover", over_);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragover", over_);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [armed]);

  return over;
}

// The query input, shared by the landing hero and the conversation composer.
// Owns auto-resize and shell-style ArrowUp/Down history recall so both places
// behave identically.
export type PromptBarHandle = { inject: (text: string) => void };

// forwardRef so a parent (the hero's example chips) can type text into the bar
// instead of submitting straight past it.
export const PromptBar = forwardRef<PromptBarHandle, PromptBarProps>(function PromptBar(
  {
    onSubmit,
    placeholder,
    autoFocus,
    variant = "hero",
    running,
    onStop,
    staged,
    onAttach,
    onUnstage,
    onPreview,
    attachError,
    mode = "answer",
    onMode,
  },
  ref,
) {
  const [val, setVal] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const attachments = staged ?? [];

  // A file the parser cannot read is refused here, with its name, rather than
  // being sent up to come back as a server error. It is a passing remark, not
  // a state the bar is in: it says so briefly and goes. The id restarts the
  // timer when the same file is refused twice in a row.
  const [rejected, setRejected] = useState<{ text: string; id: number } | null>(null);
  useEffect(() => {
    if (!rejected) return;
    const timer = setTimeout(() => setRejected(null), NOTICE_MS);
    return () => clearTimeout(timer);
  }, [rejected]);
  const take = (picked: File[]) => {
    if (!onAttach || !picked.length) return;
    const good = picked.filter(isSupported);
    const bad = picked.find((f) => !isSupported(f));
    if (bad) setRejected({ text: t.uploads.unsupported(bad.name), id: Date.now() });
    if (good.length) onAttach(good);
  };
  const dropping = useFileDrop(onAttach ? take : undefined);

  const { history, remember } = useQueryHistory();
  // null = editing a fresh draft; otherwise an index into `history` being browsed.
  const [histIdx, setHistIdx] = useState<number | null>(null);
  const draftRef = useRef(""); // the in-progress draft, stashed while browsing

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 180) + "px";
  }, [val]);

  useEffect(() => {
    if (!autoFocus) return;
    // Defer a frame: focusing during the chat entrance animation (before first
    // paint) leaves the textarea focused but with no visible caret in some
    // browsers. Placing the caret at the start also satisfies "caret at the
    // beginning of the text".
    const id = requestAnimationFrame(() => {
      const ta = taRef.current;
      if (!ta) return;
      ta.focus();
      ta.setSelectionRange(0, 0);
    });
    return () => cancelAnimationFrame(id);
  }, [autoFocus]);

  const caretToEnd = () =>
    requestAnimationFrame(() => {
      const ta = taRef.current;
      if (ta) ta.setSelectionRange(ta.value.length, ta.value.length);
    });

  const recall = (idx: number | null) => {
    setHistIdx(idx);
    setVal(idx === null ? draftRef.current : history[idx]);
    caretToEnd();
  };

  const fire = (prompt: string) => {
    if (running) return; // don't start a second run on top of the current one
    const p = prompt.trim();
    if (!p) return;
    remember(p);
    setHistIdx(null);
    draftRef.current = "";
    setVal("");
    onSubmit(p);
  };

  const change = (next: string) => {
    setVal(next);
    setHistIdx(null); // typing turns a recalled entry into a fresh draft
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const ta = e.currentTarget;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      fire(val);
      return;
    }
    // Shell-style recall: ArrowUp only when the caret is on the first line and
    // ArrowDown only on the last line, so multi-line editing still works.
    const noSelection = ta.selectionStart === ta.selectionEnd;
    if (e.key === "ArrowUp" && history.length && noSelection) {
      if (val.slice(0, ta.selectionStart).includes("\n")) return;
      e.preventDefault();
      if (histIdx === null) draftRef.current = val;
      recall(histIdx === null ? history.length - 1 : Math.max(0, histIdx - 1));
    } else if (e.key === "ArrowDown" && histIdx !== null && noSelection) {
      if (val.slice(ta.selectionEnd).includes("\n")) return;
      e.preventDefault();
      recall(histIdx >= history.length - 1 ? null : histIdx + 1);
    }
  };

  // Paste an example into the bar and register it to history, so it lands in the
  // textarea (editable, not auto-submitted) and is recallable with ↑/↓.
  useImperativeHandle(ref, () => ({
    inject: (text: string) => {
      const p = text.trim();
      if (!p) return;
      remember(p);
      setHistIdx(null);
      draftRef.current = "";
      setVal(text);
      taRef.current?.focus();
      caretToEnd(); // actual text: caret sits at the end
    },
  }));

  const active = !!running || val.trim().length > 0;

  // In deep mode the bar says what the report should cover, since that is what
  // sending it will produce. While a run is in flight the caller's placeholder
  // wins: what is happening now matters more than what the mode is.
  const hint = mode !== "answer" && !running
    ? t.modePlaceholder[mode]
    : (placeholder ?? t.hero.placeholder);

  const files = onAttach && (attachments.length > 0 || attachError) && (
    <div className="staged">
      {attachments.map((file, i) => (
        <FileTile
          key={file.name + i}
          name={file.name}
          bytes={file.size}
          onOpen={onPreview && (() => onPreview(file))}
          onRemove={() => onUnstage?.(i)}
        />
      ))}
      {attachError && <span className="staged-error">{attachError}</span>}
    </div>
  );

  // While a mode is on it says so in words, above the input: it changes what
  // sending does (minutes and a report, not seconds and an answer), and a lit
  // pill alone is not enough warning for something that spends real money.
  const modeChip = mode !== "answer" && onMode && (
    <div className="mode-chip">
      <span className="mode-chip-icon" aria-hidden="true">
        {mode === "deep" ? I.microscope : I.clipboardCheck}
      </span>
      <span className="mode-chip-label">{t.modes[mode].label}:</span>
      <button
        type="button"
        className="mode-chip-x"
        onClick={() => onMode("answer")}
        aria-label={t.modes.off}
        title={t.modes.off}
      >
        {I.close}
      </button>
    </div>
  );

  // Everything the bar carries above the text being typed: what is about to be
  // sent with the message, and the mode it will be sent in.
  const chips = (modeChip || files) && (
    <div className="cinput-top">
      {modeChip}
      {files}
    </div>
  );

  // Over the whole window, because the drop is: it says the page will take the
  // file, which is the only thing a drag needs told.
  // Anchored to the bar it is about, just above it, where the eye already is
  // when the file was picked.
  const notice = rejected && (
    <div key={rejected.id} className="notice" role="alert">
      <span className="notice-ic" aria-hidden="true">{I.warn}</span>
      {rejected.text}
    </div>
  );

  const veil =
    dropping &&
    createPortal(
      <div className="drop-veil">
        <div className="drop-card">
          <span className="drop-ic" aria-hidden="true">{I.paperclip}</span>
          <span className="drop-title">{t.uploads.drop}</span>
          <span className="drop-hint">{t.uploads.dropHint}</span>
        </div>
      </div>,
      document.body,
    );

  const modeButton = onMode && (
    <ModePicker mode={mode} onMode={onMode} canFactCheck={attachments.length > 0} />
  );

  const attachButton = onAttach && (
    <>
      <input
        ref={fileRef}
        type="file"
        multiple
        className="visually-hidden"
        accept={UPLOAD_ACCEPT}
        onChange={(e) => {
          take(Array.from(e.target.files ?? []));
          e.target.value = ""; // so the same file can be picked again
        }}
      />
      <button
        className="cinput-attach"
        data-tour="attach"
        onClick={() => fileRef.current?.click()}
        aria-label={t.uploads.add}
        title={t.uploads.add}
      >
        {I.paperclip}
      </button>
    </>
  );

  if (variant === "composer") {
    return (
      <>
      {veil}
      <div
        className={"cinput" + (mode !== "answer" ? " deep" : "")}
        onClick={(e) => {
          if (!(e.target as HTMLElement).closest("button, textarea")) taRef.current?.focus();
        }}
      >
        {notice}
        {chips}
        <textarea
          ref={taRef}
          rows={1}
          value={val}
          onChange={(e) => change(e.target.value)}
          onKeyDown={onKey}
          placeholder={hint}
          aria-label={hint}
          className="cinput-ta"
        />
        <div className="cinput-row">
          <div className="cinput-left">
            {attachButton}
            {modeButton}
          </div>
          <div className="cinput-actions">
            <button
              className={"cinput-send" + (active ? " active" : "") + (running ? " stop" : "")}
              onClick={() => (running ? onStop?.() : fire(val))}
              disabled={!running && !val.trim()}
              aria-label={running ? "Stop generating" : "Send"}
              title={running ? "Stop generating" : "Send"}
            >
              {running ? I.stop : I.arrowUp}
            </button>
          </div>
        </div>
      </div>
      </>
    );
  }

  return (
    <div className="prompt-wrap">
      {veil}
      <div className={"prompt" + (chips ? " with-staged" : "")}>
        {notice}
        {chips}
        <div className="prompt-row">
        <div className="cinput-left">
          {attachButton}
          {modeButton}
        </div>
        <textarea
          ref={taRef}
          rows={1}
          value={val}
          onChange={(e) => change(e.target.value)}
          onKeyDown={onKey}
          placeholder={hint}
          aria-label={hint}
        />
        {running ? (
          <button className="prompt-go stop" onClick={() => onStop?.()} aria-label="Stop generating" title="Stop generating">
            {I.stop}
          </button>
        ) : (
          <button className="prompt-go" onClick={() => fire(val)} disabled={!val.trim()} aria-label="Start research">
            {I.arrowUp}
          </button>
        )}
        </div>
      </div>
    </div>
  );
});

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import { useQueryHistory } from "../lib/history";
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
  // The conversation already holds a document, so there is something to check
  // even with nothing staged.
  hasDocuments?: boolean;
};

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
    attachError,
    mode = "answer",
    onMode,
    hasDocuments,
  },
  ref,
) {
  const [val, setVal] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const attachments = staged ?? [];

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

  // A file is a message on its own. Someone who only wants a document checked
  // or read has nothing to add, and making them type a word to unlock the send
  // button turns "the message is optional" into a lie.
  const canSend = val.trim().length > 0 || attachments.length > 0;

  const fire = (prompt: string) => {
    if (running) return; // don't start a second run on top of the current one
    const p = prompt.trim();
    if (!p && attachments.length === 0) return;
    if (p) remember(p); // nothing typed is nothing to recall with the arrows
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

  const active = !!running || canSend;

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
        {mode === "deep" ? I.telescope : I.shield}
      </span>
      <span className="mode-chip-label">{t.modes[mode].label}</span>
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

  const modeButton = onMode && (
    <ModePicker mode={mode} onMode={onMode} canFactCheck={attachments.length > 0 || !!hasDocuments} />
  );

  const attachButton = onAttach && (
    <>
      <input
        ref={fileRef}
        type="file"
        multiple
        className="visually-hidden"
        accept=".pdf,.docx,.doc,.txt,.md"
        onChange={(e) => {
          const picked = Array.from(e.target.files ?? []);
          if (picked.length) onAttach(picked);
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
      <div
        className={"cinput" + (mode !== "answer" ? " deep" : "")}
        onClick={(e) => {
          if (!(e.target as HTMLElement).closest("button, textarea")) taRef.current?.focus();
        }}
      >
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
              disabled={!running && !canSend}
              aria-label={running ? "Stop generating" : "Send"}
              title={running ? "Stop generating" : "Send"}
            >
              {running ? I.stop : I.arrowUp}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="prompt-wrap">
      <div className={"prompt" + (chips ? " with-staged" : "")}>
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
          <button className="prompt-go" onClick={() => fire(val)} disabled={!canSend} aria-label="Start research">
            {I.arrowUp}
          </button>
        )}
        </div>
      </div>
    </div>
  );
});

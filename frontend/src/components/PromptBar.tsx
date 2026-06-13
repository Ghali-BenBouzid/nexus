import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import { useQueryHistory } from "../lib/history";

type PromptBarProps = {
  onSubmit: (prompt: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
  // The composer variant (pinned in the conversation) hides the verbose hint row.
  showHint?: boolean;
  // "hero" = the big landing input; "composer" = the chat-style pinned bar.
  variant?: "hero" | "composer";
  // While a run is in flight the submit button becomes a stop button and new
  // submissions are blocked until the current run is stopped or finishes.
  running?: boolean;
  onStop?: () => void;
};

// The query input, shared by the landing hero and the conversation composer.
// Owns auto-resize and shell-style ArrowUp/Down history recall so both places
// behave identically.
export type PromptBarHandle = { inject: (text: string) => void };

// forwardRef so a parent (the hero's example chips) can type text into the bar
// instead of submitting straight past it.
export const PromptBar = forwardRef<PromptBarHandle, PromptBarProps>(function PromptBar(
  { onSubmit, placeholder, autoFocus, showHint = true, variant = "hero", running, onStop },
  ref,
) {
  const [val, setVal] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);

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

  if (variant === "composer") {
    return (
      <div
        className="cinput"
        onClick={(e) => {
          if (!(e.target as HTMLElement).closest("button, textarea")) taRef.current?.focus();
        }}
      >
        <textarea
          ref={taRef}
          rows={1}
          value={val}
          onChange={(e) => change(e.target.value)}
          onKeyDown={onKey}
          placeholder={placeholder ?? t.hero.placeholder}
          aria-label={placeholder ?? t.hero.placeholder}
          className="cinput-ta"
        />
        <div className="cinput-actions">
          {history.length > 0 && <span className="cinput-hint">{t.chat.historyHint}</span>}
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
    );
  }

  return (
    <div className="prompt-wrap">
      <div className="prompt">
        <textarea
          ref={taRef}
          rows={1}
          value={val}
          onChange={(e) => change(e.target.value)}
          onKeyDown={onKey}
          placeholder={placeholder ?? t.hero.placeholder}
          aria-label={placeholder ?? t.hero.placeholder}
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
      {showHint && (
        <div className="prompt-meta">
          <span>
            Press <b style={{ color: "var(--muted)" }}>Enter</b> to research · Shift+Enter for a new line
            {history.length > 0 && (
              <>
                {" · "}
                <b style={{ color: "var(--muted)" }}>↑↓</b> for history
              </>
            )}
          </span>
        </div>
      )}
    </div>
  );
});

import { useEffect, useRef, useState } from "react";

import { I } from "../icons";
import { back, choose, forward, start, type AskState } from "../lib/ask";
import { t } from "../lib/i18n";
import type { Answered, Question } from "../types";

type AskPanelProps = {
  questions: Question[];
  // Every question answered (or skipped): send them as one message.
  onAnswer: (answers: Answered[]) => void;
  // Closed without answering: the questions stay unanswered, nothing is sent.
  onDismiss: () => void;
};

// A key pressed while typing belongs to what is being typed. The composer is
// the exception while it is empty: arrows and Enter there do nothing else, so
// they drive the panel, the way the hint under the composer says.
function typing(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target instanceof HTMLTextAreaElement) return target.value.length > 0;
  return target instanceof HTMLInputElement || target.isContentEditable;
}

// The questions the supervisor ended its turn on, docked above the composer:
// one at a time, numbered options, a free answer, and a skip. Choosing moves to
// the next question; choosing on the last sends them all. Typing in the
// composer instead sends an ordinary message, which closes the panel too.
export function AskPanel({ questions, onAnswer, onDismiss }: AskPanelProps) {
  const [state, setState] = useState<AskState>(() => start(questions));
  const [cursor, setCursor] = useState(0);
  const [other, setOther] = useState("");
  const otherRef = useRef<HTMLInputElement>(null);
  const question = questions[state.index];
  const count = question.options.length;

  // Landing on a question (first, next, or back) puts the cursor on what was
  // chosen there before, or on the first option. Keyed on the index alone:
  // choosing records an answer too, and that must not move the cursor.
  useEffect(() => {
    const previous = state.answers[state.index];
    const at = previous == null ? -1 : question.options.indexOf(previous);
    setCursor(at >= 0 ? at : 0);
    setOther(previous != null && at < 0 ? previous : "");
  }, [state.index]);

  const pick = (answer: string | null) => {
    const { state: next, done } = choose(state, questions, answer);
    if (done) onAnswer(done);
    else setState(next);
  };

  // Latest `pick` and cursor for the window listener, without re-binding it on
  // every keystroke.
  const live = useRef({ pick, cursor, options: question.options });
  live.current = { pick, cursor, options: question.options };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
      const { pick, cursor, options } = live.current;
      const count = options.length;
      if (e.key === "Escape") {
        // Handled here, so the chat's own Escape (leave, or stop a run) does
        // not fire as well: closing the panel is all it asked for.
        e.preventDefault();
        onDismiss();
        return;
      }
      if (typing(e.target)) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const step = e.key === "ArrowDown" ? 1 : -1;
        // The free-answer row is one past the last option.
        setCursor((c) => (c + step + count + 1) % (count + 1));
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (cursor < count) pick(options[cursor]);
        else otherRef.current?.focus();
      } else if (/^[1-9]$/.test(e.key) && Number(e.key) <= count) {
        // Only outside a text field: a "2" typed into the composer is a message.
        if (e.target instanceof HTMLTextAreaElement) return;
        e.preventDefault();
        pick(options[Number(e.key) - 1]);
      }
    };
    // On the document, which hears a key before the window the chat listens on.
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onDismiss]);

  const many = questions.length > 1;
  return (
    <div className="ask-panel" role="group" aria-labelledby="ask-question">
      <div className="ask-head">
        <p className="ask-q" id="ask-question">{question.question}</p>
        {many && (
          <div className="ask-nav">
            <button
              type="button"
              className="ask-icon flip"
              onClick={() => setState(back(state))}
              disabled={state.index === 0}
              aria-label={t.ask.previous}
            >
              {I.chevron}
            </button>
            <span className="ask-pos">{t.ask.position(state.index + 1, questions.length)}</span>
            <button
              type="button"
              className="ask-icon"
              onClick={() => setState(forward(state, questions))}
              disabled={state.index === questions.length - 1}
              aria-label={t.ask.next}
            >
              {I.chevron}
            </button>
          </div>
        )}
        <button type="button" className="ask-icon" onClick={onDismiss} aria-label={t.ask.close}>
          {I.close}
        </button>
      </div>

      <ul className="ask-options">
        {question.options.map((option, i) => (
          <li key={`${state.index}-${option}`}>
            <button
              type="button"
              className={
                "ask-opt" +
                (i === cursor ? " active" : "") +
                (state.answers[state.index] === option ? " chosen" : "")
              }
              onClick={() => pick(option)}
              onMouseEnter={() => setCursor(i)}
              aria-keyshortcuts={String(i + 1)}
            >
              <span className="ask-num">{i + 1}</span>
              <span className="ask-label">{option}</span>
              {i === cursor && <span className="ask-enter" aria-hidden="true">{I.enter}</span>}
            </button>
          </li>
        ))}
        <li className={"ask-other" + (cursor === count ? " active" : "")}>
          <span className="ask-num" aria-hidden="true">{I.pencil}</span>
          <input
            ref={otherRef}
            className="ask-input"
            value={other}
            placeholder={t.ask.other}
            aria-label={t.ask.other}
            onFocus={() => setCursor(count)}
            onChange={(e) => setOther(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && other.trim()) {
                e.preventDefault();
                pick(other.trim());
              }
            }}
          />
          {!question.confirm && (
            <button type="button" className="ask-skip" onClick={() => pick(null)}>
              {t.ask.skip}
            </button>
          )}
        </li>
      </ul>
    </div>
  );
}

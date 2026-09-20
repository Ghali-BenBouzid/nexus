import { Fragment, useRef } from "react";

import { t } from "../lib/i18n";
import { PromptBar, type PromptBarHandle } from "./PromptBar";

// ``note``: the one line an invited visitor gets under the bar, their credits or
// why their invite link did not work. The chat's composer carries the same line.
type HeroProps = {
  onSubmit: (prompt: string) => void;
  note?: string | null;
  // Attaching from the landing page works the same as in the chat: the file goes
  // with the first message, which is what creates the chat.
  staged?: File[];
  onAttach?: (files: File[]) => void;
  onUnstage?: (index: number) => void;
  attachError?: string | null;
};

export function Hero({
  onSubmit,
  note,
  staged,
  onAttach,
  onUnstage,
  attachError,
}: HeroProps) {
  const barRef = useRef<PromptBarHandle>(null);
  // Each word is an inline-block unit (nowrap), so a line break can only happen at
  // a real space between words, never mid-word. Chars animate in with a continuous
  // stagger across the whole line (ci runs through every word).
  const words = t.hero.headline.split(" ");
  let ci = 0;
  return (
    <header className="hero">
      <div className="wrap">
        <h1>
          {words.map((word, wi) => (
            <Fragment key={wi}>
              <span className="hword">
                {word.split("").map((ch, k) => (
                  <span key={k} className="char" style={{ animationDelay: ci++ * 0.05 + 0.35 + "s" }}>
                    {ch}
                  </span>
                ))}
              </span>
              {wi < words.length - 1 ? " " : null}
            </Fragment>
          ))}
        </h1>
        <p className="hero-sub">{t.hero.sub}</p>

        <div className="prompt-wrap-outer">
          <PromptBar
            ref={barRef}
            onSubmit={onSubmit}
            staged={staged}
            onAttach={onAttach}
            onUnstage={onUnstage}
            attachError={attachError}
          />
          {note && <p className="composer-note">{note}</p>}
          <p className="chips-label">{t.hero.examplesLabel}</p>
          <div className="chips">
            {t.hero.chips.map((prompt, i) => (
              <button key={i} className="chip" onClick={() => barRef.current?.inject(prompt)}>
                {prompt}
              </button>
            ))}
          </div>
        </div>
      </div>
    </header>
  );
}

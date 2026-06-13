import { Fragment, useRef } from "react";

import { t } from "../lib/i18n";
import { PromptBar, type PromptBarHandle } from "./PromptBar";

type HeroProps = { onSubmit: (prompt: string) => void };

export function Hero({ onSubmit }: HeroProps) {
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
          <PromptBar ref={barRef} onSubmit={onSubmit} showHint={false} />
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

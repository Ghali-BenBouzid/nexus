import { useEffect, useRef, useState } from "react";

import { I } from "../icons";
import { PRESETS } from "../lib/simulatedEngine";

type HeroProps = { onSubmit: (prompt: string) => void };

export function Hero({ onSubmit }: HeroProps) {
  const [val, setVal] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);
  const headline = ["Ask anything.", "Get a cited answer."];

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 180) + "px";
  }, [val]);

  const submit = () => {
    if (val.trim()) onSubmit(val.trim());
  };
  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  let ci = 0;
  return (
    <header className="hero">
      <div className="wrap">
        <div className="hero-badge">
          <span className="pip" />A team of agents researches for you · <b>cited, in real time</b>
        </div>
        <h1>
          {headline.map((line, li) => (
            <span className="word" key={li} style={{ display: "block" }}>
              {line.split("").map((ch, k) => {
                const d = ci++ * 0.028 + 0.5;
                const cls = li === 1 ? "char grad" : "char";
                return (
                  <span key={k} className={cls} style={{ animationDelay: d + "s" }}>
                    {ch === " " ? " " : ch}
                  </span>
                );
              })}
            </span>
          ))}
        </h1>
        <p className="hero-sub">
          Nexus plans your question into sub-questions, sends a team of agents to research the live
          web, and returns one report where every claim is backed by a source.
        </p>

        <div className="prompt-wrap">
          <div className="prompt">
            <textarea
              ref={taRef}
              rows={1}
              value={val}
              onChange={(e) => setVal(e.target.value)}
              onKeyDown={onKey}
              placeholder="Ask Nexus to research anything…"
            />
            <button className="prompt-go" onClick={submit} disabled={!val.trim()} aria-label="Start research">
              {I.arrowUp}
            </button>
          </div>
          <div className="prompt-meta">
            <span>
              Press <b style={{ color: "var(--muted)" }}>Enter</b> to research · Shift+Enter for a new line
            </span>
            <span className="steps-mini">
              <span className="dot" />Plan<span className="arrow">→</span>Research<span className="arrow">→</span>Cite
            </span>
          </div>
          <div className="chips">
            {PRESETS.map((p, i) => (
              <button key={i} className="chip" onClick={() => onSubmit(p.prompt)}>
                {p.prompt}
              </button>
            ))}
          </div>
        </div>
      </div>
    </header>
  );
}

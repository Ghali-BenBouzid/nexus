import { useEffect, useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import type { Mode } from "../types";

// What sending does. A mode is not a setting hidden behind an icon: it changes
// how long the wait is, what comes back and how much of the budget it costs, so
// it names itself in the bar and stays named while it is on.
const MODES: { id: Mode; icon: keyof typeof I }[] = [
  { id: "answer", icon: "spark" },
  { id: "deep", icon: "microscope" },
  { id: "factcheck", icon: "clipboardCheck" },
];

export function ModePicker({
  mode,
  onMode,
  canFactCheck,
}: {
  mode: Mode;
  onMode: (next: Mode) => void;
  // Fact check needs something to check, so it stays unavailable, and says why,
  // until a document is attached.
  canFactCheck: boolean;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  const current = MODES.find((m) => m.id === mode) ?? MODES[0];
  const on = mode !== "answer";

  return (
    <div className="mode-pick" ref={box}>
      <button
        type="button"
        className={"mode-pill" + (on ? " on" : "")}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        data-tour="mode"
      >
        <span className="mode-pill-ic" aria-hidden="true">{I[current.icon]}</span>
        <span className="mode-pill-label">{on ? t.modes[mode].label : t.modes.pick}</span>
        <span className="mode-pill-chev" aria-hidden="true">{I.chevron}</span>
      </button>

      {open && (
        <div className="mode-menu" role="menu">
          {MODES.map((m) => {
            const blocked = m.id === "factcheck" && !canFactCheck;
            return (
              <button
                key={m.id}
                type="button"
                role="menuitemradio"
                aria-checked={mode === m.id}
                className={"mode-item" + (mode === m.id ? " on" : "") + (blocked ? " blocked" : "")}
                disabled={blocked}
                onClick={() => {
                  onMode(m.id);
                  setOpen(false);
                }}
              >
                <span className="mode-item-ic" aria-hidden="true">{I[m.icon]}</span>
                <span className="mode-item-main">
                  <span className="mode-item-label">{t.modes[m.id].label}</span>
                  <span className="mode-item-note">
                    {blocked ? t.modes.factcheck.needsFile : t.modes[m.id].note}
                  </span>
                </span>
                {mode === m.id && <span className="mode-item-tick" aria-hidden="true">{I.check}</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

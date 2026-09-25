import { useState } from "react";

import { I } from "../icons";
import { EFFORTS, getEffort, setEffort, type Effort } from "../lib/effort";
import { t } from "../lib/i18n";
import { useMenu } from "./useMenu";

// How hard the supervisor thinks before it answers. Named in the bar like the
// mode, because it is the user's own trade: a slower reply they chose is one
// they expect, where a slow one they did not choose reads as the app hanging.
export function EffortPicker() {
  const [effort, choose] = useState<Effort>(getEffort);
  const { open, setOpen, box } = useMenu();

  return (
    <div className="mode-pick" ref={box}>
      <button
        type="button"
        className="mode-pill"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`${t.effort.pick}: ${t.effort[effort].label}`}
        title={t.effort.pick}
      >
        <span className="mode-pill-ic" aria-hidden="true">{I.gauge}</span>
        <span className="mode-pill-label">{t.effort[effort].label}</span>
        <span className="mode-pill-chev" aria-hidden="true">{I.chevron}</span>
      </button>

      {open && (
        <div className="mode-menu" role="menu" aria-label={t.effort.pick}>
          <p className="mode-menu-head">{t.effort.head}</p>
          {EFFORTS.map((id) => (
            <button
              key={id}
              type="button"
              role="menuitemradio"
              aria-checked={effort === id}
              className={"mode-item" + (effort === id ? " on" : "")}
              onClick={() => {
                setEffort(id);
                choose(id);
                setOpen(false);
              }}
            >
              <span className="mode-item-main">
                <span className="mode-item-label">{t.effort[id].label}</span>
                <span className="mode-item-note">{t.effort[id].note}</span>
              </span>
              {effort === id && <span className="mode-item-tick" aria-hidden="true">{I.check}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

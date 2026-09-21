import { useEffect, useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";

// Long enough to read a report's title and decide, short enough that a stack of
// them clears itself while the user works.
const LIFE_MS = 8000;

// A report finished while the user was somewhere else. It says so from the
// corner the Outputs panel opens from, so the news and the place it leads to
// share a corner, and it goes away on its own: nothing here is a decision the
// user has to make now.
export function Toast({
  title,
  onOpen,
  onDismiss,
}: {
  title: string;
  onOpen: () => void;
  onDismiss: () => void;
}) {
  // Reaching for it stops the clock, so a toast never disappears from under the
  // pointer that came to click it.
  const [held, setHeld] = useState(false);
  const dismiss = useRef(onDismiss);
  dismiss.current = onDismiss;

  useEffect(() => {
    if (held) return;
    const id = setTimeout(() => dismiss.current(), LIFE_MS);
    return () => clearTimeout(id);
  }, [held]);

  return (
    <div
      className="toast"
      role="status"
      onMouseEnter={() => setHeld(true)}
      onMouseLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={() => setHeld(false)}
    >
      <span className="toast-text">{t.outputs.ready(title)}</span>
      <button className="toast-open" onClick={onOpen}>
        {t.outputs.open}
      </button>
      <button className="toast-close" onClick={onDismiss} aria-label={t.outputs.dismiss}>
        {I.close}
      </button>
    </div>
  );
}

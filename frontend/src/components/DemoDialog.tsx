import { useEffect, useRef } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";

// Demo accounts are created by hand, so asking for one goes to the owner.
export const DEMO_ACCOUNT_URL = "https://www.linkedin.com/in/ghali-ben-bouzid-6b6582268";

// Shown when someone without an invite tries a live research run: live runs spend
// real credits, so they go through a demo account. A native <dialog>, so focus,
// Esc and the backdrop come from the browser.
export function DemoDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      dialog.querySelector<HTMLElement>(".btn-primary")?.focus();
    }
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="demo-dialog"
      aria-labelledby="demo-title"
      onClose={onClose}
      // A click on the backdrop lands on the <dialog> itself; the content sits in
      // an inner box, so only a click outside it closes.
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="demo-body">
        <h2 id="demo-title">{t.demo.title}</h2>
        <p>{t.demo.body}</p>
        <div className="demo-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            {t.demo.later}
          </button>
          <a className="btn btn-primary" href={DEMO_ACCOUNT_URL} target="_blank" rel="noreferrer" onClick={onClose}>
            {t.demo.cta}
            {I.ext}
          </a>
        </div>
      </div>
    </dialog>
  );
}

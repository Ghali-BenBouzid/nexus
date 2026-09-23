import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { I } from "../icons";
import { type Account, signOut } from "../lib/api";
import { creditsLeft } from "../lib/credits";
import { lang, t } from "../lib/i18n";
import { initials } from "../lib/initials";

// Below this the bar turns red: the next deep run may not fit.
const LOW = 15;

// Who is signed in, and what they have left. The row (or, on the collapsed
// rail, the avatar alone) opens a small menu over the page: drawn against the
// viewport rather than inside the sidebar, which would clip it on the rail.
export function AccountMenu({ account, compact }: { account: Account; compact?: boolean }) {
  const trigger = useRef<HTMLButtonElement>(null);
  const [at, setAt] = useState<{ left: number; bottom: number } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const open = at !== null;

  useEffect(() => {
    if (!open) {
      setConfirming(false);
      return;
    }
    const close = () => setAt(null);
    const away = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!trigger.current?.contains(target) && !target.closest?.(".acct-menu")) close();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault(); // this Escape is ours, not the chat's
      close();
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  const toggle = () => {
    if (open) return setAt(null);
    const box = trigger.current?.getBoundingClientRect();
    if (!box) return;
    // Up from the row, like a chat app's account menu; beside the avatar on
    // the rail, where there is no room above to speak of.
    setAt(
      compact
        ? { left: box.right + 10, bottom: window.innerHeight - box.bottom }
        : { left: box.left, bottom: window.innerHeight - box.top + 8 },
    );
  };

  const percent = creditsLeft(account.remaining_usd, account.budget_usd);
  const until =
    account.expires_at &&
    new Date(account.expires_at).toLocaleDateString(lang, { day: "numeric", month: "long" });
  const avatar = (
    <span className="ch-avatar" aria-hidden="true">
      {initials(account.name)}
    </span>
  );

  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={compact ? "ch-rail-avatar" : "ch-account"}
        onClick={toggle}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={`${t.account.menu}: ${account.name}`}
        title={compact ? `${account.name} · ${t.account.plan}` : undefined}
      >
        {avatar}
        {!compact && (
          <>
            <span className="ch-account-who">
              <span className="ch-account-name">{account.name}</span>
              <span className="ch-account-plan"> · {t.account.plan}</span>
            </span>
            <span className="ch-account-chev" aria-hidden="true">{I.chevron}</span>
          </>
        )}
      </button>

      {at &&
        createPortal(
          <div
            className="acct-menu"
            role="dialog"
            aria-label={t.account.menu}
            style={{ left: at.left, bottom: at.bottom }}
          >
            <div className="acct-head">
              {avatar}
              <div className="acct-who">
                <span className="acct-name">{account.name}</span>
                <span className="acct-kind">{t.account.kind}</span>
              </div>
            </div>

            <div className="acct-section">
              <div className="acct-row">
                <span>{t.account.credits}</span>
                <span className="acct-num">{t.account.left(percent)}</span>
              </div>
              <div
                className={"acct-bar" + (percent < LOW ? " low" : "")}
                role="progressbar"
                aria-valuenow={percent}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <span style={{ width: `${percent}%` }} />
              </div>
              {until && <div className="acct-note">{t.account.until(until)}</div>}
            </div>

            <div className="acct-section">
              {confirming ? (
                <>
                  <p className="acct-warn">{t.account.confirm}</p>
                  <div className="acct-actions">
                    <button type="button" className="acct-btn" onClick={() => setConfirming(false)}>
                      {t.account.cancel}
                    </button>
                    <button
                      type="button"
                      className="acct-btn danger"
                      onClick={() => {
                        signOut();
                        // A full reload rather than resetting state by hand:
                        // nothing of this account can linger in memory after it.
                        window.location.assign("/");
                      }}
                    >
                      {t.account.signOut}
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <p className="acct-note">{t.account.stays}</p>
                  <button type="button" className="acct-item" onClick={() => setConfirming(true)}>
                    {I.signOut}
                    {t.account.signOut}
                  </button>
                </>
              )}
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}

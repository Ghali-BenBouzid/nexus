import { useEffect, useState } from "react";

import { listConversations, type ConversationSummary } from "../lib/api";
import { lang, t } from "../lib/i18n";

type HistoryProps = {
  open: boolean;
  onClose: () => void;
  onOpen: (id: number) => void;
};

function when(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(lang, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// Slide-in drawer over the whole app: the caller's past queries, pulled from the
// backend. Selecting one rehydrates it as a turn in the conversation.
export function History({ open, onClose, onOpen }: HistoryProps) {
  const [items, setItems] = useState<ConversationSummary[] | null>(null);

  useEffect(() => {
    if (!open) return;
    setItems(null);
    listConversations()
      .then(setItems)
      .catch(() => setItems([]));
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <div className={"drawer-scrim" + (open ? " open" : "")} onClick={onClose}>
      <aside className={"drawer" + (open ? " open" : "")} onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <span className="drawer-title">{t.history.recent}</span>
          <button className="drawer-x" onClick={onClose} aria-label={t.history.close}>×</button>
        </div>
        <div className="drawer-body">
          {items === null && <div className="drawer-empty">{t.history.loading}</div>}
          {items?.length === 0 && <div className="drawer-empty">{t.history.empty}</div>}
          {items?.map((c) => (
            <button key={c.id} className="hist-item" onClick={() => onOpen(c.id)}>
              <span className="hist-dot complete" />
              <div className="hist-main">
                <div className="hist-q">{c.title ?? t.history.untitled}</div>
                <div className="hist-meta">{when(c.updated_at)}</div>
              </div>
            </button>
          ))}
        </div>
      </aside>
    </div>
  );
}

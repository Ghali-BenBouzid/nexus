import { useEffect, useState } from "react";

import { I } from "../icons";
import { listConversations, type ConversationSummary } from "../lib/api";
import { lang, t } from "../lib/i18n";

function when(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(lang, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

type ChatHistoryProps = {
  open: boolean;
  onToggle: () => void;
  onOpen: (id: number) => void;
  onNewChat: () => void;
  // Bumped by the caller (e.g. turn count) to re-pull the list as queries run.
  refreshKey: number;
};

// The persistent left column of the chat workspace: the caller's past queries,
// most-recent first. Selecting one loads it as the conversation. Collapsing never
// hides it entirely: it shrinks to a slim icon rail (expand + new chat) that is
// always reachable, so the toggle lives next to the column it controls.
export function ChatHistory({ open, onToggle, onOpen, onNewChat, refreshKey }: ChatHistoryProps) {
  const [items, setItems] = useState<ConversationSummary[] | null>(null);

  useEffect(() => {
    listConversations()
      .then(setItems)
      .catch(() => setItems([]));
  }, [refreshKey]);

  const sorted = items && [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at));

  return (
    <aside className={"chat-history" + (open ? "" : " collapsed")}>
      {open ? (
        <>
          <div className="ch-head">
            <span className="ch-title">{t.history.recent}</span>
            <button className="icon-btn" onClick={onToggle} aria-label={t.history.collapse} title={t.history.collapse}>
              {I.arrowLeft}
            </button>
          </div>
          <button className="ch-newchat" onClick={onNewChat}>
            {I.plus}
            <span>{t.history.newChat}</span>
          </button>
          <div className="ch-body">
            {sorted === null && <div className="drawer-empty">{t.history.loading}</div>}
            {sorted?.length === 0 && <div className="drawer-empty">{t.history.empty}</div>}
            {sorted?.map((c) => (
              <button key={c.id} className="hist-item" onClick={() => onOpen(c.id)}>
                <span className="hist-dot complete" />
                <div className="hist-main">
                  <div className="hist-q">{c.title ?? t.history.untitled}</div>
                  <div className="hist-meta">{when(c.updated_at)}</div>
                </div>
              </button>
            ))}
          </div>
        </>
      ) : (
        <div className="ch-rail">
          <button className="icon-btn" onClick={onToggle} aria-label={t.history.expand} title={t.history.expand}>
            {I.sidebar}
          </button>
          <button className="icon-btn" onClick={onNewChat} aria-label={t.history.newChat} title={t.history.newChat}>
            {I.plus}
          </button>
        </div>
      )}
    </aside>
  );
}

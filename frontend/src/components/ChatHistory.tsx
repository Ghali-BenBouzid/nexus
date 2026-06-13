import { useEffect, useState } from "react";

import { I } from "../icons";
import { listQueries, type QuerySummary } from "../lib/api";
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
  const [items, setItems] = useState<QuerySummary[] | null>(null);

  useEffect(() => {
    listQueries()
      .then(setItems)
      .catch(() => setItems([]));
  }, [refreshKey]);

  const sorted = items && [...items].sort((a, b) => b.created_at.localeCompare(a.created_at));

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
            {sorted?.map((q) => (
              <button key={q.id} className="hist-item" onClick={() => onOpen(q.id)}>
                <span className={"hist-dot " + q.status} />
                <div className="hist-main">
                  <div className="hist-q">{q.prompt}</div>
                  <div className="hist-meta">{t.history.status(q.status)} · {when(q.created_at)}</div>
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

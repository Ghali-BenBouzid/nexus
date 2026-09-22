import { useEffect, useState } from "react";

import { I } from "../icons";
import { listConversations, type ConversationSummary } from "../lib/api";
import { lang, setLang, t } from "../lib/i18n";
import type { ConversationId, Theme } from "../types";
import { NexusLockup, NexusMark } from "./NexusLogo";

function when(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(lang, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

type ChatHistoryProps = {
  open: boolean;
  onToggle: () => void;
  // Opens a past conversation. Absent without a live account: no list to show.
  onOpen?: (id: ConversationId) => void;
  onNewChat: () => void;
  onHome: () => void;
  // Bumped by the caller (e.g. turn count) to re-pull the list as queries run.
  refreshKey: number;
  // Mobile: the column is a slide-in drawer with a tap-to-close scrim, and it
  // always renders the full list (never the desktop slim rail) so it slides out
  // with its content intact rather than swapping to the rail mid-animation.
  isMobile?: boolean;
  theme: Theme;
  toggleTheme: () => void;
};

// The chat workspace's left column, laid out like a chat app's: the brand in the
// top-left corner, a new chat button, the caller's past conversations, and the
// language and theme switches at the bottom. The chat has no nav bar, so this is
// its only chrome. Collapsed, it shrinks to a slim icon rail, never away.
export function ChatHistory({
  open,
  onToggle,
  onOpen,
  onNewChat,
  onHome,
  refreshKey,
  isMobile,
  theme,
  toggleTheme,
}: ChatHistoryProps) {
  const [items, setItems] = useState<ConversationSummary[] | null>(null);
  const listed = onOpen != null;

  useEffect(() => {
    if (!listed) return;
    listConversations()
      .then(setItems)
      .catch(() => setItems([]));
  }, [refreshKey, listed]);

  const sorted = items && [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at));

  const settings = (
    <>
      <button
        className="icon-btn lang-btn"
        onClick={() => setLang(lang === "en" ? "fr" : "en")}
        title={lang === "en" ? "Voir en français" : "View in English"}
      >
        {lang === "en" ? "FR" : "EN"}
      </button>
      <button className="icon-btn" onClick={toggleTheme} aria-label={t.nav.theme} title={t.nav.theme}>
        {theme === "dark" ? I.sun : I.moon}
      </button>
    </>
  );

  return (
    <>
      {isMobile && open && <div className="chat-history-scrim" onClick={onToggle} aria-hidden="true" />}
      <aside className={"chat-history" + (open ? "" : " collapsed")}>
        {open || isMobile ? (
          <>
            <div className="ch-head">
              <button className="ch-brand" onClick={onHome} aria-label={t.nav.home} title={t.nav.home}>
                <NexusLockup size={20} />
              </button>
              <button className="icon-btn" onClick={onToggle} aria-label={t.history.collapse} title={t.history.collapse}>
                {I.sidebar}
              </button>
            </div>
            <button className="ch-newchat" onClick={onNewChat}>
              {I.plus}
              <span>{t.history.newChat}</span>
            </button>
            {onOpen ? (
              <>
                <div className="ch-label">{t.history.recent}</div>
                <div className="ch-body">
                  {sorted === null && <div className="drawer-empty">{t.history.loading}</div>}
                  {sorted?.length === 0 && <div className="drawer-empty">{t.history.empty}</div>}
                  {sorted?.map((c) => (
                    <button key={c.id} className="hist-item" onClick={() => onOpen(c.id)}>
                      <div className="hist-main">
                        <div className="hist-q">{c.title ?? t.history.untitled}</div>
                        <div className="hist-meta">{when(c.updated_at)}</div>
                      </div>
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <div className="ch-space" />
            )}
            <div className="ch-foot">{settings}</div>
          </>
        ) : (
          <div className="ch-rail">
            <button className="ch-mark" onClick={onHome} aria-label={t.nav.home} title={t.nav.home}>
              <NexusMark size={22} />
            </button>
            <button className="icon-btn" onClick={onToggle} aria-label={t.history.expand} title={t.history.expand}>
              {I.sidebar}
            </button>
            <button className="icon-btn" onClick={onNewChat} aria-label={t.history.newChat} title={t.history.newChat}>
              {I.plus}
            </button>
            <div className="ch-rail-foot">{settings}</div>
          </div>
        )}
      </aside>
    </>
  );
}

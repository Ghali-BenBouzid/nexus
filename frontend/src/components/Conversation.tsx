import { useEffect, useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import { useIsMobile } from "../lib/useIsMobile";
import type { LayoutMode, Turn } from "../types";
import { ArtifactPanel, isArtifactTurn } from "./ArtifactPanel";
import { ChatHistory } from "./ChatHistory";
import { PromptBar } from "./PromptBar";
import { TurnCard } from "./TurnCard";

type ConversationProps = {
  turns: Turn[];
  now: number;
  layout: LayoutMode;
  onLayout: (m: LayoutMode) => void;
  focusedId: number | null;
  onFocus: (id: number | null) => void;
  onSubmit: (prompt: string) => void;
  onStop: () => void;
  onExit: () => void;
  onRefresh: (turn: Turn) => void;
  onConfirmPlan: (turn: Turn) => void;
  onRevisePlan: (turn: Turn, feedback: string) => void;
  onDiscardPlan: (turn: Turn) => void;
  running: boolean;
  onNewChat: () => void;
  feedTag: string;
  // Left "Recent" column (live mode only): open state + toggle + load handler.
  historyOpen: boolean;
  onToggleHistory: () => void;
  onOpenHistory?: (id: number) => void;
};

export function Conversation({
  turns,
  now,
  layout,
  onLayout,
  focusedId,
  onFocus,
  onSubmit,
  onStop,
  onExit,
  onRefresh,
  onConfirmPlan,
  onRevisePlan,
  onDiscardPlan,
  running,
  onNewChat,
  feedTag,
  historyOpen,
  onToggleHistory,
  onOpenHistory,
}: ConversationProps) {
  const isMobile = useIsMobile();
  const bodyRef = useRef<HTMLDivElement>(null);
  // Stick-to-bottom: the view follows the latest events by default. A manual
  // scroll up drops into free mode; following resumes on the next query (and via
  // the "jump to latest" pill). `following` is a ref so streaming updates don't
  // each trigger a re-render.
  const [atBottom, setAtBottom] = useState(true);
  const following = useRef(true);
  const lastScrollTop = useRef(0);
  const prevTurns = useRef(turns.length);

  const isNearBottom = () => {
    const el = bodyRef.current;
    return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };
  const stickToBottom = () => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight; // instant, to keep pace with streaming
  };
  const scrollToBottom = () => {
    following.current = true; // the pill re-arms follow mode
    const el = bodyRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  };

  // A manual scroll *up* leaves follow mode; scrolling all the way back to the
  // absolute bottom re-arms it. Programmatic sticks move the viewport down to the
  // bottom, which simply keeps follow mode on.
  const onBodyScroll = () => {
    const el = bodyRef.current;
    if (!el) return;
    const distToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (el.scrollTop < lastScrollTop.current - 2) following.current = false;
    if (distToBottom <= 2) following.current = true;
    lastScrollTop.current = el.scrollTop;
    setAtBottom(isNearBottom());
  };

  // Each new query in the same chat resets to the default follow behavior.
  useEffect(() => {
    if (turns.length > prevTurns.current) following.current = true;
    prevTurns.current = turns.length;
  }, [turns.length]);

  // While following, stay pinned to the bottom as turns and events stream in.
  useEffect(() => {
    if (following.current) stickToBottom();
    setAtBottom(isNearBottom());
  }, [turns, now, layout]);

  const submit = (prompt: string) => {
    following.current = true;
    onSubmit(prompt);
  };

  // Esc stops a run while one is in flight, and otherwise leaves the chat back to
  // the landing page (the conversation stays saved and reopenable from Recent).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (running) onStop();
      else onExit();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [running, onStop, onExit]);

  // Cmd/Ctrl+K jumps to the composer from anywhere in the workspace.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        document.querySelector<HTMLTextAreaElement>(".composer textarea")?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Opening a report reveals the side panel (switching to split) and focuses it.
  const openReport = (id: number) => {
    if (layout !== "split") onLayout("split");
    onFocus(id);
  };

  // Mobile-only: the top-right corner button toggles the Artifacts list (a top
  // sheet). It is "open" when the panel is split and no report is selected.
  const artifactsListOpen = layout === "split" && focusedId === null;
  const toggleArtifacts = () => {
    if (artifactsListOpen) onLayout("thread");
    else {
      onFocus(null); // land on the list, never a stale preview
      onLayout("split");
    }
  };
  // A report is drawn up as a bottom sheet on mobile whenever one is focused.
  const reportUp = focusedId != null;

  // The panel has two states with two widths: the slim, fixed Artifacts list, and
  // the wide, resizable report Preview. `previewing` is true once a real artifact
  // is selected (a running/empty turn keeps the slim list). The slim width is the
  // resize floor, so the list is exactly as narrow as a preview is allowed to get.
  const SLIM_WIDTH = 320;
  const previewing = focusedId != null && turns.some((t) => t.id === focusedId && isArtifactTurn(t));

  // Split-screen resize: drag the divider to set the report preview's width.
  // Default a little under half the screen for comfortable reading.
  const mainRef = useRef<HTMLDivElement>(null);
  const [artifactWidth, setArtifactWidth] = useState(() => Math.round(window.innerWidth * 0.46));
  const startResize = (e: React.MouseEvent) => {
    e.preventDefault();
    const main = mainRef.current;
    if (!main) return;
    const onMove = (ev: MouseEvent) => {
      const rect = main.getBoundingClientRect();
      const w = rect.right - ev.clientX;
      setArtifactWidth(Math.max(320, Math.min(rect.width * 0.6, w)));
    };
    const stop = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", stop);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    };
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", stop);
  };

  const chatColumn = (
    <div className="chat-scroll" ref={bodyRef} onScroll={onBodyScroll}>
      <div className="chat-col">
        {turns.map((t) => (
          <TurnCard
            key={t.id}
            turn={t}
            now={now}
            feedTag={feedTag}
            inSplit={layout === "split"}
            focused={t.id === focusedId}
            onSelect={() => onFocus(t.id)}
            onOpenReport={() => openReport(t.id)}
            onRerun={submit}
            onConfirmPlan={onConfirmPlan}
            onRevisePlan={onRevisePlan}
            onDiscardPlan={onDiscardPlan}
          />
        ))}
      </div>
    </div>
  );

  return (
    <main className="chat" data-layout={layout}>
      {/* Mobile chrome: fixed corner buttons. Recent (left) opens the drawer;
          Artifacts (right) toggles the list, and is hidden while a report is up so
          only the Recent button remains. Desktop keeps its rail + floating fab. */}
      {isMobile && onOpenHistory && (
        <button
          className="chat-corner chat-corner-left"
          onClick={onToggleHistory}
          aria-label={t.history.recent}
          title={t.history.recent}
        >
          {I.history}
        </button>
      )}
      {isMobile && !reportUp && (
        <button
          className={"chat-corner chat-corner-right" + (artifactsListOpen ? " active" : "")}
          onClick={toggleArtifacts}
          aria-label={t.chat.showArtifacts}
          title={t.chat.showArtifacts}
        >
          {I.doc}
        </button>
      )}
      {/* The blurred top strip behind a drawn-up report, so the eye lands on it. */}
      {isMobile && reportUp && <div className="report-scrim" aria-hidden="true" />}

      <div className="chat-main" ref={mainRef}>
        {onOpenHistory && (
          <ChatHistory
            open={historyOpen}
            onToggle={onToggleHistory}
            onOpen={onOpenHistory}
            onNewChat={onNewChat}
            // Reload the list when a turn is added and again once a title lands, so
            // a freshly named conversation shows its title instead of "Untitled".
            refreshKey={turns.length + turns.filter((t) => t.title).length}
          />
        )}

        {/* The conversation column owns the composer, so the prompt bar stays
            aligned beneath the thread and shifts as the side panels open/close. */}
        <div className="chat-center">
          {chatColumn}

          {!atBottom && turns.length > 0 && (
            <button className="jump-latest" onClick={scrollToBottom} aria-label={t.chat.jumpLatest}>
              {I.arrowDown}{t.chat.jumpLatest}
            </button>
          )}

          <div className="composer">
            <div className="composer-inner">
              <PromptBar
                variant="composer"
                onSubmit={submit}
                onStop={onStop}
                running={running}
                showHint={false}
                autoFocus
                placeholder={running ? t.chat.runningPlaceholder : t.chat.idlePlaceholder}
              />
            </div>
          </div>
        </div>

        {layout === "split" ? (
          <>
            {/* The divider only exists in the wide preview; the slim list is fixed. */}
            {previewing && (
              <div className="resizer" role="separator" aria-orientation="vertical" onMouseDown={startResize} />
            )}
            <ArtifactPanel
              turns={turns}
              width={previewing ? artifactWidth : SLIM_WIDTH}
              selectedId={focusedId}
              onSelect={onFocus}
              onClose={() => onLayout("thread")}
              onRefresh={onRefresh}
              isMobile={isMobile}
            />
          </>
        ) : (
          !isMobile && (
            <button
              className="artifact-fab"
              onClick={() => {
                onFocus(null); // always land on the Artifacts list, never a stale preview
                onLayout("split");
              }}
              aria-label={t.chat.showArtifacts}
              title={t.chat.showArtifacts}
            >
              {I.doc}
            </button>
          )
        )}
      </div>
    </main>
  );
}

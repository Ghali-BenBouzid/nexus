import { useCallback, useEffect, useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import { openQuestion } from "../lib/ask";
import { useIsMobile } from "../lib/useIsMobile";
import type { Account } from "../lib/api";
import type {
  Answered,
  ConversationId,
  Doc,
  LayoutMode,
  Mode,
  Output,
  Result,
  Theme,
  Turn,
} from "../types";
import { AskPanel } from "./AskPanel";
import { OutputsPanel } from "./OutputsPanel";
import { ChatHistory } from "./ChatHistory";
import { NexusLockup } from "./NexusLogo";
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
  // Answers from the question panel, sent as one message.
  onAnswer: (answers: Answered[]) => void;
  onStop: () => void;
  onExit: () => void;
  // What sending does, owned by App because App is what sends.
  mode: Mode;
  onMode: ((next: Mode) => void) | undefined;
  // The right-hand panel: what this account has produced, and what it attached.
  outputs: Output[];
  documents: Doc[];
  openOutputId: number | null;
  openOutputResult: Result | null;
  onOpenOutput: (id: number | null) => void;
  // Finished reports the user has not opened since they last changed.
  unread: Set<number>;
  // Chats with a finished report not yet opened, marked in Recent.
  unreadChats: Set<ConversationId>;
  onRefreshOutput: (id: number) => void;
  onUpload: (file: File) => void;
  // Files picked in the composer, sent with the next message.
  staged: File[];
  onAttach: (files: File[]) => void;
  onUnstage: (index: number) => void;
  onRemoveDocument: (doc: Doc) => void;
  onFactCheck: (doc: Doc) => void;
  // Open an attached file to read it: one the server has, or one still staged.
  onPreviewDoc: (doc: Doc) => void;
  onPreviewFile: (file: File) => void;
  uploadError?: string | null;
  running: boolean;
  onNewChat: () => void;
  // One line under the composer: the demo credits left, or why an invite failed.
  accessNote?: string | null;
  // The left column: open state + toggle, and the conversation loader (live only).
  historyOpen: boolean;
  onToggleHistory: () => void;
  onOpenHistory?: (id: ConversationId) => void;
  // The chat has no nav bar, so the theme switch lives in the left column.
  theme: Theme;
  toggleTheme: () => void;
  account?: Account | null;
};

export function Conversation({
  turns,
  now,
  layout,
  onLayout,
  focusedId,
  onFocus,
  onSubmit,
  onAnswer,
  onStop,
  onExit,
  mode,
  onMode,
  outputs,
  documents,
  openOutputId,
  openOutputResult,
  onOpenOutput,
  unread,
  unreadChats,
  onRefreshOutput,
  onUpload,
  staged,
  onAttach,
  onUnstage,
  onRemoveDocument,
  onFactCheck,
  onPreviewDoc,
  onPreviewFile,
  uploadError,
  running,
  onNewChat,
  accessNote,
  historyOpen,
  onToggleHistory,
  onOpenHistory,
  theme,
  account,
  toggleTheme,
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

  // The thread also changes height with nothing new in it: a side panel opening
  // narrows the column and every answer reflows taller, as do late fonts and
  // favicons. Whoever was at the bottom stays there through it.
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      if (following.current) stickToBottom();
      setAtBottom(isNearBottom());
    });
    ro.observe(el);
    ro.observe(el.firstElementChild!);
    return () => ro.disconnect();
  }, []);

  const submit = (prompt: string) => {
    following.current = true;
    onSubmit(prompt);
  };

  // The questions the latest turn ended on, until they are answered (any new
  // message does that) or closed. Closing is for this view only: the thread
  // still ends on a question, so a reload shows it again.
  const asked = openQuestion(turns);
  const askingTurn = turns[turns.length - 1]?.id;
  const [closedFor, setClosedFor] = useState<number | null>(null);
  const questions = asked && closedFor !== askingTurn ? asked : null;
  const closeQuestions = useCallback(() => setClosedFor(askingTurn ?? null), [askingTurn]);
  const answer = (answers: Answered[]) => {
    following.current = true;
    onAnswer(answers);
  };

  // Esc stops a run while one is in flight, and otherwise leaves the chat back to
  // the landing page (the conversation stays saved and reopenable from Recent).
  // Only an Escape nothing else wanted: a viewer, popover, menu or drawer that
  // closes on it marks it handled, and listens on the document so it hears the
  // key before this does. Otherwise closing a PDF would also stop the answer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (document.querySelector("dialog[open]")) return; // Esc closes the dialog
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

  // Mobile-only: the top-right corner button toggles the Outputs list (a top
  // sheet). It is "open" when the panel is split and no report is selected.
  const outputsListOpen = layout === "split" && openOutputId === null;
  const toggleOutputs = () => {
    if (outputsListOpen) onLayout("thread");
    else {
      onOpenOutput(null); // land on the list, never a stale preview
      onLayout("split");
    }
  };
  // A report is drawn up as a bottom sheet on mobile whenever one is open.
  const reportUp = openOutputId != null;

  // The panel has two states with two widths: the slim, fixed Outputs list, and
  // the wide, resizable report reader. The slim width is the resize floor, so the
  // list is exactly as narrow as a report is allowed to get.
  const SLIM_WIDTH = 320;
  const previewing = openOutputId != null;

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
            inSplit={layout === "split"}
            focused={t.id === focusedId}
            onSelect={() => onFocus(t.id)}
            onRerun={submit}
            onPreview={onPreviewDoc}
          />
        ))}
      </div>
    </div>
  );

  return (
    <main className="chat" data-layout={layout}>
      {/* Mobile chrome: the only header, a chat app's top bar with the menu and
          the brand on the left and Artifacts on the right. Artifacts hides while a
          report is up. Desktop keeps its left column + floating fab. */}
      {isMobile && (
        <div className="chat-topbar">
          <div className="chat-topbar-left">
            <button
              className="chat-corner chat-corner-left"
              onClick={onToggleHistory}
              aria-label={t.history.recent}
              title={t.history.recent}
            >
              {I.sidebar}
            </button>
            <button className="ch-brand" onClick={onExit} aria-label={t.nav.home} title={t.nav.home}>
              <NexusLockup size={19} />
            </button>
          </div>
          {!reportUp && (
            <button
              className={"chat-corner chat-corner-right" + (outputsListOpen ? " active" : "")}
              data-tour="outputs"
              onClick={toggleOutputs}
              aria-label={t.chat.showArtifacts}
              title={t.chat.showArtifacts}
            >
              {I.doc}
              {unread.size > 0 && <span className="unread-badge">{unread.size}</span>}
            </button>
          )}
        </div>
      )}
      {/* The blurred top strip behind a drawn-up report, so the eye lands on it. */}
      {isMobile && reportUp && <div className="report-scrim" aria-hidden="true" />}
      {/* Tap the thread to close the artifacts top sheet (matches the Recent
          drawer's tap-outside-to-close). Without it a tap falls through to the
          thread, focuses a turn, hides the toggle, and strands the list open. */}
      {isMobile && outputsListOpen && (
        <div className="artifact-list-scrim" onClick={() => onLayout("thread")} aria-hidden="true" />
      )}

      {/* Which panel is up, so the stylesheet can decide whether the side
          columns float over the page or push the thread aside. */}
      <div
        className="chat-main"
        data-panel={layout === "split" ? (previewing ? "reader" : "list") : "none"}
        ref={mainRef}
      >
        <ChatHistory
          open={historyOpen}
          onToggle={onToggleHistory}
          onOpen={onOpenHistory}
          onNewChat={onNewChat}
          onHome={onExit}
          // Reload the list as each turn moves on, not just when it is added: a
          // new conversation is only listed once its first message is stored,
          // which is after the turn appears. A landed title reloads it too, so a
          // freshly named conversation shows its title instead of "Untitled".
          refreshKey={turns.map((t) => `${t.queryId ?? ""}:${t.status}:${t.title ?? ""}`).join("|")}
          isMobile={isMobile}
          theme={theme}
          toggleTheme={toggleTheme}
          account={account}
          unread={unreadChats}
        />

        {/* The conversation column owns the composer, so the prompt bar stays
            aligned beneath the thread and shifts as the side panels open/close. */}
        <div className="chat-center">
          {chatColumn}

          <div className="composer">
            {/* Inside the composer, so it rides on its top edge: the bar changes
                height with a mode line, an attachment or a wrapped message, and
                anything measuring it in pixels goes stale the first time it does. */}
            {!atBottom && turns.length > 0 && (
              <button className="jump-latest" onClick={scrollToBottom} aria-label={t.chat.jumpLatest}>
                {I.arrowDown}{t.chat.jumpLatest}
              </button>
            )}
            <div className="composer-inner" data-tour="composer">
              {questions && (
                <AskPanel
                  key={askingTurn}
                  questions={questions}
                  onAnswer={answer}
                  onDismiss={closeQuestions}
                />
              )}
              <PromptBar
                variant="composer"
                onSubmit={submit}
                onStop={onStop}
                running={running}
                staged={staged}
                onAttach={onAttach}
                onUnstage={onUnstage}
                onPreview={onPreviewFile}
                attachError={uploadError}
                mode={mode}
                onMode={onMode}
                hasDocuments={documents.length > 0}
                asking={!!questions}
                autoFocus
                placeholder={
                  running
                    ? t.chat.runningPlaceholder
                    : questions
                      ? t.ask.placeholder
                      : t.chat.idlePlaceholder
                }
              />
              {questions && (
                <p className="composer-note ask-hints" aria-hidden="true">
                  <kbd>↑</kbd>
                  <kbd>↓</kbd> {t.ask.navigate} · <kbd>↵</kbd> {t.ask.select} · {t.ask.typeBelow}
                </p>
              )}
              {accessNote && <p className="composer-note">{accessNote}</p>}
            </div>
          </div>
        </div>

        {layout === "split" ? (
          <>
            {/* The divider only exists in the wide preview; the slim list is fixed. */}
            {previewing && (
              <div className="resizer" role="separator" aria-orientation="vertical" onMouseDown={startResize} />
            )}
            <OutputsPanel
              tourAnchor
              outputs={outputs}
              documents={documents}
              width={previewing ? artifactWidth : SLIM_WIDTH}
              openId={openOutputId}
              openResult={openOutputResult}
              onOpen={onOpenOutput}
              unread={unread}
              onClose={() => onLayout("thread")}
              onRefresh={onRefreshOutput}
              onUpload={onUpload}
              onRemove={onRemoveDocument}
              onFactCheck={onFactCheck}
              onPreview={onPreviewDoc}
              uploadError={uploadError}
              isMobile={isMobile}
            />
          </>
        ) : (
          !isMobile && (
            <button
              className="artifact-fab"
              data-tour="outputs"
              onClick={() => {
                onOpenOutput(null); // land on the Outputs list, never a stale report
                onLayout("split");
              }}
              aria-label={t.chat.showArtifacts}
              title={t.chat.showArtifacts}
            >
              {I.doc}
              {unread.size > 0 && <span className="unread-badge">{unread.size}</span>}
            </button>
          )
        )}
      </div>
    </main>
  );
}

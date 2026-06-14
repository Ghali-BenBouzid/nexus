import { Fragment, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";

import { Conversation } from "./components/Conversation";
import { Hero } from "./components/Hero";
import { History } from "./components/History";
import { Nav } from "./components/Nav";
import { About, Engineering, Footer, HowItWorks } from "./components/Sections";
import {
  cancelQuery,
  confirmPlan as confirmPlanApi,
  loadConversation,
  openQuery,
  resumeRun,
  revisePlan as revisePlanApi,
  type LoadedTurn,
} from "./lib/api";
import { t } from "./lib/i18n";
import { outcomeFor } from "./lib/outcome";
import { getRoute, navigate, onPopState, type Route } from "./lib/router";
import {
  applyBackground,
  applyFont,
  applyPalette,
  getStoredBloom,
  getStoredDarkLevel,
  getStoredFont,
  getStoredPalette,
} from "./lib/design";
import { initFluidBackground, type FluidHandle } from "./lib/fluidBackground";
import { LIVE_MODE, runResearch, type ResearchCallbacks } from "./lib/research";
import type { LayoutMode, Theme, Turn, View } from "./types";

const FEED_TAG = LIVE_MODE ? t.feed.liveTag : t.feed.simTag;

export default function App() {
  const [theme, setTheme] = useState<Theme>(
    () => (document.documentElement.getAttribute("data-theme") as Theme) || "dark",
  );
  // The URL is the source of truth for the view; a deep link or reload on
  // /chat/:id starts on the chat view and the conversation is loaded on mount.
  const [view, setView] = useState<View>(() => getRoute().view);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [layout, setLayout] = useState<LayoutMode>("thread");
  const [focusedId, setFocusedId] = useState<number | null>(null);
  const [now, setNow] = useState(0);
  const [scrolled, setScrolled] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  // Locked design (the live Design Lab was removed): one accent palette for both
  // themes, a font, the dark-mode glow and background level. Applied once on mount.
  const [palette] = useState(getStoredPalette);
  const [font] = useState(getStoredFont);
  const [bloom] = useState(getStoredBloom);
  const [darkLevel] = useState(getStoredDarkLevel);
  // The Recent column is hidden by default; the user's open/closed choice is
  // remembered across sessions.
  const [chatHistoryOpen, setChatHistoryOpen] = useState(() => {
    try {
      return localStorage.getItem("nexus-history-open") === "true";
    } catch {
      return false;
    }
  });
  const toggleChatHistory = () =>
    setChatHistoryOpen((open) => {
      const next = !open;
      try {
        localStorage.setItem("nexus-history-open", String(next));
      } catch {
        /* ignore */
      }
      return next;
    });

  // The live conversation this chat belongs to (null = a fresh, unsaved chat).
  // A page refresh starts fresh and lands on home; the previous conversation
  // stays saved server-side and is reopened on demand from Recent/history.
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const setActiveConversation = (id: number | null) => setActiveConversationId(id);

  const turnSeq = useRef(0);
  const cancelled = useRef<Set<number>>(new Set());
  const fluidRef = useRef<FluidHandle | null>(null);

  // Map a rehydrated backend turn into the conversation's Turn shape. A turn that
  // was still in flight when the snapshot was taken keeps a null endedAt so its
  // timer runs (and a resumed poll, below, drives it to completion).
  const turnFromLoaded = (lt: LoadedTurn): Turn => {
    const inFlight = lt.status === "running" || lt.status === "pending";
    return {
      id: ++turnSeq.current,
      queryId: lt.queryId ?? undefined,
      query: lt.query,
      title: lt.title,
      status: lt.status,
      events: [],
      reply: lt.reply,
      plan: lt.plan,
      result: lt.reply ? null : lt.result, // an answer turn carries no report
      outcome: outcomeFor(lt.status, lt.result.report, lt.result.sources.length),
      error: lt.error,
      startedAt: performance.now(),
      endedAt: inFlight ? null : performance.now(),
    };
  };

  // Re-attach a poll to any turn that was still running when its conversation was
  // snapshotted (e.g. reopened mid-planning), so it keeps progressing to the plan
  // prompt or the report instead of sticking on "running" with nothing driving it.
  const resumeInFlight = (loaded: Turn[]) => {
    loaded.forEach((turn) => {
      if (turn.queryId == null) return;
      if (turn.status !== "running" && turn.status !== "pending") return;
      const id = turn.id;
      setNow(performance.now());
      resumeRun(turn.queryId, callbacksFor(id))
        .then((res) => {
          if (!cancelled.current.has(id)) applyOutcome(id, res);
        })
        .catch((err) => {
          if (!cancelled.current.has(id)) failTurn(id, err);
        });
    });
  };

  // Mount the WebGL fluid background on the canvas declared in index.html.
  useEffect(() => {
    const canvas = document.getElementById("fluid-canvas") as HTMLCanvasElement | null;
    if (!canvas) return;
    fluidRef.current = initFluidBackground(canvas, theme);
    return () => {
      fluidRef.current?.dispose();
      fluidRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Theme side-effects: persist, set the attribute, recolor the fluid.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("nexus-theme-2", theme);
    } catch {
      /* ignore */
    }
    fluidRef.current?.setTheme(theme);
  }, [theme]);

  // Apply the locked palette (CSS accent vars + the fluid blob colors) and font.
  // Runs after the theme effect so the fluid override wins.
  useEffect(() => {
    applyPalette(palette);
    fluidRef.current?.setPalette(palette.fluidA, palette.fluidB);
  }, [palette]);
  // Adaptive backdrop: dark bg is derived from the accent; the same color drives
  // the fluid's clear color. Re-runs on theme so it tracks dark/light.
  useEffect(() => {
    const clear = applyBackground(palette, theme, darkLevel);
    fluidRef.current?.setBackground(clear);
  }, [palette, theme, darkLevel]);
  useEffect(() => {
    fluidRef.current?.setBloom(bloom);
  }, [bloom]);
  useEffect(() => {
    applyFont(font);
  }, [font]);

  // Body stage dims the fluid behind dense content.
  useEffect(() => {
    document.body.dataset.stage = view === "home" ? "home" : "chat";
  }, [view]);

  // A shared clock that ticks only while a run is in flight, so every running
  // turn's elapsed timer advances without a per-turn interval.
  const anyRunning = turns.some((t) => t.status === "running" || t.status === "pending");
  useEffect(() => {
    if (!anyRunning) return;
    const id = setInterval(() => setNow(performance.now()), 150);
    return () => clearInterval(id);
  }, [anyRunning]);

  // Nav shadow on scroll + hero-focal fluid fade: the blob is full behind the
  // hero and fades out over the first ~70vh as the sections rise. On chat stages
  // the body pins --fluid-op low (CSS), which wins over this since it's closer.
  useEffect(() => {
    const onScroll = () => {
      const y = window.scrollY;
      setScrolled(y > 16);
      const fade = Math.max(0.12, 1 - y / (window.innerHeight * 0.7));
      document.documentElement.style.setProperty("--fluid-op", fade.toFixed(3));
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Keep the view in sync with the URL on back/forward (and the phone back
  // gesture). A ref holds the latest handler so the listener is registered once
  // but always reads current state.
  const syncRoute = (route: Route) => {
    if (route.view === "home") {
      setView("home");
      window.scrollTo({ top: 0 });
      return;
    }
    if (route.conversationId == null) {
      setView("chat"); // /chat: a fresh chat
      return;
    }
    if (route.conversationId === activeConversationId) {
      setView("chat"); // already loaded; just show it again
      return;
    }
    if (LIVE_MODE) openHistory(route.conversationId);
    else {
      navigate("/", { replace: true });
      setView("home");
    }
  };
  const syncRouteRef = useRef(syncRoute);
  syncRouteRef.current = syncRoute;

  // On mount, load a deep-linked /chat/:id (redirecting home if it isn't the
  // user's), then wire popstate to the same sync.
  useEffect(() => {
    const route = getRoute();
    if (route.view === "chat" && route.conversationId != null) {
      if (LIVE_MODE) openHistory(route.conversationId);
      else {
        navigate("/", { replace: true });
        setView("home");
      }
    }
    return onPopState((r) => syncRouteRef.current(r));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Update only one turn; turns run independently and never clobber each other.
  const patchTurn = (id: number, fn: (t: Turn) => Turn) =>
    setTurns((prev) => prev.map((t) => (t.id === id ? fn(t) : t)));

  // The live callbacks for a turn, shared by a fresh run and a resumed poll.
  const callbacksFor = (id: number): ResearchCallbacks => ({
    onEvent: (e) => {
      if (!cancelled.current.has(id)) patchTurn(id, (t) => ({ ...t, events: [...t.events, e] }));
    },
    onStatus: (s) => {
      if (!cancelled.current.has(id)) patchTurn(id, (t) => ({ ...t, status: s }));
    },
    isCancelled: () => cancelled.current.has(id),
    onQueryId: (qid) => patchTurn(id, (t) => ({ ...t, queryId: qid })),
    onConversation: (cid) => {
      setActiveConversation(cid);
      // The fresh /chat now has a real id: rewrite the URL in place (no extra
      // history entry) so a reload or back/forward resolves to this conversation.
      navigate(`/chat/${cid}`, { replace: true });
    },
    onTitle: (title) => patchTurn(id, (t) => ({ ...t, title })),
  });

  // Apply a finished run's outcome to its turn: a paused plan awaiting confirmation,
  // a direct reply, a research report, or nothing if the run was superseded.
  const applyOutcome = (id: number, res: Awaited<ReturnType<typeof runResearch>>) => {
    if (!res) {
      patchTurn(id, (t) => ({ ...t, endedAt: performance.now() }));
      return;
    }
    if (res.awaitingPlan) {
      patchTurn(id, (t) => ({ ...t, status: "awaiting_plan", plan: res.plan, endedAt: performance.now() }));
      return;
    }
    if (res.reply != null) {
      patchTurn(id, (t) => ({ ...t, reply: res.reply, result: null, outcome: "ok", status: "complete", endedAt: performance.now() }));
      return;
    }
    patchTurn(id, (t) => ({
      ...t,
      result: res.result,
      outcome: res.outcome,
      title: res.title ?? t.title,
      error: res.error ?? null,
      status: res.outcome === "failed" ? "failed" : "complete",
      endedAt: performance.now(),
    }));
    if (res.outcome === "ok" && res.result) {
      setLayout("split");
      setFocusedId(id);
    }
  };

  const failTurn = (id: number, err: unknown) =>
    patchTurn(id, (t) => ({
      ...t,
      status: "failed",
      outcome: "failed",
      error: err instanceof Error ? err.message : "The research run failed.",
      endedAt: performance.now(),
    }));

  // The hero always opens a brand-new conversation: launching from the landing
  // page starts a fresh chat rather than appending to whatever was open last.
  function heroSubmit(prompt: string) {
    turns.forEach((t) => cancelled.current.add(t.id));
    setActiveConversation(null);
    navigate("/chat"); // a fresh chat; becomes /chat/:id once the backend assigns one
    startResearch(prompt, { fresh: true });
  }

  async function startResearch(prompt: string, opts?: { fresh?: boolean }) {
    const fresh = opts?.fresh ?? false;
    // One run at a time: ignore a follow-up while another is in flight. A fresh
    // hero submission replaces the workspace, so it is never blocked this way.
    if (!fresh && turns.some((t) => t.status === "running" || t.status === "pending")) return;
    // A new question supersedes any plan still waiting for confirmation: cancel it
    // on the backend and mark it stopped, rather than orphaning the paused query.
    if (!fresh) {
      turns.forEach((tn) => {
        if (tn.status === "awaiting_plan") {
          if (tn.queryId != null) cancelQuery(tn.queryId);
          patchTurn(tn.id, (t) => ({ ...t, status: "failed", stopped: true, plan: undefined, endedAt: performance.now() }));
        }
      });
    }
    const id = ++turnSeq.current;
    const turn: Turn = {
      id,
      query: prompt,
      status: "running",
      events: [],
      result: null,
      outcome: "ok",
      error: null,
      startedAt: performance.now(),
      endedAt: null,
    };
    setNow(turn.startedAt);
    setView("chat");
    // Fresh: drop the previous thread and start a new conversation; the explicit
    // null below means this run never appends to the prior conversation.
    if (fresh) {
      setFocusedId(null);
      setLayout("thread");
      setTurns([turn]);
    } else {
      setTurns((prev) => [...prev, turn]);
    }
    const conversationId = fresh ? null : activeConversationId;

    try {
      const res = await runResearch(prompt, callbacksFor(id), conversationId);
      if (cancelled.current.has(id)) return;
      applyOutcome(id, res);
    } catch (err) {
      if (!cancelled.current.has(id)) failTurn(id, err);
    }
  }

  // Approve the proposed plan: run the research, then resume polling to completion.
  async function confirmPlan(turn: Turn) {
    if (turn.queryId == null) return;
    const id = turn.id;
    // Resume the feed after the events already shown, so the phase-1 planner events
    // are not re-drained and duplicated when the research run streams in.
    const sinceEventId = turn.events.reduce((m, e) => Math.max(m, e.id), 0);
    patchTurn(id, (t) => ({ ...t, status: "running", plan: undefined, startedAt: performance.now(), endedAt: null }));
    setNow(performance.now());
    try {
      await confirmPlanApi(turn.queryId);
      const res = await resumeRun(turn.queryId, callbacksFor(id), sinceEventId);
      if (cancelled.current.has(id)) return;
      applyOutcome(id, res);
    } catch (err) {
      if (!cancelled.current.has(id)) failTurn(id, err);
    }
  }

  // Reject the plan with optional feedback: re-plan, then resume (pauses again).
  async function revisePlan(turn: Turn, feedback: string) {
    if (turn.queryId == null) return;
    const id = turn.id;
    const sinceEventId = turn.events.reduce((m, e) => Math.max(m, e.id), 0);
    patchTurn(id, (t) => ({ ...t, status: "running", plan: undefined, startedAt: performance.now(), endedAt: null }));
    setNow(performance.now());
    try {
      await revisePlanApi(turn.queryId, feedback);
      const res = await resumeRun(turn.queryId, callbacksFor(id), sinceEventId);
      if (cancelled.current.has(id)) return;
      applyOutcome(id, res);
    } catch (err) {
      if (!cancelled.current.has(id)) failTurn(id, err);
    }
  }

  // Discard a plan awaiting confirmation: stop it server-side and mark the turn
  // stopped, so it does not linger as a paused query (and is not rehydrated as
  // still awaiting confirmation on reload).
  function discardPlan(turn: Turn) {
    if (turn.queryId != null) cancelQuery(turn.queryId);
    patchTurn(turn.id, (t) => ({ ...t, status: "failed", stopped: true, plan: undefined, endedAt: performance.now() }));
  }

  function stopResearch() {
    setTurns((prev) =>
      prev.map((t) => {
        if (t.status === "running" || t.status === "pending") {
          cancelled.current.add(t.id); // the run loop bails at its next checkpoint
          // Tell the backend to actually stop the job, so it stops spending quota
          // instead of running on in the background after the user stops it.
          if (t.queryId != null) cancelQuery(t.queryId);
          return { ...t, status: "failed", stopped: true, endedAt: performance.now() };
        }
        return t;
      }),
    );
  }

  // Refresh the open report: re-fetch this turn's stored query from the backend
  // and sync the artifact to it. This is NOT a re-run; it just pulls the latest
  // persisted report/sources for the same query (no-op without a backend id).
  async function refreshArtifact(turn: Turn) {
    if (turn.queryId == null) return;
    const data = await openQuery(turn.queryId);
    if (!data) return;
    const outcome = outcomeFor(data.status, data.result.report, data.result.sources.length);
    setTurns((prev) =>
      prev.map((t) =>
        t.id === turn.id
          ? {
              ...t,
              status: data.status,
              result: data.result,
              events: data.events,
              outcome,
              title: data.title ?? t.title,
              error: data.error,
            }
          : t,
      ),
    );
  }

  const chooseLayout = (m: LayoutMode) => setLayout(m);

  function goHome() {
    navigate("/");
    setView("home");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // Open a past conversation from the sidebar: load its whole thread and make it
  // the active conversation. Anything running in the current chat is cancelled.
  async function openHistory(conversationId: number) {
    setHistoryOpen(false);
    const conv = await loadConversation(conversationId);
    // Missing or not owned by this user: the API 404s and we land back on home
    // rather than showing an empty chat for a conversation that isn't theirs.
    if (!conv) {
      navigate("/", { replace: true });
      setView("home");
      return;
    }
    navigate(`/chat/${conv.id}`);
    turns.forEach((t) => {
      if (t.status === "running" || t.status === "pending") cancelled.current.add(t.id);
    });
    const loaded = conv.turns.map(turnFromLoaded);
    setTurns(loaded);
    setActiveConversation(conv.id);
    setFocusedId(null);
    setView("chat");
    setLayout("thread");
    resumeInFlight(loaded);
  }

  function newChat() {
    turns.forEach((t) => cancelled.current.add(t.id));
    setTurns([]);
    setFocusedId(null);
    setLayout("thread");
    setActiveConversation(null); // a fresh chat starts a new conversation
    navigate("/chat"); // becomes /chat/:id once the backend assigns one
    setView("chat"); // land on a fresh, empty conversation, not the hero
  }

  // Cross-fade between themes. The View Transitions API snapshots the whole
  // viewport (CSS chrome + the fluid canvas) and fades old into new; flushSync
  // commits the theme synchronously so the "after" snapshot is the new theme.
  // Browsers without the API just switch instantly.
  const toggleTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    const start = (
      document as Document & { startViewTransition?: (cb: () => void) => void }
    ).startViewTransition?.bind(document);
    if (start) {
      start(() => flushSync(() => setTheme(next)));
    } else {
      setTheme(next);
    }
  };

  return (
    <Fragment>
      <Nav
        theme={theme}
        toggleTheme={toggleTheme}
        onLogo={goHome}
        scrolled={scrolled || view === "chat"}
        showLinks={view === "home"}
        onHistory={
          // Home: the nav rail opens the history drawer. In chat the Recent column
          // owns its own slim-rail toggle, so the nav control drops away there.
          LIVE_MODE && view !== "chat" ? () => setHistoryOpen(true) : undefined
        }
        onStart={() => {
          if (view === "chat") document.querySelector<HTMLTextAreaElement>(".composer textarea")?.focus();
          else document.querySelector<HTMLTextAreaElement>(".prompt textarea")?.focus();
        }}
      />

      {LIVE_MODE && (
        <History open={historyOpen} onClose={() => setHistoryOpen(false)} onOpen={openHistory} />
      )}

      {view === "home" && (
        <Fragment>
          <Hero onSubmit={heroSubmit} />
          <About />
          <HowItWorks />
          <Engineering />
          <Footer />
        </Fragment>
      )}

      {view === "chat" && (
        <Conversation
          turns={turns}
          now={now}
          layout={layout}
          onLayout={chooseLayout}
          focusedId={focusedId}
          onFocus={setFocusedId}
          onSubmit={startResearch}
          onStop={stopResearch}
          onExit={goHome}
          onRefresh={refreshArtifact}
          onConfirmPlan={confirmPlan}
          onRevisePlan={revisePlan}
          onDiscardPlan={discardPlan}
          running={anyRunning}
          onNewChat={newChat}
          feedTag={FEED_TAG}
          historyOpen={chatHistoryOpen}
          onToggleHistory={toggleChatHistory}
          onOpenHistory={LIVE_MODE ? openHistory : undefined}
        />
      )}
    </Fragment>
  );
}

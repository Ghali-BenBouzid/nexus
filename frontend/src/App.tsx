import { Fragment, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";

import { Conversation } from "./components/Conversation";
import { Hero } from "./components/Hero";
import { History } from "./components/History";
import { Nav } from "./components/Nav";
import { About, Engineering, Footer, HowItWorks } from "./components/Sections";
import { openQuery } from "./lib/api";
import { t } from "./lib/i18n";
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
import { LIVE_MODE, runResearch } from "./lib/research";
import type { LayoutMode, Outcome, Theme, Turn, View } from "./types";

const FEED_TAG = LIVE_MODE ? t.feed.liveTag : t.feed.simTag;

export default function App() {
  const [theme, setTheme] = useState<Theme>(
    () => (document.documentElement.getAttribute("data-theme") as Theme) || "dark",
  );
  const [view, setView] = useState<View>("home");
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

  const turnSeq = useRef(0);
  const cancelled = useRef<Set<number>>(new Set());
  const fluidRef = useRef<FluidHandle | null>(null);

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

  async function startResearch(prompt: string) {
    // One run at a time: ignore a new submission while another is in flight.
    if (turns.some((t) => t.status === "running" || t.status === "pending")) return;
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
    setTurns((prev) => [...prev, turn]);
    // Don't touch the preview selection on submit: if the user is reading an
    // earlier report it stays put until this run produces its own artifact.

    // Update only this turn; turns run independently and never clobber each other.
    const patch = (fn: (t: Turn) => Turn) =>
      setTurns((prev) => prev.map((t) => (t.id === id ? fn(t) : t)));

    try {
      const res = await runResearch(prompt, {
        onEvent: (e) => {
          if (!cancelled.current.has(id)) patch((t) => ({ ...t, events: [...t.events, e] }));
        },
        onStatus: (s) => {
          if (!cancelled.current.has(id)) patch((t) => ({ ...t, status: s }));
        },
        isCancelled: () => cancelled.current.has(id),
      });
      if (cancelled.current.has(id)) return;
      if (!res) {
        patch((t) => ({ ...t, endedAt: performance.now() }));
        return;
      }
      patch((t) => ({
        ...t,
        result: res.result,
        outcome: res.outcome,
        error: res.error ?? null,
        status: res.outcome === "failed" ? "failed" : "complete",
        endedAt: performance.now(),
      }));
      // A finished report opens directly in the wide preview, exactly as if the
      // user had opened the panel and clicked it.
      if (res.outcome === "ok" && res.result) {
        setLayout("split");
        setFocusedId(id);
      }
    } catch (err) {
      if (cancelled.current.has(id)) return;
      patch((t) => ({
        ...t,
        status: "failed",
        outcome: "failed",
        error: err instanceof Error ? err.message : "The research run failed.",
        endedAt: performance.now(),
      }));
    }
  }

  function stopResearch() {
    setTurns((prev) =>
      prev.map((t) => {
        if (t.status === "running" || t.status === "pending") {
          cancelled.current.add(t.id); // the run loop bails at its next checkpoint
          return { ...t, status: "failed", stopped: true, endedAt: performance.now() };
        }
        return t;
      }),
    );
  }

  const chooseLayout = (m: LayoutMode) => setLayout(m);

  function goHome() {
    setView("home");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function openHistory(id: number) {
    setHistoryOpen(false);
    const data = await openQuery(id);
    if (!data) return;
    // Opening a past query navigates to *that* chat: a stored query is its own
    // conversation, so we replace the thread rather than appending to the current
    // one. Anything still running in the current chat is cancelled as we leave.
    turns.forEach((t) => {
      if (t.status === "running" || t.status === "pending") cancelled.current.add(t.id);
    });
    let outcome: Outcome = "ok";
    if (data.status === "failed") outcome = "failed";
    else if (!data.result.report.trim() && data.result.sources.length === 0) outcome = "empty";
    const tid = ++turnSeq.current;
    const loaded: Turn = {
      id: tid,
      query: data.prompt,
      status: data.status,
      events: data.events,
      result: data.result,
      outcome,
      error: data.error,
      startedAt: performance.now(),
      endedAt: performance.now(),
    };
    setTurns([loaded]);
    // Loading a past chat does not pop the report: the panel stays closed, so the
    // artifact button lands on the Artifacts list when the user opens it.
    setFocusedId(null);
    setView("chat");
    setLayout("thread");
  }

  function newChat() {
    turns.forEach((t) => cancelled.current.add(t.id));
    setTurns([]);
    setFocusedId(null);
    setLayout("thread");
    goHome();
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
          <Hero onSubmit={startResearch} />
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

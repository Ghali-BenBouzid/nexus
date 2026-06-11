import { Fragment, useEffect, useRef, useState } from "react";

import { Hero } from "./components/Hero";
import { Nav } from "./components/Nav";
import { RunScreen } from "./components/RunScreen";
import { ComingSoon, FeatureLiveFeed, FeatureSources, Footer, HowItWorks } from "./components/Sections";
import { initFluidBackground, type FluidHandle } from "./lib/fluidBackground";
import { LIVE_MODE, runResearch } from "./lib/research";
import type { Outcome, Result, Status, Theme, TimelineEvent, View } from "./types";

const FEED_TAG = LIVE_MODE ? "Live run · streaming-ready" : "Simulated run · streaming-ready";

export default function App() {
  const [theme, setTheme] = useState<Theme>(
    () => (document.documentElement.getAttribute("data-theme") as Theme) || "dark",
  );
  const [view, setView] = useState<View>("home");
  const [query, setQuery] = useState("");
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [status, setStatus] = useState<Status>("pending");
  const [result, setResult] = useState<Result | null>(null);
  const [outcome, setOutcome] = useState<Outcome>("ok");
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [scrolled, setScrolled] = useState(false);

  const runId = useRef(0);
  const startRef = useRef(0);
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
      localStorage.setItem("nexus-theme", theme);
    } catch {
      /* ignore */
    }
    fluidRef.current?.setTheme(theme);
  }, [theme]);

  // Body stage dims the fluid behind dense content.
  useEffect(() => {
    document.body.dataset.stage = view === "home" ? "home" : status === "complete" ? "report" : "run";
  }, [view, status]);

  // Elapsed timer while running.
  useEffect(() => {
    if (status !== "running" && status !== "pending") return;
    const id = setInterval(() => setElapsed((performance.now() - startRef.current) / 1000), 100);
    return () => clearInterval(id);
  }, [status]);

  // Nav shadow on scroll.
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 16);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  async function startResearch(prompt: string) {
    const myId = ++runId.current;
    setView("run");
    setQuery(prompt);
    setEvents([]);
    setResult(null);
    setOutcome("ok");
    setError(null);
    setElapsed(0);
    startRef.current = performance.now();
    setStatus("running");
    window.scrollTo(0, 0);

    let res;
    try {
      res = await runResearch(prompt, {
        onEvent: (e) => setEvents((prev) => (runId.current === myId ? [...prev, e] : prev)),
        onStatus: (s) => {
          if (runId.current === myId) setStatus(s);
        },
        isCancelled: () => runId.current !== myId,
      });
    } catch (err) {
      if (runId.current !== myId) return;
      setOutcome("failed");
      setError(err instanceof Error ? err.message : "The research run failed.");
      setStatus("failed");
      return;
    }

    if (!res || runId.current !== myId) return;
    setResult(res.result);
    setOutcome(res.outcome);
    setError(res.error ?? null);
    setStatus(res.outcome === "failed" ? "failed" : "complete");
  }

  function goHome() {
    runId.current++;
    setView("home");
    setStatus("pending");
    window.scrollTo(0, 0);
  }

  const toggleTheme = () => setTheme((t) => (t === "dark" ? "light" : "dark"));

  return (
    <Fragment>
      <Nav
        theme={theme}
        toggleTheme={toggleTheme}
        onLogo={goHome}
        scrolled={scrolled || view === "run"}
        onStart={() => {
          if (view === "run") goHome();
          else document.querySelector<HTMLTextAreaElement>(".prompt textarea")?.focus();
        }}
      />

      {view === "home" && (
        <Fragment>
          <Hero onSubmit={startResearch} />
          <HowItWorks />
          <FeatureLiveFeed onChip={startResearch} />
          <FeatureSources />
          <ComingSoon />
          <Footer />
        </Fragment>
      )}

      {view === "run" && (
        <RunScreen
          query={query}
          status={status}
          events={events}
          result={result}
          outcome={outcome}
          error={error}
          elapsed={elapsed}
          feedTag={FEED_TAG}
          onBack={goHome}
          onNew={goHome}
        />
      )}
    </Fragment>
  );
}

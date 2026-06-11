/* global React, ReactDOM */
const { useState, useEffect, useRef } = React;
const I = window.NX_ICONS;
const { Markdown, Nav, Hero, HowItWorks, FeatureLiveFeed, FeatureSources, ComingSoon, Footer } = window;
const ND = window.NexusData;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ============================================================
//  Agent activity feed
// ============================================================
function FeedEvent({ e, isLast, running }) {
  const liveCaret = running && isLast;
  const Caret = liveCaret ? <span className="caret" /> : null;

  if (e.kind === "planner") {
    return (
      <div className="ev">
        <div className="ev-rail"><span className={"ev-dot accent" + (liveCaret ? " pulse" : "")} /><span className="ev-line" /></div>
        <div className="ev-body">
          <div className="ev-title"><span className="role">PLANNER</span>{e.title}{Caret}</div>
          <div className="ev-sub">{e.sub}</div>
        </div>
      </div>
    );
  }
  if (e.kind === "plan") {
    return (
      <div className="ev">
        <div className="ev-rail"><span className="ev-dot accent" /><span className="ev-line" /></div>
        <div className="ev-body">
          <div className="ev-title">Research plan · {e.items.length} sub-questions</div>
          <div className="plan-card">
            {e.items.map((q, i) => <div className="pq" key={i}><span className="pn">{i + 1}</span><span>{q}</span></div>)}
          </div>
        </div>
      </div>
    );
  }
  if (e.kind === "researcher" && e.state === "start") {
    return (
      <div className="ev">
        <div className="ev-rail"><span className={"ev-dot accent" + (liveCaret ? " pulse" : "")} /><span className="ev-line" /></div>
        <div className="ev-body">
          <div className="ev-title"><span className="role">RESEARCHER {e.index}/{e.total}</span>{e.question}{Caret}</div>
        </div>
      </div>
    );
  }
  if (e.kind === "tool") {
    const isErr = e.action === "error";
    return (
      <div className={"ev tool" + (isErr ? " err" : "")}>
        <div className="ev-rail"><span className={"ev-dot " + (isErr ? "warn" : "")} /><span className="ev-line" /></div>
        <div className="ev-body">
          <div className="tool-line">
            {e.action === "search" && <React.Fragment><span className="tk">search</span><span>"{e.text}"</span></React.Fragment>}
            {e.action === "read" && <React.Fragment><span className="tk">read</span><span className="dom">{e.domain}</span><span>· {e.title}</span></React.Fragment>}
            {isErr && <React.Fragment><span style={{ display: "inline-flex", width: 14, height: 14 }}>{I.warn}</span><span>{e.text}</span></React.Fragment>}
            {liveCaret && Caret}
          </div>
        </div>
      </div>
    );
  }
  if (e.kind === "researcher" && e.state === "done") {
    return (
      <div className="ev">
        <div className="ev-rail"><span className="ev-dot ok" /><span className="ev-line" /></div>
        <div className="ev-body">
          <div className="ev-title" style={{ fontWeight: 500 }}>Researcher {e.index} done</div>
          <div className="ev-sub">{e.sub}</div>
        </div>
      </div>
    );
  }
  if (e.kind === "writer") {
    const done = e.state === "done";
    return (
      <div className="ev">
        <div className="ev-rail"><span className={"ev-dot " + (done ? "ok" : "accent") + (liveCaret ? " pulse" : "")} />{!isLast && <span className="ev-line" />}</div>
        <div className="ev-body">
          <div className="ev-title"><span className="role">WRITER</span>{e.title}{Caret}</div>
          <div className="ev-sub">{e.sub}</div>
        </div>
      </div>
    );
  }
  return null;
}

function AgentFeed({ events, status, compact }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current && !compact) ref.current.scrollTop = ref.current.scrollHeight;
  }, [events, compact]);
  const running = status === "running" || status === "pending";
  return (
    <div className="feed-shell">
      <div className="feed-bar">
        <span>Agent activity</span>
        <span className="demo-tag"><span className="pip" />Simulated run · streaming-ready</span>
      </div>
      <div className="feed" ref={ref} style={compact ? { maxHeight: "none" } : null}>
        {events.map((e, i) => <FeedEvent key={e.id} e={e} isLast={i === events.length - 1} running={running} />)}
      </div>
    </div>
  );
}

// ============================================================
//  Sources panel (cited + consulted provenance)
// ============================================================
function SourcesPanel({ result, activeCite, onPick, listRef }) {
  const [prov, setProv] = useState(false);
  return (
    <div className="src-panel">
      <div className="src-card">
        <div className="src-card-head">
          <h4>Sources</h4>
          <span className="cnt">{result.sources.length} cited{prov ? ` · ${result.consulted.length} consulted` : ""}</span>
        </div>
        <div className="src-list" ref={listRef}>
          {result.sources.map((s, i) => {
            const n = i + 1;
            return (
              <a key={n} className={"src-item" + (activeCite === n ? " active" : "")} data-n={n} href={s.url} target="_blank" rel="noreferrer"
                onClick={(e) => { onPick(n); }}>
                <span className="sn">{n}</span>
                <div><div className="st">{s.title}</div><div className="su">{s.url.replace(/^https?:\/\//, "")}</div></div>
              </a>
            );
          })}
          {prov && result.consulted.map((s, i) => (
            <a key={"c" + i} className="src-item consulted" href={s.url} target="_blank" rel="noreferrer">
              <span className="sn">·</span>
              <div><div className="st">{s.title}</div><div className="su">{s.url.replace(/^https?:\/\//, "")}</div></div>
            </a>
          ))}
        </div>
        <div className="prov-toggle" onClick={() => setProv(p => !p)}>
          <span className={"switch" + (prov ? " on" : "")} />
          Show everything consulted
        </div>
      </div>
    </div>
  );
}

function GapsCard({ gaps }) {
  if (!gaps || !gaps.length) return null;
  return (
    <div className="gaps-card">
      <h4><span style={{ display: "inline-flex", width: 17, height: 17 }}>{I.warn}</span>Gaps · {gaps.length} unanswered</h4>
      <ul>{gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
    </div>
  );
}

function StateCard({ kind, error, onRetry }) {
  if (kind === "failed") {
    return (
      <div className="state-card failed">
        <div className="sic">{I.warn}</div>
        <h3>This run failed</h3>
        <p>{error || "A system error stopped the research before it finished. No report was produced."}</p>
        <button className="btn btn-primary" onClick={onRetry}>Try again</button>
      </div>
    );
  }
  return (
    <div className="state-card empty">
      <div className="sic">{I.empty}</div>
      <h3>No sources found</h3>
      <p>The agents ran successfully but couldn't find evidence to answer this question. That's a valid result — try rewording it, or narrowing the scope.</p>
      <button className="btn btn-primary" onClick={onRetry}>Edit & retry</button>
    </div>
  );
}

// ============================================================
//  Run screen (running → complete | failed | empty)
// ============================================================
function RunScreen({ query, status, events, result, outcome, error, elapsed, onBack, onNew }) {
  const [activeCite, setActiveCite] = useState(null);
  const [showActivity, setShowActivity] = useState(false);
  const listRef = useRef(null);

  const onCite = (n) => {
    setActiveCite(n);
    const c = listRef.current;
    if (c) {
      const el = c.querySelector(`[data-n="${n}"]`);
      if (el) c.scrollTop += el.getBoundingClientRect().top - c.getBoundingClientRect().top - 8;
    }
  };

  const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const statusLabel = status === "complete" ? "complete" : status === "failed" ? "failed" : "running";

  const isComplete = status === "complete" && outcome === "ok";
  const isFailed = status === "failed" || outcome === "failed";
  const isEmpty = status === "complete" && outcome === "empty";

  return (
    <main className="run">
      <div className="wrap">
        <div className="run-head">
          <button className="run-back" onClick={onBack} title="Back" aria-label="Back">{I.arrowLeft}</button>
          <div className="run-q">
            <div className="eyebrow">Research query</div>
            <h1>{query}</h1>
          </div>
          <div className={"run-status " + statusLabel}>
            <span className="sd" />{statusLabel}<span className="elapsed">· {fmt(elapsed)}</span>
          </div>
        </div>

        {(status === "running" || status === "pending") && <AgentFeed events={events} status={status} />}

        {isComplete && (
          <React.Fragment>
            <button className="btn btn-ghost" style={{ marginBottom: 8 }} onClick={() => setShowActivity(s => !s)}>
              {I.feed}{showActivity ? "Hide" : "Show"} agent activity · {events.length} steps
            </button>
            {showActivity && <div style={{ marginBottom: 18 }}><AgentFeed events={events} status="complete" compact /></div>}

            <div className="report-grid">
              <div>
                <article className="report">
                  <Markdown text={result.report} onCite={onCite} activeCite={activeCite} />
                  <div className="report-foot">
                    <button className="btn btn-primary" onClick={onNew}>New research</button>
                    <button className="btn btn-ghost">Copy report</button>
                    <button className="btn btn-ghost">Re-run</button>
                  </div>
                </article>
              </div>
              <div className="src-panel-col" style={{ display: "grid", gap: 16 }}>
                <SourcesPanel result={result} activeCite={activeCite} onPick={onCite} listRef={listRef} />
                <GapsCard gaps={result.gaps} />
              </div>
            </div>
          </React.Fragment>
        )}

        {isEmpty && <StateCard kind="empty" onRetry={onBack} />}
        {isFailed && <StateCard kind="failed" error={error} onRetry={onBack} />}
      </div>
    </main>
  );
}

// ============================================================
//  App
// ============================================================
function App() {
  const [theme, setTheme] = useState(document.documentElement.getAttribute("data-theme") || "dark");
  const [view, setView] = useState("home"); // home | run
  const [query, setQuery] = useState("");
  const [events, setEvents] = useState([]);
  const [status, setStatus] = useState("pending"); // pending | running | complete | failed
  const [result, setResult] = useState(null);
  const [outcome, setOutcome] = useState("ok"); // ok | empty | failed
  const [error, setError] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const [scrolled, setScrolled] = useState(false);

  const runId = useRef(0);
  const startRef = useRef(0);

  // theme side-effects
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("nexus-theme", theme); } catch (e) {}
    if (window.setFluidTheme) window.setFluidTheme(theme);
  }, [theme]);

  // body stage (dims the fluid bg behind dense content)
  useEffect(() => {
    document.body.dataset.stage = view === "home" ? "home" : (status === "complete" ? "report" : "run");
  }, [view, status]);

  // debug hook: jump straight to a completed report (used for verification)
  useEffect(() => {
    window.__nxDemo = (i = 0) => {
      const run = ND.PRESETS[i] || ND.PRESETS[0];
      const { timeline, result: res } = ND.toTimeline(run);
      runId.current++;
      setView("run"); setQuery(run.prompt); setEvents(timeline);
      setResult(res); setOutcome("ok"); setError(null); setStatus("complete");
      window.scrollTo(0, 0);
    };
  }, []);

  // elapsed timer while running
  useEffect(() => {
    if (status !== "running" && status !== "pending") return;
    const id = setInterval(() => setElapsed((performance.now() - startRef.current) / 1000), 100);
    return () => clearInterval(id);
  }, [status]);

  // nav shadow on scroll
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 16);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  async function startResearch(prompt) {
    const runObj = ND.pickRun(prompt);
    const { timeline, result: res } = ND.toTimeline(runObj);

    // outcome easter-eggs to exercise honest states
    let oc = "ok";
    const p = prompt.toLowerCase();
    if (/^fail\b/.test(p)) oc = "failed";
    else if (/^empty\b/.test(p)) oc = "empty";

    const myId = ++runId.current;
    setView("run"); setQuery(prompt); setEvents([]); setResult(null);
    setOutcome(oc); setError(null); setElapsed(0);
    startRef.current = performance.now();
    setStatus("running");
    window.scrollTo(0, 0);

    for (const e of timeline) {
      await sleep(e.delay);
      if (runId.current !== myId) return;
      // a failed run dies partway through the writer
      if (oc === "failed" && e.kind === "writer" && e.state === "done") {
        setError("The writer agent lost its connection to the model provider (502). Re-running usually clears it.");
        setStatus("failed");
        return;
      }
      setEvents((prev) => [...prev, e]);
    }
    if (runId.current !== myId) return;
    setResult(oc === "empty" ? { ...res, report: "", sources: [], consulted: [], gaps: [] } : res);
    setStatus("complete");
  }

  function goHome() {
    runId.current++;
    setView("home");
    setStatus("pending");
    window.scrollTo(0, 0);
  }

  const toggleTheme = () => setTheme((t) => (t === "dark" ? "light" : "dark"));

  return (
    <React.Fragment>
      <Nav theme={theme} toggleTheme={toggleTheme} onLogo={goHome} scrolled={scrolled || view === "run"}
        onStart={() => { if (view === "run") goHome(); else document.querySelector(".prompt textarea")?.focus(); }} />

      {view === "home" && (
        <React.Fragment>
          <Hero onSubmit={startResearch} />
          <HowItWorks />
          <FeatureLiveFeed onChip={startResearch} />
          <FeatureSources />
          <ComingSoon />
          <Footer />
        </React.Fragment>
      )}

      {view === "run" && (
        <RunScreen
          query={query} status={status} events={events} result={result}
          outcome={outcome} error={error} elapsed={elapsed}
          onBack={goHome} onNew={goHome}
        />
      )}
    </React.Fragment>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);

/* global React */
const { useState, useEffect, useRef } = React;

// ============================================================
//  Icons (simple line set)
// ============================================================
const I = {
  sun: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>,
  moon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>,
  arrowUp: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>,
  arrowLeft: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>,
  check: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5"/></svg>,
  plan: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4" cy="6" r="1.4"/><circle cx="4" cy="12" r="1.4"/><circle cx="4" cy="18" r="1.4"/></svg>,
  search: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>,
  cite: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/><path d="M9 13h6M9 17h4"/></svg>,
  feed: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M4 6h16M4 12h10M4 18h7"/><circle cx="19" cy="16" r="3"/></svg>,
  shield: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z"/><path d="M9 12l2 2 4-4"/></svg>,
  doc: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/></svg>,
  layers: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/></svg>,
  warn: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>,
  empty: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3M8 11h6"/></svg>,
  ext: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M7 17L17 7M7 7h10v10"/></svg>,
  history: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 4v4h4M12 8v4l3 2"/></svg>,
};

// ============================================================
//  Markdown (subset) with [n] citations
// ============================================================
function citeNodes(str, kp, onCite, activeCite) {
  return str.split(/(\[\d+\])/g).map((p, i) => {
    const m = p.match(/^\[(\d+)\]$/);
    if (m) {
      const n = +m[1];
      return <sup key={kp + "c" + i} className={"cite" + (activeCite === n ? " active" : "")} onClick={() => onCite(n)}>[{n}]</sup>;
    }
    return <React.Fragment key={kp + "t" + i}>{p}</React.Fragment>;
  });
}
function inline(str, kp, onCite, activeCite) {
  return str.split(/(\*\*[^*]+\*\*)/g).map((s, i) => {
    const b = s.match(/^\*\*([^*]+)\*\*$/);
    if (b) return <strong key={kp + "b" + i}>{citeNodes(b[1], kp + "b" + i, onCite, activeCite)}</strong>;
    return <React.Fragment key={kp + "s" + i}>{citeNodes(s, kp + "s" + i, onCite, activeCite)}</React.Fragment>;
  });
}
function Markdown({ text, onCite, activeCite }) {
  const blocks = text.trim().split(/\n\n+/);
  return (
    <div className="doc">
      {blocks.map((blk, bi) => {
        if (blk.startsWith("## ")) return <h2 key={bi}>{inline(blk.slice(3), "h" + bi, onCite, activeCite)}</h2>;
        if (blk.startsWith("### ")) return <h3 key={bi}>{inline(blk.slice(4), "h" + bi, onCite, activeCite)}</h3>;
        if (blk.startsWith("> ")) return <blockquote key={bi}>{inline(blk.slice(2), "q" + bi, onCite, activeCite)}</blockquote>;
        if (blk.split("\n").every(l => l.startsWith("- "))) {
          return <ul key={bi}>{blk.split("\n").map((l, li) => <li key={li}>{inline(l.slice(2), "l" + bi + li, onCite, activeCite)}</li>)}</ul>;
        }
        return <p key={bi}>{inline(blk, "p" + bi, onCite, activeCite)}</p>;
      })}
    </div>
  );
}

// ============================================================
//  Nav
// ============================================================
function Nav({ theme, toggleTheme, onLogo, scrolled, onStart }) {
  return (
    <nav className={"nav" + (scrolled ? " scrolled" : "")}>
      <div className="wrap">
        <div className="brand" onClick={onLogo}>
          <div className="brand-mark">≈</div>
          <span className="brand-name">Nexus</span>
        </div>
        <div className="nav-links">
          <a className="nav-link" href="#how">How it works</a>
          <a className="nav-link" href="#feed">Live agents</a>
          <a className="nav-link" href="#sources">Citations</a>
          <a className="nav-link" href="#soon">Documents</a>
        </div>
        <div className="nav-right">
          <button className="theme-toggle" onClick={toggleTheme} aria-label="Toggle theme" title="Toggle theme">
            {theme === "dark" ? I.sun : I.moon}
          </button>
          <a className="nav-link" href="#">Sign in</a>
          <button className="btn btn-primary" onClick={onStart}>Start researching</button>
        </div>
      </div>
    </nav>
  );
}

// ============================================================
//  Hero + prompt box
// ============================================================
function Hero({ onSubmit }) {
  const [val, setVal] = useState("");
  const taRef = useRef(null);
  const headline = ["Ask anything.", "Get a cited answer."];

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 180) + "px";
  }, [val]);

  const submit = () => { if (val.trim()) onSubmit(val.trim()); };
  const onKey = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } };

  let ci = 0;
  return (
    <header className="hero">
      <div className="wrap">
        <div className="hero-badge"><span className="pip"></span>A team of agents researches for you · <b>cited, in real time</b></div>
        <h1>
          {headline.map((line, li) => (
            <span className="word" key={li} style={{ display: "block" }}>
              {line.split("").map((ch, k) => {
                const d = (ci++) * 0.028 + 0.5;
                const cls = li === 1 ? "char grad" : "char";
                return <span key={k} className={cls} style={{ animationDelay: d + "s" }}>{ch === " " ? "\u00A0" : ch}</span>;
              })}
            </span>
          ))}
        </h1>
        <p className="hero-sub">
          Nexus plans your question into sub-questions, sends a team of agents to research the live web,
          and returns one report where every claim is backed by a source.
        </p>

        <div className="prompt-wrap">
          <div className="prompt">
            <textarea
              ref={taRef}
              rows={1}
              value={val}
              onChange={(e) => setVal(e.target.value)}
              onKeyDown={onKey}
              placeholder="Ask Nexus to research anything…"
            />
            <button className="prompt-go" onClick={submit} disabled={!val.trim()} aria-label="Start research">
              {I.arrowUp}
            </button>
          </div>
          <div className="prompt-meta">
            <span>Press <b style={{ color: "var(--muted)" }}>Enter</b> to research · Shift+Enter for a new line</span>
            <span className="steps-mini">
              <span className="dot"></span>Plan<span className="arrow">→</span>Research<span className="arrow">→</span>Cite
            </span>
          </div>
          <div className="chips">
            {window.NexusData.PRESETS.map((p, i) => (
              <button key={i} className="chip" onClick={() => onSubmit(p.prompt)}>{p.prompt}</button>
            ))}
          </div>
        </div>
      </div>
    </header>
  );
}

// ============================================================
//  Marketing sections (idle only)
// ============================================================
function HowItWorks() {
  const steps = [
    { ic: I.plan, n: "01", t: "Plan", d: "A planner agent breaks your question into focused sub-questions — the research strategy, made explicit." },
    { ic: I.search, n: "02", t: "Research", d: "A researcher works each sub-question in parallel against the live web — searching, reading, and extracting evidence." },
    { ic: I.cite, n: "03", t: "Cite", d: "A writer synthesizes the findings into one report where every claim links to the source that backs it." },
  ];
  return (
    <section className="section" id="how">
      <div className="wrap">
        <div className="section-head">
          <span className="eyebrow">How it works</span>
          <h2>A research team, working in the open.</h2>
          <p>Not one model guessing — a pipeline of agents that plan, gather evidence, and write. You watch every step.</p>
        </div>
        <div className="steps-grid">
          {steps.map((s, i) => (
            <div className="step-card" key={i}>
              <div className="step-num">{s.n}</div>
              <div className="step-ic">{s.ic}</div>
              <h3>{s.t}</h3>
              <p>{s.d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function FeatureLiveFeed({ onChip }) {
  return (
    <section className="section" id="feed">
      <div className="wrap">
        <div className="feature-row">
          <div className="feature-copy">
            <span className="eyebrow">Live agent feed</span>
            <h2>Watch the research happen.</h2>
            <p>Most tools hand you an answer and hope you trust it. Nexus shows its work — the plan, every search, every page read, and where a lead fell through.</p>
            <ul className="feature-list">
              <li><span className="tick">{I.check}</span>The plan and its sub-questions, the moment they're formed.</li>
              <li><span className="tick">{I.check}</span>Each search query and page the agents read, as it streams.</li>
              <li><span className="tick">{I.check}</span>Failures degrade honestly into "gaps" — never silent.</li>
            </ul>
            <button className="btn btn-ghost" onClick={() => onChip(window.NexusData.PRESETS[0].prompt)}>See a live run</button>
          </div>
          <div className="feature-visual">
            <div className="mini-feed">
              <div className="mini-row done"><span className="md"></span><div><b>Planner</b> · created a 3-part plan</div></div>
              <div className="mini-row done"><span className="md"></span><div><b>Researcher 1</b> · 2 sources<div className="ind">→ search "LFP cost per kWh"</div><div className="ind">↳ read iea.org</div></div></div>
              <div className="mini-row run"><span className="md"></span><div><b>Researcher 2</b> · reading…<div className="ind">↳ read nrel.gov</div></div></div>
              <div className="mini-row idle"><span className="md"></span><div><b>Writer</b> · queued</div></div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function FeatureSources() {
  const [hot, setHot] = useState(1);
  return (
    <section className="section" id="sources">
      <div className="wrap">
        <div className="feature-row flip">
          <div className="feature-copy">
            <span className="eyebrow">Citations, first-class</span>
            <h2>Every claim, traceable.</h2>
            <p>Click any <span style={{ color: "var(--accent)", fontFamily: "var(--font-mono)" }}>[n]</span> to jump to its source. Flip on provenance to separate the sources that back the claims from everything the agents merely consulted.</p>
            <ul className="feature-list">
              <li><span className="tick">{I.check}</span>A persistent, numbered Sources panel.</li>
              <li><span className="tick">{I.check}</span>Cited vs. consulted — an honest audit trail.</li>
              <li><span className="tick">{I.check}</span>"Found nothing" is a valid result, shown plainly.</li>
            </ul>
          </div>
          <div className="feature-visual">
            <div className="mini-src">
              <div className="mini-claim">LFP now dominates new stationary projects on cost and cycle-life grounds<sup onClick={() => setHot(2)}>[2]</sup>, while long-duration storage moves into first deployments<sup onClick={() => setHot(3)}>[3]</sup>.</div>
              <div className="mini-src-list">
                {[{ n: 2, t: "2025 Battery Price Survey", u: "about.bnef.com" }, { n: 3, t: "Long-Duration Energy Storage", u: "nrel.gov" }].map(s => (
                  <div key={s.n} className={"mini-src-item" + (hot === s.n ? " hot" : "")} onClick={() => setHot(s.n)}>
                    <span className="n">{s.n}</span><div><div style={{ color: "var(--fg)", fontWeight: 600 }}>{s.t}</div><div>{s.u}</div></div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function ComingSoon() {
  const items = [
    { ic: I.feed, t: "Live streaming", d: "Polling today, server-sent events next — the feed is built for it." },
    { ic: I.history, t: "Research history", d: "Every query you run, saved and searchable, scoped to you." },
    { ic: I.layers, t: "Provenance audit", d: "Separate cited sources from everything consulted." },
    { ic: I.doc, t: "Your private documents", d: "Upload files; research them alongside the live web. Next phase." },
  ];
  return (
    <section className="section" id="soon">
      <div className="wrap">
        <div className="section-head">
          <span className="eyebrow">On the roadmap</span>
          <h2>Built forward-compatible.</h2>
          <p>The interface is designed for what's shipping next — no rebuild required.</p>
        </div>
        <div className="steps-grid" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
          {items.map((s, i) => (
            <div className="step-card" key={i}>
              <div className="step-ic">{s.ic}</div>
              <h3>{s.t}</h3>
              <p>{s.d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="footer">
      <div className="wrap">
        <div className="footer-brand">
          <div className="brand">
            <div className="brand-mark">≈</div>
            <span className="brand-name">Nexus</span>
          </div>
          <p>An API-first agentic research platform. Ask a question; a team of agents returns a cited report.</p>
        </div>
        <div className="footer-cols">
          <div className="footer-col">
            <h5>Product</h5>
            <a href="#how">How it works</a>
            <a href="#feed">Live agents</a>
            <a href="#sources">Citations</a>
            <a href="#soon">Roadmap</a>
          </div>
          <div className="footer-col">
            <h5>Developers</h5>
            <a href="#">API reference</a>
            <a href="#">Authentication</a>
            <a href="#">Self-hosting</a>
            <a href="#">Status</a>
          </div>
          <div className="footer-col">
            <h5>Company</h5>
            <a href="#">About</a>
            <a href="#">Privacy</a>
            <a href="#">Terms</a>
          </div>
        </div>
      </div>
      <div className="wrap"><div className="footer-note">Nexus · deep research, cited. Polling-based today, streaming-ready tomorrow.</div></div>
    </footer>
  );
}

Object.assign(window, {
  NX_ICONS: I, Markdown, Nav, Hero, HowItWorks, FeatureLiveFeed, FeatureSources, ComingSoon, Footer,
});

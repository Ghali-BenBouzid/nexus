import { useState } from "react";

import { I } from "../icons";
import { PRESETS } from "../lib/simulatedEngine";

export function HowItWorks() {
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

export function FeatureLiveFeed({ onChip }: { onChip: (prompt: string) => void }) {
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
            <button className="btn btn-ghost" onClick={() => onChip(PRESETS[0].prompt)}>See a live run</button>
          </div>
          <div className="feature-visual">
            <div className="mini-feed">
              <div className="mini-row done"><span className="md" /><div><b>Planner</b> · created a 3-part plan</div></div>
              <div className="mini-row done"><span className="md" /><div><b>Researcher 1</b> · 2 sources<div className="ind">→ search "LFP cost per kWh"</div><div className="ind">↳ read iea.org</div></div></div>
              <div className="mini-row run"><span className="md" /><div><b>Researcher 2</b> · reading…<div className="ind">↳ read nrel.gov</div></div></div>
              <div className="mini-row idle"><span className="md" /><div><b>Writer</b> · queued</div></div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export function FeatureSources() {
  const [hot, setHot] = useState(1);
  const items = [
    { n: 2, t: "2025 Battery Price Survey", u: "about.bnef.com" },
    { n: 3, t: "Long-Duration Energy Storage", u: "nrel.gov" },
  ];
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
              <div className="mini-claim">
                LFP now dominates new stationary projects on cost and cycle-life grounds
                <sup onClick={() => setHot(2)}>[2]</sup>, while long-duration storage moves into first
                deployments<sup onClick={() => setHot(3)}>[3]</sup>.
              </div>
              <div className="mini-src-list">
                {items.map((s) => (
                  <div key={s.n} className={"mini-src-item" + (hot === s.n ? " hot" : "")} onClick={() => setHot(s.n)}>
                    <span className="n">{s.n}</span>
                    <div>
                      <div style={{ color: "var(--fg)", fontWeight: 600 }}>{s.t}</div>
                      <div>{s.u}</div>
                    </div>
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

export function ComingSoon() {
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

export function Footer() {
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
      <div className="wrap">
        <div className="footer-note">Nexus · deep research, cited. Polling-based today, streaming-ready tomorrow.</div>
      </div>
    </footer>
  );
}

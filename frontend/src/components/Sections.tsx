import { useEffect, useRef, useState } from "react";

import { t } from "../lib/i18n";
import { NexusLockup } from "./NexusLogo";

const REPO_URL = "https://github.com/Ghali-BenBouzid/nexus";
const PORTFOLIO_URL = "https://ghalibenbouzid.com";

// ---- What it is: plain intro, proof row, and a quiet "built with" strip ----
export function About() {
  return (
    <section className="section" id="about">
      <div className="wrap">
        <div className="section-head">
          <h2>{t.about.title}</h2>
          <p>{t.about.body}</p>
        </div>
        <ul className="proof-row">
          {t.about.proof.map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
        <p className="built-with">
          <span>{t.about.builtWithLabel}</span> {t.about.builtWith}
        </p>
        <div className="about-links">
          <a className="btn btn-ghost" href={REPO_URL} target="_blank" rel="noreferrer">
            {t.about.sourceLink}
          </a>
        </div>
      </div>
    </section>
  );
}

// Hover/tap detail for each node: not just what it does, but why it's built that
// way. The consolidate/write notes carry the hallucination-mitigation argument.
const HIW_PARTS = t.hiw.parts;
const HIW_DEFAULT = t.hiw.default;
const L = t.hiw.labels;

// ---- How it works: the orchestrator workflow as a directed graph ----
export function HowItWorks() {
  const figRef = useRef<HTMLElement>(null);
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    const el = figRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          el.classList.add("in");
          io.disconnect();
        }
      },
      { threshold: 0.2 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // Researcher stack: three web agents plus a dashed "Documents (RAG)" slot.
  const rows = [
    { cy: 100, rag: false },
    { cy: 160, rag: false },
    { cy: 220, rag: false },
    { cy: 286, rag: true },
  ];

  const bind = (id: string, label: string) => ({
    tabIndex: 0,
    role: "button",
    "aria-label": label,
    onMouseEnter: () => setActive(id),
    onMouseLeave: () => setActive(null),
    onFocus: () => setActive(id),
    onBlur: () => setActive(null),
    onClick: () => setActive((a) => (a === id ? null : id)),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        setActive((a) => (a === id ? null : id));
      }
    },
  });

  return (
    <section className="section" id="how">
      <div className="wrap">
        <div className="section-head">
          <h2>{t.hiw.title}</h2>
        </div>

        <figure className="hiw" ref={figRef}>
          <svg className="hiw-svg" viewBox="0 0 980 380" role="img" aria-label={t.hiw.aria}>
            <defs>
              <marker id="hiw-arrow" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6" className="hiw-arrowhead" />
              </marker>
            </defs>

            <rect className="hiw-orch" x="70" y="28" width="840" height="324" rx="18" />
            <text className="hiw-orch-label" x="92" y="52">{L.orchestrator}</text>

            <path className="hiw-edge flow" d="M20,190 H104" markerEnd="url(#hiw-arrow)" pathLength={1} />
            {rows.map((r, i) => (
              <path key={"fo" + i} className="hiw-edge" d={`M224,190 C292,190 292,${r.cy} 348,${r.cy}`} pathLength={1} />
            ))}
            {rows.map((r, i) => (
              <path key={"fi" + i} className="hiw-edge" d={`M524,${r.cy} C566,${r.cy} 566,190 600,190`} pathLength={1} />
            ))}
            <path className="hiw-edge flow" d="M730,190 H760" markerEnd="url(#hiw-arrow)" pathLength={1} />
            <path className="hiw-edge flow" d="M870,190 H958" markerEnd="url(#hiw-arrow)" pathLength={1} />

            <text className="hiw-io" x="20" y="176">{L.question}</text>
            <text className="hiw-io" x="978" y="176" textAnchor="end">{L.citedReport}</text>
            <text className="hiw-stack-label" x="436" y="58" textAnchor="middle">{L.fanout}</text>

            <g className={"hiw-node" + (active === "plan" ? " active" : "")} {...bind("plan", L.plan)}>
              <rect x="104" y="150" width="120" height="80" rx="12" />
              <text className="hiw-title" x="164" y="186" textAnchor="middle">{L.plan}</text>
              <text className="hiw-role" x="164" y="206" textAnchor="middle">{L.planRole}</text>
            </g>

            {rows.map((r, i) => {
              const id = r.rag ? "documents" : "researcher";
              return (
                <g
                  key={"n" + i}
                  className={"hiw-node" + (r.rag ? " rag" : "") + (active === id ? " active" : "")}
                  {...bind(id, r.rag ? L.documents : L.researcher)}
                >
                  <rect x="348" y={r.cy - 22} width="176" height="44" rx="11" />
                  <text className="hiw-title sm" x="436" y={r.cy + (r.rag ? -2 : 5)} textAnchor="middle">
                    {r.rag ? L.documents : L.researcher}
                  </text>
                  {r.rag && (
                    <text className="hiw-role" x="436" y={r.cy + 13} textAnchor="middle">
                      {L.docRole}
                    </text>
                  )}
                </g>
              );
            })}

            <g className={"hiw-node" + (active === "consolidate" ? " active" : "")} {...bind("consolidate", L.consolidate)}>
              <rect x="600" y="150" width="130" height="80" rx="12" />
              <text className="hiw-title" x="665" y="186" textAnchor="middle">{L.consolidate}</text>
              <text className="hiw-role" x="665" y="206" textAnchor="middle">{L.consolidateRole}</text>
            </g>

            <g className={"hiw-node" + (active === "write" ? " active" : "")} {...bind("write", L.write)}>
              <rect x="760" y="150" width="110" height="80" rx="12" />
              <text className="hiw-title" x="815" y="186" textAnchor="middle">{L.write}</text>
              <text className="hiw-role" x="815" y="206" textAnchor="middle">{L.writeRole}</text>
            </g>
          </svg>

          {/* Mobile fallback: the same flow, stacked and readable. */}
          <div className="hiw-stack-wrap" aria-hidden="true">
            <span className="hiw-stack-orch">{L.orchestrator}</span>
            <ol className="hiw-stack">
              {t.hiw.stack.map((s, i) => (
                <li key={i} className={i === 2 ? "rag" : undefined}>
                  <b>{s.lead}</b>
                  {s.rest}
                </li>
              ))}
            </ol>
          </div>

          <figcaption className={"hiw-cap" + (active ? " on" : "")} aria-live="polite">{active ? HIW_PARTS[active] : HIW_DEFAULT}</figcaption>
        </figure>
      </div>
    </section>
  );
}

// ---- Engineering challenges: Problem -> how I solved it -> why it matters ----
export function Engineering() {
  return (
    <section className="section" id="engineering">
      <div className="wrap">
        <div className="section-head">
          <h2>{t.eng.title}</h2>
        </div>
        <ul className="took-list">
          {t.eng.challenges.map((c, i) => (
            <li key={i} className="took-item">
              <h3>{c.problem}</h3>
              <p>{c.how}</p>
              <p className="took-why">
                <span>{t.eng.why}</span>
                {c.why}
              </p>
            </li>
          ))}
        </ul>
        <div className="whats-next">
          <h3>{t.eng.nextTitle}</h3>
          <p className="next-intro">{t.eng.nextIntro}</p>
          <ul className="acad-list muted">
            {t.eng.next.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
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
            <NexusLockup size={24} />
          </div>
          <p>
            {t.footer.builtBy}
            <br />
            {t.footer.restPre}
            <a className="footer-loop" href={PORTFOLIO_URL} target="_blank" rel="noreferrer">
              ghalibenbouzid.com
            </a>
            {t.footer.restPost}
          </p>
        </div>
        <div className="footer-cols">
          <div className="footer-col">
            <h3>{t.footer.exploreTitle}</h3>
            <a href="#about">{t.nav.about}</a>
            <a href="#how">{t.nav.how}</a>
            <a href="#engineering">{t.nav.engineering}</a>
          </div>
          <div className="footer-col">
            <h3>{t.footer.codeTitle}</h3>
            <a href={REPO_URL} target="_blank" rel="noreferrer">{t.footer.source}</a>
            <a href={`${REPO_URL}/tree/main/app`} target="_blank" rel="noreferrer">{t.footer.agentOrch}</a>
          </div>
        </div>
      </div>
      <div className="wrap">
        <div className="footer-note">{t.footer.note}</div>
      </div>
    </footer>
  );
}

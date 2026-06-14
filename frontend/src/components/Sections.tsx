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
    { cy: 300, rag: false },
    { cy: 352, rag: false },
    { cy: 404, rag: false },
    { cy: 456, rag: true },
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
          <svg className="hiw-svg" viewBox="0 0 1320 540" role="img" aria-label={t.hiw.aria}>
            <defs>
              <marker id="hiw-arrow" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6" className="hiw-arrowhead" />
              </marker>
            </defs>

            {/* Two lanes: the conversation lane (the supervisor agent and its three
                moves) sits above the research subgraph it can launch. */}
            <rect className="hiw-orch" x="230" y="250" width="932" height="272" rx="18" />
            <text className="hiw-orch-label" x="252" y="276">{L.orchestrator}</text>

            {/* Conversation lane: message in, then the supervisor's three routes. */}
            <path className="hiw-edge flow" d="M52,146 H67" markerEnd="url(#hiw-arrow)" pathLength={1} />
            {/* answer: a short branch up from the supervisor's centre to a reply (terminal). */}
            <path className="hiw-edge flow" d="M152,100 V62" markerEnd="url(#hiw-arrow)" pathLength={1} />
            {/* compose: across the top to the Compose node, then down into Write. */}
            <path className="hiw-edge flow" d="M234,124 H1005" markerEnd="url(#hiw-arrow)" pathLength={1} />
            <path className="hiw-edge flow" d="M1085,158 V343" markerEnd="url(#hiw-arrow)" pathLength={1} />
            {/* research: down into the plan step, kept left of the orchestrator title. */}
            <path className="hiw-edge flow" d="M152,192 C 158,300 248,312 282,343" markerEnd="url(#hiw-arrow)" pathLength={1} />

            {/* Research subgraph edges. */}
            <path className="hiw-edge flow" d="M362,385 H392" markerEnd="url(#hiw-arrow)" pathLength={1} />
            {/* The revise arc loops the review back to re-plan. */}
            <path className="hiw-edge" d="M495,345 C 486,302 362,302 332,343" markerEnd="url(#hiw-arrow)" pathLength={1} />
            {/* Confirm fans the approved plan out to the researchers, and back in. */}
            {rows.map((r, i) => (
              <path key={"fo" + i} className="hiw-edge" d={`M522,385 H582 C 602,385 602,${r.cy} 636,${r.cy}`} pathLength={1} />
            ))}
            {rows.map((r, i) => (
              <path key={"fi" + i} className="hiw-edge" d={`M812,${r.cy} C 850,${r.cy} 850,385 876,385`} pathLength={1} />
            ))}
            <path className="hiw-edge flow" d="M1006,385 H1032" markerEnd="url(#hiw-arrow)" pathLength={1} />
            <path className="hiw-edge flow" d="M1144,385 H1198" markerEnd="url(#hiw-arrow)" pathLength={1} />

            <text className="hiw-io" x="2" y="150">{L.message}</text>
            <text className="hiw-io" x="152" y="52" textAnchor="middle">{L.directAnswer}</text>
            <text className="hiw-io" x="1206" y="389">{L.citedReport}</text>
            <text className="hiw-stack-label" x="724" y="276" textAnchor="middle">{L.fanout}</text>
            <text className="hiw-gate-label" x="600" y="114" textAnchor="middle">{L.routeCompose}</text>
            <text className="hiw-gate-label" x="150" y="254" textAnchor="end">{L.routeResearch}</text>
            <text className="hiw-gate-label" x="424" y="300" textAnchor="middle">{L.revise}</text>
            <text className="hiw-gate-label" x="560" y="374" textAnchor="middle">{L.confirm}</text>

            {/* Supervisor: the agent the user talks to; sits above the subgraph. */}
            <g className={"hiw-node" + (active === "supervisor" ? " active" : "")} {...bind("supervisor", L.supervisor)}>
              <rect x="70" y="100" width="164" height="92" rx="12" />
              <text className="hiw-title" x="152" y="136" textAnchor="middle">{L.supervisor}</text>
              <text className="hiw-role" x="152" y="156" textAnchor="middle">{L.supervisorRole}</text>
              <text className="hiw-sub" x="152" y="174" textAnchor="middle">{L.supervisorTools}</text>
            </g>

            {/* Compose: merge existing reports into one new report, no new search. */}
            <g className={"hiw-node" + (active === "compose" ? " active" : "")} {...bind("compose", L.compose)}>
              <rect x="1010" y="98" width="150" height="62" rx="12" />
              <text className="hiw-title sm" x="1085" y="125" textAnchor="middle">{L.compose}</text>
              <text className="hiw-role" x="1085" y="143" textAnchor="middle">{L.composeRole}</text>
            </g>

            <g className={"hiw-node" + (active === "plan" ? " active" : "")} {...bind("plan", L.plan)}>
              <rect x="250" y="345" width="112" height="80" rx="12" />
              <text className="hiw-title" x="306" y="381" textAnchor="middle">{L.plan}</text>
              <text className="hiw-role" x="306" y="401" textAnchor="middle">{L.planRole}</text>
            </g>

            {/* Human-in-the-loop review: accent-styled, with a revise loop to Plan. */}
            <g className={"hiw-node hiw-human" + (active === "review" ? " active" : "")} {...bind("review", L.review)}>
              <rect x="392" y="345" width="130" height="80" rx="12" />
              <text className="hiw-title" x="457" y="381" textAnchor="middle">{L.review}</text>
              <text className="hiw-role" x="457" y="401" textAnchor="middle">{L.reviewRole}</text>
            </g>

            {rows.map((r, i) => {
              const id = r.rag ? "documents" : "researcher";
              return (
                <g
                  key={"n" + i}
                  className={"hiw-node" + (r.rag ? " rag" : "") + (active === id ? " active" : "")}
                  {...bind(id, r.rag ? L.documents : L.researcher)}
                >
                  <rect x="636" y={r.cy - 22} width="176" height="44" rx="11" />
                  <text className="hiw-title sm" x="724" y={r.cy + (r.rag ? -2 : 5)} textAnchor="middle">
                    {r.rag ? L.documents : L.researcher}
                  </text>
                  {r.rag && (
                    <text className="hiw-role" x="724" y={r.cy + 13} textAnchor="middle">
                      {L.docRole}
                    </text>
                  )}
                </g>
              );
            })}

            <g className={"hiw-node" + (active === "consolidate" ? " active" : "")} {...bind("consolidate", L.consolidate)}>
              <rect x="876" y="345" width="130" height="80" rx="12" />
              <text className="hiw-title" x="941" y="381" textAnchor="middle">{L.consolidate}</text>
              <text className="hiw-role" x="941" y="401" textAnchor="middle">{L.consolidateRole}</text>
            </g>

            <g className={"hiw-node" + (active === "write" ? " active" : "")} {...bind("write", L.write)}>
              <rect x="1032" y="345" width="112" height="80" rx="12" />
              <text className="hiw-title" x="1088" y="381" textAnchor="middle">{L.write}</text>
              <text className="hiw-role" x="1088" y="401" textAnchor="middle">{L.writeRole}</text>
            </g>
          </svg>

          {/* Mobile fallback: the same flow, stacked and readable. */}
          <div className="hiw-stack-wrap" aria-hidden="true">
            <span className="hiw-stack-orch">{L.orchestrator}</span>
            <ol className="hiw-stack">
              {t.hiw.stack.map((s, i) => (
                <li key={i} className={i === 3 ? "rag" : undefined}>
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

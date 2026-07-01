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
        <div className="built-with">
          <span className="built-with-label">{t.about.builtWithLabel}</span>
          <div className="stack-grid">
            {t.about.builtWith.map((group) => (
              <div className="stack-col" key={group.label}>
                <h3 className="stack-col-head">{group.label}</h3>
                <ul className="stack-col-list">
                  {group.items.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
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

// Flow-light spine: the ordered primary path (branches stay static). `i` is the
// segment's position along the path so the single light hands off start -> end. The
// `d` strings mirror the base edges below; keep them in sync. The fan-out/in conduit
// uses the middle researcher row so the light passes through the research subgraph.
const HIW_FLOW = [
  { d: "M28,146 H67", i: 0 }, // message -> supervisor (start)
  { d: "M164,192 C 164,302 250,312 282,343", i: 1 }, // route research -> plan
  { d: "M362,385 H389", i: 2 }, // plan -> review
  // Split: the packet fans out into the three active researcher lanes at once.
  { d: "M522,385 H582 C 602,385 602,300 636,300", i: 3 },
  { d: "M522,385 H582 C 602,385 602,352 636,352", i: 3 },
  { d: "M522,385 H582 C 602,385 602,404 636,404", i: 3 },
  // Recombine: the three lanes converge back into consolidate.
  { d: "M812,300 C 850,300 850,385 876,385", i: 4 },
  { d: "M812,352 C 850,352 850,385 876,385", i: 4 },
  { d: "M812,404 C 850,404 850,385 876,385", i: 4 },
  { d: "M1006,385 H1029", i: 5 }, // consolidate -> write
  { d: "M1144,385 H1198", i: 6 }, // write -> cited report (end)
];
const HIW_FLOW_M = [
  { d: "M100,24 V40", i: 0 }, // message -> supervisor (start)
  { d: "M100,88 V156", i: 1 }, // route research -> plan
  { d: "M144,176 H170", i: 2 }, // plan -> review
  // Split: into the three active researcher tiles, then recombine.
  { d: "M60,228 V240", i: 3 },
  { d: "M140,228 V240", i: 3 },
  { d: "M220,228 V240", i: 3 },
  { d: "M60,278 V290", i: 4 },
  { d: "M140,278 V290", i: 4 },
  { d: "M220,278 V290", i: 4 },
  { d: "M180,290 V300", i: 5 }, // collect -> consolidate
  { d: "M180,340 V358", i: 6 }, // consolidate -> write
  { d: "M180,398 V416", i: 7 }, // write -> cited report (end)
];
// One comet = three stacked strokes (bright head, dimmer/longer tails) over each segment.
const COMET_LAYERS = ["head", "mid", "tail"] as const;

// ---- How it works: the orchestrator workflow as a directed graph ----
export function HowItWorks() {
  const figRef = useRef<HTMLElement>(null);
  const [active, setActive] = useState<string | null>(null);
  // Touch devices skip the hover/focus preview: there, the synthetic mouseenter
  // and focus that precede a tap would set the node active and the click would
  // immediately toggle it back off, so it took two taps. A plain click toggle is
  // a single tap. Pointer devices keep hover.
  const isTouch = typeof window !== "undefined" && window.matchMedia("(pointer: coarse)").matches;

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

  // Mobile fan-out: the same three researchers + dashed Documents slot, laid out
  // horizontally so the concurrency is visible across the screen width.
  const mTiles = [
    { x: 23, rag: false },
    { x: 103, rag: false },
    { x: 183, rag: false },
    { x: 263, rag: true },
  ];

  const bind = (id: string, label: string) => ({
    tabIndex: 0,
    role: "button",
    "aria-label": label,
    ...(isTouch
      ? {}
      : {
          onMouseEnter: () => setActive(id),
          onMouseLeave: () => setActive(null),
          onFocus: () => setActive(id),
          onBlur: () => setActive(null),
        }),
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
            <path className="hiw-edge flow start" d="M28,146 H67" markerEnd="url(#hiw-arrow)" pathLength={1} />
            {/* answer: a short branch up from the supervisor's centre to a reply (terminal). */}
            <path className="hiw-edge flow" d="M164,100 V62" markerEnd="url(#hiw-arrow)" pathLength={1} />
            {/* compose: across the top to the Compose node, then down into Write. */}
            <path className="hiw-edge flow" d="M258,124 H1005" markerEnd="url(#hiw-arrow)" pathLength={1} />
            <path className="hiw-edge flow" d="M1085,158 V343" markerEnd="url(#hiw-arrow)" pathLength={1} />
            {/* research: down into the plan step, kept left of the orchestrator title. */}
            <path className="hiw-edge flow" d="M164,192 C 164,302 250,312 282,343" markerEnd="url(#hiw-arrow)" pathLength={1} />

            {/* Research subgraph edges. */}
            <path className="hiw-edge flow" d="M362,385 H389" markerEnd="url(#hiw-arrow)" pathLength={1} />
            {/* The revise arc loops the review back to re-plan. */}
            <path className="hiw-edge" d="M495,345 C 486,302 362,302 332,343" markerEnd="url(#hiw-arrow)" pathLength={1} />
            {/* Confirm fans the approved plan out to the researchers, and back in. */}
            {rows.map((r, i) => (
              <path key={"fo" + i} className="hiw-edge" d={`M522,385 H582 C 602,385 602,${r.cy} 636,${r.cy}`} pathLength={1} />
            ))}
            {rows.map((r, i) => (
              <path key={"fi" + i} className="hiw-edge" d={`M812,${r.cy} C 850,${r.cy} 850,385 876,385`} pathLength={1} />
            ))}
            <path className="hiw-edge flow" d="M1006,385 H1029" markerEnd="url(#hiw-arrow)" pathLength={1} />
            <path className="hiw-edge flow" d="M1144,385 H1198" markerEnd="url(#hiw-arrow)" pathLength={1} />

            {/* Traveling flow-light: one packet, three stacked layers per segment. */}
            {HIW_FLOW.map((e, i) =>
              COMET_LAYERS.map((layer) => (
                <path key={"c" + i + layer} className={"hiw-comet " + layer} d={e.d} pathLength={1} style={{ "--i": e.i } as React.CSSProperties} />
              )),
            )}

            <circle className="hiw-ping" cx="28" cy="146" r="3" />
            <circle className="hiw-start-dot" cx="28" cy="146" r="3" />
            <text className="hiw-io hiw-io-start" x="28" y="130" textAnchor="middle">{L.message}</text>
            <text className="hiw-io" x="164" y="52" textAnchor="middle">{L.directAnswer}</text>
            <text className="hiw-io hiw-io-key" x="1206" y="389">{L.citedReport}</text>
            <text className="hiw-stack-label" x="724" y="276" textAnchor="middle">{L.fanout}</text>
            <text className="hiw-gate-label" x="600" y="114" textAnchor="middle">{L.routeCompose}</text>
            <text className="hiw-gate-label" x="150" y="254" textAnchor="end">{L.routeResearch}</text>
            <text className="hiw-gate-label" x="424" y="300" textAnchor="middle">{L.revise}</text>
            <text className="hiw-gate-label" x="560" y="374" textAnchor="middle">{L.confirm}</text>

            {/* Supervisor: the agent the user talks to; sits above the subgraph. */}
            <g className={"hiw-node hiw-glow" + (active === "supervisor" ? " active" : "")} style={{ "--d": 1 } as React.CSSProperties} {...bind("supervisor", L.supervisor)}>
              <rect x="70" y="100" width="188" height="92" rx="12" />
              <text className="hiw-title" x="164" y="140" textAnchor="middle">{L.supervisor}</text>
              <text className="hiw-role" x="164" y="160" textAnchor="middle">{L.supervisorRole}</text>
            </g>

            {/* Compose: merge existing reports into one new report, no new search. */}
            <g className={"hiw-node" + (active === "compose" ? " active" : "")} {...bind("compose", L.compose)}>
              <rect x="1010" y="98" width="150" height="62" rx="12" />
              <text className="hiw-title sm" x="1085" y="125" textAnchor="middle">{L.compose}</text>
              <text className="hiw-role" x="1085" y="143" textAnchor="middle">{L.composeRole}</text>
            </g>

            <g className={"hiw-node hiw-glow" + (active === "plan" ? " active" : "")} style={{ "--d": 2 } as React.CSSProperties} {...bind("plan", L.plan)}>
              <rect x="250" y="345" width="112" height="80" rx="12" />
              <text className="hiw-title" x="306" y="381" textAnchor="middle">{L.plan}</text>
              <text className="hiw-role" x="306" y="401" textAnchor="middle">{L.planRole}</text>
            </g>

            {/* Human-in-the-loop review: accent-styled, with a revise loop to Plan. */}
            <g className={"hiw-node hiw-human hiw-glow" + (active === "review" ? " active" : "")} style={{ "--d": 3 } as React.CSSProperties} {...bind("review", L.review)}>
              <rect x="392" y="345" width="130" height="80" rx="12" />
              <text className="hiw-title" x="457" y="381" textAnchor="middle">{L.review}</text>
              <text className="hiw-role" x="457" y="401" textAnchor="middle">{L.reviewRole}</text>
            </g>

            {rows.map((r, i) => {
              const id = r.rag ? "documents" : "researcher";
              return (
                <g
                  key={"n" + i}
                  className={"hiw-node" + (r.rag ? " rag" : " hiw-glow") + (active === id ? " active" : "")}
                  style={{ "--d": 4 } as React.CSSProperties}
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

            <g className={"hiw-node hiw-glow" + (active === "consolidate" ? " active" : "")} style={{ "--d": 5 } as React.CSSProperties} {...bind("consolidate", L.consolidate)}>
              <rect x="876" y="345" width="130" height="80" rx="12" />
              <text className="hiw-title" x="941" y="381" textAnchor="middle">{L.consolidate}</text>
              <text className="hiw-role" x="941" y="401" textAnchor="middle">{L.consolidateRole}</text>
            </g>

            <g className={"hiw-node hiw-glow" + (active === "write" ? " active" : "")} style={{ "--d": 6 } as React.CSSProperties} {...bind("write", L.write)}>
              <rect x="1032" y="345" width="112" height="80" rx="12" />
              <text className="hiw-title" x="1088" y="381" textAnchor="middle">{L.write}</text>
              <text className="hiw-role" x="1088" y="401" textAnchor="middle">{L.writeRole}</text>
            </g>
          </svg>

          {/* Mobile: vertical flow, but the orchestrator is a real container box and
              the researchers fan out horizontally so the concurrency shows. Same
              nodes, interactivity, and captions as the desktop graph. */}
          <svg className="hiw-svg-m" viewBox="0 0 384 446" role="img" aria-label={t.hiw.aria}>
            <defs>
              <marker id="hiw-arrow-m" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6" className="hiw-arrowhead" />
              </marker>
            </defs>

            {/* the orchestrator surrounds the whole research subgraph */}
            <rect className="hiw-orch" x="12" y="126" width="336" height="288" rx="16" />
            <text className="hiw-orch-label" x="180" y="145" textAnchor="middle">{L.orchestrator}</text>

            {/* message in */}
            <circle className="hiw-ping" cx="100" cy="26" r="3" />
            <circle className="hiw-start-dot" cx="100" cy="26" r="3" />
            <text className="hiw-io hiw-io-start" x="100" y="13" textAnchor="middle">{L.message}</text>
            <path className="hiw-edge flow start" d="M100,24 V40" markerEnd="url(#hiw-arrow-m)" pathLength={1} />

            {/* supervisor's three moves: answer + compose branch right, research drops in */}
            <path className="hiw-edge flow" d="M180,54 H236" markerEnd="url(#hiw-arrow-m)" pathLength={1} />
            <path className="hiw-edge flow" d="M180,70 C 196,70 198,90 214,90" markerEnd="url(#hiw-arrow-m)" pathLength={1} />
            {/* compose reuses the writer: it runs down the right, outside the
                orchestrator, and back into Write. */}
            <path className="hiw-edge flow" d="M338,92 C 382,166 374,342 252,378" markerEnd="url(#hiw-arrow-m)" pathLength={1} />
            <path className="hiw-edge flow" d="M100,88 V156" markerEnd="url(#hiw-arrow-m)" pathLength={1} />

            {/* research subgraph */}
            <path className="hiw-edge flow" d="M144,176 H170" markerEnd="url(#hiw-arrow-m)" pathLength={1} />
            <path className="hiw-edge" d="M170,186 C 150,206 104,206 86,196" markerEnd="url(#hiw-arrow-m)" pathLength={1} />
            {/* confirm feeds an orthogonal fan-out manifold: one rail distributes to
                the tiles and another collects them, instead of crossing curves. */}
            <path className="hiw-edge" d="M240,196 V214 H180 V228" pathLength={1} />
            <path className="hiw-edge" d="M60,228 H300" pathLength={1} />
            {mTiles.map((m, i) => (
              <path key={"mfo" + i} className="hiw-edge" d={`M${m.x + 37},228 V240`} pathLength={1} />
            ))}
            {mTiles.map((m, i) => (
              <path key={"mfi" + i} className="hiw-edge" d={`M${m.x + 37},278 V290`} pathLength={1} />
            ))}
            <path className="hiw-edge" d="M60,290 H300" pathLength={1} />
            <path className="hiw-edge flow" d="M180,290 V300" markerEnd="url(#hiw-arrow-m)" pathLength={1} />
            <path className="hiw-edge flow" d="M180,340 V358" markerEnd="url(#hiw-arrow-m)" pathLength={1} />
            <path className="hiw-edge flow" d="M180,398 V416" markerEnd="url(#hiw-arrow-m)" pathLength={1} />

            {/* Traveling flow-light: one packet, three stacked layers per segment. */}
            {HIW_FLOW_M.map((e, i) =>
              COMET_LAYERS.map((layer) => (
                <path key={"cm" + i + layer} className={"hiw-comet " + layer} d={e.d} pathLength={1} style={{ "--i": e.i } as React.CSSProperties} />
              )),
            )}

            <text className="hiw-io" x="242" y="58" textAnchor="start">{L.directAnswer}</text>
            <text className="hiw-io hiw-io-key" x="180" y="432" textAnchor="middle">{L.citedReport}</text>
            {/* answer + compose are self-labelled by their targets; only the research
                branch into the orchestrator needs a route label. */}
            <text className="hiw-gate-label" x="100" y="120" textAnchor="middle">{L.routeResearch}</text>
            <text className="hiw-gate-label" x="132" y="215" textAnchor="middle">{L.revise}</text>
            <text className="hiw-gate-label" x="245" y="215" textAnchor="start">{L.confirm}</text>

            <g className={"hiw-node hiw-glow" + (active === "supervisor" ? " active" : "")} style={{ "--d": 1 } as React.CSSProperties} {...bind("supervisor", L.supervisor)}>
              <rect x="20" y="40" width="160" height="48" rx="12" />
              <text className="hiw-title" x="100" y="69" textAnchor="middle">{L.supervisor}</text>
            </g>

            <g className={"hiw-node" + (active === "compose" ? " active" : "")} {...bind("compose", L.compose)}>
              <rect x="214" y="72" width="124" height="36" rx="11" />
              <text className="hiw-title sm" x="276" y="95" textAnchor="middle">{L.compose}</text>
            </g>

            <g className={"hiw-node hiw-glow" + (active === "plan" ? " active" : "")} style={{ "--d": 2 } as React.CSSProperties} {...bind("plan", L.plan)}>
              <rect x="24" y="156" width="120" height="40" rx="12" />
              <text className="hiw-title sm" x="84" y="181" textAnchor="middle">{L.plan}</text>
            </g>

            <g className={"hiw-node hiw-human hiw-glow" + (active === "review" ? " active" : "")} style={{ "--d": 3 } as React.CSSProperties} {...bind("review", L.review)}>
              <rect x="170" y="156" width="140" height="40" rx="12" />
              <text className="hiw-title sm" x="240" y="181" textAnchor="middle">{L.review}</text>
            </g>

            {mTiles.map((m, i) => {
              const id = m.rag ? "documents" : "researcher";
              const cx = m.x + 37;
              return (
                <g
                  key={"mt" + i}
                  className={"hiw-node" + (m.rag ? " rag" : " hiw-glow") + (active === id ? " active" : "")}
                  style={{ "--d": 4 } as React.CSSProperties}
                  {...bind(id, m.rag ? L.documents : L.researcher)}
                >
                  <rect x={m.x} y="240" width="74" height="38" rx="10" />
                  {m.rag ? (
                    <text className="hiw-role" x={cx} y="263" textAnchor="middle">{L.docRole}</text>
                  ) : (
                    <>
                      <circle className="hiw-tile-ic" cx={cx - 2} cy="257" r="4.5" />
                      <line className="hiw-tile-ic" x1={cx + 1.5} y1="260.5" x2={cx + 5} y2="264" />
                    </>
                  )}
                </g>
              );
            })}

            <g className={"hiw-node hiw-glow" + (active === "consolidate" ? " active" : "")} style={{ "--d": 5 } as React.CSSProperties} {...bind("consolidate", L.consolidate)}>
              <rect x="110" y="300" width="140" height="40" rx="12" />
              <text className="hiw-title sm" x="180" y="325" textAnchor="middle">{L.consolidate}</text>
            </g>

            <g className={"hiw-node hiw-glow" + (active === "write" ? " active" : "")} style={{ "--d": 6 } as React.CSSProperties} {...bind("write", L.write)}>
              <rect x="110" y="358" width="140" height="40" rx="12" />
              <text className="hiw-title sm" x="180" y="383" textAnchor="middle">{L.write}</text>
            </g>
          </svg>

          {/* Deeper fallback (kept for no-SVG / very old engines): the flow as text. */}
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

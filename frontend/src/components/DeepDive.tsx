import { t } from "../lib/i18n";
import { I } from "../icons";
import { NexusLockup } from "./NexusLogo";

const REPO_URL = "https://github.com/Ghali-BenBouzid/nexus";

const A = t.deep.agentLabels;
const S = t.deep.sysLabels;

function Notes({ notes }: { notes: readonly { lead: string; rest: string }[] }) {
  return (
    <ul className="dd-notes">
      {notes.map((n) => (
        <li key={n.lead}>
          <b>{n.lead}</b>
          {n.rest}
        </li>
      ))}
    </ul>
  );
}

// The agent diagram. Deliberately not the old landing-page graph: that one drew a
// router with three fixed routes and a plan you had to approve, and neither
// exists any more. What is true now is one agent with tools, so that is what it
// draws: solid for the path a message always takes, dashed for a tool the
// supervisor may or may not reach for.
function AgentDiagram() {
  return (
    <svg className="dd-svg" viewBox="0 0 900 430" role="img" aria-label={t.deep.agentAria}>
      <defs>
        <marker id="dd-a" markerWidth="8" markerHeight="8" refX="5.5" refY="3" orient="auto-start-reverse">
          <path d="M0,0 L6,3 L0,6" className="dd-arrowhead" />
        </marker>
      </defs>

      {/* The path every message takes: in, and back out as an answer. */}
      <path className="dd-edge" d="M96,60 H196" markerEnd="url(#dd-a)" />
      <path className="dd-edge" d="M420,60 H520" markerEnd="url(#dd-a)" />

      <text className="dd-io" x="20" y="64">{A.message}</text>
      <text className="dd-io key" x="536" y="64">{A.answer}</text>

      <g className="dd-node lead">
        <rect x="200" y="32" width="216" height="56" rx="12" />
        <text className="dd-t" x="308" y="56" textAnchor="middle">{A.supervisor}</text>
        <text className="dd-r" x="308" y="74" textAnchor="middle">{A.supervisorRole}</text>
      </g>

      {/* Tools: reached for as needed, any number of times, so they hang off the
          supervisor rather than sitting on the path. The first three point both
          ways, because a tool call comes back: the supervisor asks and reads the
          answer. The background pair is one way, because those hand the work off
          and write their own report instead of replying. */}
      <text className="dd-lane" x="318" y="112" textAnchor="start">{A.tools}</text>
      <path className="dd-edge dash" d="M308,92 V128 H150 V150" markerStart="url(#dd-a)" markerEnd="url(#dd-a)" />
      <path className="dd-edge dash" d="M308,92 V128 H308 V150" markerStart="url(#dd-a)" markerEnd="url(#dd-a)" />
      <path className="dd-edge dash" d="M308,92 V128 H492 V150" markerStart="url(#dd-a)" markerEnd="url(#dd-a)" />
      <path className="dd-edge dash" d="M308,92 V128 H700 V150" markerEnd="url(#dd-a)" />

      <g className="dd-node">
        <rect x="60" y="152" width="180" height="40" rx="10" />
        <text className="dd-t sm" x="150" y="177" textAnchor="middle">{A.search}</text>
      </g>
      <g className="dd-node">
        <rect x="256" y="152" width="150" height="40" rx="10" />
        <text className="dd-t sm" x="331" y="177" textAnchor="middle">{A.doc}</text>
      </g>

      {/* The research tool is itself a small pipeline, so it gets a container. */}
      <rect className="dd-group" x="424" y="152" width="242" height="118" rx="14" />
      <text className="dd-group-t" x="440" y="172">{A.research}</text>
      <g className="dd-node">
        <rect x="440" y="182" width="86" height="34" rx="9" />
        <text className="dd-t sm" x="483" y="204" textAnchor="middle">{A.plan}</text>
      </g>
      <path className="dd-edge" d="M526,199 H556" markerEnd="url(#dd-a)" />
      <g className="dd-node">
        <rect x="556" y="182" width="96" height="34" rx="9" />
        <text className="dd-t xs" x="604" y="203" textAnchor="middle">{A.researchers}</text>
      </g>
      <text className="dd-r" x="604" y="236" textAnchor="middle">{A.parallel}</text>

      {/* The two background runs: they leave the conversation and write documents. */}
      <rect className="dd-group bg" x="676" y="152" width="200" height="176" rx="14" />
      <text className="dd-group-t" x="692" y="172">{A.background}</text>
      <g className="dd-node">
        <rect x="692" y="182" width="168" height="48" rx="10" />
        <text className="dd-t sm" x="776" y="202" textAnchor="middle">{A.deep}</text>
        <text className="dd-r" x="776" y="219" textAnchor="middle">{A.deepRole}</text>
      </g>
      <g className="dd-node">
        <rect x="692" y="242" width="168" height="48" rx="10" />
        <text className="dd-t sm" x="776" y="262" textAnchor="middle">{A.factCheck}</text>
        <text className="dd-r" x="776" y="279" textAnchor="middle">{A.factRole}</text>
      </g>
      <path className="dd-edge" d="M776,290 V352" markerEnd="url(#dd-a)" />
      <g className="dd-node key">
        <rect x="694" y="354" width="164" height="42" rx="10" />
        <text className="dd-t sm" x="776" y="380" textAnchor="middle">{A.outputs}</text>
      </g>
    </svg>
  );
}

// The system diagram: the same message, seen from the outside. Three hosts, and
// the queue that keeps a model call out of an HTTP request.
function SystemDiagram() {
  return (
    <svg className="dd-svg" viewBox="0 0 900 400" role="img" aria-label={t.deep.sysAria}>
      <defs>
        <marker id="dd-b" markerWidth="8" markerHeight="8" refX="5.5" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6" className="dd-arrowhead" />
        </marker>
      </defs>

      <g className="dd-node lead">
        <rect x="24" y="112" width="150" height="62" rx="12" />
        <text className="dd-t" x="99" y="138" textAnchor="middle">{S.browser}</text>
        <text className="dd-r" x="99" y="156" textAnchor="middle">{S.frontend}</text>
      </g>
      <text className="dd-host" x="99" y="196" textAnchor="middle">{S.cdn}</text>

      {/* Request out, stream back: one line each way, because that is the whole
          contract between the browser and the system. */}
      <path className="dd-edge" d="M176,132 H272" markerEnd="url(#dd-b)" />
      <path className="dd-edge" d="M272,158 H176" markerEnd="url(#dd-b)" />
      <text className="dd-lane" x="224" y="124" textAnchor="middle">HTTP</text>
      <text className="dd-lane" x="224" y="180" textAnchor="middle">{S.stream}</text>

      {/* Railway holds both processes; drawing the boundary is the point. */}
      <rect className="dd-group" x="274" y="40" width="330" height="300" rx="16" />
      <text className="dd-group-t" x="290" y="62">{S.host}</text>

      <g className="dd-node">
        <rect x="292" y="112" width="150" height="62" rx="12" />
        <text className="dd-t" x="367" y="138" textAnchor="middle">{S.api}</text>
        <text className="dd-r" x="367" y="156" textAnchor="middle">{S.apiRole}</text>
      </g>

      <g className="dd-node">
        <rect x="292" y="248" width="150" height="62" rx="12" />
        <text className="dd-t" x="367" y="274" textAnchor="middle">{S.worker}</text>
        <text className="dd-r" x="367" y="292" textAnchor="middle">{S.workerRole}</text>
      </g>

      {/* Redis sits between them, carrying jobs down and frames back up. */}
      <g className="dd-node accent">
        <rect x="474" y="160" width="116" height="62" rx="12" />
        <text className="dd-t sm" x="532" y="186" textAnchor="middle">{S.queue}</text>
        <text className="dd-r" x="532" y="203" textAnchor="middle">{S.queueRole}</text>
      </g>
      <path className="dd-edge" d="M442,150 H532 V158" markerEnd="url(#dd-b)" />
      <text className="dd-lane" x="500" y="143" textAnchor="middle">{S.job}</text>
      <path className="dd-edge" d="M532,224 V286 H444" markerEnd="url(#dd-b)" />
      <path className="dd-edge" d="M420,310 V330 H612 V196 H592" markerEnd="url(#dd-b)" />
      <text className="dd-lane" x="628" y="270" textAnchor="middle">{S.frames}</text>

      {/* Both processes read and write the same database. */}
      <g className="dd-node">
        <rect x="686" y="40" width="180" height="62" rx="12" />
        <text className="dd-t" x="776" y="66" textAnchor="middle">{S.db}</text>
        <text className="dd-r" x="776" y="84" textAnchor="middle">{S.dbRole}</text>
      </g>
      <path className="dd-edge thin" d="M442,124 H660 C 676,124 676,104 686,96" markerEnd="url(#dd-b)" />
      <path className="dd-edge thin" d="M442,262 H664 C 684,262 684,110 700,104" markerEnd="url(#dd-b)" />

      {/* Everything the worker pays for is outside. */}
      <g className="dd-node">
        <rect x="686" y="248" width="180" height="40" rx="10" />
        <text className="dd-t sm" x="776" y="273" textAnchor="middle">{S.models}</text>
      </g>
      <g className="dd-node">
        <rect x="686" y="300" width="180" height="40" rx="10" />
        <text className="dd-t sm" x="776" y="325" textAnchor="middle">{S.search}</text>
      </g>
      <path className="dd-edge dash" d="M444,296 H640 V268 H686" markerEnd="url(#dd-b)" />
      <path className="dd-edge dash" d="M444,300 H640 V320 H686" markerEnd="url(#dd-b)" />
    </svg>
  );
}

// The technical deep dive: what happens to a message, and where that runs. Its
// own page rather than a landing-page section, because the landing page should
// say what Nexus is in one screen and this is two screens of how.
export function DeepDive({ onBack }: { onBack: () => void }) {
  return (
    <main className="dd">
      <div className="wrap">
        <button className="dd-back" onClick={onBack}>
          {I.arrowLeft}
          {t.deep.back}
        </button>

        <header className="dd-head">
          <NexusLockup size={26} />
          <h1>{t.deep.title}</h1>
          <p>{t.deep.lede}</p>
        </header>

        <section className="dd-section">
          <h2>{t.deep.agentTitle}</h2>
          <p>{t.deep.agentBody}</p>
          <figure className="dd-fig">
            <AgentDiagram />
          </figure>
          <Notes notes={t.deep.agentNotes} />
        </section>

        <section className="dd-section">
          <h2>{t.deep.sysTitle}</h2>
          <p>{t.deep.sysBody}</p>
          <figure className="dd-fig">
            <SystemDiagram />
          </figure>
          <Notes notes={t.deep.sysNotes} />
        </section>

        <div className="dd-foot">
          <a className="btn btn-ghost" href={REPO_URL} target="_blank" rel="noreferrer">
            {t.deep.source}
          </a>
        </div>
      </div>
    </main>
  );
}

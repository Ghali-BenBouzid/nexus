// The shapes the feed/report UI speak. They mirror the backend's data contract
// (handoff §"Data Contract"): a run resolves to a cited report, and streams
// AgentEvents while running.

export type Theme = "dark" | "light";
export type View = "home" | "chat";
// How the conversation workspace is laid out: a single-column chat thread, or a
// split workspace (conversation on the left, the focused run's activity on the
// right, the slot the future parallel-agent graph will live in).
export type LayoutMode = "thread" | "split";
export type Status = "pending" | "awaiting_plan" | "running" | "complete" | "failed";
export type Outcome = "ok" | "empty" | "failed";

export type Source = { title: string; url: string };

export type Result = {
  report: string; // markdown with [n] citation tokens
  sources: Source[]; // cited, index+1 maps to [n] in the report
  consulted: Source[]; // consulted but not cited (provenance)
  gaps: string[]; // unanswered questions / failed leads
};

// One agent event, as the progress bar reads it. `index` is the researcher an
// event came from, when it came from one.
export type AgentEvent =
  | { kind: "planner"; state: "start" }
  | { kind: "plan"; items: string[] }
  // An agent is waiting on the model (a reasoning model may think for a minute).
  | { kind: "thinking"; agent: "supervisor" | "planner" | "researcher" | "writer"; index?: number }
  | { kind: "researcher"; state: "start"; index: number; total: number; question: string }
  | {
      kind: "researcher";
      state: "done";
      index: number;
      question: string;
      outcome: "found" | "empty" | "failed";
    }
  | { kind: "tool"; action: "search"; text: string; index?: number }
  | { kind: "tool"; action: "read"; domain: string; index?: number }
  | { kind: "tool"; action: "error"; text: string; index?: number }
  | { kind: "writer"; state: "start" | "done" };

// An event on a turn's timeline: the event plus an id, the delay (ms) the
// simulated engine waits before revealing it, and `at`, the performance.now()
// instant it reached the UI (what the step timers count from).
export type TimelineEvent = AgentEvent & { id: number; delay: number; at?: number };

// One turn in the conversation: a submitted query and everything that run
// produced. The thread is an ordered list of these; each runs independently.
export type Turn = {
  id: number;
  queryId?: number; // backend query id (live mode), for refresh + cancel
  query: string;
  title?: string; // the supervisor-given report/artifact title
  status: Status;
  events: TimelineEvent[];
  // The supervisor answered from existing reports instead of researching: this is
  // the chat reply, rendered in place of a report.
  reply?: string;
  // The proposed sub-questions, shown for confirmation while status=awaiting_plan.
  plan?: string[];
  result: Result | null;
  outcome: Outcome;
  error: string | null;
  startedAt: number; // performance.now() when the run began
  endedAt: number | null; // performance.now() when it resolved; null while running
  stopped?: boolean; // the user halted this run before it finished
  // Live mode: seconds since the backend job last showed signs of life, as of the
  // last poll (heartbeatSeenAt, performance.now()), so the bar can flag a stuck run.
  heartbeatAge?: number | null;
  heartbeatSeenAt?: number;
};

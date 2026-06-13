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

// One event appended to the feed as it arrives.
export type AgentEvent =
  | { kind: "planner"; state: "start"; title: string; sub: string }
  | { kind: "plan"; items: string[] }
  | { kind: "researcher"; state: "start"; index: number; total: number; question: string }
  | { kind: "tool"; action: "search"; text: string }
  | { kind: "tool"; action: "read"; domain: string; title: string }
  | { kind: "tool"; action: "error"; text: string }
  | {
      kind: "researcher";
      state: "done";
      index: number;
      question: string;
      sub: string;
      hasGap: boolean;
    }
  | { kind: "writer"; state: "start" | "done"; title: string; sub: string };

// An event placed on the simulated timeline: the event plus an id and the delay
// (ms) the UI waits before revealing it.
export type TimelineEvent = AgentEvent & { id: number; delay: number };

// One turn in the conversation: a submitted query and everything that run
// produced. The thread is an ordered list of these; each runs independently.
export type Turn = {
  id: number;
  queryId?: number; // backend query id (live mode), for refresh + cancel
  query: string;
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
};

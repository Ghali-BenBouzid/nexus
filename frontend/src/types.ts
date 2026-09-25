// The shapes the feed/report UI speak. They mirror the backend's data contract
// (handoff §"Data Contract"): a run resolves to a cited report, and streams
// AgentEvents while running.

export type Theme = "dark" | "light";
export type View = "home" | "chat" | "how";
// How the conversation workspace is laid out: a single-column chat thread, or a
// split workspace (conversation on the left, the focused run's activity on the
// right, the slot the future parallel-agent graph will live in).
export type LayoutMode = "thread" | "split";
export type Status = "pending" | "running" | "complete" | "failed";
export type Outcome = "ok" | "empty" | "failed";

// What sending a message does. "answer" is the ordinary turn; the other two
// hand the work to a background run that writes its own report.
export type Mode = "answer" | "deep" | "factcheck";

// What the API calls a conversation: an opaque UUID, never the database's
// integer key, so a chat's URL gives nothing away and cannot be guessed.
export type ConversationId = string;

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
  | { kind: "planner"; state: "start"; team?: string }
  | { kind: "plan"; items: string[]; team?: string }
  // An agent is waiting on the model (a reasoning model may think for a minute).
  | {
      kind: "thinking";
      agent: "supervisor" | "planner" | "researcher" | "writer" | "fact_checker";
      index?: number;
      team?: string;
    }
  | { kind: "researcher"; state: "start"; index: number; total: number; question: string; team?: string }
  | {
      kind: "researcher";
      state: "done";
      index: number;
      question: string;
      outcome: "found" | "empty" | "failed";
      team?: string;
    }
  // A stretch of the supervisor's thinking, and the few words a small model
  // later named it with. The thinking itself never reaches the browser.
  | { kind: "step"; step: number }
  | { kind: "step_title"; step: number; title: string }
  // The supervisor sent a research team after this question. ``team`` ties
  // the team's own events (its plan, its researchers) back to this step.
  | { kind: "tool"; action: "research"; text: string; team?: string; index?: undefined }
  | { kind: "tool"; action: "search"; text: string; index?: number; team?: string }
  | { kind: "tool"; action: "read"; domain: string; index?: number; team?: string }
  | { kind: "tool"; action: "error"; text: string; index?: number }
  // The supervisor passed a change of mind to a deep run that is still working.
  | { kind: "tool"; action: "steer" }
  | { kind: "tool"; action: "claims" }
  // The supervisor read a file attached to the conversation.
  | { kind: "tool"; action: "document"; text: string }
  // A run the supervisor started in the background, which finishes on its own.
  | { kind: "started"; run: "deep_research" | "fact_check"; text: string }
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
  // The files sent with this message, shown on the bubble that carries them.
  attachments?: Doc[];
  // Stopped before the message reached the server: the files it carried were
  // dropped with it, so there is nothing left to run again.
  unsent?: boolean;
  title?: string; // the supervisor-given report/artifact title
  status: Status;
  events: TimelineEvent[];
  // The assistant's answer, rendered in the thread. Every turn has one now: a
  // report is a separate output, not what a turn produces.
  reply?: string;
  // The reply as it streams in, before the finished one lands. Kept apart from
  // `reply` so the answer the user keeps is always the one the server stored.
  streamed?: string;
  // The sources the answer cites, and nothing else: a turn produces no report.
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

// A report the account keeps: a deep research run or a fact check. It is started
// from a conversation but outlives it, so it is loaded and listed on its own.
export type OutputKind = "deep_research" | "fact_check";

export type Output = {
  id: number; // the backend query id
  kind: OutputKind;
  title: string;
  prompt: string;
  status: Status;
  conversationId: ConversationId | null;
  error: string | null;
  createdAt: string;
  completedAt: string | null;
  // Filled when the output is opened; null until then.
  result?: Result | null;
};

// A file the user attached to the conversation.
export type Doc = {
  id: number;
  // The message this file was sent with, when it was attached in the composer.
  messageId?: number | null;
  filename: string;
  mediaType: string;
  sizeBytes: number;
  pages: number | null;
  chars: number;
  truncated: boolean;
  ocr: boolean;
  // How far the file has got. "uploading" is client-side only, while its bytes
  // go up: the tile exists the moment the file is picked rather than appearing
  // when it lands. "reading" is the server's own job turning it into text, and
  // outlives the page, so it comes back on a reload. "failed" is either a
  // refused upload or a file that could not be read, with the reason in error.
  // A read file carries no state at all. Placeholders hold a negative id, so
  // nothing mistakes one for something that can be fetched or deleted.
  state?: "uploading" | "reading" | "failed";
  error?: string;
};

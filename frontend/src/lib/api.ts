// Real Nexus backend client. Used only when VITE_LIVE_MODE === "true".
//
// The run path is: submit -> poll the detail endpoint for the terminal result,
// while tailing GET /research/query/{id}/events for the real agent feed. The
// backend persists every emitted AgentEvent, so the feed shows the actual
// planner/researcher/writer progress (real "researcher k/N"), not a placeholder.
import type { AgentEvent, Result, Source, Status, TimelineEvent } from "../types";
import type { ResearchCallbacks, ResearchOutcome } from "./research";

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const TOKEN_KEY = "nexus-token";
const CREDS_KEY = "nexus-demo-creds";

type QueryDetail = {
  id: number;
  prompt: string;
  status: Status;
  report: string | null;
  error: string | null;
  plan: string[] | null;
  sources: Source[];
  consulted_sources: Source[];
  gaps: string[];
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// The throwaway per-browser demo account. Created lazily and kept in localStorage
// so every visitor gets a stable identity (and its own server-side history) without
// ever seeing a login screen. Read-or-create is synchronous (no network).
function getOrCreateCreds(): { email: string; password: string } {
  const existing = localStorage.getItem(CREDS_KEY);
  if (existing) {
    try {
      return JSON.parse(existing) as { email: string; password: string };
    } catch {
      // corrupt blob: fall through and mint a fresh identity
    }
  }
  const rand = Math.random().toString(36).slice(2, 10);
  const creds = { email: `demo+${rand}@nexus.app`, password: rand + "Aa1!" };
  localStorage.setItem(CREDS_KEY, JSON.stringify(creds));
  return creds;
}

// A stable per-browser identity for namespacing local state (e.g. query history),
// so two demo accounts on one machine don't share a list.
export function currentUserKey(): string {
  return getOrCreateCreds().email;
}

async function ensureToken(): Promise<string> {
  const existing = localStorage.getItem(TOKEN_KEY);
  if (existing) return existing;

  const { email, password } = getOrCreateCreds();

  // Register is idempotent enough for a demo: ignore "already exists" and log in.
  await fetch(`${BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  }).catch(() => undefined);

  const form = new URLSearchParams({ username: email, password });
  const res = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
  });
  if (!res.ok) throw new Error("Could not start a demo session.");
  const token = (await res.json()).access_token as string;
  localStorage.setItem(TOKEN_KEY, token);
  return token;
}

// Authenticated GET that self-heals a stale/expired token: on 401 it drops the
// cached token, mints a fresh session, and retries once. The cached JWT is
// returned by ensureToken without validation, so a backend restart (rotated
// signing secret) or an expiry would otherwise make every read 401 silently.
async function authedGet(path: string): Promise<Response | null> {
  let token = await ensureToken();
  let res = await fetch(`${BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (res.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    token = await ensureToken();
    res = await fetch(`${BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  }
  return res;
}

async function getQuery(id: number, token: string): Promise<QueryDetail> {
  const res = await fetch(`${BASE}/research/query/${id}?include_provenance=true`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Could not read the query (${res.status}).`);
  return (await res.json()) as QueryDetail;
}

// One persisted agent event from GET /research/query/{id}/events.
type BackendEvent = {
  id: number;
  type: string;
  message: string;
  data: Record<string, unknown> | null;
};

async function getEvents(
  id: number,
  after: number,
  token: string,
): Promise<BackendEvent[]> {
  const res = await fetch(`${BASE}/research/query/${id}/events?after=${after}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) return []; // the feed is best-effort; never fail the run over it
  return (await res.json()) as BackendEvent[];
}

function hostname(url: unknown): string {
  if (typeof url !== "string") return "source";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "source";
  }
}

// Map a persisted backend event to the feed's AgentEvent shape. Returns null for
// internal events the feed doesn't surface (planner_clamped, researcher_forced…).
function toAgentEvent(e: BackendEvent): AgentEvent | null {
  const d = e.data ?? {};
  switch (e.type) {
    case "planner_start":
      return { kind: "planner", state: "start", title: "Planning your research", sub: e.message };
    case "planner_done":
      return { kind: "plan", items: (d.sub_questions as string[]) ?? [] };
    case "researcher_start":
      return {
        kind: "researcher",
        state: "start",
        index: (d.index as number) ?? 1,
        total: (d.total as number) ?? 1,
        question: (d.sub_question as string) ?? e.message,
      };
    case "tool_call":
      if (d.tool === "fetch_page") {
        const url = (d.args as Record<string, unknown> | undefined)?.url;
        return { kind: "tool", action: "read", domain: hostname(url), title: hostname(url) };
      }
      return {
        kind: "tool",
        action: "search",
        text: String((d.args as Record<string, unknown> | undefined)?.query ?? e.message),
      };
    case "tool_error":
      return { kind: "tool", action: "error", text: e.message };
    case "researcher_done":
      return {
        kind: "researcher",
        state: "done",
        index: (d.index as number) ?? 1,
        question: (d.sub_question as string) ?? "",
        sub: d.found_info === false ? "No information found." : "Findings gathered.",
        hasGap: d.found_info === false,
      };
    case "researcher_failed":
      return {
        kind: "researcher",
        state: "done",
        index: (d.index as number) ?? 1,
        question: (d.sub_question as string) ?? "",
        sub: "Could not research this area.",
        hasGap: true,
      };
    case "writer_start":
      return { kind: "writer", state: "start", title: "Writing report", sub: e.message };
    case "writer_done":
      return { kind: "writer", state: "done", title: "Report ready", sub: "Citations linked to sources." };
    default:
      return null;
  }
}

// --- conversations ----------------------------------------------------------
// A research turn now belongs to a conversation: the first message creates one,
// follow-ups append to it. The conversation (server-side) is what makes the chat
// survive reload and is the foundation the supervisor + plan-confirmation build on.

type ConvMessageQuery = {
  status: Status;
  report: string | null;
  error: string | null;
  plan: string[] | null;
  sources: Source[];
  gaps: string[];
};
type ConvMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  query_id: number | null;
  created_at: string;
  query: ConvMessageQuery | null;
};
type ConvDetail = { id: number; title: string | null; created_at: string; messages: ConvMessage[] };

function lastAssistant(detail: ConvDetail): ConvMessage | null {
  for (let i = detail.messages.length - 1; i >= 0; i--) {
    if (detail.messages[i].role === "assistant") return detail.messages[i];
  }
  return null;
}

async function postConvJson(path: string, body: object, token: string): Promise<ConvDetail> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (res.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    throw new Error("Session expired. Try again.");
  }
  if (!res.ok) throw new Error(`Could not reach the research service (${res.status}).`);
  return (await res.json()) as ConvDetail;
}

const startTurn = (prompt: string, conversationId: number | null, token: string) =>
  conversationId == null
    ? postConvJson(`/conversations`, { prompt }, token)
    : postConvJson(`/conversations/${conversationId}/messages`, { content: prompt }, token);

export async function runLiveResearch(
  prompt: string,
  cb: ResearchCallbacks,
  conversationId: number | null,
): Promise<ResearchOutcome | null> {
  cb.onStatus("running");

  let token = await ensureToken();
  let detail: ConvDetail;
  try {
    detail = await startTurn(prompt, conversationId, token);
  } catch {
    // One retry after a fresh session, in case a stored token went stale.
    token = await ensureToken();
    detail = await startTurn(prompt, conversationId, token);
  }
  cb.onConversation?.(detail.id);

  const assistant = lastAssistant(detail);
  // The supervisor either started a research run (poll it) or answered directly
  // from the conversation's reports (show the reply, no polling).
  if (assistant && assistant.query_id == null) {
    return {
      result: { report: "", sources: [], consulted: [], gaps: [] },
      outcome: "ok",
      reply: assistant.content,
    };
  }
  if (!assistant || assistant.query_id == null) {
    throw new Error("The message did not produce a response.");
  }
  cb.onQueryId?.(assistant.query_id);
  return pollQuery(assistant.query_id, token, cb);
}

// Poll a query to its terminal state, draining the agent event feed as it goes.
async function pollQuery(
  id: number,
  token: string,
  cb: ResearchCallbacks,
): Promise<ResearchOutcome | null> {
  // The backend event id is a monotonic cursor and a stable, unique timeline id.
  let lastEventId = 0;
  const drainEvents = async () => {
    const events = await getEvents(id, lastEventId, token);
    for (const e of events) {
      lastEventId = Math.max(lastEventId, e.id);
      const mapped = toAgentEvent(e);
      if (mapped) cb.onEvent({ ...mapped, id: e.id, delay: 0 });
    }
  };

  // Poll until terminal. The 5-min backstop on the backend bounds this.
  for (let i = 0; i < 240; i++) {
    if (cb.isCancelled()) return null;
    const detail = await getQuery(id, token);
    await drainEvents();

    // Human-in-the-loop: the run paused for the user to confirm the plan. End the
    // poll and surface the plan; confirm/revise resumes a fresh poll.
    if (detail.status === "awaiting_plan") {
      return {
        result: { report: "", sources: [], consulted: [], gaps: [] },
        outcome: "ok",
        awaitingPlan: true,
        plan: detail.plan ?? [],
      };
    }

    if (detail.status === "complete") {
      const result: Result = {
        report: detail.report ?? "",
        sources: detail.sources,
        consulted: detail.consulted_sources,
        gaps: detail.gaps,
      };
      const empty = !result.report.trim() && result.sources.length === 0;
      return { result, outcome: empty ? "empty" : "ok" };
    }

    if (detail.status === "failed") {
      return {
        result: { report: "", sources: [], consulted: [], gaps: [] },
        outcome: "failed",
        error: detail.error ?? "The research run failed.",
      };
    }

    await sleep(1500);
  }
  return {
    result: { report: "", sources: [], consulted: [], gaps: [] },
    outcome: "failed",
    error: "The research run timed out.",
  };
}

// Approve the proposed plan (POST /research/query/{id}/confirm): the backend runs
// the research. Resume polling afterwards to track it to completion.
export async function confirmPlan(queryId: number): Promise<void> {
  const token = await ensureToken();
  await fetch(`${BASE}/research/query/${queryId}/confirm`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

// Reject the plan with optional feedback (POST .../revise): the backend re-plans
// and pauses again at awaiting_plan.
export async function revisePlan(queryId: number, feedback: string): Promise<void> {
  const token = await ensureToken();
  await fetch(`${BASE}/research/query/${queryId}/revise`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ feedback }),
  });
}

// Resume polling an existing query (after confirm/revise) without posting a new
// message. Reuses the same poll loop, so it handles awaiting_plan again on revise.
export async function resumeRun(
  queryId: number,
  cb: ResearchCallbacks,
): Promise<ResearchOutcome | null> {
  cb.onStatus("running");
  const token = await ensureToken();
  return pollQuery(queryId, token, cb);
}

// Ask the backend to stop a run (POST /research/query/{id}/cancel). Best-effort
// and fire-and-forget: the UI has already marked the turn stopped, so a failure
// here (network, expiry) must not surface. This is what actually halts the
// server-side job so it stops spending quota after the user stops it.
export async function cancelQuery(id: number): Promise<void> {
  try {
    const token = await ensureToken();
    await fetch(`${BASE}/research/query/${id}/cancel`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    /* ignore */
  }
}

// --- query history ----------------------------------------------------------

export type LoadedQuery = {
  prompt: string;
  status: Status;
  error: string | null;
  result: Result;
  events: TimelineEvent[];
};

// Rehydrate a past query into the shape a conversation turn needs: its final
// result plus the full agent activity trace (so the log is browsable again).
export async function openQuery(id: number): Promise<LoadedQuery | null> {
  const detailRes = await authedGet(`/research/query/${id}?include_provenance=true`);
  if (!detailRes || !detailRes.ok) return null;
  const detail = (await detailRes.json()) as QueryDetail;

  const events: TimelineEvent[] = [];
  const eventsRes = await authedGet(`/research/query/${id}/events?after=0`);
  if (eventsRes && eventsRes.ok) {
    for (const e of (await eventsRes.json()) as BackendEvent[]) {
      const mapped = toAgentEvent(e);
      if (mapped) events.push({ ...mapped, id: e.id, delay: 0 });
    }
  }
  return {
    prompt: detail.prompt,
    status: detail.status,
    error: detail.error,
    result: {
      report: detail.report ?? "",
      sources: detail.sources,
      consulted: detail.consulted_sources,
      gaps: detail.gaps,
    },
    events,
  };
}

// --- conversation history ----------------------------------------------------

export type ConversationSummary = {
  id: number;
  title: string | null;
  updated_at: string;
};

// The caller's conversations, newest-active first (for the sidebar).
export async function listConversations(): Promise<ConversationSummary[]> {
  const res = await authedGet(`/conversations`);
  if (!res || !res.ok) return [];
  return (await res.json()) as ConversationSummary[];
}

export type LoadedTurn = {
  queryId: number | null;
  query: string;
  status: Status;
  error: string | null;
  result: Result;
  reply?: string; // a supervisor answer instead of a research report
  plan?: string[]; // proposed sub-questions, when the turn is awaiting_plan
};
export type LoadedConversation = { id: number; title: string | null; turns: LoadedTurn[] };

// Rehydrate a whole conversation thread into turns (used on reload and when
// opening a past conversation). Each assistant message that carries a research
// run becomes a turn, with the preceding user message as its prompt.
export async function loadConversation(id: number): Promise<LoadedConversation | null> {
  const res = await authedGet(`/conversations/${id}`);
  if (!res || !res.ok) return null;
  const detail = (await res.json()) as ConvDetail;

  const turns: LoadedTurn[] = [];
  let prompt = "";
  for (const m of detail.messages) {
    if (m.role === "user") {
      prompt = m.content;
      continue;
    }
    // An assistant message with no query is a supervisor answer.
    if (m.query_id == null) {
      turns.push({
        queryId: null,
        query: prompt,
        status: "complete",
        error: null,
        result: { report: "", sources: [], consulted: [], gaps: [] },
        reply: m.content,
      });
      continue;
    }
    const q = m.query;
    turns.push({
      queryId: m.query_id,
      query: prompt,
      status: q?.status ?? "complete",
      error: q?.error ?? null,
      plan: q?.plan ?? undefined,
      result: {
        report: q?.report ?? "",
        sources: q?.sources ?? [],
        consulted: [],
        gaps: q?.gaps ?? [],
      },
    });
  }
  return { id: detail.id, title: detail.title, turns };
}

// Real Nexus backend client. Used only when VITE_LIVE_MODE === "true".
//
// The run path is: submit -> poll the detail endpoint for the terminal result,
// while tailing GET /research/query/{id}/events for the real agent feed. The
// backend persists every emitted AgentEvent, so the feed shows the actual
// planner/researcher/writer progress (real "researcher k/N"), not a placeholder.
import type { AgentEvent, Result, Source, Status, TimelineEvent } from "../types";
import { t } from "./i18n";
import { outcomeFor } from "./outcome";
import type { ResearchCallbacks, ResearchOutcome } from "./research";

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const TOKEN_KEY = "nexus-token";
// The invite token from the link an admin handed out (/invite/:token). It is the
// visitor's credential: exchanged for a short-lived access token, and exchanged
// again whenever that expires. Without one, the app runs the simulated demo.
const INVITE_KEY = "nexus-invite";

type QueryDetail = {
  id: number;
  prompt: string;
  title: string | null;
  status: Status;
  report: string | null;
  error: string | null;
  plan: string[] | null;
  sources: Source[];
  consulted_sources: Source[];
  gaps: string[];
  // The supervisor's direct answer, when the turn needed no research.
  reply?: string | null;
  // How long ago the job last showed signs of life (null before it starts).
  seconds_since_heartbeat?: number | null;
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
// The backend bounds a run (research budget, timeouts); this only stops a poll
// that would otherwise never end, such as a run whose job died unnoticed.
const MAX_POLL_MS = 20 * 60_000;

export function hasInvite(): boolean {
  try {
    return !!localStorage.getItem(INVITE_KEY);
  } catch {
    return false;
  }
}

// A stable per-account key for namespacing local state (e.g. query history), so
// two invites opened on one machine don't share a list.
export function currentUserKey(): string {
  return (localStorage.getItem(INVITE_KEY) ?? "").slice(0, 12);
}

// Drop the credential entirely (the link was revoked or the access expired), so
// the app falls back to the simulated demo instead of failing every request.
function forgetAccess(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(INVITE_KEY);
}

// A 401 on a request made with a stored access token: that token went stale, and
// one retry with a fresh one is worth it. Any other refusal is final.
class SessionExpiredError extends Error {}

// The server's own reason for a refusal (FastAPI's {"detail": "..."}), so budget,
// expiry and provider errors read exactly as the backend words them.
async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    /* not JSON */
  }
  return fallback;
}

async function exchangeInvite(invite: string): Promise<string> {
  const res = await fetch(`${BASE}/auth/invite`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: invite }),
  });
  if (!res.ok) {
    const message = await errorMessage(res, t.access.invalid);
    forgetAccess();
    throw new Error(message);
  }
  const token = (await res.json()).access_token as string;
  localStorage.setItem(INVITE_KEY, invite);
  localStorage.setItem(TOKEN_KEY, token);
  return token;
}

// Redeem a freshly opened invite link. Throws with the server's reason (not
// valid, expired) so the caller can show it.
export async function redeemInvite(invite: string): Promise<void> {
  localStorage.removeItem(TOKEN_KEY); // a new link replaces any previous session
  await exchangeInvite(invite);
}

async function ensureToken(): Promise<string> {
  const existing = localStorage.getItem(TOKEN_KEY);
  if (existing) return existing;
  const invite = localStorage.getItem(INVITE_KEY);
  if (!invite) throw new Error(t.access.none);
  return exchangeInvite(invite);
}

export type Account = {
  name: string;
  budget_usd: number;
  remaining_usd: number;
  expires_at: string | null;
};

// The signed-in account and its remaining budget, or null without live access.
export async function getAccount(): Promise<Account | null> {
  try {
    const res = await authedGet(`/auth/me`);
    if (!res || !res.ok) return null;
    return (await res.json()) as Account;
  } catch {
    return null;
  }
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
  if (res.status === 403) forgetAccess(); // the account expired
  return res;
}

// Authenticated POST with the same 401 self-heal as authedGet, and it throws on a
// non-OK response so callers can't silently proceed against a request that never
// took effect (e.g. a 409 confirm/revise on a query no longer awaiting a plan).
async function authedPost(path: string, body?: object): Promise<Response> {
  const init = (token: string): RequestInit => ({
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  let token = await ensureToken();
  let res = await fetch(`${BASE}${path}`, init(token));
  if (res.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    token = await ensureToken();
    res = await fetch(`${BASE}${path}`, init(token));
  }
  if (res.status === 403) forgetAccess(); // the account expired
  if (!res.ok) throw new Error(await errorMessage(res, `Request failed (${res.status}).`));
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

const AGENTS = ["supervisor", "planner", "researcher", "writer"] as const;
type Agent = (typeof AGENTS)[number];
const isAgent = (value: unknown): value is Agent => AGENTS.includes(value as Agent);

// Map a persisted backend event to the AgentEvent the progress bar reads. Returns
// null for internal events it doesn't surface (planner_clamped, researcher_forced…).
function toAgentEvent(e: BackendEvent): AgentEvent | null {
  const d = e.data ?? {};
  // Events from inside a researcher carry its number (the orchestrator tags them).
  const index = typeof d.index === "number" ? d.index : undefined;
  switch (e.type) {
    case "planner_start":
      return { kind: "planner", state: "start" };
    case "planner_done":
      return { kind: "plan", items: (d.sub_questions as string[]) ?? [] };
    case "thinking":
      return isAgent(d.agent) ? { kind: "thinking", agent: d.agent, index } : null;
    case "researcher_start":
      return {
        kind: "researcher",
        state: "start",
        index: index ?? 1,
        total: (d.total as number) ?? 1,
        question: (d.sub_question as string) ?? e.message,
      };
    case "tool_call":
      if (d.tool === "fetch_page") {
        const url = (d.args as Record<string, unknown> | undefined)?.url;
        return { kind: "tool", action: "read", domain: hostname(url), index };
      }
      return {
        kind: "tool",
        action: "search",
        text: String((d.args as Record<string, unknown> | undefined)?.query ?? e.message),
        index,
      };
    case "tool_error":
      return { kind: "tool", action: "error", text: e.message, index };
    case "researcher_done":
      return {
        kind: "researcher",
        state: "done",
        index: index ?? 1,
        question: (d.sub_question as string) ?? "",
        outcome: d.found_info === false ? "empty" : "found",
      };
    case "researcher_failed":
      return {
        kind: "researcher",
        state: "done",
        index: index ?? 1,
        question: (d.sub_question as string) ?? "",
        outcome: "failed",
      };
    case "writer_start":
      return { kind: "writer", state: "start" };
    case "writer_done":
      return { kind: "writer", state: "done" };
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
  title: string | null;
  report: string | null;
  reply?: string | null;
  error: string | null;
  stopped?: boolean;
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
    throw new SessionExpiredError("Session expired. Try again.");
  }
  if (res.status === 403) forgetAccess(); // the account expired
  // 402 (budget used up) and 503 (provider down) carry a message worth showing.
  if (!res.ok) {
    throw new Error(await errorMessage(res, `Could not reach the research service (${res.status}).`));
  }
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
  } catch (err) {
    // One retry after a fresh session, only when the stored token went stale.
    if (!(err instanceof SessionExpiredError)) throw err;
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
  // The supervisor named the report when it created the query, so the title is
  // already on the assistant message: surface it before polling for the result.
  if (assistant.query?.title) cb.onTitle?.(assistant.query.title);
  return pollQuery(assistant.query_id, token, cb);
}

// Poll a query to its terminal state, draining the agent event feed as it goes.
// `sinceEventId` seeds the event cursor: a resumed poll (after confirm/revise)
// passes the last id it already showed, so the planner events from phase 1 are not
// re-fetched and duplicated into the feed.
async function pollQuery(
  id: number,
  token: string,
  cb: ResearchCallbacks,
  sinceEventId = 0,
): Promise<ResearchOutcome | null> {
  // The backend event id is a monotonic cursor and a stable, unique timeline id.
  let lastEventId = sinceEventId;
  const drainEvents = async () => {
    const events = await getEvents(id, lastEventId, token);
    for (const e of events) {
      lastEventId = Math.max(lastEventId, e.id);
      const mapped = toAgentEvent(e);
      if (mapped) cb.onEvent({ ...mapped, id: e.id, delay: 0 });
    }
  };

  // Poll until terminal.
  const giveUpAt = Date.now() + MAX_POLL_MS;
  let title: string | null = null;
  while (Date.now() < giveUpAt) {
    if (cb.isCancelled()) return null;
    const detail = await getQuery(id, token);
    cb.onHeartbeat?.(detail.seconds_since_heartbeat ?? null);
    // The routing job names the report once it has decided; show it as it lands.
    if (detail.title && detail.title !== title) {
      title = detail.title;
      cb.onTitle?.(title);
    }
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
      // The supervisor answered directly: a reply, and no report to open.
      if (detail.reply != null && !detail.report) {
        return {
          result: { report: "", sources: [], consulted: [], gaps: [] },
          outcome: "ok",
          reply: detail.reply,
        };
      }
      const result: Result = {
        report: detail.report ?? "",
        sources: detail.sources,
        consulted: detail.consulted_sources,
        gaps: detail.gaps,
      };
      return {
        result,
        outcome: outcomeFor(detail.status, result.report, result.sources.length),
        title: detail.title ?? undefined,
      };
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
// the research. Throws on a non-OK response so the caller surfaces the failure
// instead of polling a query that never started.
export async function confirmPlan(queryId: number): Promise<void> {
  await authedPost(`/research/query/${queryId}/confirm`);
}

// Reject the plan with optional feedback (POST .../revise): the backend re-plans
// and pauses again at awaiting_plan. Throws on a non-OK response.
export async function revisePlan(queryId: number, feedback: string): Promise<void> {
  await authedPost(`/research/query/${queryId}/revise`, { feedback });
}

// Resume polling an existing query (after confirm/revise) without posting a new
// message. Reuses the same poll loop, so it handles awaiting_plan again on revise.
// `sinceEventId` is the last feed event already shown, so the resumed poll appends
// only new events instead of re-draining the phase-1 planner events.
export async function resumeRun(
  queryId: number,
  cb: ResearchCallbacks,
  sinceEventId = 0,
): Promise<ResearchOutcome | null> {
  cb.onStatus("running");
  const token = await ensureToken();
  return pollQuery(queryId, token, cb, sinceEventId);
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
  title?: string;
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
    title: detail.title ?? undefined,
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
  title?: string; // the supervisor-given report title
  status: Status;
  error: string | null;
  stopped?: boolean; // the user stopped it: not shown as an error
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
    // A supervisor answer: older ones carry no query, newer ones a finished query
    // holding the reply.
    if (m.query_id == null || m.query?.reply) {
      turns.push({
        queryId: m.query_id,
        query: prompt,
        status: "complete",
        error: null,
        result: { report: "", sources: [], consulted: [], gaps: [] },
        reply: m.query?.reply ?? m.content,
      });
      continue;
    }
    const q = m.query;
    turns.push({
      queryId: m.query_id,
      query: prompt,
      title: q?.title ?? undefined,
      status: q?.status ?? "complete",
      error: q?.error ?? null,
      stopped: q?.stopped,
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

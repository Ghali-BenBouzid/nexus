// Real Nexus backend client. Used only when VITE_LIVE_MODE === "true".
//
// The run path is: submit -> poll the detail endpoint for the terminal result,
// while tailing GET /research/query/{id}/events for the real agent feed. The
// backend persists every emitted AgentEvent, so the feed shows the actual
// planner/researcher/writer progress (real "researcher k/N"), not a placeholder.
import type {
  AgentEvent,
  ConversationId,
  Doc,
  Mode,
  Output,
  OutputKind,
  Result,
  Source,
  Status,
  TimelineEvent,
} from "../types";
import { t } from "./i18n";
import { outcomeFor } from "./outcome";
import type { ResearchCallbacks, ResearchOutcome } from "./research";
import { sseFrames } from "./sse";

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
  kind?: string;
  report: string | null;
  error: string | null;
  sources: Source[];
  consulted_sources: Source[];
  gaps: string[];
  // The assistant's answer in the conversation.
  reply?: string | null;
  // Follow-up questions offered under the answer.
  // How long ago the job last showed signs of life (null before it starts).
  seconds_since_heartbeat?: number | null;
};

// The backend bounds a run (research budget, timeouts); this only stops a stream
// that would otherwise never end, such as a run whose job died unnoticed. It has
// to outlast the longest run there is, which is a deep one: settings.deep_timeout
// is 35 minutes, and cutting the stream first would read the still-running query
// row and report a finished run as failed.
const MAX_STREAM_MS = 50 * 60_000;

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

async function getQuery(id: number, token: string): Promise<QueryDetail> {
  const res = await fetch(`${BASE}/research/query/${id}?include_provenance=true`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Could not read the query (${res.status}).`);
  return (await res.json()) as QueryDetail;
}

// One agent event as the feed carries it.
type BackendEvent = {
  id: number;
  type: string;
  message: string;
  data: Record<string, unknown> | null;
};

function hostname(url: unknown): string {
  if (typeof url !== "string") return "source";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "source";
  }
}

const AGENTS = ["supervisor", "planner", "researcher", "writer", "fact_checker"] as const;
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
    case "document_read":
      return { kind: "tool", action: "document", text: String(d.document ?? e.message) };
    case "factcheck_start":
      return { kind: "started", run: "fact_check", text: String(d.document ?? "") };
    case "tool_call": {
      const args = (d.args as Record<string, unknown> | undefined) ?? {};
      if (d.tool === "fetch_page") {
        return { kind: "tool", action: "read", domain: hostname(args.url), index };
      }
      if (d.tool === "read_document" || d.tool === "read_report") {
        return { kind: "tool", action: "document", text: e.message };
      }
      if (d.tool === "deep_research" || d.tool === "fact_check") {
        return { kind: "started", run: d.tool, text: String(args.title ?? "") };
      }
      return {
        kind: "tool",
        action: "search",
        text: String(args.query ?? args.question ?? e.message),
        index,
      };
    }
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
// A turn belongs to a conversation: the first message creates one, follow-ups
// append to it. The conversation is what makes the chat survive a reload, and
// what a background run points back at when it finishes.

type ConvMessageQuery = {
  status: Status;
  title: string | null;
  report: string | null;
  reply?: string | null;
  error: string | null;
  stopped?: boolean;
  sources: Source[];
  gaps: string[];
};

type BackendOutput = {
  id: number;
  kind: string;
  conversation_id: ConversationId | null;
  title: string | null;
  prompt: string;
  status: Status;
  error: string | null;
  created_at: string;
  completed_at: string | null;
};

function toOutput(raw: BackendOutput): Output {
  return {
    id: raw.id,
    kind: (raw.kind as OutputKind) ?? "deep_research",
    title: raw.title ?? raw.prompt,
    prompt: raw.prompt,
    status: raw.status,
    conversationId: raw.conversation_id,
    error: raw.error,
    createdAt: raw.created_at,
    completedAt: raw.completed_at,
  };
}
export type ConvMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  query_id: number | null;
  created_at: string;
  documents?: BackendDoc[];
  query: ConvMessageQuery | null;
};
type BackendDoc = {
  id: number;
  message_id?: number | null;
  filename: string;
  media_type: string;
  size_bytes: number;
  pages: number | null;
  chars: number;
  truncated: boolean;
  ocr: boolean;
};

function toDoc(raw: BackendDoc): Doc {
  return {
    id: raw.id,
    messageId: raw.message_id ?? null,
    filename: raw.filename,
    mediaType: raw.media_type,
    sizeBytes: raw.size_bytes,
    pages: raw.pages,
    chars: raw.chars,
    truncated: raw.truncated,
    ocr: raw.ocr,
  };
}

type ConvDetail = {
  id: ConversationId;
  title: string | null;
  created_at: string;
  messages: ConvMessage[];
  documents?: BackendDoc[];
  artifacts?: BackendOutput[];
};

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

const startTurn = (
  prompt: string,
  conversationId: ConversationId | null,
  documentIds: number[],
  token: string,
  mode: Mode,
) =>
  conversationId == null
    ? postConvJson(`/conversations`, { prompt, document_ids: documentIds, mode }, token)
    : postConvJson(
        `/conversations/${conversationId}/messages`,
        { content: prompt, document_ids: documentIds, mode },
        token,
      );

// Create a conversation with no message in it. A file belongs to a conversation,
// so attaching one before the first message needs somewhere to put it; the
// message that carries it follows.
export async function createConversation(): Promise<ConversationId> {
  const token = await ensureToken();
  const detail = await postConvJson(`/conversations`, { prompt: "" }, token);
  return detail.id;
}

export async function runLiveResearch(
  prompt: string,
  cb: ResearchCallbacks,
  conversationId: ConversationId | null,
  documentIds: number[] = [],
  mode: Mode = "answer",
): Promise<ResearchOutcome | null> {
  cb.onStatus("running");

  let token = await ensureToken();
  let detail: ConvDetail;
  try {
    detail = await startTurn(prompt, conversationId, documentIds, token, mode);
  } catch (err) {
    // One retry after a fresh session, only when the stored token went stale.
    if (!(err instanceof SessionExpiredError)) throw err;
    token = await ensureToken();
    detail = await startTurn(prompt, conversationId, documentIds, token, mode);
  }
  cb.onConversation?.(detail.id);

  const assistant = lastAssistant(detail);
  // An older turn with no run behind it: show what it said and stop there.
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
  if (assistant.query?.title) cb.onTitle?.(assistant.query.title);
  return followQuery(assistant.query_id, token, cb);
}

// Follow a query to its terminal state over server-sent events.
//
// The stream carries two kinds of frame. Stored ones (a stage the run reached)
// have an `id`, which is the durable feed's cursor, so a reconnection can say
// where it got to. Live ones (a thought, a token) have none, because they are
// never stored: the reply is persisted whole when the turn ends.
//
// The stream says what is happening; the query row says what happened. So the
// run's outcome is read once, from the row, after the stream closes. A dropped
// connection then costs a redraw rather than the answer.
//
// `sinceEventId` seeds the cursor: a resumed follow passes the last id it has
// already drawn, so reopening a running conversation appends instead of
// duplicating.
async function followQuery(
  id: number,
  token: string,
  cb: ResearchCallbacks,
  sinceEventId = 0,
): Promise<ResearchOutcome | null> {
  let lastEventId = sinceEventId;
  const stop = new AbortController();
  const watchCancel = setInterval(() => {
    if (cb.isCancelled()) stop.abort();
  }, 250);
  const giveUp = setTimeout(() => stop.abort(), MAX_STREAM_MS);

  try {
    // fetch, not EventSource: EventSource cannot send an Authorization header,
    // and the usual workaround puts the token in the query string, where it
    // lands in access logs and browser history.
    const res = await fetch(
      `${BASE}/research/query/${id}/stream?after=${lastEventId}`,
      { headers: { Authorization: `Bearer ${token}` }, signal: stop.signal },
    );
    if (!res.ok || !res.body) throw new Error(`Could not follow the run (${res.status}).`);

    for await (const frame of sseFrames(res.body, stop.signal)) {
      if (frame.type === "done") break;
      if (frame.type === "token") {
        cb.onToken?.(frame.message);
        continue;
      }
      if (frame.type === "thought") {
        cb.onThought?.(frame.message);
        continue;
      }
      if (frame.type === "heartbeat") {
        const since = frame.data?.since;
        cb.onHeartbeat?.(typeof since === "number" ? since : null);
        continue;
      }
      if (typeof frame.id === "number") lastEventId = Math.max(lastEventId, frame.id);
      const mapped = toAgentEvent({
        id: frame.id ?? lastEventId,
        type: frame.type,
        message: frame.message,
        data: frame.data,
      });
      if (mapped) cb.onEvent({ ...mapped, id: frame.id ?? lastEventId, delay: 0 });
    }
  } catch (err) {
    // An aborted stream is either the user stopping or our own time limit; the
    // query row below still says what really happened.
    if (!stop.signal.aborted) throw err;
  } finally {
    clearInterval(watchCancel);
    clearTimeout(giveUp);
  }

  if (cb.isCancelled()) return null;
  return outcomeOf(await getQuery(id, token));
}

// What the run produced, from the row that is the source of truth.
function outcomeOf(detail: QueryDetail): ResearchOutcome {
  if (detail.status === "failed") {
    return {
      result: { report: "", sources: [], consulted: [], gaps: [] },
      outcome: "failed",
      error: detail.error ?? "The research run failed.",
    };
  }
  const result: Result = {
    report: detail.report ?? "",
    sources: detail.sources,
    consulted: detail.consulted_sources,
    gaps: detail.gaps,
  };
  if (detail.status !== "complete") {
    return { result, outcome: "failed", error: "The run stopped before it finished." };
  }
  return {
    result,
    outcome: outcomeFor(detail.status, detail.reply ?? "", result.sources.length),
    reply: detail.reply ?? "",
    title: detail.title ?? undefined,
  };
}

// Rejoin a run already in flight, without posting a new message: used when a
// conversation is reopened while one of its turns is still going.
// `sinceEventId` is the last feed event already on screen, so the stream
// appends only what came after it.
export async function resumeRun(
  queryId: number,
  cb: ResearchCallbacks,
  sinceEventId = 0,
): Promise<ResearchOutcome | null> {
  cb.onStatus("running");
  const token = await ensureToken();
  return followQuery(queryId, token, cb, sinceEventId);
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
  id: ConversationId;
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
  attachments?: Doc[]; // the files sent with this message
  title?: string;
  status: Status;
  error: string | null;
  stopped?: boolean; // the user stopped it: not shown as an error
  result: Result;
  reply?: string; // the answer, which is what a turn produces
};
export type LoadedConversation = {
  id: ConversationId;
  title: string | null;
  turns: LoadedTurn[];
  documents: Doc[];
  outputs: Output[];
};

// Rehydrate a whole conversation thread into turns (used on reload and when
// opening a past conversation). Each assistant message that carries a research
// run becomes a turn, with the preceding user message as its prompt.
export async function loadConversation(id: ConversationId): Promise<LoadedConversation | null> {
  const res = await authedGet(`/conversations/${id}`);
  if (!res || !res.ok) return null;
  const detail = (await res.json()) as ConvDetail;
  return {
    id: detail.id,
    title: detail.title,
    turns: turnsFrom(detail.messages),
    documents: (detail.documents ?? []).map(toDoc),
    outputs: (detail.artifacts ?? []).map(toOutput),
  };
}

// The thread's messages as turns: each assistant message with the user message
// before it. Exported, and separate from the fetch, so the mapping can be
// checked on its own: it is where a turn decides what it is and what it said.
export function turnsFrom(messages: ConvMessage[]): LoadedTurn[] {
  const detail = { messages };
  const turns: LoadedTurn[] = [];
  let prompt = "";
  let attached: Doc[] = [];
  for (const m of detail.messages) {
    if (m.role === "user") {
      prompt = m.content;
      attached = (m.documents ?? []).map(toDoc);
      continue;
    }
    // A turn with no run behind it (an older thread) still said something.
    if (m.query_id == null) {
      turns.push({
        queryId: null,
        query: prompt,
        attachments: attached,
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
      attachments: attached,
      title: q?.title ?? undefined,
      status: q?.status ?? "complete",
      error: q?.error ?? null,
      stopped: q?.stopped,
      reply: q?.reply ?? m.content,
      result: {
        report: "",
        sources: q?.sources ?? [],
        consulted: [],
        gaps: q?.gaps ?? [],
      },
    });
  }
  return turns;
}

// --- outputs (deep research reports, fact checks) ----------------------------

// Every report this account has, newest first. Listed across conversations,
// because a background run finishes long after the thread that asked for it.
export async function listOutputs(): Promise<Output[]> {
  const res = await authedGet(`/research/artifacts`);
  if (!res || !res.ok) return [];
  return ((await res.json()) as BackendOutput[]).map(toOutput);
}

// One output's report and sources, loaded when it is opened.
export async function openOutput(id: number): Promise<Result | null> {
  const loaded = await openQuery(id);
  return loaded ? loaded.result : null;
}

// --- uploads ------------------------------------------------------------------

export async function listDocuments(conversationId: ConversationId): Promise<Doc[]> {
  const res = await authedGet(`/conversations/${conversationId}/documents`);
  if (!res || !res.ok) return [];
  return ((await res.json()) as BackendDoc[]).map(toDoc);
}

// Upload one file into a conversation. Throws with the server's own reason (too
// large, unreadable, too many), which is written to be shown as it is.
export async function uploadDocument(conversationId: ConversationId, file: File): Promise<Doc> {
  const token = await ensureToken();
  const body = new FormData();
  body.append("file", file);
  const res = await fetch(`${BASE}/conversations/${conversationId}/documents`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body,
  });
  if (!res.ok) throw new Error(await errorMessage(res, t.uploads.failed));
  return toDoc((await res.json()) as BackendDoc);
}

export async function deleteDocument(id: number): Promise<void> {
  const token = await ensureToken();
  await fetch(`${BASE}/documents/${id}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
}

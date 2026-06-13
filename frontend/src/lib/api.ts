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

async function submitQuery(prompt: string, token: string): Promise<number> {
  const res = await fetch(`${BASE}/research/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ prompt }),
  });
  if (res.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    throw new Error("Session expired. Try again.");
  }
  if (!res.ok) throw new Error(`Could not start research (${res.status}).`);
  return (await res.json()).id as number;
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

export async function runLiveResearch(
  prompt: string,
  cb: ResearchCallbacks,
): Promise<ResearchOutcome | null> {
  cb.onStatus("running");

  let token = await ensureToken();
  let id: number;
  try {
    id = await submitQuery(prompt, token);
  } catch {
    // One retry after a fresh session, in case a stored token went stale.
    token = await ensureToken();
    id = await submitQuery(prompt, token);
  }

  // Drain any agent events emitted since the last poll into the feed, in order.
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

// --- query history ----------------------------------------------------------

export type QuerySummary = { id: number; prompt: string; status: Status; created_at: string };

// The caller's past queries, newest first (GET /research/query). Best-effort: an
// auth/network hiccup yields an empty list rather than throwing into the UI.
export async function listQueries(): Promise<QuerySummary[]> {
  const res = await authedGet(`/research/query`);
  if (!res || !res.ok) return [];
  return (await res.json()) as QuerySummary[];
}

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

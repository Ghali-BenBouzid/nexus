// Real Nexus backend client. Used only when VITE_LIVE_MODE === "true".
//
// The submit -> poll -> report path is fully supported by the backend today.
// The detailed live event stream is NOT yet (the backend's emit sink only logs;
// no SSE endpoint), so live runs show a minimal synthetic feed and the real
// payoff is the cited report. When the streaming endpoint lands, swap the synthetic
// events for the real ones with no UI change.
import type { Result, Source, Status } from "../types";
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

async function ensureToken(): Promise<string> {
  const existing = localStorage.getItem(TOKEN_KEY);
  if (existing) return existing;

  // A throwaway per-browser demo account so anyone can try a live run.
  let creds = localStorage.getItem(CREDS_KEY);
  if (!creds) {
    const rand = Math.random().toString(36).slice(2, 10);
    creds = JSON.stringify({ email: `demo+${rand}@nexus.app`, password: rand + "Aa1!" });
    localStorage.setItem(CREDS_KEY, creds);
  }
  const { email, password } = JSON.parse(creds) as { email: string; password: string };

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

async function getQuery(id: number, token: string): Promise<QueryDetail> {
  const res = await fetch(`${BASE}/research/query/${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Could not read the query (${res.status}).`);
  return (await res.json()) as QueryDetail;
}

export async function runLiveResearch(
  prompt: string,
  cb: ResearchCallbacks,
): Promise<ResearchOutcome | null> {
  cb.onStatus("running");
  cb.onEvent({
    id: 0,
    delay: 0,
    kind: "planner",
    state: "start",
    title: "Planning your research",
    sub: "Submitting the question to the agent pipeline.",
  });

  let token = await ensureToken();
  let id: number;
  try {
    id = await submitQuery(prompt, token);
  } catch {
    // One retry after a fresh session, in case a stored token went stale.
    token = await ensureToken();
    id = await submitQuery(prompt, token);
  }

  let announcedRunning = false;
  // Poll until terminal. The 5-min backstop on the backend bounds this.
  for (let i = 0; i < 240; i++) {
    if (cb.isCancelled()) return null;
    const detail = await getQuery(id, token);

    if (detail.status === "running" && !announcedRunning) {
      announcedRunning = true;
      cb.onEvent({
        id: 1,
        delay: 0,
        kind: "researcher",
        state: "start",
        index: 1,
        total: 1,
        question: "Researching the live web…",
      });
    }

    if (detail.status === "complete") {
      cb.onEvent({
        id: 2,
        delay: 0,
        kind: "writer",
        state: "done",
        title: "Report ready",
        sub: "Citations linked to sources.",
      });
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

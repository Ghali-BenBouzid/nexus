// Simulated research engine — ported from the handoff's nexus-data.js. Mirrors
// the backend contract: a job emits AgentEvents while running, then resolves to
// a cited Result. Used for the instant, no-auth demo runs (example chips and any
// prompt while VITE_LIVE_MODE is off).
import type { AgentEvent, Result, TimelineEvent } from "../types";

type ToolStep =
  | { action: "search"; text: string }
  | { action: "read"; domain: string; title: string }
  | { action: "error"; text: string };

type Researcher = { q: string; tools: ToolStep[]; found: number; gap?: string };

export type Run = {
  prompt: string;
  plan: string[];
  researchers: Researcher[];
  result: Result;
};

const GRID: Run = {
  prompt: "What are the most promising approaches to grid-scale energy storage in 2026?",
  plan: [
    "How do lithium-ion and emerging battery chemistries compare for grid-scale storage today?",
    "Which long-duration storage technologies are maturing, and what do they cost?",
    "What 2025–2026 policies and market signals are driving deployment?",
  ],
  researchers: [
    {
      q: "Lithium-ion vs. emerging chemistries",
      tools: [
        { action: "search", text: "grid-scale lithium-ion LFP cost per kWh 2026" },
        { action: "read", domain: "iea.org", title: "Grid-Scale Storage — IEA" },
        { action: "read", domain: "about.bnef.com", title: "2025 Battery Price Survey" },
        { action: "search", text: "sodium-ion grid storage commercial deployment" },
      ],
      found: 2,
    },
    {
      q: "Long-duration storage (LDES)",
      tools: [
        { action: "search", text: "long-duration energy storage technologies cost 2026" },
        { action: "read", domain: "nrel.gov", title: "Long-Duration Energy Storage" },
        { action: "read", domain: "nature.com", title: "Flow batteries for grid storage" },
        { action: "error", text: "iron-air vendor pricing page timed out (504)" },
      ],
      found: 2,
      gap: "Verified 2026 grid-scale pricing for iron-air batteries — the primary vendor source timed out, so cost figures could not be confirmed.",
    },
    {
      q: "Policy & market drivers",
      tools: [
        { action: "search", text: "energy storage policy IRA 45X 2025 2026 incentives" },
        { action: "read", domain: "energy.gov", title: "Energy Storage Grand Challenge" },
        { action: "read", domain: "iea.org", title: "Electricity 2026 — market outlook" },
      ],
      found: 3,
    },
  ],
  result: {
    report: `## The short answer

Grid-scale storage in 2026 is no longer a single bet on one chemistry. **Lithium iron phosphate (LFP) remains the workhorse** for the 1–4 hour duration band, while a credible field of **long-duration** technologies is moving from pilots into first commercial deployments to cover the 8–100+ hour gap that renewables increasingly demand [1][3].

## Lithium-ion is cheaper and safer than the headlines suggest

Pack prices fell sharply through 2025, and LFP now dominates new stationary projects on cost and cycle-life grounds, having largely displaced nickel-manganese chemistries for grid use [2]. For daily cycling up to ~4 hours, lithium-ion is the default — abundant, bankable, and fast to deploy [1].

The interesting frontier is **sodium-ion**: it trades some energy density for cheaper, more abundant materials and better cold-weather behavior, and the first grid-scale installations are now online — promising for cost-sensitive, stationary use where footprint matters less than price [2].

## Long-duration storage is the real 2026 story

Beyond ~6 hours, lithium economics weaken and a portfolio of approaches competes [3]:

- **Flow batteries** (vanadium and iron) decouple power from energy, so adding hours is cheap — well-suited to 8–12 hour shifting [5].
- **Iron-air** targets multi-day duration at very low material cost, with first utility deployments underway.
- **Thermal and gravity/mechanical** storage offer 10–100 hour discharge for grid firming.

The U.S. DOE's storage program explicitly targets a large cost reduction for long-duration systems this decade, and treats LDES as the missing piece for a high-renewables grid [4].

## What's actually driving deployment

Policy is the accelerant. Manufacturing and investment incentives have pulled battery supply chains onshore and improved project economics, while capacity markets increasingly value the firm, dispatchable capability that storage provides [4]. Market signals — rising curtailment and widening price spreads on renewable-heavy grids — now make daily arbitrage profitable in more regions than a year ago [1].

**Bottom line:** pair LFP (and increasingly sodium-ion) for daily cycling with an emerging LDES layer — flow and iron-air leading — and let policy plus arbitrage economics decide the mix region by region [1][3][4].`,
    sources: [
      { title: "Grid-Scale Storage", url: "https://www.iea.org/energy-system/electricity/grid-scale-storage" },
      { title: "2025 Battery Price Survey", url: "https://about.bnef.com/insights/clean-energy/battery-prices" },
      { title: "Long-Duration Energy Storage", url: "https://www.nrel.gov/analysis/long-duration-storage.html" },
      { title: "Energy Storage Grand Challenge", url: "https://www.energy.gov/energy-storage-grand-challenge" },
      { title: "Flow batteries for grid storage", url: "https://www.nature.com/nenergy" },
    ],
    consulted: [
      { title: "Grid energy storage — overview", url: "https://en.wikipedia.org/wiki/Grid_energy_storage" },
      { title: "Sodium-ion battery", url: "https://en.wikipedia.org/wiki/Sodium-ion_battery" },
      { title: "Form Energy — iron-air", url: "https://formenergy.com/technology" },
      { title: "EIA — battery storage capacity", url: "https://www.eia.gov/todayinenergy" },
    ],
    gaps: [],
  },
};

const LLM: Run = {
  prompt: "How are small language models changing on-device AI in 2026?",
  plan: [
    "What capability thresholds have small (1–8B) models crossed for on-device use?",
    "Which quantization and runtime techniques make them practical on phones and laptops?",
    "What are the privacy, latency, and cost trade-offs versus cloud models?",
  ],
  researchers: [
    {
      q: "Capability of small models",
      tools: [
        { action: "search", text: "small language models 2026 benchmark on-device" },
        { action: "read", domain: "arxiv.org", title: "Survey: efficient small LMs" },
        { action: "read", domain: "huggingface.co", title: "Open model leaderboard" },
      ],
      found: 2,
    },
    {
      q: "Quantization & runtimes",
      tools: [
        { action: "search", text: "4-bit quantization on-device inference llama.cpp 2026" },
        { action: "read", domain: "github.com", title: "On-device runtime benchmarks" },
        { action: "error", text: "vendor whitepaper behind login (401)" },
      ],
      found: 1,
      gap: "Independent battery-draw measurements for sustained on-device inference were not available from a primary source.",
    },
    {
      q: "Trade-offs vs cloud",
      tools: [
        { action: "search", text: "on-device vs cloud LLM privacy latency cost" },
        { action: "read", domain: "arxiv.org", title: "Edge vs cloud inference economics" },
      ],
      found: 2,
    },
  ],
  result: {
    report: `## The short answer

Small language models (roughly 1–8B parameters) have crossed the threshold where **useful assistants now run entirely on a phone or laptop**, with no network round-trip. The shift in 2026 is less about raw quality and more about *good-enough quality at near-zero marginal cost and full privacy* [1][3].

## What changed

Distillation and better training data closed much of the gap: today's small models match the general-assistant quality of cloud models from ~18 months earlier on everyday tasks — summarizing, drafting, classification, and structured extraction [1]. They still trail frontier models on long-horizon reasoning, so the emerging pattern is **hybrid**: handle most requests locally, escalate the hard ones to the cloud [3].

## Why it's now practical

Two engineering advances did the heavy lifting: aggressive **quantization** (4-bit and below with minimal quality loss) and tightly optimized **on-device runtimes** that exploit the NPUs now shipping in mainstream phones and laptops [2]. Together these cut memory and energy enough to make sustained inference viable on consumer hardware.

## The trade-offs

- **Privacy:** data never leaves the device — decisive for messaging, health, and enterprise use [3].
- **Latency:** no network hop means instant first-token response.
- **Cost:** no per-call inference bill, shifting economics from operators to a one-time hardware cost [3].

**Bottom line:** small on-device models won't replace frontier systems, but they're absorbing the long tail of everyday AI — privately, instantly, and essentially for free [1][3].`,
    sources: [
      { title: "A survey of efficient small language models", url: "https://arxiv.org/list/cs.CL/recent" },
      { title: "Open model leaderboard", url: "https://huggingface.co/spaces/open-llm-leaderboard" },
      { title: "Edge vs cloud inference economics", url: "https://arxiv.org/abs/2401.00001" },
    ],
    consulted: [
      { title: "llama.cpp", url: "https://github.com/ggml-org/llama.cpp" },
      { title: "Quantization — overview", url: "https://en.wikipedia.org/wiki/Quantization_(signal_processing)" },
    ],
    gaps: [],
  },
};

export const PRESETS: Run[] = [GRID, LLM];

function buildGeneric(prompt: string): Run {
  const topic = prompt.replace(/\s+/g, " ").trim().replace(/[?.!]+$/, "");
  const t = topic.length > 64 ? topic.slice(0, 64) + "…" : topic;
  return {
    prompt,
    plan: [
      `Establish the background and key definitions behind ${t}.`,
      `Survey the current state of the art and leading approaches.`,
      `Identify open challenges, risks, and what comes next.`,
    ],
    researchers: [
      {
        q: "Background & definitions",
        tools: [
          { action: "search", text: `${t} overview explained` },
          { action: "read", domain: "wikipedia.org", title: `${t} — overview` },
          { action: "read", domain: "nature.com", title: "Foundational review" },
        ],
        found: 2,
      },
      {
        q: "State of the art",
        tools: [
          { action: "search", text: `${t} latest developments 2026` },
          { action: "read", domain: "arxiv.org", title: "Recent advances" },
          { action: "search", text: `${t} leading approaches comparison` },
        ],
        found: 2,
      },
      {
        q: "Challenges & outlook",
        tools: [
          { action: "search", text: `${t} open problems limitations` },
          { action: "read", domain: "reuters.com", title: "Industry outlook" },
        ],
        found: 2,
      },
    ],
    result: {
      report: `## Overview

This report synthesizes what the agents found on **${topic}**. The sources below back each claim; click any **[n]** marker to jump to its source, and switch on *Show everything consulted* to audit the full trail.

## Background

A grounded answer starts with definitions and the problem space around ${t} [1]. The literature converges on a shared vocabulary that the more recent, applied work then builds on [2].

## State of the art

Current approaches cluster into a few families, each with distinct trade-offs in cost, maturity, and applicability [2]. The most active frontier is where these approaches are being combined rather than used in isolation [1].

## Challenges & outlook

The open problems are as much practical as theoretical — data, deployment, and trust — and the near-term trajectory favors incremental, measurable gains over step changes [2].

> This is a **simulated** run wired to the live agent-feed UI. Connect the Nexus API and the same interface streams real plans, searches, and a cited report.`,
      sources: [
        { title: `${t} — overview`, url: "https://en.wikipedia.org/wiki/Main_Page" },
        { title: "Recent advances (preprint)", url: "https://arxiv.org/list/cs/recent" },
      ],
      consulted: [
        { title: "Industry outlook", url: "https://www.reuters.com/technology" },
        { title: "Foundational review", url: "https://www.nature.com" },
      ],
      gaps: [],
    },
  };
}

// Match a typed prompt to a preset so demo chips & related prompts get the rich report.
export function pickRun(prompt: string): Run {
  const p = (prompt || "").toLowerCase();
  if (/(storage|battery|batteries|grid|energy)/.test(p)) return GRID;
  if (/(language model|llm|on-device|on device|ai model|small model)/.test(p)) return LLM;
  return buildGeneric(prompt);
}

// Flatten a run into an ordered, timed event list the UI reveals one by one.
export function toTimeline(run: Run): { timeline: TimelineEvent[]; result: Result } {
  const ev: TimelineEvent[] = [];
  let id = 0;
  const push = (e: AgentEvent, delay: number) =>
    ev.push({ ...e, id: id++, delay } as TimelineEvent);

  push(
    {
      kind: "planner",
      state: "start",
      title: "Planning your research",
      sub: "Decomposing the question into sub-questions to research in parallel.",
    },
    500,
  );
  push({ kind: "plan", items: run.plan }, 1300);

  run.researchers.forEach((r, i) => {
    push(
      { kind: "researcher", state: "start", index: i + 1, total: run.researchers.length, question: r.q },
      900,
    );
    r.tools.forEach((tool) => {
      push({ kind: "tool", ...tool }, tool.action === "read" ? 850 : 700);
    });
    const sub = r.gap
      ? `Found ${r.found} relevant source${r.found === 1 ? "" : "s"} · 1 lead degraded to a gap`
      : `Found ${r.found} relevant source${r.found === 1 ? "" : "s"}`;
    push({ kind: "researcher", state: "done", index: i + 1, question: r.q, sub, hasGap: !!r.gap }, 650);
  });

  push(
    {
      kind: "writer",
      state: "start",
      title: "Writing the report",
      sub: `Synthesizing ${run.researchers.length} findings into a single cited report.`,
    },
    1000,
  );
  push({ kind: "writer", state: "done", title: "Report ready", sub: "Citations linked to sources." }, 1600);

  const gaps = run.researchers.filter((r) => r.gap).map((r) => r.gap as string);
  const result: Result = { ...run.result, gaps: gaps.concat(run.result.gaps || []) };
  return { timeline: ev, result };
}

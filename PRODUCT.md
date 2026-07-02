# Nexus — Product Context

## Register
Product (app UI) with a brand landing surface. The conversation workspace, report
panel, and composer are product UI (design serves the task); the marketing hero +
sections are brand (design is part of the showcase). When the two conflict, the
app surface follows the product register and the hero follows brand.

## What it is
An API-first agentic research platform. The UI is a chat workspace where a
supervisor routes each message: answer directly from the conversation and prior
reports, compose (merge and expand existing reports), or launch a fresh research
run. A run is a team of agents (planner → parallel researchers with web-search/fetch
tools → consolidator → writer) that produces one cited report. Live agent activity
streams as the assistant's reply, and each finished report opens as an artifact in a
side panel with numbered, clickable sources.

## Target users
- **Recruiters / hiring managers** landing on the live demo (primary for this phase).
  They skim for craft, then try one query. First impression + one smooth run decide everything.
- **Engineers** evaluating the design patterns (agent orchestration, provider seam,
  rate-limiting, streaming) — they read the code and poke the API.

## Purpose / job-to-be-done
Demonstrate, in under two minutes, (1) strong product/UX craft and (2) real agentic
AI capability: plan a question, research the live web in parallel, and return a
report where every claim is backed by a source. It must run reliably on a free LLM
tier (~50-90s per run).

## Brand personality
Precise, calm, technical-but-legible. A "research instrument," not a toy chatbot.
Signature look: a single gold accent across both themes (dark, default: gold on
near-black; light: gold on warm neutral) over a live WebGL fluid background, with
glass panels reserved for surfaces that sit over that background. A Design Lab lets
the user switch accent palette and font; gold + Hanken Grotesk is the locked default.
Mono (JetBrains Mono) for system/agent voice, Hanken Grotesk for headings and body.

## Anti-references (what it must NOT look like)
- Generic SaaS-cream landing with a hero-metric template and identical card grids.
- A toy chatbot with rainbow gradients and emoji.
- Decorative glassmorphism everywhere / gradient text as "premium."
- Clinical enterprise dashboard with no point of view.

## Strategic design principles
1. **The agent's work is the product.** Show real progress (planner, researcher k/N,
   tool calls, writer), never a fake spinner standing in for the truth.
2. **Citations are first-class.** Every report claim maps to a numbered source the
   user can click; sources read as part of the document, not a dumped list.
3. **One run, no dead ends.** Stop, retry, history, honest empty/failed states.
   The user is never trapped or guessing.
4. **Free-tier honesty.** Latency is real (~1 min); the UI makes the wait legible
   and reassuring rather than hiding it.
5. **Earned familiarity in the app, point-of-view in the hero.** The chat behaves
   like tools people trust; the landing shows craft.

## Near-term direction (not yet shipped)
- **Identity-aware answers.** The supervisor knows what Nexus is and who built it
  (Ghali Ben Bouzid), and handles identity questions directly or via targeted search.
- **Demo transparency.** Visible free-tier framing: queries remaining, limits, and
  usage, so the constraints are honest and legible rather than hidden.
- **Multi-user concurrency.** Support ~20 simultaneous users via pooled API keys and
  per-agent provider/model routing.
- **Language robustness.** Reliably match the user's language on short or ambiguous
  queries (confidence-gated detection with a soft fallback).

# Nexus: Product Context

## Register
Product (app UI) with a brand landing surface. The conversation workspace, report
panel, and composer are product UI (design serves the task); the marketing hero +
sections are brand (design is part of the showcase). When the two conflict, the
app surface follows the product register and the hero follows brand.

## What it is
An API-first agentic research platform. The UI is a chat workspace where you talk
to one agent that decides how much work your message deserves: answer now, run a
search, send a team of researchers after it in parallel, read a file you attached,
or start a run that takes minutes. Answers land in the conversation with every
claim cited to a page that was actually read; live agent activity streams above
the answer as it happens. Two kinds of work produce a document rather than a reply,
and both run in the background: deep research, and fact-checking an uploaded file.
Those appear in a Reports panel, with a notification when one is ready.

Live research is invite-only. Each demo account comes from an invite link, has its
own dollar budget (shown under the composer), and is billed from what each model
call actually cost. Visitors without an invite get a clearly labeled simulated run.

## Target users
- **Recruiters / hiring managers** landing on the live demo (primary for this phase).
  They skim for craft, then try one query. First impression + one smooth run decide everything.
- **Engineers** evaluating the design patterns (agent orchestration, provider seam,
  rate-limiting, streaming): they read the code and poke the API.

## Purpose / job-to-be-done
Demonstrate, in under two minutes, (1) strong product/UX craft and (2) real agentic
AI capability: plan a question, research the live web in parallel, and return a
report where every claim is backed by a source. Live runs use a paid OpenRouter key
with a hard credit limit, split into small per-account budgets.

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
1. **The agent's work is the product.** Show real progress (which tool, researcher
   k/N, what it searched), never a fake spinner standing in for the truth.
2. **Citations are first-class.** Every report claim maps to a numbered source the
   user can click; sources read as part of the document, not a dumped list.
3. **One run, no dead ends.** Stop, retry, history, honest empty/failed states,
   and follow-up suggestions under every answer. The user is never trapped or guessing.
4. **Honest constraints.** Latency is real and the demo budget is finite; the UI
   shows both (the wait, the budget left) rather than hiding them.
5. **Earned familiarity in the app, point-of-view in the hero.** The chat behaves
   like tools people trust; the landing shows craft.

## Near-term direction (not yet shipped)
- **Per-agent model routing** chosen from eval results: a cheap model for the
  supervisor's own turns, a stronger one for a deep run's report.
- **Language robustness.** Reliably match the user's language on short or ambiguous
  queries (confidence-gated detection with a soft fallback).
- **A free search backend**, so breadth and prompt-injection resistance can be
  measured at the scale the eval set deserves without a per-search bill.

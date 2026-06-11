# Handoff: Nexus — Agentic Research Frontend

## Overview
Nexus is an API-first agentic research product: a user asks a question, a team of
agents (planner → researchers → writer) researches the live web, and the product
returns a single report where **every claim is backed by a cited source**.

This design is a single immersive page that flows through three states:

1. **Home / hero** — a living-fluid 3D background, a headline, and a working prompt box.
2. **Run** — a live, streaming agent-activity feed (Claude-Code style) while the research executes.
3. **Report** — a cited markdown report beside a persistent Sources panel, plus a "gaps" card.

A dark theme (signature violet fluid) and a light theme (amber fluid) are both first-class,
toggled from the nav.

---

## About the Design Files
The files in this bundle are **design references created in HTML/CSS/React-via-Babel** —
prototypes that demonstrate the intended look, motion, and behavior. **They are not meant
to be shipped as-is.** Babel-in-the-browser, CDN React, and inline JSX are prototyping
conveniences, not production choices.

Your task is to **recreate these designs in the target codebase's environment** using its
established patterns, component library, and build pipeline. If no frontend environment
exists yet, choose an appropriate stack — **React + TypeScript + Vite** is a natural fit
given the component structure here, with the Three.js background as a single self-contained
module.

The one piece worth porting nearly verbatim is **`fluid-background.js`** — the WebGL/Three.js
shader. It is framework-agnostic and can be dropped into a React `useEffect` / Vue `onMounted`
with minimal change. See "The Fluid Background" below.

## Fidelity
**High-fidelity (hifi).** Final colors, typography, spacing, motion, and interaction states
are all specified. Recreate the UI pixel-perfectly using the codebase's existing primitives
where they exist (buttons, cards), but match the exact tokens listed under **Design Tokens**.

---

## The Big Picture: a state machine
The entire app is one state machine. Model it explicitly.

```
view: "home" | "run"
status: "pending" | "running" | "complete" | "failed"   (only meaningful when view === "run")
outcome: "ok" | "empty" | "failed"                        (resolved result shape)
```

- `home` renders the hero + marketing sections + footer.
- Submitting the prompt → `view: "run"`, `status: "running"`, the feed begins streaming events.
- On success → `status: "complete"`, `outcome: "ok"` → render report + sources.
- `outcome: "empty"` → "No sources found" state card. `outcome / status: "failed"` → "This run failed" card.
- The nav logo and the run-screen back button return to `home`.

> **In the prototype the run is *simulated*** — `nexus-data.js` holds scripted demo runs and a
> `toTimeline()` function that flattens a run into timed events the UI reveals one by one.
> In production, replace this with real API calls. The UI contract (event kinds + report shape)
> is documented under **Data Contract** so the feed and report components stay unchanged.

---

## Screens / Views

### 1. Navigation (persistent)
- **Layout**: Fixed top bar, full width, `padding: 18px 0`, content constrained to `max-width: 1120px`
  centered with `28px` inline padding. Flex row, space-between.
- **Left**: Brand — a 30×30px rounded-square mark (`border-radius: 9px`) with a `≈` glyph,
  filled with a `150deg` linear gradient from `--accent-2` → `--accent`, soft accent shadow.
  Wordmark "Nexus" in Space Grotesk 700, 19px, beside it (gap 11px).
- **Center**: Nav links (How it works / Live agents / Citations / Documents) — Instrument Sans
  14.5px, `--muted`, hover → `--fg`. Hidden below 920px.
- **Right**: Circular theme toggle (38px, sun/moon icon, rotates 18° on hover), a "Sign in"
  text link, and a primary "Start researching" pill button.
- **Scroll behavior**: After 16px scroll (or whenever `view === "run"`), the nav gains class
  `scrolled`: a translucent `--bg` background at 72% opacity, `backdrop-filter: blur(18px)
  saturate(1.4)`, and a `1px` bottom border in `--line`. Above the fold on home it is transparent.

### 2. Hero (home)
- **Layout**: `min-height: 100vh`, flex column, centered both axes, `text-align: center`,
  `padding: 130px 0 80px`. A `::before` radial scrim (theme-bg, fading to transparent) sits
  behind the copy to lift text off the bright center of the fluid blob.
- **Badge**: Pill, `--surface` with `--line` border, `backdrop-filter: blur(10px)`. A 7px
  accent pip with a 4px soft-glow ring, then "A team of agents researches for you · **cited,
  in real time**". 13px.
- **Headline**: Two lines, Space Grotesk 700, `clamp(44px, 8.2vw, 96px)`, `line-height: 0.98`,
  `letter-spacing: -0.035em`.
  - Line 1: "Ask anything." in `--fg`.
  - Line 2: "Get a cited answer." with a `110deg` gradient text fill (`--accent-2` → `--accent`
    → `--accent-2`, clipped to text).
  - Each character is wrapped in a `.char` span for the entrance animation (see Motion).
- **Subhead**: Instrument Sans, `clamp(17px, 2.1vw, 21px)`, `--muted`, `max-width: 56ch`,
  `line-height: 1.5`. Copy: "Nexus plans your question into sub-questions, sends a team of
  agents to research the live web, and returns one report where every claim is backed by a source."
- **Prompt box** (the primary CTA — see component spec below).
- **Example chips**: A centered flex-wrap row of pill buttons, each a preset research prompt.
  13.5px, `--surface` bg, `--line` border; hover → `--fg` text, `--accent` border,
  `--accent-soft` bg. Clicking a chip starts that research run.

### 3. Marketing sections (home, below hero)
These appear only on home, in this order. Each is a `.section` (`padding: 96px 0`),
content in the 1120px wrap.
- **How it works** (`#how`): Eyebrow + h2 ("A research team, working in the open.") + sub, then a
  3-column card grid (Plan / Research / Cite), each card with a numbered label, an icon tile
  (42px, `--accent-soft` bg, `--accent` icon), title (Space Grotesk 600, 21px) and description.
  Cards: `--surface` bg, `--line` border, `border-radius: 22px`, `28px` padding, lift `-3px`
  and brighten border on hover.
- **Live agent feed** (`#feed`): Two-column feature row (1.05fr / 1fr). Left: copy + a checklist
  (accent ticks) + a ghost "See a live run" button that triggers the first preset. Right: a
  static mini-feed preview card (mono 12.5px rows with colored status dots: done = `--ok`,
  running = pulsing `--accent-2`, idle = `--faint`).
- **Citations** (`#sources`): Same feature row, **flipped** (visual on left). Right copy explains
  click-to-cite + provenance. Left: an interactive mini demo — a claim sentence with `[2]` `[3]`
  superscripts; clicking one highlights the matching source card below.
- **Roadmap** (`#soon`): Eyebrow + h2 ("Built forward-compatible.") + a 2-column card grid
  (Live streaming / Research history / Provenance audit / Your private documents).

### 4. Footer
- Top border `--line`, `padding: 60px 0 50px`. Flex row, space-between, wrap. Left: brand +
  one-line description. Right: three link columns (Product / Developers / Company) with mono
  uppercase 11px headers. A bottom note row separated by a `--line` divider.

### 5. Run screen (view === "run")
- **Layout**: `.run`, `padding: 110px 0 80px`, content in the 1120px wrap. When this view is
  active, `body[data-stage]` becomes `run` (or `report` once complete), which **dims the fluid
  canvas to ~0.12 opacity** and raises a gradient scrim so dense text stays legible.
- **Run header**: Flex row, gap 18px.
  - Back button: 42px rounded square, `--surface`/`--line`, left-arrow icon.
  - Query block: a mono eyebrow "Research query" + the question in Space Grotesk 700,
    `clamp(24px, 3.4vw, 36px)`.
  - Status pill (right): mono 12.5px with a status dot — running = pulsing `--accent-2`,
    complete = `--ok`, failed = `--bad` — plus an elapsed `m:ss` timer in `--faint`.
- **While running** → the **Agent Feed** (below). **When complete** → a "Show agent activity"
  toggle (collapsed feed) above the **Report + Sources grid**. **Empty/failed** → a centered
  state card.

---

## Key Component Specs

### Prompt box
- Container `.prompt`: flex row, `align-items: flex-end`, `--surface` bg, `1px --line-strong`
  border, `border-radius: 28px`, `padding: 16px 16px 16px 22px`, `backdrop-filter: blur(22px)
  saturate(1.5)`, the shared `--shadow`. On focus-within: border → `--accent` plus a 4px
  `--accent-soft` focus ring.
- Textarea: transparent, no border/outline, auto-grows from 1 row to `max-height: 180px`
  (`overflow: hidden`), Instrument Sans 17px. Placeholder "Ask Nexus to research anything…"
  in `--faint`.
- Submit button `.prompt-go`: 46px, `border-radius: 14px`, `--accent` bg, up-arrow icon,
  lifts on hover, **disabled (40% opacity) when the field is empty**.
- **Keyboard**: Enter submits; Shift+Enter inserts a newline.
- Meta row below: left hint text ("Press **Enter** to research · Shift+Enter for a new line"),
  right a mono "Plan → Research → Cite" stepper.

### Agent Feed (`.feed-shell`)
The signature UX. A glass card (`--panel` bg, `--line` border, `border-radius: 22px`,
`backdrop-filter: blur(20px) saturate(1.4)`, `--shadow`).
- **Header bar**: mono uppercase 12px, `--faint`, space-between. Left "Agent activity",
  right a "Simulated run · streaming-ready" tag with an accent pip. *(In production, replace
  the tag with a real live/streaming indicator.)*
- **Feed body**: `padding: 20px 22px 26px`, `max-height: 60vh`, scrolls vertically, auto-scrolls
  to the newest event while running. Custom thin scrollbar (`--line-strong` thumb).
- **Events** — each is a 2-column grid (26px rail + body). The rail draws a **timeline**: an
  11px status dot over a 2px connector line, so events thread together vertically. Event kinds:
  - `planner` — accent dot (pulsing while live), a "PLANNER" role chip (mono 11px, bordered),
    title "Planning your research", sub text.
  - `plan` — renders a nested **plan card** (`--surface-2` bg) listing the numbered sub-questions.
  - `researcher` (start) — accent dot, "RESEARCHER n/total" chip, the sub-question as title.
  - `tool` — mono line. `search` → an accent "search" keyword + the query in quotes.
    `read` → "read" keyword + domain (accent) + page title. `error` → a warning-colored row
    with a warn icon and the failure text (this is how degraded leads surface).
  - `researcher` (done) — `--ok` dot, "Researcher n done" + a summary ("Found 2 relevant sources
    · 1 lead degraded to a gap").
  - `writer` — accent (then `--ok`) dot, "WRITER" chip, "Writing the report" → "Report ready".
  - **Live caret**: the most recent event while running shows a blinking accent caret
    (`.caret`, 8×15px, 1s blink) to convey streaming.
- Events fade/slide in (`slideUp`, transform-only — see Motion).

### Report (`.report`)
- Glass card: `--panel` bg, `--line` border, `border-radius: 22px`, `padding: 40px 44px`,
  `backdrop-filter: blur(20px)`, `--shadow`.
- **Markdown subset** rendered to HTML: `## h2` (Space Grotesk 700, 25px), `### h3` (600, 19px),
  paragraphs (16.5px, `line-height: 1.72`), `- ` bullet lists, `**bold**`, and `> ` blockquotes
  (left accent border, `--accent-soft` bg).
- **Citations**: inline `[n]` tokens render as `.cite` superscripts — mono, 0.72em, `--accent`,
  clickable. On click (or when active) they invert to `--accent` bg / `--accent-ink` text, and
  the Sources panel scrolls + highlights source `n`.
- **Footer actions**: primary "New research" + ghost "Copy report" / "Re-run" buttons.

### Sources panel (`.src-panel`)
- Sticky (`top: 92px`), 340px wide in the report grid (`1fr / 340px`, gap 40px; collapses to a
  single column below 920px).
- Card header: "Sources" (Space Grotesk 600, 15px) + a mono count ("5 cited · 4 consulted" when
  provenance is on).
- **Source items**: 2-column grid (24px number + body). Number in mono accent. Title (13.5px 600)
  over a truncated mono URL (`--faint`, ellipsis). Hover → `--surface-2`; active (matching a
  clicked citation) → `--accent-soft` bg + `--accent` border. Each links out (`target="_blank"`).
- **Provenance toggle**: a footer row with a custom switch (34×20px track, 16px knob). Off → only
  cited sources. On → also lists "consulted" sources (de-emphasized, `·` instead of a number).
  This is the **cited-vs-consulted audit trail**.
- **Gaps card** (below sources, only if gaps exist): warning-tinted card listing unanswered
  questions / failed leads, e.g. "Verified 2026 grid-scale pricing for iron-air batteries — the
  primary vendor source timed out, so cost figures could not be confirmed."

### State cards (empty / failed)
Centered glass card, `max-width: 620px`. Empty: accent search-slash icon, "No sources found",
explanatory copy, "Edit & retry". Failed: red warning icon, "This run failed", the error message,
"Try again". Both return to home/edit.

---

## Interactions & Behavior
- **Submit research**: prompt Enter / submit button / example chip / "See a live run" → enter run
  view, reset feed, begin streaming events, start the elapsed timer.
- **Streaming**: events appear sequentially with per-event delays (prototype) — in production,
  append events as they arrive from the API. Auto-scroll the feed to the newest event.
- **Citation ↔ source linking**: clicking `[n]` sets `activeCite = n`, scrolls the source list so
  item `n` is visible, and highlights it; clicking a source card sets the same active state.
- **Provenance toggle**: reveals/hides consulted sources and updates the count.
- **Theme toggle**: flips `data-theme` on `<html>`, persists to `localStorage["nexus-theme"]`,
  and calls `window.setFluidTheme(theme)` to recolor the WebGL background. **Apply the saved theme
  before first paint** (inline script in `<head>`) to avoid a flash.
- **Back / logo**: cancels any in-flight run (guarded by a run-id ref so a stale simulation can't
  resolve over a new view) and returns home.
- **Responsive**: nav links hide < 920px; report grid and feature rows collapse to single column
  < 920px; tighter padding < 600px.

## Motion
- **Entrance animations are transform-only** (translateY → 0), never opacity-based, and gated
  behind `@media (prefers-reduced-motion: no-preference)`. **This is deliberate** — keep it.
  The visible end-state is the base style so content is always present for print, reduced-motion,
  and any context that pauses CSS animations; motion only adds a slide-up.
  - Hero chars: `charUp` 0.9s, staggered ~28ms each. Badge/sub/prompt/chips: `slideUp` 0.9s with
    staggered delays. Feed events: `slideUp` 0.45s.
- **Theme transitions are instant for text `color`** (do NOT transition `color`) — animating it
  caused frozen-color artifacts. Background/border may transition.
- Pulse animation on live status dots (1.3s). Caret blink (1s steps).
- Easing token: `cubic-bezier(0.2, 0.65, 0.3, 0.9)`.

---

## The Fluid Background (`fluid-background.js`)
A self-contained Three.js module — **port this nearly verbatim**.
- A high-detail `IcosahedronGeometry(1.5, 48)` with a custom `ShaderMaterial`.
- **Vertex shader**: 3D simplex noise displaces vertices along their normals over time; the mouse
  position (smoothed via lerp toward a target) pushes a dent into the surface near the cursor.
- **Fragment shader**: a true rim light (bright at the silhouette, body keeps its color) mixing
  two palette colors across the surface normal's Y.
- **Dark theme**: colors `#8A2BE2` → `#4B0082`, additive blending, transparent, **UnrealBloomPass**
  (strength 0.55, threshold 0.55) for the glow. Clear color `#060409`.
- **Light theme**: colors `#ffae00` → `#ff5e00`, normal blending, opaque, **bloom disabled**
  (a bright background blooms itself), clear color `#faf7f2`.
- `window.setFluidTheme(theme)` swaps palette, blending, clear color, and bloom; the render loop
  runs the bloom composer only in dark mode, else renders direct.
- Pixel ratio capped at 2. Resizes with the window.
- **Gotcha**: the composer renders an opaque clear color — it MUST match the theme background, or
  light mode paints black. Keep the per-theme clear color.

> Port notes: instantiate once on mount, store the renderer/scene in a ref, drive `setFluidTheme`
> from your theme state, and dispose the renderer on unmount. Consider lowering the geometry detail
> or disabling bloom on low-end devices, and pausing the RAF loop when the canvas is offscreen.

---

## Data Contract
Keep the feed/report components stable by preserving these shapes when wiring the real API.

**A research run resolves to:**
```ts
type Result = {
  report: string;          // markdown with [n] citation tokens
  sources: Source[];       // cited — index+1 maps to [n] in the report
  consulted: Source[];     // consulted but not cited (provenance)
  gaps: string[];          // unanswered questions / failed leads
};
type Source = { title: string; url: string };
```

**Streaming events** (each appended to the feed as it arrives):
```ts
type AgentEvent =
  | { kind: "planner"; state: "start"; title: string; sub: string }
  | { kind: "plan"; items: string[] }
  | { kind: "researcher"; state: "start"; index: number; total: number; question: string }
  | { kind: "tool"; action: "search"; text: string }
  | { kind: "tool"; action: "read"; domain: string; title: string }
  | { kind: "tool"; action: "error"; text: string }
  | { kind: "researcher"; state: "done"; index: number; question: string; sub: string; hasGap: boolean }
  | { kind: "writer"; state: "start" | "done"; title: string; sub: string };
```
The prototype polls/scripts these; the design is built for **server-sent events / streaming**
to replace the scripted timing with no UI change.

---

## Design Tokens

### Colors — Dark (default)
| Token | Value |
|---|---|
| `--bg` | `#060409` |
| `--bg-2` | `#0c0812` |
| `--fg` | `#f4f1f8` |
| `--muted` | `rgba(244,241,248,0.62)` |
| `--faint` | `rgba(244,241,248,0.38)` |
| `--line` | `rgba(255,255,255,0.10)` |
| `--line-strong` | `rgba(255,255,255,0.18)` |
| `--surface` | `rgba(255,255,255,0.045)` |
| `--surface-2` | `rgba(255,255,255,0.07)` |
| `--panel` | `rgba(14,10,21,0.74)` |
| `--accent` | `#a855f7` |
| `--accent-2` | `#c084fc` |
| `--accent-ink` | `#ffffff` |
| `--accent-soft` | `rgba(168,85,247,0.16)` |
| `--ok` | `#5eead4` |
| `--warn` | `#fbbf24` |
| `--bad` | `#fb7185` |

### Colors — Light
| Token | Value |
|---|---|
| `--bg` | `#faf7f2` |
| `--bg-2` | `#f3ede4` |
| `--fg` | `#1c1714` |
| `--muted` | `rgba(28,23,20,0.64)` |
| `--faint` | `rgba(28,23,20,0.42)` |
| `--line` | `rgba(28,18,8,0.12)` |
| `--line-strong` | `rgba(28,18,8,0.20)` |
| `--surface` | `rgba(255,255,255,0.66)` |
| `--surface-2` | `rgba(255,255,255,0.86)` |
| `--panel` | `rgba(255,255,255,0.84)` |
| `--accent` | `#ea580c` |
| `--accent-2` | `#f97316` |
| `--accent-ink` | `#ffffff` |
| `--accent-soft` | `rgba(234,88,12,0.12)` |
| `--ok` | `#0d9488` |
| `--warn` | `#b45309` |
| `--bad` | `#dc2626` |

### Typography
- **Display** (headings, brand, buttons-as-headings): **Space Grotesk** — weights 400/500/600/700.
- **Sans** (body, UI): **Instrument Sans** — 400/500/600.
- **Mono** (eyebrows, roles, tool lines, citations, counts): **JetBrains Mono** — 400/500/600.
- Scale highlights: hero `clamp(44px,8.2vw,96px)`/700/`-0.035em`; section h2 `clamp(30px,4.4vw,46px)`/700;
  report body 16.5px/1.72; UI text 14.5–15px; mono labels 11–13px.

### Radius
`--r-sm: 10px` · `--r-md: 16px` · `--r-lg: 22px` · `--r-xl: 28px` · pills `999px` · brand mark `9px`.

### Shadow
- Dark: `0 24px 60px -20px rgba(0,0,0,0.8)`
- Light: `0 24px 60px -24px rgba(80,40,0,0.28)`
- Button (primary): `0 10px 26px -10px var(--accent)`

### Layout
- Content max-width **1120px**, inline padding **28px** (18px below 600px).
- Section vertical rhythm **96px**. Easing `cubic-bezier(0.2,0.65,0.3,0.9)`.

---

## Assets
- **No raster/image assets.** The hero visual is generated live in WebGL (no image files).
- **Icons** are inline SVGs (stroke-based, ~1.7–2 stroke width) defined in `nexus-components.jsx`
  (`I` object). Swap for the codebase's icon library (e.g. Lucide) — names map closely
  (sun, moon, arrow-up, arrow-left, check, search, file-text, layers, shield, alert-triangle, etc.).
- **Fonts** load from Google Fonts (Space Grotesk, Instrument Sans, JetBrains Mono). Self-host or
  use the project's font pipeline in production.
- The brand mark is a typographic `≈` glyph on a gradient tile — no logo file required.

---

## Files in this bundle
| File | What it is |
|---|---|
| `Nexus.html` | Entry point — fonts, importmap (Three.js), React/Babel CDN, mounts the app. |
| `styles.css` | All styling + design tokens (both themes) + animations + responsive rules. |
| `fluid-background.js` | Three.js WebGL fluid background (port this). Shaders + bloom + theme API. |
| `nexus-data.js` | **Simulated** research engine: demo runs, prompt→run matching, event timeline builder. Replace with the real API. |
| `nexus-components.jsx` | Presentational components: Nav, Hero, marketing sections, footer, Markdown renderer, icons. |
| `nexus-app.jsx` | App state machine + Agent Feed + Report + Sources panel + run orchestration. |

To preview the reference: open `Nexus.html` in a browser. Type a prompt about energy storage or
on-device AI (or click an example) for a rich cited report; any other prompt yields a generic run.
Prefix a prompt with `fail` or `empty` to preview those states.

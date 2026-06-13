# Nexus

Nexus is an API-first agentic research platform. You ask a question; a team of
agents plans it into sub-questions, searches the web, reasons over what it finds,
and returns a single structured report where every claim is cited and traceable
to its source.

The agents run as an async pipeline behind a FastAPI backend, with a Vite/React
frontend that streams their progress live and renders the cited report.

## How it works

```
question -> plan -> research (fan-out) -> consolidate -> write -> cited report
```

- **Planner** decomposes the question into a small set of self-contained,
  non-overlapping sub-questions (a forced structured call, not prose parsing).
- **Researchers** run a ReAct tool-use loop (`web_search`, `fetch_page` via
  Tavily) under an iteration cap, fan out concurrently bounded by a semaphore,
  and submit findings with the sources that back them.
- **Consolidator** is deterministic code: it dedupes sources by URL into one
  global numbered list and remaps each finding's citations. No LLM ever assigns
  a citation, which keeps the citation surface free of hallucination.
- **Writer** renders the structured result into prose, preserving the citation
  markers. A post-write pass strips any marker the model invents and prunes the
  source list to what the prose actually cites.

Failure is handled by degradation: a researcher that errors or times out becomes
a reported gap rather than failing the run; only an empty plan or every
researcher failing is a hard failure. Three timeout layers (per researcher,
whole job, max tool iterations) guarantee a query never hangs.

Agent progress is emitted as events and persisted, so the frontend tails a live
"researcher k of N" feed by polling `GET /research/query/{id}/events`.

## Tech stack

- **Backend:** FastAPI, async SQLAlchemy + asyncpg, Alembic, Pydantic, JWT auth
- **Agents:** a hand-rolled orchestrator over a provider seam (one
  OpenAI-compatible adapter for Gemini / Groq / Cerebras / SambaNova) and a
  swappable Tavily search backend, with a token + request-aware rate limiter
- **Frontend:** Vite, React, TypeScript, three.js (WebGL background), framework
  -free i18n (English / French)
- **Evaluation:** a deterministic Tier 1 harness (citation integrity, coverage)
  plus an LLM-as-judge Tier 2 (faithfulness, relevance, coverage quality)

## Local development

### Backend

Requires [uv](https://docs.astral.sh/uv/) and a Postgres database.

```bash
uv sync                      # install dependencies
cp .env.example .env         # then fill in the values (see below)
uv run alembic upgrade head  # create the schema
uv run uvicorn main:app --reload
```

The API serves at `http://localhost:8000` (`/docs` for Swagger). Set at least
`DATABASE_URL`, `SECRET_KEY`, `TAVILY_API_KEY`, and the key for your chosen
`LLM_PROVIDER` (Gemini by default). Every variable is documented in
`.env.example`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env         # VITE_LIVE_MODE=true to call the real backend
npm run dev
```

The frontend runs at `http://localhost:5173`. In simulated mode (the default) it
runs instant demo research with no backend or API cost; set `VITE_LIVE_MODE=true`
and `VITE_API_BASE_URL` to drive the real pipeline.

## Testing

```bash
uv run pytest            # full backend suite (no network: fakes for LLM + search)
uv run ruff check .      # lint
cd frontend && npm run build   # type-check + production build
```

The suite is fully offline: a `FakeLLMProvider` and fake tools script the agents,
so it is deterministic and CI-safe.

### Evaluating report quality

```bash
uv run python -m app.evals.live            # run the curated prompts, score them
uv run python -m app.evals.live --no-judge # Tier 1 only (no LLM-judge cost)
```

This drives the real pipeline over a curated prompt set, scores each report on
citation integrity, coverage, faithfulness, relevance, and coverage quality, and
writes the reports to `evals_runs/` for reading. It spends provider and search
quota.

## Deployment

The live stack is Railway (backend) + Neon (Postgres) + Cloudflare Pages
(frontend).

1. **Database (Neon):** create a Postgres database and copy its connection
   string. Use the `postgresql+asyncpg://...` form and set `DATABASE_SSL=true`.
2. **Backend (Railway):** deploy from the repo root `Dockerfile`. The image runs
   `alembic upgrade head` then serves on `$PORT`. Set the environment variables
   from `.env.example` (`DATABASE_URL`, `DATABASE_SSL=true`, `SECRET_KEY`,
   `CORS_ORIGINS` = your frontend URL, `TAVILY_API_KEY`, `LLM_PROVIDER` and its
   key). `GET /health` is the health check.
3. **Frontend (Cloudflare Pages):** build command `npm run build`, output
   directory `dist`, with `VITE_API_BASE_URL` = the Railway URL and
   `VITE_LIVE_MODE=true`.

Set `CORS_ORIGINS` on the backend to the deployed frontend origin so the browser
can call the API.

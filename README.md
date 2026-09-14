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
  OpenAI-compatible adapter for OpenRouter / Gemini / Groq / Cerebras /
  SambaNova) and a swappable Tavily search backend, with a token +
  request-aware rate limiter
- **Access and cost:** invite-only demo accounts, each with its own dollar
  budget checked against a ledger of what every model call actually cost
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
`LLM_PROVIDER` (OpenRouter by default). Every variable is documented in
`.env.example`.

### Demo accounts

There is no signup page. Each visitor gets an account and an invite link from
the admin command, which talks to whatever `DATABASE_URL` points at:

```bash
uv run python -m app.admin create "Jane Doe (Acme)" --budget 0.5 --days 14
uv run python -m app.admin list                     # spend, budget, expiry
uv run python -m app.admin update 7 --budget 1 --new-link
```

The link opens the app already signed in. Every model call is billed to the
account from the cost the provider reports, and new work is refused once the
budget is spent. Visitors without an invite get the simulated demo.

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

### Evaluating quality

```bash
uv run python -m app.evals run                          # every golden, then score
uv run python -m app.evals run --category owner,current # a slice
uv run python -m app.evals score evals_runs/<run id>    # re-score saved traces
```

`app/evals/goldens.toml` holds about 60 realistic first messages (questions
about the app and its author, time-sensitive questions, facts, comparisons,
false premises, unanswerable and multilingual queries), each with the behavior a
good response shows. `collect` runs them through the real pipeline and records
every stage: the routing decision, the plan, each researcher's searches, pages
and claims, the report and its cost. `score` then measures each stage with
deterministic checks and DeepEval metrics judged by `EVAL_JUDGE_MODEL`: plan
relevance and searchability, researcher success and search yield, retrieval
relevance and faithfulness, report completeness, depth, concision and gap
honesty, and whether the final response does what the golden expects. Results
land in `evals_runs/<run id>/summary.md`.

Collecting spends provider and Tavily credits; scoring spends judge credits.

## Deployment

The live stack is Railway (backend) + Neon (Postgres) + Cloudflare Pages
(frontend).

1. **Database (Neon):** create a Postgres database and copy its connection
   string. Use the `postgresql+asyncpg://...` form and set `DATABASE_SSL=true`.
2. **Backend (Railway):** deploy from the repo root `Dockerfile`. The image runs
   `alembic upgrade head` then serves on `$PORT`. Set the environment variables
   from `.env.example` (`DATABASE_URL`, `DATABASE_SSL=true`, `SECRET_KEY`,
   `CORS_ORIGINS` and `FRONTEND_URL` = your frontend URL, `TAVILY_API_KEY`,
   `OPENROUTER_API_KEY`). Give the OpenRouter key a hard credit limit: it caps
   the total bill. `GET /health` is the health check. Create accounts with
   `railway run uv run python -m app.admin create ...`.
3. **Frontend (Cloudflare Pages):** the frontend lives in a subdirectory, so set
   the project's **root directory** to `frontend`. Build command `npm run build`,
   build output directory `dist` (Vite compiles the static site to
   `frontend/dist`). Set `VITE_API_BASE_URL` = the Railway URL and
   `VITE_LIVE_MODE=true`.

Set `CORS_ORIGINS` on the backend to the deployed frontend origin so the browser
can call the API.

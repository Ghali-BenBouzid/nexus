from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    # database settings
    database_url: str
    database_ssl: bool = False  # True for managed Postgres (Neon); off locally

    # auth settings
    secret_key: str
    algorithm: str
    access_token_expire_minutes: int

    # CORS: comma-separated allowed frontend origins (empty = no browser access)
    cors_origins: str = ""

    # Demo accounts. There is no public signup: an admin creates each account with
    # `python -m app.admin` and hands out its invite link. These are the defaults
    # for a new account; each one can be topped up or extended later.
    frontend_url: str = "http://localhost:5173"  # base of the invite links
    default_budget_usd: float = 0.50
    default_access_days: int = 14  # 0 = never expires

    # Uploaded documents. The text goes in the database; the original file goes
    # in an S3-compatible bucket (Cloudflare R2). Unset means uploads are refused
    # with a clear error, so the app still runs without a bucket.
    r2_endpoint_url: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str | None = None
    max_upload_mb: float = 10.0
    max_documents_per_conversation: int = 10
    # Cap on the text kept from one file (about 50k tokens): enough for a long
    # report, short of a whole book blowing up a context window.
    max_document_chars: int = 200_000
    # Scanned pages are read by OCR at roughly three seconds a page, in the
    # request that uploaded them, so a long scan is refused rather than waited on.
    max_ocr_pages: int = 10

    # agent / provider settings
    gemini_api_key: str | None = None
    tavily_api_key: str | None = None
    # The self-hosted pair that replaces Tavily: a SearXNG instance for the
    # index and a Crawl4AI server for reading a page. Setting searxng_url is
    # what selects them; leaving it unset falls back to Tavily, so a deployment
    # can move over one environment at a time.
    searxng_url: str | None = None
    crawl4ai_url: str | None = None
    crawl4ai_token: str | None = None
    # A metasearch query answers in about a second; reading a page starts a
    # browser, so it gets its own, much longer budget.
    search_timeout: float = 20.0  # seconds
    page_read_timeout: float = 60.0  # seconds

    # LLM provider selection: openrouter | gemini | groq | cerebras | sambanova
    llm_provider: str = "openrouter"
    llm_model: str | None = None  # overrides the provider's default model
    # Names each stretch of the supervisor's thinking for the live feed. Picked
    # as the cheapest fast model on OpenRouter that writes a clean title in both
    # English and French (~1 s, a hundredth of a cent). Empty turns titles off.
    step_title_model: str | None = "mistralai/mistral-nemo"
    openrouter_api_key: str | None = None
    groq_api_key: str | None = None
    cerebras_api_key: str | None = None
    sambanova_api_key: str | None = None
    # Pace all LLM calls under the active provider's free RPM (set below it).
    llm_rate_limit_per_min: int = 25

    # orchestration knobs (12-factor: env-overridable defaults). Kept small so a
    # run stays quick and cheap; a future "deep research" mode raises these.
    # Sub-questions, so researchers, per run. The planner picks how many the
    # question needs and stops there, so this is a ceiling for broad questions,
    # not a target: a narrow one still gets one or two. Raising it widens a
    # report's breadth and costs about that much more per run.
    cap: int = 6  # max sub-questions
    max_iters: int = 3  # max tool rounds per researcher
    # Web searches one researcher may make. The engines behind SearXNG block a
    # burst (CAPTCHA, 429) for minutes, so fewer, better searches go further than
    # many; reading a page does not count, it goes to Crawl4AI.
    searches: int = 3
    # Researchers run in parallel on a paid key. On a free tier, drop this to 1:
    # parallel researchers split a small tokens-per-minute budget and time out.
    # Matches cap, so every researcher of a run starts at once and they share the
    # same research_budget window. OpenRouter's limits (1000 rpm, 10M tpm) are far
    # above this; on a free tier, drop it to 1.
    max_concurrency: int = 6  # simultaneous researchers
    planner_retry_cap: int = 2
    # Soft deadline for the research fan-out: once it passes, each researcher stops
    # searching and submits what it has, so a slow (reasoning) model still yields a
    # report instead of a timeout. per_researcher_timeout stays the hard stop for a
    # researcher stuck inside a single call.
    research_budget: float = 120.0  # seconds
    per_researcher_timeout: float = 150.0  # seconds
    # The writer's own limit: past it, the report is assembled straight from the
    # findings (claims and citations intact) instead of losing them to a timeout.
    writer_timeout: float = 150.0  # seconds
    # Whole-job backstop for bugs, above the budgets that normally bound a run
    # (research ~150 s + writer 150 s, plus planning on the one-shot path).
    global_timeout: float = 420.0  # seconds
    # Supervisor tool-loop budget: how many rounds of "use a tool, look at what
    # came back" it may take before it must answer with what it has. Higher than
    # the old router's, because the supervisor now does the work itself: a
    # search, a read, a research run and an answer is already four.
    supervisor_max_iters: int = 8

    # Deep research: the same run told to go wide, for a question the user asked
    # to have properly covered. It takes minutes, writes its own report, and runs
    # in the background, so its ceilings are set by what is worth paying for
    # rather than by how long someone will sit and watch.
    deep_cap: int = 6  # max sub-questions in one round
    deep_max_iters: int = 6  # max tool rounds per researcher
    deep_searches: int = 5  # web searches per researcher
    deep_concurrency: int = 6  # simultaneous researchers
    deep_research_budget: float = 180.0  # seconds one round's researchers get
    # The lead sends rounds of researchers until it judges the subject covered.
    # These are the ceilings on that judgement, not a target: a confused lead
    # must not research all day, and every researcher is model calls paid for.
    # Sized for depth on a few angles, not breadth: at 5 rounds and 40
    # researchers a run spent 32 minutes writing a 22,000-word textbook.
    deep_max_rounds: int = 3
    deep_max_researchers: int = 15
    deep_research_window: float = 720.0  # seconds of research across rounds
    # Well past the budget: a researcher out of time is asked to submit what it
    # read, and on a reasoning model that call alone can take two minutes. Cut
    # off inside it, every page the researcher read is lost.
    deep_researcher_timeout: float = 330.0  # hard stop for one researcher
    # The writer's limit on a deep run. Its own setting because a deep run hands
    # the writer several times the material a normal one does: twelve
    # sub-questions of findings instead of six, each researched six rounds deep.
    # At the normal 150 s it timed out every time, and a timed-out writer does
    # not produce a shorter report, it produces no report at all: the findings
    # are dumped raw, uncurated, citing every source anyone touched.
    deep_writer_timeout: float = 480.0  # seconds
    # How many findings a deep report is built from. Researchers work in
    # parallel and never see each other's claims, so what comes back overlaps
    # and every claim drags its sources into the citation list: one run came
    # back with 134 claims behind 215 sources. The curator cuts to this before
    # the writer sees anything.
    #
    # Now a guard against runaway runs, not a step every run pays for: with
    # researchers capped at ten claims, a normal run hands in 40 to 80, the
    # writer chooses by the lead's outline, and a curator reading 79 claims
    # still timed out after two and a half minutes of the user's wait.
    deep_claim_cap: int = 80
    # The curator's own limit. Reading 134 claims took five minutes on a real
    # run (researchers now submit at most ten claims each), and past this the
    # report is built from an even share of every sub-question's claims rather
    # than losing the writer's budget to the step before it.
    deep_curate_timeout: float = 150.0  # seconds
    # Whole-run backstop, above what the stages can spend between them: the
    # research window (720 s, plus the last round's hard stop of 330 s), then
    # the curator (150 s), then the writer (480 s). At 1500 s a one-round run
    # that used all three was killed just before it wrote anything.
    deep_timeout: float = 2_100.0  # whole-run backstop
    # The fact checker's own loop: read, search, read, write. Wider than a
    # researcher's because it checks several claims inside one loop.
    # Every web search this process sends, whichever agent sends it, paced so
    # a round of researchers does not arrive at the engines as one burst.
    search_rate_per_min: int = 40
    factcheck_max_iters: int = 14  # steps before the claim list is confirmed
    factcheck_most_iters: int = 40  # the most it can grow to, with many claims
    factcheck_timeout: float = 900.0  # seconds, room for most_iters steps

    # Where jobs run (routing a message, planning, research, composing). "redis":
    # the API only enqueues them and the worker process runs them
    # (`arq app.worker.WorkerSettings`), so no model call lives inside an HTTP
    # request and redeploying the API never kills a run. "inline": they run in the
    # API process after the response, for the tests or a one-process setup.
    job_queue: Literal["redis", "inline"] = "redis"
    redis_url: str = "redis://localhost:6379"
    worker_max_jobs: int = 10  # jobs one worker runs at once

    # transient-error retry/backoff for provider & search calls. Also re-rolls a
    # stochastic 400 tool_use_failed (a malformed tool call usually parses on a
    # fresh generation) — rare on the default model, common on llama-family ones.
    retry_max_attempts: int = 3
    retry_base_delay: float = 0.5  # seconds before the first retry
    retry_max_delay: float = 8.0  # backoff ceiling

    # observability (LangSmith). Off by default: the @traceable decorators stay in
    # the hot path year-round but are inert no-ops until tracing is switched on with
    # a key. configure_tracing() bridges these into the LANGSMITH_* env the SDK reads.
    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "nexus"
    langsmith_endpoint: str | None = None  # set for self-hosted / EU LangSmith

    # Evals (python -m app.evals): the judge that scores recorded runs, any
    # OpenRouter model id, billed to OPENROUTER_API_KEY. Deliberately a different
    # model family from the one under test, to limit self-preference bias. No
    # default: judging refuses to start without it, so the judge behind a score is
    # always one someone chose. Optional here because only the evals need it.
    eval_judge_model: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def db_connect_args(self) -> dict[str, object]:
        # asyncpg (unlike psycopg2) won't read sslmode from the URL; pass ssl here.
        return {"ssl": True} if self.database_ssl else {}


settings = Settings()

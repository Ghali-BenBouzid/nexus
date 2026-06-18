"""Run the curated eval prompts as a LangSmith experiment.

Each prompt runs through the real pipeline (the *target*), the run is traced, and
the existing evaluation (Tier 1 deterministic checks + the Tier 2 LLM-as-judge
dimensions, via ``evaluate_full``) scores it. The scores attach to the run as
feedback, so LangSmith stores a versioned experiment you can compare across prompt
or model changes, with the full trace behind every number.

This reuses the same orchestrator and judge as the rest of the app, so the only
new thing here is the LangSmith dataset + experiment wiring.

Run with::

    uv run python -m app.evals.langsmith_eval

Requires LangSmith configured (``langsmith_tracing=true`` + a key in ``.env``) and
costs real provider + Tavily quota, like the live runner.
"""

import asyncio
import logging
from typing import Any

from langsmith import Client, aevaluate

from app.agents import orchestrator
from app.agents.search_cache import CachingSearchBackend
from app.agents.tools import FetchPage, WebSearch
from app.core.config import settings
from app.evals.cases import EVAL_PROMPTS
from app.evals.judge import evaluate_full
from app.observability import configure_tracing
from app.research.dependencies import get_provider, get_search_backend

logger = logging.getLogger(__name__)

DATASET_NAME = "nexus-research-evals"


def ensure_dataset(client: Client) -> None:
    """Create the dataset of curated prompts once (idempotent by name). Each
    example's input is just ``{"prompt": ...}``; there are no reference outputs
    because the judges score quality, not an exact match."""
    if client.has_dataset(dataset_name=DATASET_NAME):
        return
    dataset = client.create_dataset(
        DATASET_NAME, description="Curated prompts for evaluating the Nexus pipeline."
    )
    client.create_examples(
        dataset_id=dataset.id,
        examples=[{"inputs": {"prompt": prompt}} for prompt in EVAL_PROMPTS],
    )
    logger.info("created dataset %r with %d examples", DATASET_NAME, len(EVAL_PROMPTS))


async def target(inputs: dict[str, Any]) -> dict[str, Any]:
    """One experiment row: run the prompt through the orchestrator (traced) under
    the global timeout, then score it with the full Tier 1 + Tier 2 evaluation.
    Returns the report plus the structured evaluation for the evaluators to surface."""
    prompt = inputs["prompt"]
    provider = get_provider()
    backend = CachingSearchBackend(get_search_backend())
    async with provider, backend:
        tools = [WebSearch(backend=backend), FetchPage(backend=backend)]
        report, result = await asyncio.wait_for(
            orchestrator.run(
                prompt,
                provider=provider,
                tools=tools,
                cap=settings.cap,
                max_iters=settings.max_iters,
                max_concurrency=settings.max_concurrency,
                per_researcher_timeout=settings.per_researcher_timeout,
                retry_cap=settings.planner_retry_cap,
            ),
            timeout=settings.global_timeout,
        )
        # The judges call the provider, so score while it is still open.
        evaluation = await evaluate_full(prompt, report, result, provider=provider)
    return {
        "report": report.content,
        "n_sources": len(report.sources),
        "evaluation": evaluation.model_dump(),
    }


def quality_checks(outputs: dict[str, Any]) -> dict[str, Any]:
    """Surface every check from the target's evaluation as its own feedback key, so
    each Tier 1 and Tier 2 dimension shows up as a separate score in the
    experiment. One evaluator returning many results keeps the judging in the
    target (where the provider is open) and avoids re-running it here."""
    checks = outputs.get("evaluation", {}).get("checks", [])
    return {
        "results": [
            {"key": c["name"], "score": c["score"], "comment": c.get("detail")}
            for c in checks
        ]
    }


async def amain() -> None:
    configure_tracing()
    if not settings.langsmith_tracing or not settings.langsmith_api_key:
        print(
            "LangSmith is not configured. Set langsmith_tracing=true and "
            "langsmith_api_key in .env, then re-run."
        )
        return
    client = Client()
    ensure_dataset(client)
    # Concurrency is 1 because the provider's free-tier TPM is the bottleneck, the
    # same reason max_concurrency defaults to 1 for a live run.
    results = await aevaluate(
        target,
        data=DATASET_NAME,
        evaluators=[quality_checks],
        experiment_prefix="nexus",
        max_concurrency=1,
        client=client,
    )
    print(f"Experiment complete. View it in LangSmith: {DATASET_NAME}")
    print(results)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(amain())


if __name__ == "__main__":
    main()

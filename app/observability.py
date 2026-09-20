"""LangSmith tracing wiring for the agent pipeline.

One import seam so call sites never touch the SDK directly and the backend could
be swapped without editing them. Everything here is inert unless tracing is turned
on (``langsmith_tracing`` + an API key): ``@traceable`` runs the wrapped function
directly with no run created, so the decorators can live in the hot path
year-round at near-zero cost. ``configure_tracing()`` is what flips them on.

``traced_step`` decorates the pipeline steps (plan, research, write) as nested
"chain" runs. The model calls inside them trace themselves: LangChain instruments
its own chat models, which is one of the things adopting it bought.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from langsmith import get_current_run_tree, traceable

from app.core.config import settings

# Which part of a run is calling the model right now. A context variable rather
# than an argument because everything that wants to know (the usage tally, the
# search recorder in the evals) sits under the call, not next to it, and because
# a researcher running in its own task inherits a copy rather than racing with
# its siblings over one shared field.
STAGE: ContextVar[str] = ContextVar("nexus_stage", default="supervisor")


@contextmanager
def stage(name: str) -> Iterator[None]:
    token = STAGE.set(name)
    try:
        yield
    finally:
        STAGE.reset(token)


# Plumbing args that carry no data worth recording on a step's trace inputs.
_INFRA_KEYS = frozenset({"provider", "emit", "tools", "should_cancel", "backend"})


def _step_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in inputs.items() if k not in _INFRA_KEYS}


def traced_step(name: str) -> Any:
    """Chain-span decorator for an orchestration step (plan, research, write, ...).
    Keeps the data arguments (prompt, sub-questions, knobs) and drops the provider,
    emit sink, and tools so the trace inputs read cleanly."""
    return traceable(name=name, process_inputs=_step_inputs)


def configure_tracing() -> None:
    """Bridge our Settings into the ``LANGSMITH_*`` env vars the SDK reads, so the
    same ``.env`` that configures the app configures tracing. Called once at app
    startup and at the top of the eval scripts. A no-op when tracing is off or no
    key is set, so it is always safe to call."""
    if not settings.langsmith_tracing or not settings.langsmith_api_key:
        return
    import os

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    if settings.langsmith_endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint


def _dump(obj: Any) -> Any:
    """Best-effort serialize a pydantic model for a trace payload."""
    dump = getattr(obj, "model_dump", None)
    return dump(exclude_none=True) if callable(dump) else obj


def record_metadata(**fields: Any) -> None:
    """Attach arbitrary key/values to the current run (e.g. query_id on the root).
    A no-op when tracing is off."""
    run = get_current_run_tree()
    if run is not None:
        run.add_metadata(fields)


def _drop_self(inputs: dict[str, Any]) -> dict[str, Any]:
    """Strip the bound ``self`` from a traced method's inputs so the run records
    only the real arguments."""
    return {k: v for k, v in inputs.items() if k != "self"}


def traced_tool() -> Any:
    """Decorator for ``BaseTool.execute``: records the call as a tool run with its
    arguments (query, url, ...). Pair with ``record_run_name`` inside ``execute``
    so each run is labeled with the concrete tool name instead of "execute"."""
    return traceable(run_type="tool", process_inputs=_drop_self)


def record_run_name(name: str) -> None:
    """Rename the current run (used to label a tool run with its tool name).
    A no-op when tracing is off."""
    run = get_current_run_tree()
    if run is not None:
        run.name = name

"""LangSmith tracing wiring for the agent pipeline.

One import seam so call sites never touch the SDK directly and the backend could
be swapped without editing them. Everything here is inert unless tracing is turned
on (``langsmith_tracing`` + an API key): ``@traceable`` runs the wrapped function
directly with no run created, so the decorators can live in the hot path
year-round at near-zero cost. ``configure_tracing()`` is what flips them on.

Two kinds of span:
- ``traced`` decorates the pipeline steps (plan, research, consolidate, write) as
  nested "chain" runs. The decorated functions take pydantic args, which serialize
  cleanly, so the tree reads well with no extra work.
- ``traced_llm`` decorates each provider's ``generate`` as an "llm" run, recording
  the messages in, the response out, and token usage (so LangSmith can show cost).
"""

from typing import Any

from langsmith import get_current_run_tree, traceable

from app.core.config import settings

# Plumbing args that carry no data worth recording on a step's trace inputs.
_INFRA_KEYS = frozenset(
    {"provider", "emit", "tools", "should_cancel", "backend", "make_coro"}
)


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


def _llm_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Shape a ``generate(self, messages, tools, tool_choice)`` call into a clean
    trace input: drop ``self``, dump the messages, reduce tools to their names."""
    messages = inputs.get("messages") or []
    tools = inputs.get("tools") or []
    return {
        "messages": [_dump(m) for m in messages],
        "tools": [getattr(t, "name", str(t)) for t in tools],
        "tool_choice": inputs.get("tool_choice", "auto"),
    }


def _llm_outputs(response: Any) -> dict[str, Any]:
    """Shape an ``LLMResponse`` into a trace output. ``usage_metadata`` is the key
    LangSmith reads on an llm run to populate token counts and compute cost."""
    calls = getattr(response, "tool_calls", None) or []
    out: dict[str, Any] = {
        "text": getattr(response, "text", None),
        "tool_calls": [_dump(tc) for tc in calls],
    }
    usage = getattr(response, "usage", None)
    if usage is not None:
        out["usage_metadata"] = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        }
    return out


def traced_llm(name: str) -> Any:
    """Decorator for a provider's ``generate``: records it as an llm run with the
    messages, the response, and token usage. Pair with ``record_model`` inside the
    method so the run also carries the provider + model (needed for cost)."""
    return traceable(
        run_type="llm",
        name=name,
        process_inputs=_llm_inputs,
        process_outputs=_llm_outputs,
    )


def record_model(provider: str, model: str) -> None:
    """Tag the current llm run with its provider + model so LangSmith can price it.
    Safe to call when tracing is off (there is no active run, so it does nothing)."""
    run = get_current_run_tree()
    if run is not None:
        run.add_metadata({"ls_provider": provider, "ls_model_name": model})


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

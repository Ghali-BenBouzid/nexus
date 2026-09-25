"""What agents retrieve with, and how retrieved text is handed to them.

Two rules hold for every tool here, whichever agent calls it:

- Retrieved text arrives inside a named tag, so an agent can tell a page's words
  from its own instructions, and a page cannot close the tag to write outside it.
- Sources are registered into the turn's ``Sources`` registry by code, and the
  tool hands back the numbers it issued. A claim can only cite a number that a
  real retrieval produced.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.agents.schemas import AgentEvent, Source
from app.agents.sources import Sources

logger = logging.getLogger(__name__)

Emit = Callable[[AgentEvent], Awaitable[None]]
_Retrieving = Callable[[], Awaitable["RetrievalResult"]]

MAX_PAGE_CHARS = 6_000  # cap fetched page text so it can't blow the token budget


def tagged(tag: str, body: str, **attributes: str) -> str:
    """Retrieved text inside a named tag, so an agent can tell it from its own
    instructions. A page that says "ignore your instructions" then reads as page
    content; the prompts say everything inside such a tag is data. The body's own
    closing tag is defanged so a page cannot end the block early and continue
    outside it."""
    # An attribute's value is itself untrusted (a search query, a URL, a user's
    # earlier prompt), so it cannot be allowed to carry quotes or angle brackets.
    head = tag + "".join(f' {k}="{_attribute(v)}"' for k, v in attributes.items() if v)
    body = body.replace(f"</{tag}>", f"<\\/{tag}>")
    return f"<{head}>\n{body}\n</{tag}>"


def _attribute(value: str) -> str:
    clean = "".join(c for c in value if c not in '"<>').strip()
    return clean[:200]


class RetrievalResult(BaseModel):
    content: str
    sources: list[Source] = []


class SearchHit(BaseModel):
    title: str
    url: str
    content: str  # snippet returned by the search backend


class SearchBackend(Protocol):
    """A swappable web-retrieval backend (Tavily, Brave, ...). Isolates the
    concrete search provider from the tools that depend on it. It is an async
    context manager so the job can scope the client's lifetime with
    ``async with backend:``."""

    async def __aenter__(self) -> "SearchBackend": ...

    async def __aexit__(self, exc_type, exc, tb) -> None: ...

    async def search(self, query: str, max_results: int) -> list[SearchHit]: ...

    async def extract(self, url: str) -> str: ...


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """The same JSON schema with every ``$ref`` replaced by the definition it
    points to, and ``$defs`` dropped.

    Pydantic moves nested models into ``$defs`` and points at them with ``$ref``.
    Some providers (Gemini behind OpenRouter) never follow the reference and guess
    the shape instead: submit_finding's claims came back as plain strings, so every
    researcher's finding was rejected. Spelling the shape out works everywhere.
    Assumes no self-referencing model (none exists); one would recurse endlessly.
    """
    definitions = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(definitions[node["$ref"].rsplit("/", 1)[-1]])
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


# --- the argument schemas models fill ---------------------------------------


class SubmitPlanArgs(BaseModel):
    sub_questions: list[str] = Field(description="The list of sub-questions")


class DispatchResearchersArgs(BaseModel):
    reasoning: str = Field(
        description="what the findings so far show, what is still missing or "
        "unclear, and why these sub-questions are the next step"
    )
    sub_questions: list[str] = Field(
        description="self-contained sub-questions, one researcher each"
    )


class WriteReportArgs(BaseModel):
    reasoning: str = Field(description="why the question is now answered")
    outline: str = Field(
        description="how the report should be organised, from what the findings "
        "support, and what stays open; its length is set separately"
    )


class SubmitSelectionArgs(BaseModel):
    keep: list[int] = Field(
        default_factory=list,
        description="the numbers of the claims worth reporting, best first",
    )


class SubmitFindingClaim(BaseModel):
    text: str = Field(description="A single, self-contained factual statement")
    cited_source_ids: list[int] = Field(
        default_factory=list,
        description="numbers of the sources that back THIS statement (empty if none)",
    )


# Per finding. Researchers told "at most 10" in the prompt still sent 30 to 50,
# and a deep run's curator then timed out reading them all.
MAX_CLAIMS = 10


class SubmitFindingArgs(BaseModel):
    # Required, not defaulted to empty: a default makes it optional in the
    # schema the model sees, and after a long read a model will leave it out
    # and send only found_info=true, throwing away every page it read.
    claims: list[SubmitFindingClaim] = Field(
        description="the answer broken into individual claims, each with the "
        "source numbers that support it; empty if no relevant info was found",
        # Advertised, not validated: rejecting an eleventh claim would pay for
        # a whole new submission, so the researcher keeps the first ten.
        json_schema_extra={"maxItems": MAX_CLAIMS},
    )
    found_info: bool = Field(description="False if no relevant info was found")


class DocumentClaim(BaseModel):
    claim: str = Field(description="the claim as the document makes it, in a sentence")
    passage: str = Field(
        description="a few words quoted from the passage the claim comes from"
    )


class LeftOut(BaseModel):
    passage: str = Field(description="a few words quoted from the passage")
    why: str = Field(description="why it holds nothing to check")


class SubmitClaimsArgs(BaseModel):
    claims: list[DocumentClaim] = Field(
        description="every distinct claim the document makes that can be checked"
    )
    left_out: list[LeftOut] = Field(
        description="the passages no claim covers, each with why; empty if none"
    )
    confirmed: bool = Field(
        description="true only once you have reviewed this exact list against "
        "the review you were given and it is final"
    )


class WebSearchArgs(BaseModel):
    query: str = Field(description="The search query to run against the web")
    max_results: int = Field(default=5, description="How many results to return")


class FetchPageArgs(BaseModel):
    url: str = Field(description="The URL of the page to fetch and read in full")


# --- retrieval ---------------------------------------------------------------


async def web_search_results(
    backend: SearchBackend, query: str, max_results: int = 5
) -> RetrievalResult:
    """One web search, tagged as retrieved material."""
    hits = await backend.search(query, max_results)
    sources = [Source(title=hit.title, url=hit.url) for hit in hits]
    body = (
        "\n\n".join(f"{hit.title}\n{hit.url}\n{hit.content}" for hit in hits)
        or "No results found."
    )
    return RetrievalResult(
        content=tagged("search_results", body, query=query), sources=sources
    )


async def fetch_page_text(backend: SearchBackend, url: str) -> RetrievalResult:
    """One page, cleaned and capped so it cannot blow the context window."""
    text = await backend.extract(url)
    if len(text) > MAX_PAGE_CHARS:
        text = text[:MAX_PAGE_CHARS] + "\n\n[...truncated]"
    return RetrievalResult(
        content=tagged("page", text, url=url),
        sources=[Source(title=url, url=url)],
    )


async def _noop(event: AgentEvent) -> None:
    return None


def retrieval_tools(
    backend: SearchBackend,
    sources: Sources,
    *,
    emit: Emit = _noop,
    agent: str = "agent",
    searches: int | None = None,
    reads: list[int] | None = None,
) -> list[StructuredTool]:
    """The two tools every web-facing agent gets: search, and read a page in
    full. Both register what they retrieved into ``sources`` and append the
    numbers the agent may cite. A failure is told to the agent and to the live
    feed, never raised: one dead search should cost a search, not the turn.

    ``searches`` caps how many web searches the agent may make; past it, a
    search is refused without reaching the engines. None is no cap. ``reads``,
    when given, counts the pages the agent asked to read, in its first item."""
    used = [0]

    async def retrieve(what: str, retrieving: _Retrieving) -> str:
        try:
            result = await retrieving()
        except Exception as exc:  # noqa: BLE001 -- a failed tool is not a failed run
            # The agent and the feed are told only that the tool failed, on
            # purpose: the chained cause can carry a key or an internal
            # address. But it is also the only thing that says *why* (a 403
            # from a search instance with JSON off, a 401 from a missing
            # token, a timeout against a private address), so it goes to the
            # log. Without this a deployment cannot be diagnosed at all.
            logger.warning("%s failed for %s", what, agent, exc_info=exc)
            await emit(
                AgentEvent(
                    type="tool_error",
                    message=f"{what} failed: {exc}",
                    data={"agent": agent, "tool": what},
                )
            )
            return f"{what} failed: {exc}. Try a different approach."
        return with_numbers(result, sources)

    async def web_search(query: str, max_results: int = 5) -> str:
        if searches is not None and used[0] >= searches:
            return (
                f"No searches left: all {searches} are used. Read the most "
                "promising pages you already found with fetch_page, or submit."
            )
        used[0] += 1
        return await retrieve(
            "web_search", lambda: web_search_results(backend, query, max_results)
        )

    async def fetch_page(url: str) -> str:
        if reads is not None:
            reads[0] += 1
        return await retrieve("fetch_page", lambda: fetch_page_text(backend, url))

    return [
        StructuredTool.from_function(
            coroutine=web_search,
            name="web_search",
            description=(
                "Run a web search for a query and return up to max_results results."
            ),
            args_schema=WebSearchArgs,
        ),
        StructuredTool.from_function(
            coroutine=fetch_page,
            name="fetch_page",
            description=(
                "Fetch a web page by URL and return its cleaned full text, for when "
                "a search snippet is promising but insufficient."
            ),
            args_schema=FetchPageArgs,
        ),
    ]


def with_numbers(result: RetrievalResult, sources: Sources) -> str:
    """Register a retrieval's sources and append the legend the agent cites from."""
    if not result.sources:
        return result.content
    numbers = sources.register(result.sources)
    legend = sources.legend(numbers)
    return f"{result.content}\n\nCite these sources by number:\n{legend}"

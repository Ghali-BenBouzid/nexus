from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.agents.schemas import Source


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


class ToolResult(BaseModel):
    content: str


class RetrievalResult(ToolResult):
    sources: list[Source] = []


class SearchHit(BaseModel):
    title: str
    url: str
    content: str  # snippet returned by the search backend


class SearchBackend(Protocol):
    """A swappable web-retrieval backend (Tavily, Brave, ...). Isolates the
    concrete search provider from the tools that depend on it. It is an async
    context manager so the job can scope the client's lifetime with
    ``async with backend:`` (mirrors LLMProvider)."""

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


class SubmitPlanArgs(BaseModel):
    sub_questions: list[str] = Field(description="The list of sub-questions")


class SubmitFindingClaim(BaseModel):
    text: str = Field(description="A single, self-contained factual statement")
    cited_source_ids: list[int] = Field(
        default_factory=list,
        description="ids of the sources that back THIS statement (empty if none)",
    )


class SubmitFindingArgs(BaseModel):
    claims: list[SubmitFindingClaim] = Field(
        default_factory=list,
        description="the answer broken into individual claims, each with the "
        "source ids that support it; empty if no relevant info was found",
    )
    found_info: bool = Field(description="False if no relevant info was found")


class WebSearchArgs(BaseModel):
    query: str = Field(description="The search query to run against the web")
    max_results: int = Field(default=5, description="How many results to return")


async def web_search_results(
    backend: SearchBackend, query: str, max_results: int = 5
) -> RetrievalResult:
    """One web search, tagged as retrieved material. Shared by every agent that
    searches, so results look the same wherever they are read."""
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


class FetchPageArgs(BaseModel):
    url: str = Field(description="The URL of the page to fetch and read in full")


MAX_PAGE_CHARS = 6_000  # cap fetched page text so it can't blow the token budget

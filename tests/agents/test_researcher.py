"""One researcher, end to end, with a scripted model.

What these pin: a claim can only cite a source that was really retrieved, work is
never lost when the rounds or the clock run out, and finding nothing is a real
answer rather than a failure. Source numbers are 1-based, because that is what
the tools hand the model and what a citation marker means everywhere else.
"""

import time

from app.agents.researcher import research_one
from app.agents.schemas import AgentEvent
from app.agents.tools import SearchHit
from tests.agents.fakes import ScriptedModel, call

SUBMIT = "SubmitFindingArgs"  # the submit schema's name, as the model sees it


class FakeSearchBackend:
    def __init__(self, hits: list[SearchHit] | None = None, slow: float = 0.0) -> None:
        self.hits = hits or [
            SearchHit(title="A", url="http://a", content="alpha"),
            SearchHit(title="B", url="http://b", content="beta"),
        ]
        self.slow = slow
        self.searches: list[str] = []

    async def __aenter__(self) -> "FakeSearchBackend":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        self.searches.append(query)
        if self.slow:
            import asyncio

            await asyncio.sleep(self.slow)
        return self.hits[:max_results]

    async def extract(self, url: str) -> str:
        return "the whole page"


def cited(finding) -> list[str]:
    """The urls the finding's claims actually cite, in order."""
    seen: list[str] = []
    for claim in finding.claims:
        for number in claim.source_ids:
            url = finding.sources[number - 1].url
            if url not in seen:
                seen.append(url)
    return seen


def _submit(**args) -> object:
    return call(SUBMIT, **args)


def _search(query: str = "q") -> object:
    return call("web_search", query=query, max_results=5)


async def test_a_researcher_searches_then_submits_with_its_sources() -> None:
    model = ScriptedModel(
        [
            _search(),
            _submit(
                claims=[{"text": "the answer", "cited_source_ids": [1]}],
                found_info=True,
            ),
        ]
    )
    backend = FakeSearchBackend()

    finding = await research_one("sub q", model=model, backend=backend, max_iters=5)

    assert finding.answer == "the answer"
    assert finding.found_info
    assert backend.searches == ["q"]
    # everything retrieved is kept; only what a claim cited is cited
    assert [s.url for s in finding.sources] == ["http://a", "http://b"]
    assert cited(finding) == ["http://a"]


async def test_each_claim_carries_the_sources_it_cited() -> None:
    model = ScriptedModel(
        [
            _search(),
            _submit(
                claims=[
                    {"text": "from A", "cited_source_ids": [1]},
                    {"text": "from B", "cited_source_ids": [2]},
                ],
                found_info=True,
            ),
        ]
    )

    finding = await research_one(
        "sub q", model=model, backend=FakeSearchBackend(), max_iters=5
    )

    urls = [[finding.sources[n - 1].url for n in c.source_ids] for c in finding.claims]

    assert urls == [["http://a"], ["http://b"]]


async def test_a_cited_id_that_was_never_retrieved_is_dropped() -> None:
    # The guarantee: a number the tools never handed out cannot reach a report.
    model = ScriptedModel(
        [
            _search(),
            _submit(
                claims=[{"text": "invented", "cited_source_ids": [7]}],
                found_info=True,
            ),
        ]
    )

    finding = await research_one(
        "sub q", model=model, backend=FakeSearchBackend(), max_iters=5
    )

    assert finding.claims[0].source_ids == []


async def test_a_malformed_submission_is_fed_back_and_recovered() -> None:
    # The first submission omits found_info; the researcher has already paid for
    # its searching, so it is told what was wrong instead of losing the work.
    model = ScriptedModel(
        [
            _submit(claims=[]),  # missing found_info
            _submit(claims=[{"text": "ok", "cited_source_ids": []}], found_info=True),
        ]
    )

    finding = await research_one(
        "sub q", model=model, backend=FakeSearchBackend(), max_iters=5
    )

    assert finding.answer == "ok"


async def test_finding_nothing_is_an_answer_not_a_failure() -> None:
    model = ScriptedModel(
        [
            _submit(
                claims=[{"text": "nothing found", "cited_source_ids": []}],
                found_info=False,
            )
        ]
    )

    finding = await research_one(
        "sub q", model=model, backend=FakeSearchBackend(), max_iters=5
    )

    assert finding.found_info is False
    assert cited(finding) == []


async def test_running_out_of_rounds_still_submits_what_was_read() -> None:
    events: list[AgentEvent] = []

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    # It keeps searching and never submits, so the cap ends the loop and the
    # researcher is asked once more, with the schema forced.
    model = ScriptedModel(
        respond=lambda messages, tools: (
            _submit(
                claims=[{"text": "forced", "cited_source_ids": [1]}], found_info=True
            )
            if tools == [SUBMIT]
            else _search()
        )
    )

    finding = await research_one(
        "sub q", model=model, backend=FakeSearchBackend(), emit=collect, max_iters=2
    )

    assert finding.answer == "forced"
    assert cited(finding) == ["http://a"]
    assert [e.type for e in events] == ["researcher_forced"]


async def test_a_forced_finish_that_forgets_its_claims_is_asked_again() -> None:
    """After a long read the model sent {"found_info": true} and nothing else,
    three times in three, and every page it read was lost. It is told so and
    asked again."""
    forced: list[int] = []

    def respond(messages, tools):
        if tools != [SUBMIT]:
            return _search()
        forced.append(1)
        if len(forced) == 1:
            return _submit(found_info=True)
        return _submit(
            claims=[{"text": "read", "cited_source_ids": [1]}], found_info=True
        )

    finding = await research_one(
        "sub q",
        model=ScriptedModel(respond=respond),
        backend=FakeSearchBackend(),
        max_iters=2,
    )

    assert len(forced) == 2
    assert finding.answer == "read"
    assert cited(finding) == ["http://a"]


async def test_a_finding_keeps_at_most_ten_claims() -> None:
    """Told "at most 10", researchers sent up to 49. The first ten are kept
    rather than paying for another submission."""
    many = [{"text": f"c{n}", "cited_source_ids": [1]} for n in range(14)]
    model = ScriptedModel([_search(), _submit(claims=many, found_info=True)])

    finding = await research_one("sub q", model=model, backend=FakeSearchBackend())

    assert [c.text for c in finding.claims] == [f"c{n}" for n in range(10)]


async def test_a_researcher_is_told_when_its_next_step_is_its_last() -> None:
    """Cut off without warning, a researcher was mid-search when its rounds ran
    out. On its last call it is told so, and submits on its own."""
    model = ScriptedModel(
        respond=lambda messages, tools: (
            _submit(claims=[{"text": "done", "cited_source_ids": [1]}], found_info=True)
            if "This is your last step" in str(messages[-1].content)
            else _search()
        )
    )
    events: list[AgentEvent] = []

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    finding = await research_one(
        "sub q", model=model, backend=FakeSearchBackend(), emit=collect, max_iters=3
    )

    assert finding.answer == "done"
    assert events == []  # it finished itself: no forced submission was needed


async def test_out_of_time_is_reported_as_the_reason() -> None:
    events: list[AgentEvent] = []

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    model = ScriptedModel(
        respond=lambda messages, tools: (
            _submit(claims=[], found_info=False) if tools == [SUBMIT] else _search()
        )
    )

    await research_one(
        "sub q",
        model=model,
        backend=FakeSearchBackend(),
        emit=collect,
        max_iters=1,
        deadline=time.monotonic() - 1,  # already past
    )

    assert [e.message for e in events] == ["Time budget reached"]


async def test_a_researcher_that_never_submits_returns_an_empty_finding() -> None:
    # Nothing usable came back even when forced: a gap, not a crash.
    model = ScriptedModel(respond=lambda messages, tools: _search())

    finding = await research_one(
        "sub q", model=model, backend=FakeSearchBackend(), max_iters=1
    )

    assert finding.found_info is False
    assert finding.claims == []
    assert [s.url for s in finding.sources] == ["http://a", "http://b"]

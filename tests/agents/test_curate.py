"""The curator: what survives into a report, and how it is numbered.

The model's judgement is not what these pin. What they pin is that choosing
cannot invent, cannot mislead, and cannot leave a report citing a number that
points at nothing.
"""

import asyncio
from types import SimpleNamespace

from app.agents.curate import curate
from app.agents.schemas import Claim, ResearchPoint, ResearchResult, Source
from tests.agents.fakes import ScriptedModel, call


def _source(n: int) -> Source:
    return Source(title=f"S{n}", url=f"https://example.com/{n}")


def _result(
    *points: tuple[str, list[tuple[str, list[int]]]], sources: int | None = None
) -> ResearchResult:
    """A result from (sub_question, [(claim text, source ids)]) pairs. ``sources``
    sets how many sources exist, so a test can cite one that does not."""
    highest = sources or max(
        (sid for _, claims in points for _, ids in claims for sid in ids), default=0
    )
    return ResearchResult(
        points=[
            ResearchPoint(
                sub_question=question,
                claims=[Claim(text=text, source_ids=ids) for text, ids in claims],
            )
            for question, claims in points
        ],
        sources=[_source(n) for n in range(1, highest + 1)],
        gaps=[],
    )


def _keeps(*numbers: int) -> ScriptedModel:
    return ScriptedModel([call("SubmitSelectionArgs", keep=list(numbers))])


async def test_a_small_result_is_not_worth_a_call() -> None:
    """Under the cap there is nothing to choose, so nothing is spent choosing."""
    result = _result(("q", [("one", [1]), ("two", [2])]))
    model = _keeps(1)

    curated = await curate(result, model=model, cap=10)

    assert curated is result
    assert model.seen == []


async def test_it_keeps_what_was_chosen_and_drops_the_rest() -> None:
    result = _result(("q", [("keep me", [1]), ("drop me", [2]), ("keep me too", [3])]))

    curated = await curate(result, model=_keeps(1, 3), cap=2)

    assert [c.text for c in curated.points[0].claims] == ["keep me", "keep me too"]


async def test_sources_are_pruned_and_renumbered_from_one() -> None:
    """A report must never cite [187] out of a list of two. The kept claims'
    sources are renumbered in order of first appearance, and the ones nobody
    kept are gone."""
    result = _result(("q", [("a", [1]), ("b", [2]), ("c", [3, 1])]))

    curated = await curate(result, model=_keeps(2, 3), cap=2)

    assert [c.source_ids for c in curated.points[0].claims] == [[1], [2, 3]]
    # source 2 became 1, source 3 became 2, source 1 became 3; source order
    # follows the claims that cite them.
    assert [s.title for s in curated.sources] == ["S2", "S3", "S1"]


async def test_a_sub_question_left_with_nothing_becomes_a_gap() -> None:
    """Saying a sub-question found nothing worth reporting is honest; silently
    dropping it from the report is not."""
    result = _result(("kept", [("a", [1])]), ("emptied", [("b", [2])]))

    curated = await curate(result, model=_keeps(1), cap=1)

    assert [p.sub_question for p in curated.points] == ["kept"]
    assert curated.gaps == ["emptied"]


async def test_a_number_that_means_nothing_is_ignored() -> None:
    """The curator returns numbers, and a number out of range would otherwise
    become an IndexError in the middle of a fifteen-minute run."""
    result = _result(("q", [("a", [1]), ("b", [2]), ("c", [3])]))

    curated = await curate(result, model=_keeps(2, 99, -1, 0), cap=1)

    assert [c.text for c in curated.points[0].claims] == ["b"]


async def test_keeping_nothing_keeps_an_even_share() -> None:
    """A curator that comes back empty must not empty the report, and must not
    hand the writer everything either."""
    result = _result(("q", [("a", [1]), ("b", [2]), ("c", [3])]))

    curated = await curate(result, model=_keeps(), cap=1)

    assert [c.text for p in curated.points for c in p.claims] == ["a"]


async def test_the_curator_reads_claims_with_their_backing() -> None:
    """How well a claim is sourced is part of choosing it, so the numbers go
    along; the source list itself does not, because it never looks one up."""
    result = _result(("why is it blue?", [("Rayleigh scattering", [2, 5])]))
    result.points[0].claims.append(Claim(text="unbacked", source_ids=[]))
    model = _keeps(1)

    await curate(result, model=model, cap=1)

    sent = str(model.seen[-1])
    assert "why is it blue?" in sent
    assert "[1] Rayleigh scattering (sources: 2, 5)" in sent
    assert "[2] unbacked (sources: nothing)" in sent
    assert "https://example.com" not in sent


async def test_a_source_number_that_indexes_nothing_is_dropped() -> None:
    """Claims carry the numbers a researcher wrote. A run that has already spent
    fifteen minutes researching must not die on one that points nowhere."""
    result = _result(("q", [("a", [1]), ("b", [2, 99]), ("c", [3])]), sources=3)

    curated = await curate(result, model=_keeps(2, 3), cap=1)

    assert [c.source_ids for c in curated.points[0].claims] == [[1], [2]]
    assert [s.title for s in curated.sources] == ["S2", "S3"]


class _SlowModel(ScriptedModel):
    """A model that never answers in time."""

    def bind_tools(self, tools, **kwargs):
        async def forever(messages, **_):
            await asyncio.sleep(10)
            raise AssertionError("should have been cut off")

        return SimpleNamespace(ainvoke=forever)


async def test_running_out_of_time_keeps_an_even_share_of_every_angle() -> None:
    """Curating is worth minutes, but never the writer's minutes. Past its
    budget it used to report everything, and a timed-out deep run wrote 22,000
    words; now every sub-question keeps its first claims, in turn, to the cap."""
    result = _result(
        ("q1", [("a", [1]), ("b", [2]), ("c", [3])]),
        ("q2", [("d", [4])]),
        ("q3", [("e", [5]), ("f", [6])]),
    )

    curated = await curate(result, model=_SlowModel(), cap=4, timeout=0.05)

    kept = {p.sub_question: [c.text for c in p.claims] for p in curated.points}
    assert kept == {"q1": ["a", "b"], "q2": ["d"], "q3": ["e"]}

"""The fact checker sets down its claims, reviewed, before it searches."""

from langchain_core.messages import ToolMessage

from app.agents.factcheck import NOT_YET, REVIEW, fact_check
from app.agents.sources import Sources
from tests.agents.fakes import ScriptedModel, call, says
from tests.research.test_research import FakeBackend

CLAIMS = [
    {"claim": "The bridge opened in 1932", "passage": "opened in 1932"},
    {"claim": "It is 503 m long", "passage": "503 metres"},
]


async def test_claims_are_reviewed_and_confirmed_before_any_search() -> None:
    model = ScriptedModel(
        [
            call("web_search", query="too early"),
            # Confirmed on the first try still gets the review.
            call("submit_claims", claims=CLAIMS, left_out=[], confirmed=True),
            call("submit_claims", claims=CLAIMS, left_out=[], confirmed=True),
            call("web_search", query="bridge opened"),
            says("the report"),
        ]
    )

    report = await fact_check(
        "The bridge opened in 1932 and is 503 metres long.",
        filename="bridge.md",
        model=model,
        backend=FakeBackend(),
        sources=Sources(),
        max_iters=3,  # would end before the search, had the list not grown it
    )

    replies = [str(m.content) for m in model.seen[-1] if isinstance(m, ToolMessage)]
    assert replies[0] == NOT_YET
    assert replies[1] == REVIEW
    assert replies[2].startswith("The list is confirmed: 2 claims")
    assert report.content == "the report"

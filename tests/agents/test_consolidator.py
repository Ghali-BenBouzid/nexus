from app.agents.consolidator import consolidate
from app.agents.schemas import Finding, FindingClaim, Source


def _finding(
    sub_q: str,
    answer: str,
    sources: list[Source],
    found: bool = True,
    consulted: list[Source] | None = None,
) -> Finding:
    # A single-claim finding: the whole answer cites the given sources.
    return Finding(
        sub_question=sub_q,
        claims=[FindingClaim(text=answer, sources=sources)] if answer else [],
        consulted_sources=sources if consulted is None else consulted,
        found_info=found,
    )


def test_consolidate_dedupes_sources_by_url_and_numbers_globally() -> None:
    shared = Source(title="Shared", url="http://shared")
    a = Source(title="A", url="http://a")
    b = Source(title="B", url="http://b")

    findings = [
        _finding("q1", "answer one", [shared, a]),
        _finding("q2", "answer two", [b, shared]),  # shared reused, not re-added
    ]

    result = consolidate(findings)

    # one global list, deduped by url
    assert [s.url for s in result.sources] == ["http://shared", "http://a", "http://b"]
    # citations remapped to global 1-based numbers
    assert result.points[0].source_ids == [1, 2]
    assert result.points[1].source_ids == [3, 1]


def test_consolidate_collects_gaps() -> None:
    findings = [
        _finding("answered", "ok", [Source(title="A", url="http://a")]),
        _finding("empty", "", [], found=False),  # soft no-answer
    ]

    result = consolidate(findings, failed_subquestions=["hard failed"])

    assert [p.sub_question for p in result.points] == ["answered"]
    assert set(result.gaps) == {"empty", "hard failed"}


def test_consolidate_collects_provenance_deduped_including_gaps() -> None:
    cited = Source(title="Cited", url="http://cited")
    extra = Source(title="Looked at, not cited", url="http://extra")
    gap_only = Source(title="Seen by a gap finding", url="http://gap")

    findings = [
        # consulted a superset of what it cited
        _finding("answered", "ok", [cited], consulted=[cited, extra]),
        # a gap finding still contributes provenance, plus a duplicate url
        _finding("empty", "", [], found=False, consulted=[gap_only, extra]),
    ]

    result = consolidate(findings)

    # cited list holds only the cited source
    assert [s.url for s in result.sources] == ["http://cited"]
    # provenance holds everything looked at, deduped by url, gaps included
    assert [s.url for s in result.consulted_sources] == [
        "http://cited",
        "http://extra",
        "http://gap",
    ]


def test_consolidate_attributes_sources_per_claim() -> None:
    # Each claim keeps its own sources, remapped to the global numbering.
    a = Source(title="A", url="http://a")
    b = Source(title="B", url="http://b")
    finding = Finding(
        sub_question="q",
        claims=[
            FindingClaim(text="first claim", sources=[a]),
            FindingClaim(text="second claim", sources=[b, a]),
        ],
        consulted_sources=[a, b],
    )

    result = consolidate([finding])
    point = result.points[0]

    assert [c.text for c in point.claims] == ["first claim", "second claim"]
    assert point.claims[0].source_ids == [1]  # a -> 1
    assert point.claims[1].source_ids == [2, 1]  # b -> 2 (new), a -> 1 (reused)
    assert [s.url for s in result.sources] == ["http://a", "http://b"]


def test_consolidate_all_empty() -> None:
    result = consolidate([], failed_subquestions=["x"])
    assert result.points == []
    assert result.sources == []
    assert result.gaps == ["x"]

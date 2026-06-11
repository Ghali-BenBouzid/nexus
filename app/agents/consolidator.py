from app.agents.schemas import Finding, ResearchPoint, ResearchResult, Source


def consolidate(
    findings: list[Finding],
    failed_subquestions: list[str] | None = None,
) -> ResearchResult:
    """Deterministically merge findings into a ResearchResult (no LLM).

    Dedupes every finding's cited sources by URL into one global, numbered list,
    remaps each finding's citations to those global numbers, and collects gaps
    (soft no-answers plus the sub-questions whose researchers hard-failed).
    """
    failed_subquestions = failed_subquestions or []
    sources: list[Source] = []
    number_by_url: dict[str, int] = {}  # url -> 1-based citation number
    points: list[ResearchPoint] = []
    gaps: list[str] = list(failed_subquestions)
    consulted: list[Source] = []  # provenance: everything looked at, deduped
    consulted_urls: set[str] = set()

    for finding in findings:
        # Record provenance even for findings that became gaps: "what we looked
        # at" is part of the audit trail regardless of whether it produced an
        # answer.
        for source in finding.consulted_sources:
            if source.url not in consulted_urls:
                consulted_urls.add(source.url)
                consulted.append(source)

        if not finding.found_info or not finding.answer.strip():
            gaps.append(finding.sub_question)
            continue

        source_ids: list[int] = []
        for source in finding.cited_sources:
            number = number_by_url.get(source.url)
            if number is None:
                sources.append(source)
                number = len(sources)  # 1-based
                number_by_url[source.url] = number
            if number not in source_ids:
                source_ids.append(number)

        points.append(
            ResearchPoint(
                sub_question=finding.sub_question,
                answer=finding.answer,
                source_ids=source_ids,
            )
        )

    return ResearchResult(
        points=points, sources=sources, gaps=gaps, consulted_sources=consulted
    )

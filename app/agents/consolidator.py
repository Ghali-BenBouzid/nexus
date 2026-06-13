from app.agents.schemas import Claim, Finding, ResearchPoint, ResearchResult, Source


def consolidate(
    findings: list[Finding],
    failed_subquestions: list[str] | None = None,
) -> ResearchResult:
    """Deterministically merge findings into a ResearchResult (no LLM).

    Dedupes every claim's cited sources by URL into one global, numbered list,
    remaps each claim's citations to those global numbers (so attribution stays
    per claim, not per whole answer), and collects gaps (soft no-answers plus the
    sub-questions whose researchers hard-failed).
    """
    failed_subquestions = failed_subquestions or []
    sources: list[Source] = []
    number_by_url: dict[str, int] = {}  # url -> 1-based citation number
    points: list[ResearchPoint] = []
    gaps: list[str] = list(failed_subquestions)
    consulted: list[Source] = []  # provenance: everything looked at, deduped
    consulted_urls: set[str] = set()

    def global_number(source: Source) -> int:
        number = number_by_url.get(source.url)
        if number is None:
            sources.append(source)
            number = len(sources)  # 1-based
            number_by_url[source.url] = number
        return number

    for finding in findings:
        # Record provenance even for findings that became gaps: "what we looked
        # at" is part of the audit trail regardless of whether it produced an
        # answer.
        for source in finding.consulted_sources:
            if source.url not in consulted_urls:
                consulted_urls.add(source.url)
                consulted.append(source)

        claims = [claim for claim in finding.claims if claim.text.strip()]
        if not finding.found_info or not claims:
            gaps.append(finding.sub_question)
            continue

        point_claims: list[Claim] = []
        for finding_claim in claims:
            claim_ids: list[int] = []
            for source in finding_claim.sources:
                number = global_number(source)
                if number not in claim_ids:
                    claim_ids.append(number)
            point_claims.append(Claim(text=finding_claim.text, source_ids=claim_ids))

        points.append(
            ResearchPoint(sub_question=finding.sub_question, claims=point_claims)
        )

    return ResearchResult(
        points=points, sources=sources, gaps=gaps, consulted_sources=consulted
    )

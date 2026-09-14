import json

import pytest

from app.agents.supervisor import Answer, ComposeReport, ReadReports, Research
from app.agents.tools import FetchPage, SubmitFinding, SubmitPlan, WebSearch

# Every tool the agents can call. Their parameters go to the model verbatim.
TOOLS = [
    SubmitPlan(),
    SubmitFinding(),
    WebSearch(backend=None),
    FetchPage(backend=None),
    ReadReports([]),
    Answer(),
    ComposeReport(),
    Research(),
]


@pytest.mark.parametrize("tool", TOOLS, ids=lambda tool: tool.name)
def test_tool_parameters_carry_no_references(tool) -> None:
    # Gemini behind OpenRouter does not follow $ref. Handed submit_finding's raw
    # pydantic schema, it sent every claim as a plain string, each researcher's
    # finding was rejected, and every report said nothing was found.
    schema = json.dumps(tool.parameters)

    assert "$ref" not in schema
    assert "$defs" not in schema


def test_submit_finding_spells_out_the_claim_shape() -> None:
    claim = SubmitFinding().parameters["properties"]["claims"]["items"]

    assert claim["type"] == "object"
    assert set(claim["properties"]) == {"text", "cited_source_ids"}
    assert claim["required"] == ["text"]

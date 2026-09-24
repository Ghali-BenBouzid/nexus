"""The schemas the agents' tools go to the model as.

Gemini behind OpenRouter does not follow ``$ref``. Handed submit_finding's raw
pydantic schema, it sent every claim as a plain string, each researcher's finding
was rejected, and every report said nothing was found. LangChain's converter
inlines definitions, and this pins that it keeps doing so.
"""

import json

import pytest
from langchain_core.tools import InjectedToolArg
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.agents.supervisor import (
    DeepResearchArgs,
    FactCheckArgs,
    ReadDocumentArgs,
    ReadReportArgs,
    ResearchArgs,
)
from app.agents.tools import (
    FetchPageArgs,
    SubmitClaimsArgs,
    SubmitFindingArgs,
    SubmitPlanArgs,
    WebSearchArgs,
)

SCHEMAS = [
    SubmitClaimsArgs,
    SubmitPlanArgs,
    SubmitFindingArgs,
    WebSearchArgs,
    FetchPageArgs,
    ResearchArgs,
    DeepResearchArgs,
    ReadDocumentArgs,
    ReadReportArgs,
    FactCheckArgs,
]


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda schema: schema.__name__)
def test_a_tool_schema_carries_no_references(schema) -> None:
    converted = json.dumps(convert_to_openai_tool(schema))

    assert "$ref" not in converted
    assert "$defs" not in converted


def test_submit_finding_spells_out_the_claim_shape() -> None:
    converted = convert_to_openai_tool(SubmitFindingArgs)
    claim = converted["function"]["parameters"]["properties"]["claims"]["items"]

    assert claim["type"] == "object"
    assert set(claim["properties"]) == {"text", "cited_source_ids"}
    assert claim["required"] == ["text"]


def test_a_finding_must_list_its_claims() -> None:
    # Optional in the schema, the list was left out after long reads.
    parameters = convert_to_openai_tool(SubmitFindingArgs)["function"]["parameters"]

    assert set(parameters["required"]) == {"claims", "found_info"}
    assert parameters["properties"]["claims"]["maxItems"] == 10


def test_every_field_the_agents_depend_on_is_described() -> None:
    # A field with no description is a field the model guesses at.
    for schema in SCHEMAS:
        properties = convert_to_openai_tool(schema)["function"]["parameters"][
            "properties"
        ]
        undescribed = [
            name
            for name, f in properties.items()
            if not f.get("description") and name not in _injected(schema)
        ]
        assert not undescribed, f"{schema.__name__}: {undescribed}"


def _injected(schema) -> set[str]:
    """Fields LangChain fills in itself and leaves out of what the model sees."""
    return {
        name
        for name, field in schema.model_fields.items()
        for meta in field.metadata
        if meta is InjectedToolArg
        or (isinstance(meta, type) and issubclass(meta, InjectedToolArg))
    }

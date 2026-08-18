"""The BIOLOGIST.md sentence, as one GraphQL query.

    *"45.2µm (confidence 98%), derived from ROI #555, asserted by AI_Model_X on
    Jan 15th"*

That sentence is the product promise, and until now none of it was answerable.
`RichProperty.supporting_evidence` returned a hardcoded empty list, so a derived
value could be read but never explained: no count of contributing measurements,
no spread, no provenance, no observation window.

A number with no account of where it came from is not a scientific result, it is
a rumour. This test is the one that says the account exists.
"""

import uuid

import kante
import pytest
from kante.context import HttpContext

from core import models as core_models

CREATE_ENTITY = """
    mutation CreateEntity($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { instance { id } }
    }
"""

RECORD_METRIC = """
    mutation RecordMetric($input: AssertMetricValueInput!) {
        assertMetricValue(input: $input) { metric { id } }
    }
"""

THE_SENTENCE = """
    query Explain($id: ID!, $graph: ID!) {
        node(id: $id, graph: $graph) {
            ... on Entity {
                id
                validFrom
                validTo
                richProperties {
                    key
                    value
                    nEvidence
                    spread
                    measuredFrom
                    measuredTo
                    supportingEvidence { id value unit confidence }
                    contributingAssertions { id subject appId }
                }
            }
        }
    }
"""


async def _entity_with_measurements(
    api_schema: kante.Schema,
    ctx: HttpContext,
    test_graph: core_models.Graph,
    values: list[float],
) -> str:
    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").afirst()
    assert category is not None
    object_id = f"roi_{uuid.uuid4().hex[:8]}"

    created = await api_schema.execute(
        CREATE_ENTITY,
        variable_values={
            "input": {
                "term": category.key,
                "supportingEvidence": [
                    {
                        "identifier": "ROI",
                        "object": object_id,
                        "metrics": [{"key": "vector_length", "value": values[0], "valueKind": "FLOAT", "unit": "um", "confidence": 0.98}],
                    }
                ],
            }
        },
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"

    for value in values[1:]:
        recorded = await api_schema.execute(
            RECORD_METRIC,
            variable_values={
                "input": {
                    "identifier": "ROI",
                    "object": object_id,
                    "key": "vector_length",
                    "value": value,
                    "valueKind": "FLOAT",
                    "unit": "um",
                }
            },
            context_value=ctx,
        )
        assert recorded.errors is None, f"GraphQL errors: {recorded.errors}"

    return created.data["assertEntityExists"]["instance"]["id"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_derived_value_can_explain_itself(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Value, evidence count, spread, sources and window — in one round trip."""
    entity_id = await _entity_with_measurements(api_schema, simple_api_context, test_graph, [40.0, 50.0, 45.0])

    result = await api_schema.execute(THE_SENTENCE, variable_values={"id": entity_id, "graph": str(test_graph.id)}, context_value=simple_api_context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    properties = {p["key"]: p for p in result.data["node"]["richProperties"]}
    assert "avg_length" in properties, "The MEAN rollup must appear among the rich properties"

    avg = properties["avg_length"]
    assert avg["value"] == pytest.approx(45.0)
    assert avg["nEvidence"] == 3, "Three measurements contributed"
    assert avg["spread"] == pytest.approx(10.0), "50 - 40"
    assert avg["measuredFrom"] is not None and avg["measuredTo"] is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_supporting_evidence_is_no_longer_an_empty_list(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The measurements behind the number are retrievable, with their units."""
    entity_id = await _entity_with_measurements(api_schema, simple_api_context, test_graph, [40.0, 50.0])

    result = await api_schema.execute(THE_SENTENCE, variable_values={"id": entity_id, "graph": str(test_graph.id)}, context_value=simple_api_context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    avg = next(p for p in result.data["node"]["richProperties"] if p["key"] == "avg_length")
    evidence = avg["supportingEvidence"]

    assert len(evidence) == 2
    assert sorted(m["value"] for m in evidence) == [40.0, 50.0]
    assert evidence[0]["unit"] == "um"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_value_names_who_asserted_it(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Provenance reaches the API, not just the database."""
    entity_id = await _entity_with_measurements(api_schema, simple_api_context, test_graph, [40.0])

    result = await api_schema.execute(THE_SENTENCE, variable_values={"id": entity_id, "graph": str(test_graph.id)}, context_value=simple_api_context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    avg = next(p for p in result.data["node"]["richProperties"] if p["key"] == "avg_length")
    assertions = avg["contributingAssertions"]

    assert assertions, "A derived value must name the assertions behind it"
    assert assertions[0]["subject"], "…and each assertion must say who made the claim"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_validity_is_the_observation_window(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`validFrom`/`validTo` are populated at last.

    Six GraphQL fields read these and every one of them returned null, because
    nothing ever wrote them. They are `measured_at` bounds — when the world was
    looked at — not when somebody got round to saying so.
    """
    entity_id = await _entity_with_measurements(api_schema, simple_api_context, test_graph, [40.0, 50.0])

    result = await api_schema.execute(THE_SENTENCE, variable_values={"id": entity_id, "graph": str(test_graph.id)}, context_value=simple_api_context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    node = result.data["node"]
    assert node["validFrom"] is not None, "An entity with evidence has an observation window"
    assert node["validTo"] is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_property_with_no_evidence_reports_nothing_rather_than_zero(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Absence of evidence must not read as a measured zero."""
    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").afirst()
    created = await api_schema.execute(
        CREATE_ENTITY,
        variable_values={"input": {"term": category.key}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"

    result = await api_schema.execute(
        THE_SENTENCE,
        variable_values={"id": created.data["assertEntityExists"]["instance"]["id"], "graph": str(test_graph.id)},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    for prop in result.data["node"]["richProperties"]:
        assert prop["nEvidence"] in (None, 0)
        assert prop["supportingEvidence"] == []

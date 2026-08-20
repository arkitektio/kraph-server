"""`Graph.projection` tells a client how far along the log a view's drawing is."""

import pytest

from core import models as core_models
from tests import writes

PROJECTION = """
    query($id: ID!) {
        graph(id: $id) {
            id
            projection { kind status projectedThroughSeq lag pending schemaStale derivedThroughSeq derivedAt rebuiltAt }
        }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_projection_reports_caught_up_after_a_write(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    written = await api_schema.execute(writes.ASSERT_ENTITY_EXISTS, variable_values={"input": {"term": "AIS", "supportingEvidence": []}}, context_value=simple_api_context)
    assert written.errors is None, f"GraphQL errors: {written.errors}"

    result = await api_schema.execute(PROJECTION, variable_values={"id": str(test_graph.pk)}, context_value=simple_api_context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    projection = result.data["graph"]["projection"]
    assert projection["kind"] == "age"
    assert projection["status"] == "CONSISTENT"
    assert projection["lag"] == 0
    assert projection["pending"] == 0
    assert projection["projectedThroughSeq"] > 0
    assert projection["schemaStale"] is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_last_derived_is_deprecated_and_null(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS")
    result = await api_schema.execute(
        "query($id: ID!, $graph: ID!) { node(id: $id, graph: $graph) { lastDerived ... on Entity { properties } } }",
        variable_values={"id": entity_id, "graph": str(test_graph.pk)},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["node"]["lastDerived"] is None
    assert "__last_derived" not in result.data["node"]["properties"]

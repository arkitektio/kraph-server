"""Evidence flows to derived values without being asked.

The headline claim of `docs/BIOLOGIST.md`: attach a measurement to a structure,
and the entity that structure informs updates. No explicit recalculate, no
client-side orchestration.

It has never worked before. `create_metric` never re-derived,
`link_structure_to_entity` raised a `NameError` before reaching derivation, and
`_recalculate_entity` itself was broken in three separate ways. This is the test
that says it works now, through the real GraphQL surface against a real Apache
AGE stack.
"""

import uuid

import kante
import pytest
from kante.context import HttpContext

from core import models as core_models

CREATE_ENTITY = """
    mutation CreateEntity($input: CreateEntityInput!) {
        createEntity(input: $input) { id }
    }
"""

RECORD_METRIC = """
    mutation RecordMetric($input: RecordMetricInput!) {
        recordMetric(input: $input) { id }
    }
"""

ENTITY = """
    query Entity($id: GraphID!) {
        node(id: $id) { ... on Entity { id properties } }
    }
"""


async def _properties(api_schema: kante.Schema, ctx: HttpContext, entity_id: str) -> dict:
    result = await api_schema.execute(ENTITY, variable_values={"id": entity_id}, context_value=ctx)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["node"]["properties"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_recording_a_metric_updates_the_derived_value(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Record a measurement; the entity's MEAN moves. No recalculate call."""
    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").afirst()
    assert category is not None
    object_id = f"roi_{uuid.uuid4().hex[:8]}"

    created = await api_schema.execute(
        CREATE_ENTITY,
        variable_values={
            "input": {
                "entityCategory": str(category.pk),
                "supportingEvidence": [{"identifier": "ROI", "object": object_id, "metrics": [{"key": "vector_length", "value": 40.0}]}],
            }
        },
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    entity_id = created.data["createEntity"]["id"]

    assert (await _properties(api_schema, simple_api_context, entity_id))["avg_length"] == pytest.approx(40.0)

    # A second measurement, recorded against the structure — not the entity.
    recorded = await api_schema.execute(
        RECORD_METRIC,
        variable_values={
            "input": {
                "graph": str(test_graph.pk),
                "identifier": "ROI",
                "object": object_id,
                "key": "vector_length",
                "value": 50.0,
                "valueKind": "FLOAT",
            }
        },
        context_value=simple_api_context,
    )
    assert recorded.errors is None, f"GraphQL errors: {recorded.errors}"

    after = await _properties(api_schema, simple_api_context, entity_id)
    assert after["avg_length"] == pytest.approx(45.0), "The entity's MEAN must reflect the new measurement without an explicit recalculate"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_projection_carries_its_schema_version(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Every projected node records which schema derived it.

    Without this, a value cannot be told apart from one derived under an older
    schema — which is the staleness the whole versioning story rests on.
    """
    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").afirst()
    assert category is not None

    created = await api_schema.execute(
        CREATE_ENTITY,
        variable_values={"input": {"entityCategory": str(category.pk)}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"

    result = await api_schema.execute(
        """
        query Entity($id: GraphID!) {
            node(id: $id) { ... on Entity { id schemaVersion } }
        }
        """,
        variable_values={"id": created.data["createEntity"]["id"]},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["node"]["schemaVersion"], "A projected entity must name the schema that derived it"

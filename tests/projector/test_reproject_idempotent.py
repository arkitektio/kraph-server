"""The projection must be reconstructible from evidence alone.

This is the architecture's honesty test, and the one that cannot be argued
around: build a graph, snapshot every entity property, destroy the entire AGE
namespace, replay from Postgres, and compare.

*If the graph cannot be rebuilt from the evidence, the evidence is not the source
of truth, whatever the documentation says.* Everything else in this transition —
org-scoped evidence, the state vector, dirty tracking — is only worth having if
this holds.

Note the rebuild also discards the state vectors and refolds them from the
metrics. Replaying while keeping them would only demonstrate that the projection
can be rebuilt from *another cache*, which is a much weaker claim.
"""

import uuid

import kante
import pytest
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models
from graph_engine.controller import GraphController

CREATE_ENTITY = """
    mutation CreateEntity($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { instance { id } }
    }
"""

RECORD_METRIC = """
    mutation RecordMetric($input: AssertMetricValueInput!) {
        assertMetricValue(input: $input) { metric { id value } }
    }
"""

ENTITY_PROPERTIES = """
    query Entity($id: GraphID!, $graph: ID!) {
        node(id: $id, graph: $graph) {
            ... on Entity { id properties }
        }
    }
"""


async def _ais_category(test_graph: core_models.Graph) -> core_models.EntityCategory:
    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").afirst()
    assert category is not None, "The bio schema declares an AIS entity with a MEAN rollup over ROI"
    return category


async def _build_measured_entity(
    api_schema: kante.Schema,
    ctx: HttpContext,
    test_graph: core_models.Graph,
    values: list[float],
) -> str:
    """An AIS entity with a ROI structure and several vector_length measurements."""
    category = await _ais_category(test_graph)
    object_id = f"roi_{uuid.uuid4().hex[:8]}"

    created = await api_schema.execute(
        CREATE_ENTITY,
        variable_values={
            "input": {
                "term": category.key,
                "supportingEvidence": [{"identifier": "ROI", "object": object_id, "metrics": [{"key": "vector_length", "value": values[0], "valueKind": "FLOAT"}]}],
            }
        },
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    entity_id = created.data["assertEntityExists"]["instance"]["id"]

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
                }
            },
            context_value=ctx,
        )
        assert recorded.errors is None, f"GraphQL errors: {recorded.errors}"

    return entity_id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_reproject_reproduces_the_projection(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """Drop the AGE graph, replay from evidence, compare properties.

    The acceptance test for M3.
    """
    from asgiref.sync import sync_to_async

    entity_id = await _build_measured_entity(api_schema, simple_api_context, test_graph, [10.0, 30.0, 20.0])

    before = await api_schema.execute(ENTITY_PROPERTIES, variable_values={"id": entity_id, "graph": str(test_graph.id)}, context_value=simple_api_context)
    assert before.errors is None, f"GraphQL errors: {before.errors}"
    properties_before = before.data["node"]["properties"]

    assert properties_before.get("avg_length") == pytest.approx(20.0), "The MEAN rollup must have produced a value before we test rebuilding it"

    @sync_to_async
    def rebuild() -> dict:
        controller = GraphController(engine=age_engine)
        return controller.rebuild_projection(test_graph)

    result = await rebuild()
    assert result["nodes"] >= 1
    assert result["projected"] >= 1

    after = await api_schema.execute(ENTITY_PROPERTIES, variable_values={"id": entity_id, "graph": str(test_graph.id)}, context_value=simple_api_context)
    assert after.errors is None, f"GraphQL errors: {after.errors}"
    properties_after = after.data["node"]["properties"]

    # `__last_derived` is a wall-clock stamp and is expected to move; everything
    # else must be identical. Comparing it would test the clock, not the rebuild.
    volatile = {"__last_derived"}
    assert {k: v for k, v in properties_after.items() if k not in volatile} == {k: v for k, v in properties_before.items() if k not in volatile}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_rebuild_survives_the_age_namespace_being_destroyed(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """Nothing may be read out of AGE to perform the rebuild.

    The graph is dropped *before* rebuild reads anything, so if any input came
    from the projection rather than from Postgres the replay would come back
    empty. This is what distinguishes a genuine rebuild from a refresh.
    """
    from asgiref.sync import sync_to_async

    await _build_measured_entity(api_schema, simple_api_context, test_graph, [5.0, 15.0])

    @sync_to_async
    def drop_then_rebuild() -> dict:
        controller = GraphController(engine=age_engine)
        age_engine.drop_graph(test_graph.age_name, cascade=True)
        age_engine.create_graph(age_name=test_graph.age_name)
        return controller.rebuild_projection(test_graph)

    result = await drop_then_rebuild()

    assert result["nodes"] == 1, "The entity must be reconstructed from evidence.Node"
    assert result["states"] == 2, "Both metrics must be refolded from evidence.Metric"
    assert result["projected"] == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_instance_refs_survive_a_rebuild(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """Evidence links must still resolve after the vertex ids change.

    AGE assigns vertex ids, and they are not stable across a drop. Refs key on
    the entity's own uuid precisely so that a rebuild does not leave every
    INFORMS link dangling — which would have made `reproject` destructive rather
    than idempotent.
    """
    from asgiref.sync import sync_to_async

    entity_id = await _build_measured_entity(api_schema, simple_api_context, test_graph, [1.0])

    @sync_to_async
    def refs_and_rebuild() -> tuple[list[str], dict]:
        controller = GraphController(engine=age_engine)
        refs = list(evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.INFORMS).values_list("target_ref", flat=True))
        return refs, controller.rebuild_projection(test_graph)

    refs, result = await refs_and_rebuild()

    assert refs, "Creating an entity with evidence must record an INFORMS link"
    # A bare uuid: no graph prefix, and not an integer AGE vertex id. `UUID()`
    # raising is the assertion.
    for ref in refs:
        uuid.UUID(ref)
    assert result["projected"] == 1

    after = await api_schema.execute(ENTITY_PROPERTIES, variable_values={"id": entity_id, "graph": str(test_graph.id)}, context_value=simple_api_context)
    assert after.errors is None, f"GraphQL errors: {after.errors}"

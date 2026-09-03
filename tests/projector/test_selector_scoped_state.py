"""A graph's selector must mean the same thing on ingest and on replay.

This is the test that would have caught the defect it guards. `State` had three
writers that disagreed: `refold_state` — the rebuild path — applied
`graph.selector` to the metrics it folded, while `state.merge` — the incremental
path every write goes through — did not. The same evidence therefore produced
different derived values depending on whether you had reprojected since.

`recompute` made it worse. It did not apply the selector either, and `state_for`
calls it lazily on any row a retraction marked stale — so one archived metric
after a correct rebuild silently re-admitted the out-of-scope measurements into a
row that had just been made right. The incremental fold and its own correctness
backstop agreed with each other and both were wrong, which is precisely the
hazard `State`'s docstring already warned about on a different axis.

The resolution is that `State` is organization grain and **nothing** folds under
a selector. Which metrics a view counts is answered on read. So what these tests
assert is agreement: incremental, rebuilt and post-retraction reads all return the
same number, and it is the in-scope one.
"""

import uuid
from datetime import datetime, timezone

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models
from evidence import state as state_module
from graph_engine import projector
from graph_engine.controller import GraphController

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

ENTITY_PROPERTIES = """
    query Entity($id: ID!, $graph: ID!) {
        node(id: $id, graph: $graph) { ... on Entity { id properties } }
    }
"""


#: The window the graphs below are scoped to. It contains "now", so measurements
#: recorded through the API fall inside it and only the ones written with an
#: explicit past `measured_at` fall outside.
#:
#: Deliberately `observed_window` rather than `category_keys`: the derivation
#: rule already names `source_node="ROI"`, so narrowing by structure kind would
#: be excluded by the *rule* and the selector would never be exercised at all —
#: a test that passes whatever the selector does.
WINDOW = ["2026-01-01T00:00:00Z", "2100-01-01T00:00:00Z"]
LONG_AGO = datetime(2025, 1, 1, tzinfo=timezone.utc)


async def _ais_with_roi(api_schema: kante.Schema, ctx: HttpContext, graph: core_models.Graph, value: float) -> tuple[str, str]:
    """An AIS informed by one ROI carrying one measurement, observed now."""
    category = await core_models.EntityCategory.objects.filter(graph=graph, key="AIS").afirst()
    assert category is not None, "The bio schema declares an AIS with a MEAN rollup over ROI"

    object_id = f"roi_{uuid.uuid4().hex[:8]}"
    created = await api_schema.execute(
        CREATE_ENTITY,
        variable_values={
            "input": {
                "term": category.key,
                "supportingEvidence": [{"identifier": "ROI", "object": object_id, "metrics": [{"key": "vector_length", "value": value, "valueKind": "FLOAT"}]}],
            }
        },
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertEntityExists"]["instance"]["id"], object_id


def _record_observed_at(graph: core_models.Graph, object_id: str, value: float, measured_at: datetime) -> None:
    """Append a measurement observed at a given time, through the incremental path.

    Exactly what `controller._record_metric` does — write the metric, then fold it
    into the statistics of everything the structure informs. Written here rather
    than through the API only because GraphQL's `Int` is 32-bit and a millisecond
    epoch does not fit in one, so `timestamp` cannot carry a date this far back.
    """
    from evidence import writer
    from evidence import state as state_module
    from graph_engine import projector

    organization = graph.organization
    structure = evidence_models.Structure.objects.for_organization(organization).get(identifier="ROI", object=object_id)
    kind = evidence_models.MetricKind.objects.for_organization(organization).get(structure_kind=structure.kind, key="vector_length", value_kind="FLOAT")

    metric = writer.record_metric(
        organization,
        structure,
        kind,
        key="vector_length",
        value=value,
        assertion=structure.assertion,
        measured_at=measured_at,
    )
    state_module.merge(metric, projector.refs_informed_by(organization, [structure.pk]))


async def _avg_length(api_schema: kante.Schema, ctx: HttpContext, entity_id: str, graph) -> float | None:
    read = await api_schema.execute(ENTITY_PROPERTIES, variable_values={"id": entity_id, "graph": str(graph.id)}, context_value=ctx)
    assert read.errors is None, f"GraphQL errors: {read.errors}"
    return read.data["node"]["properties"].get("avg_length")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_scoped_graph_reads_the_same_value_before_and_after_a_rebuild(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """Ingest and replay must agree under a non-empty selector.

    Both measurements come through the same ROI, so the derivation rule admits
    both and only the selector can exclude one. Before the fix the incremental
    path counted both (mean 505) while the rebuild counted one (1000) — the two
    numbers this test would have reported as unequal.
    """
    from asgiref.sync import sync_to_async

    @sync_to_async
    def scope_to_window() -> None:
        # The window is the property's own rule now (RFC 0009/0010): MEASURED_AT
        # conditions in `rule.evidence` on `avg_length`, in the stored spelling.
        category = core_models.EntityCategory.objects.get(graph=test_graph, key="AIS")
        for prop in category.property_definitions:
            if prop.get("key") == "avg_length":
                prop["rule"]["evidence"] = {
                    "rules": [
                        {
                            "when": [
                                {"field": "MEASURED_AT", "operator": "SINCE", "value": WINDOW[0]},
                                {"field": "MEASURED_AT", "operator": "BEFORE", "value": WINDOW[1]},
                            ]
                        }
                    ]
                }
        category.save()

    await scope_to_window()

    entity_id, object_id = await _ais_with_roi(api_schema, simple_api_context, test_graph, 10.0)
    await sync_to_async(_record_observed_at)(test_graph, object_id, 1000.0, LONG_AGO)

    incremental = await _avg_length(api_schema, simple_api_context, entity_id, test_graph)
    assert incremental == pytest.approx(10.0), "Only the measurement observed inside the window may count"

    @sync_to_async
    def rebuild() -> dict:
        return GraphController(projector=table_projector).rebuild_projection(test_graph)

    await rebuild()

    rebuilt = await _avg_length(api_schema, simple_api_context, entity_id, test_graph)
    assert rebuilt == pytest.approx(incremental), "A replay must produce the value the ingest did"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_retraction_after_a_rebuild_does_not_widen_the_scope(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """The sharper case, and the one that survived the obvious fix.

    Archiving a metric marks the state row stale, and the next *read* recomputes
    it lazily. If that recompute scopes differently from the rebuild, a graph goes
    from correct to wrong without anything being written to it — the hardest
    version of this defect to notice, because nothing in the request that broke it
    touched the value that changed.
    """
    from asgiref.sync import sync_to_async

    @sync_to_async
    def scope_to_window() -> None:
        # The window is the property's own rule now (RFC 0009/0010): MEASURED_AT
        # conditions in `rule.evidence` on `avg_length`, in the stored spelling.
        category = core_models.EntityCategory.objects.get(graph=test_graph, key="AIS")
        for prop in category.property_definitions:
            if prop.get("key") == "avg_length":
                prop["rule"]["evidence"] = {
                    "rules": [
                        {
                            "when": [
                                {"field": "MEASURED_AT", "operator": "SINCE", "value": WINDOW[0]},
                                {"field": "MEASURED_AT", "operator": "BEFORE", "value": WINDOW[1]},
                            ]
                        }
                    ]
                }
        category.save()

    await scope_to_window()

    # One measurement outside the window and two inside, so retracting one still
    # leaves the mean something to be right about.
    entity_id, object_id = await _ais_with_roi(api_schema, simple_api_context, test_graph, 10.0)
    await sync_to_async(_record_observed_at)(test_graph, object_id, 1000.0, LONG_AGO)

    recorded = await api_schema.execute(
        RECORD_METRIC,
        variable_values={"input": {"identifier": "ROI", "object": object_id, "key": "vector_length", "value": 20.0, "valueKind": "FLOAT"}},
        context_value=simple_api_context,
    )
    assert recorded.errors is None, f"GraphQL errors: {recorded.errors}"

    assert await _avg_length(api_schema, simple_api_context, entity_id, test_graph) == pytest.approx(15.0)

    @sync_to_async
    def rebuild() -> dict:
        return GraphController(projector=table_projector).rebuild_projection(test_graph)

    await rebuild()
    assert await _avg_length(api_schema, simple_api_context, entity_id, test_graph) == pytest.approx(15.0)

    # Now retract one in-window metric, then materialize. The read below is a
    # traversal, so it shows what the last materialization wrote — a retraction
    # that never triggered one would leave the old value standing, which is the
    # cost of materializing rather than folding on read. `retract_metric` pairs
    # the two for the same reason; this does it by hand because the test is about
    # the scoped fold, not about the mutation.
    @sync_to_async
    def retract_one_and_materialize() -> None:
        from evidence import writer

        metric = evidence_models.Metric.objects.for_organization(test_graph.organization).filter(structure__identifier="ROI", value_num=20.0).first()
        assert metric is not None
        controller = GraphController(projector=table_projector)
        instance_refs = projector.refs_informed_by(test_graph.organization, [metric.structure_id])
        writer.retract(test_graph.organization, metric, metric.assertion)
        state_module.retract(metric, instance_refs)
        controller.project_from_structures(test_graph.organization, [metric.structure_id])

    await retract_one_and_materialize()

    after = await _avg_length(api_schema, simple_api_context, entity_id, test_graph)
    assert after == pytest.approx(10.0), "The surviving in-window measurement, and nothing the selector excludes"
    assert after != pytest.approx(505.0), "The out-of-window measurement must not be re-admitted by the recompute"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_edge_state_survives_a_rebuild(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """State keyed on an edge is folded by the rebuild too.

    `_attach_supporting_evidence` keys a relation's statistics on a bare `Link`
    pk, and `refold_state` used to scope its work to nodes — so those rows were
    matched by neither its delete nor its refold. They were the one cache the
    rebuild could not rebuild, which made this module's central claim false for
    every relation carrying supporting evidence. Folding the organization covers
    them by construction, and this is what says so.
    """
    from asgiref.sync import sync_to_async

    relation_category = await core_models.RelationCategory.objects.filter(graph=test_graph, key="IS_CONNECTED_TO").afirst()
    assert relation_category is not None

    cell_category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="Cell").afirst()
    assert cell_category is not None

    async def _cell() -> str:
        created = await api_schema.execute(
            CREATE_ENTITY,
            variable_values={"input": {"term": cell_category.key, "supportingEvidence": []}},
            context_value=simple_api_context,
        )
        assert created.errors is None, f"GraphQL errors: {created.errors}"
        return created.data["assertEntityExists"]["instance"]["id"]

    source = await _cell()
    target = await _cell()

    created = await api_schema.execute(
        """
        mutation CreateRelation($input: AssertRelationExistsInput!) {
            assertRelationExists(input: $input) { link { id } }
        }
        """,
        variable_values={
            "input": {
                "term": relation_category.key,
                "sourceId": source,
                "targetId": target,
                "supportingEvidence": [
                    {
                        "identifier": "ROI",
                        "object": f"roi_{uuid.uuid4().hex[:8]}",
                        "metrics": [{"key": "vector_length", "value": 7.0, "valueKind": "FLOAT"}],
                    }
                ],
            }
        },
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    edge_id = created.data["assertRelationExists"]["link"]["id"]

    @sync_to_async
    def edge_state() -> list[tuple[int, float | None]]:
        return sorted(evidence_models.State.objects.for_organization(test_graph.organization).filter(claim_ref=edge_id).values_list("n", "sum"))

    before = await edge_state()
    assert before, "A relation with supporting evidence must fold statistics against its own ref"

    @sync_to_async
    def rebuild() -> dict:
        return GraphController(projector=table_projector).rebuild_projection(test_graph)

    await rebuild()

    assert await edge_state() == before, "The rebuild must reproduce edge-keyed state, not skip it"

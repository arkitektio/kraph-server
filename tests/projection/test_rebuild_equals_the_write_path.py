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
from core import enums
from core import models as core_models
from evidence import models as evidence_models
from graph_engine.controller import GraphController
from datetime import datetime, timezone
from asgiref.sync import sync_to_async
from evidence import state as state_module
from graph_engine import projector
from io import StringIO

from django.core.management import call_command

from evidence import claims as claims_module
from evidence import writer
from graph_engine import watermark
from tests.support import drawing, graphs, rules, writes


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
    query Entity($id: ID!, $graph: ID!) {
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
    table_projector,
) -> None:
    """Drop the AGE graph, replay from evidence, compare properties.

    The acceptance test for M3.
    """

    entity_id = await _build_measured_entity(api_schema, simple_api_context, test_graph, [10.0, 30.0, 20.0])

    before = await api_schema.execute(ENTITY_PROPERTIES, variable_values={"id": entity_id, "graph": str(test_graph.id)}, context_value=simple_api_context)
    assert before.errors is None, f"GraphQL errors: {before.errors}"
    properties_before = before.data["node"]["properties"]

    assert properties_before.get("avg_length") == pytest.approx(20.0), "The MEAN rollup must have produced a value before we test rebuilding it"

    @sync_to_async
    def rebuild() -> dict:
        controller = GraphController(projector=table_projector)
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
    table_projector,
) -> None:
    """Nothing may be read out of AGE to perform the rebuild.

    The graph is dropped *before* rebuild reads anything, so if any input came
    from the projection rather than from Postgres the replay would come back
    empty. This is what distinguishes a genuine rebuild from a refresh.
    """

    await _build_measured_entity(api_schema, simple_api_context, test_graph, [5.0, 15.0])

    @sync_to_async
    def drop_then_rebuild() -> dict:
        controller = GraphController(projector=table_projector)
        table_projector.drop_namespace(test_graph)
        table_projector.refresh_namespace(test_graph)
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
    table_projector,
) -> None:
    """Evidence links must still resolve after the vertex ids change.

    AGE assigns vertex ids, and they are not stable across a drop. Refs key on
    the entity's own uuid precisely so that a rebuild does not leave every
    INFORMS link dangling — which would have made `reproject` destructive rather
    than idempotent.
    """

    entity_id = await _build_measured_entity(api_schema, simple_api_context, test_graph, [1.0])

    @sync_to_async
    def refs_and_rebuild() -> tuple[list[str], dict]:
        controller = GraphController(projector=table_projector)
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


RECORD_METRIC_ID = """
    mutation RecordMetric($input: AssertMetricValueInput!) {
        assertMetricValue(input: $input) { metric { id } }
    }
"""
SCOPED_ENTITY_PROPERTIES = """
    query Entity($id: ID!, $graph: ID!) {
        node(id: $id, graph: $graph) { ... on Entity { id properties } }
    }
"""
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


def _record_observed_at(graph: core_models.Graph, object_id: str, value: float, observed_at: datetime) -> None:
    """Append a measurement observed at a given time, through the incremental path.

    Exactly what `controller._record_metric` does — write the metric, then fold it
    into the statistics of everything the structure informs. Written at the
    writer level so the test says nothing about the API's shape of `observedAt`.
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
        observed_at=observed_at,
    )
    state_module.merge(metric, projector.refs_informed_by(organization, [structure.pk]))


async def _avg_length(api_schema: kante.Schema, ctx: HttpContext, entity_id: str, graph) -> float | None:
    read = await api_schema.execute(SCOPED_ENTITY_PROPERTIES, variable_values={"id": entity_id, "graph": str(graph.id)}, context_value=ctx)
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

    @sync_to_async
    def scope_to_window() -> None:
        # The window is the property's own rule now (RFC 0009/0010): OBSERVED_AT
        # conditions in `rule.evidence` on `avg_length`, in the stored spelling.
        category = core_models.EntityCategory.objects.get(graph=test_graph, key="AIS")
        for prop in category.property_definitions:
            if prop.get("key") == "avg_length":
                prop["rule"]["evidence"] = {
                    "rules": [
                        {
                            "when": [
                                {"field": "OBSERVED_AT", "operator": "SINCE", "value": WINDOW[0]},
                                {"field": "OBSERVED_AT", "operator": "BEFORE", "value": WINDOW[1]},
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

    @sync_to_async
    def scope_to_window() -> None:
        # The window is the property's own rule now (RFC 0009/0010): OBSERVED_AT
        # conditions in `rule.evidence` on `avg_length`, in the stored spelling.
        category = core_models.EntityCategory.objects.get(graph=test_graph, key="AIS")
        for prop in category.property_definitions:
            if prop.get("key") == "avg_length":
                prop["rule"]["evidence"] = {
                    "rules": [
                        {
                            "when": [
                                {"field": "OBSERVED_AT", "operator": "SINCE", "value": WINDOW[0]},
                                {"field": "OBSERVED_AT", "operator": "BEFORE", "value": WINDOW[1]},
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
        RECORD_METRIC_ID,
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


CREATE_RELATION = """
    mutation CreateRelation($input: AssertRelationExistsInput!) {
        assertRelationExists(input: $input) { link { id term { key } } }
    }
"""
ARCHIVE_RELATION = """
    mutation ArchiveRelation($input: RetractRelationInput!) {
        retractRelation(input: $input) { link { id } }
    }
"""


async def _cell_category(test_graph: core_models.Graph) -> core_models.EntityCategory:
    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="Cell").afirst()
    assert category is not None, "The bio schema declares a Cell entity"
    return category


async def _connected_to_category(test_graph: core_models.Graph) -> core_models.RelationCategory:
    category = await core_models.RelationCategory.objects.filter(graph=test_graph, key="IS_CONNECTED_TO").afirst()
    assert category is not None, "The bio schema declares IS_CONNECTED_TO between two Cells"
    return category


async def _make_cell(api_schema: kante.Schema, ctx: HttpContext, category: core_models.EntityCategory) -> str:
    created = await api_schema.execute(
        CREATE_ENTITY,
        variable_values={
            "input": {
                "term": category.key,
                "supportingEvidence": [{"identifier": "ROI", "object": f"roi_{uuid.uuid4().hex[:8]}", "metrics": []}],
            }
        },
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertEntityExists"]["instance"]["id"]


async def _connect(api_schema: kante.Schema, ctx: HttpContext, category: core_models.RelationCategory, source: str, target: str) -> str:
    created = await api_schema.execute(
        CREATE_RELATION,
        variable_values={"input": {"term": category.key, "sourceId": source, "targetId": target}},
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertRelationExists"]["link"]["id"]


def _count_edges(table_projector, graph: core_models.Graph, age_name: str) -> int:
    return drawing.edge_count(graph, age_name)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_relation_survives_a_rebuild(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """Drop the AGE namespace, replay from Postgres, and the edge comes back.

    Before relations were evidence this returned an edgeless graph: `rebuild`
    recreated one vertex per `evidence.Node` and nothing else.
    """
    entity_category = await _cell_category(test_graph)
    relation_category = await _connected_to_category(test_graph)

    source = await _make_cell(api_schema, simple_api_context, entity_category)
    target = await _make_cell(api_schema, simple_api_context, entity_category)
    await _connect(api_schema, simple_api_context, relation_category, source, target)

    @sync_to_async
    def edges_before() -> int:
        return _count_edges(table_projector, test_graph, relation_category.age_name)

    assert await edges_before() == 1, "Asserting a relation must project an edge in the first place"

    @sync_to_async
    def drop_then_rebuild() -> dict:
        controller = GraphController(projector=table_projector)
        table_projector.drop_namespace(test_graph)
        table_projector.refresh_namespace(test_graph)
        return controller.rebuild_projection(test_graph)

    result = await drop_then_rebuild()

    assert result["nodes"] == 2
    assert result["edges"] == 1, "The relation must be reconstructed from evidence.Link alone"

    @sync_to_async
    def edges_after() -> int:
        return _count_edges(table_projector, test_graph, relation_category.age_name)

    assert await edges_after() == 1, "The edge must be present in AGE after the replay, not merely counted"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_archiving_the_last_assertion_removes_the_edge_and_the_replay_agrees(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """With no live claim the edge states nothing, and a rebuild must say the same.

    The failure this guards against is a projection that disagrees with a replay:
    an edge lingering behind a lifecycle flag would survive in AGE but vanish on
    the next reproject.
    """
    entity_category = await _cell_category(test_graph)
    relation_category = await _connected_to_category(test_graph)

    source = await _make_cell(api_schema, simple_api_context, entity_category)
    target = await _make_cell(api_schema, simple_api_context, entity_category)
    relation = await _connect(api_schema, simple_api_context, relation_category, source, target)

    archived = await api_schema.execute(ARCHIVE_RELATION, variable_values={"input": {"id": relation}}, context_value=simple_api_context)
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    @sync_to_async
    def after_archive() -> int:
        return _count_edges(table_projector, test_graph, relation_category.age_name)

    assert await after_archive() == 0, "A retracted relation leaves no edge behind"

    @sync_to_async
    def rebuild() -> dict:
        controller = GraphController(projector=table_projector)
        return controller.rebuild_projection(test_graph)

    result = await rebuild()
    assert result["edges"] == 0, "The replay must not resurrect a retracted relation"

    @sync_to_async
    def after_rebuild() -> int:
        return _count_edges(table_projector, test_graph, relation_category.age_name)

    assert await after_rebuild() == 0


CREATE_NATURAL_EVENT = """
    mutation CreateNaturalEvent($input: AssertNaturalEventExistsInput!) {
        assertNaturalEventExists(input: $input) { instance { id } }
    }
"""


async def _cell(api_schema: kante.Schema, ctx: HttpContext, graph: core_models.Graph) -> str:
    category = await core_models.EntityCategory.objects.filter(graph=graph, key="Cell").afirst()
    assert category is not None
    created = await api_schema.execute(
        CREATE_ENTITY,
        variable_values={"input": {"term": category.key, "supportingEvidence": []}},
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertEntityExists"]["instance"]["id"]


async def _mitosis(api_schema: kante.Schema, ctx: HttpContext, graph: core_models.Graph, source: str, target: str) -> str:
    category = await core_models.NaturalEventCategory.objects.filter(graph=graph, key="Mitosis").afirst()
    assert category is not None, "The bio schema declares a Mitosis event with Cell in and out"
    created = await api_schema.execute(
        CREATE_NATURAL_EVENT,
        variable_values={
            "input": {
                "term": category.key,
                "inputs": [{"role": "a", "entityId": source}],
                "outputs": [{"role": "b", "entityId": target}],
                "supportingEvidence": [],
            }
        },
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertNaturalEventExists"]["instance"]["id"]


def _participations(table_projector, graph: core_models.Graph) -> list[tuple[str, str]]:
    """Every projected participation edge, as (label, role).

    Two queries rather than one `UNION ALL`: AGE rejects the union with "column
    name 'label' specified more than once", and the point here is the edges, not
    the query.
    """
    found: list[tuple[str, str]] = []
    for label in ("WENT_THROUGH", "CAME_OUT_OF"):
        found.extend((label, str(role)) for role in drawing.edge_property_values(graph, label, "role"))
    return sorted(found)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_participation_survives_a_rebuild(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """The honesty test, for participation.

    Nothing about who took part in an event was replayable, because nothing about
    it was recorded — so a reproject silently returned a graph where every event
    had lost its participants.
    """
    source = await _cell(api_schema, simple_api_context, test_graph)
    target = await _cell(api_schema, simple_api_context, test_graph)
    await _mitosis(api_schema, simple_api_context, test_graph, source, target)

    @sync_to_async
    def drop_then_rebuild() -> dict:
        controller = GraphController(projector=table_projector)
        table_projector.drop_namespace(test_graph)
        table_projector.refresh_namespace(test_graph)
        return controller.rebuild_projection(test_graph)

    result = await drop_then_rebuild()
    assert result["participations"] == 2, "Both participations must be reconstructed from evidence.Link alone"

    @sync_to_async
    def edges() -> list[tuple[str, str]]:
        return _participations(table_projector, test_graph)

    assert await edges() == [("CAME_OUT_OF", "b"), ("WENT_THROUGH", "a")], "And be present in AGE afterwards, not merely counted"


# ===========================================================================
# The matrix (C2). Every kind of thing a view draws, drawn by the write path,
# then drawn again from the log alone — by a full rebuild and by the incremental
# replay — and compared whole: labels, members, properties, edges with their
# counts, participations, standings, and what a retracted datum stops feeding.
# ===========================================================================


async def _scenario_measured_entity(api_schema, ctx, graph, table_projector) -> None:
    """An entity with two measurements: derived properties over a datum."""
    await writes.create_entity(api_schema, ctx, "AIS", evidence=[{"identifier": "ROI", "object": f"roi-{uuid.uuid4().hex[:8]}", "metrics": [{"key": "vector_length", "value": 12.0, "valueKind": "FLOAT"}, {"key": "vector_length", "value": 18.0, "valueKind": "FLOAT"}]}])


async def _scenario_two_labels(api_schema, ctx, graph, table_projector) -> None:
    """A node two primitive categories admit: drawn once, under both labels (RFC 0019)."""
    ais = await writes.create_entity(api_schema, ctx, "AIS")
    await writes.classify(api_schema, ctx, [(ais, "Cell")])


async def _scenario_members(api_schema, ctx, graph, table_projector) -> None:
    """Two observations claimed to be one thing: one vertex, two members (RFC 0018)."""
    a = await writes.create_entity(api_schema, ctx, "AIS", evidence=[{"identifier": "ROI", "object": f"roi-{uuid.uuid4().hex[:8]}", "metrics": [{"key": "vector_length", "value": 10.0, "valueKind": "FLOAT"}]}])
    b = await writes.create_entity(api_schema, ctx, "AIS", evidence=[{"identifier": "ROI", "object": f"roi-{uuid.uuid4().hex[:8]}", "metrics": [{"key": "vector_length", "value": 30.0, "valueKind": "FLOAT"}]}])
    await writes.merge(api_schema, ctx, [a, b])


async def _scenario_relation_twice(api_schema, ctx, graph, table_projector) -> None:
    """Two claims of one relation: one edge, `__assertion_count` of two."""
    a = await writes.create_entity(api_schema, ctx, "Cell")
    b = await writes.create_entity(api_schema, ctx, "Cell")
    await writes.create_relation(api_schema, ctx, "IS_CONNECTED_TO", a, b)
    await writes.create_relation(api_schema, ctx, "IS_CONNECTED_TO", a, b)


async def _scenario_edge_under_two_categories(api_schema, ctx, graph, table_projector) -> None:
    """A relation claim two defined relation categories admit: two edges (RFC 0021)."""

    @sync_to_async
    def declare() -> None:
        for key, label in (("curated_touch", "CURATED"), ("loose_touch", "LOOSE")):
            core_models.RelationCategory.objects.create(graph=graph, key=key, age_name=label, label=key, term=writer.ensure_term(graph.organization, enums.CategoryKindChoices.RELATION, key), source_definition={}, target_definition={}, definition=rules.definition(rules.rule(rules.word("touches"))))

    await declare()
    a = await writes.create_entity(api_schema, ctx, "Cell")
    b = await writes.create_entity(api_schema, ctx, "Cell")
    await writes.create_relation(api_schema, ctx, "touches", a, b)


async def _scenario_participation(api_schema, ctx, graph, table_projector) -> None:
    """An event with an input and two outputs: participation edges either side of the vertex."""
    mother = await writes.create_entity(api_schema, ctx, "Cell")
    daughter = await writes.create_entity(api_schema, ctx, "Cell")
    sister = await writes.create_entity(api_schema, ctx, "Cell")
    await writes.create_event(api_schema, ctx, "Mitosis", inputs=[{"role": "a", "entityId": mother}], outputs=[{"role": "a", "entityId": daughter}, {"role": "b", "entityId": sister}])


async def _scenario_retracted_node(api_schema, ctx, graph, table_projector) -> None:
    """A retracted individual has no vertex, and its relation is gone with it."""
    a = await writes.create_entity(api_schema, ctx, "Cell")
    b = await writes.create_entity(api_schema, ctx, "Cell")
    await writes.create_relation(api_schema, ctx, "IS_CONNECTED_TO", a, b)
    await writes.execute(api_schema, ctx, "mutation R($id: ID!) { retractEntity(input: {id: $id}) { assertion { id } } }", {"id": b})


async def _scenario_retracted_datum(api_schema, ctx, graph, table_projector) -> None:
    """A retracted datum stops feeding the values it informed (RFC 0023)."""
    object_id = f"roi-{uuid.uuid4().hex[:8]}"
    await writes.create_entity(api_schema, ctx, "AIS", evidence=[{"identifier": "ROI", "object": object_id, "metrics": [{"key": "vector_length", "value": 42.0, "valueKind": "FLOAT"}]}])
    found = await writes.execute(api_schema, ctx, "query S($identifier: StructureIdentifier!, $object: StructureObject!) { structureByIdentifier(identifier: $identifier, object: $object) { id } }", {"identifier": "ROI", "object": object_id})
    await writes.execute(api_schema, ctx, "mutation R($input: RetractStructureInput!) { retractStructure(input: $input) { assertion { id } } }", {"input": {"id": found["structureByIdentifier"]["id"]}})


SCENARIOS = {
    "measured_entity": _scenario_measured_entity,
    "two_labels": _scenario_two_labels,
    "members": _scenario_members,
    "relation_twice": _scenario_relation_twice,
    "edge_under_two_categories": _scenario_edge_under_two_categories,
    "participation": _scenario_participation,
    "retracted_node": _scenario_retracted_node,
    "retracted_datum": _scenario_retracted_datum,
}


def _drawn(graph) -> tuple[dict, dict]:
    return drawing.snapshot(graph), drawing.edge_snapshot(graph)


def _replay_from_scratch(graph, table_projector) -> None:
    """The incremental path: as if no write had managed to draw.

    Every vertex is erased and every act of the organization is owed again, then
    `reproject --incremental` applies what the outbox says is outstanding.
    """
    table_projector.erase_nodes(graph, list(drawing.snapshot(graph)))
    for assertion in evidence_models.Assertion.objects.for_organization(graph.organization).order_by("seq"):
        watermark.expect(assertion)
    call_command("reproject", incremental=True, organization=graph.organization.slug, stdout=StringIO())


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["rebuild", "incremental"])
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
async def test_the_write_path_and_a_replay_draw_the_same(api_schema, api_context, test_graph, table_projector, scenario, mode) -> None:
    """C2: the drawing is a function of the log. What the write path drew and what a
    replay draws from the log alone must be identical — labels, members,
    properties, edges and their counts — for every kind of thing a view draws."""
    await SCENARIOS[scenario](api_schema, api_context, test_graph, table_projector)
    written = await sync_to_async(_drawn)(test_graph)
    assert written[0], "the scenario drew something to compare"

    if mode == "rebuild":
        await sync_to_async(graphs.rebuild)(test_graph, table_projector)
    else:
        await sync_to_async(_replay_from_scratch)(test_graph, table_projector)

    replayed = await sync_to_async(_drawn)(test_graph)
    assert replayed == written, f"{scenario}: the {mode} drew something the write path did not, or the reverse"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_standing_cache_survives_a_rebuild_for_every_kind(api_schema, api_context, test_graph, table_projector) -> None:
    """`CurrentStanding` is total over claim kinds (RFC 0024) and a rebuild refolds it
    from the log for every kind, the instance included."""
    a = await writes.create_entity(api_schema, api_context, "Cell")
    b = await writes.create_entity(api_schema, api_context, "Cell")
    link = await writes.create_relation(api_schema, api_context, "IS_CONNECTED_TO", a, b)
    await writes.execute(api_schema, api_context, "mutation R($id: ID!) { retractEntity(input: {id: $id}) { assertion { id } } }", {"id": b})
    await writes.execute(api_schema, api_context, "mutation R($input: RetractLinksInput!) { retractLinks(input: $input) { assertion { id } } }", {"input": {"ids": [link]}})

    @sync_to_async
    def folded() -> dict[str, bool]:
        organization = test_graph.organization
        return {"node": claims_module.current(organization, "node", b), "link": claims_module.current(organization, "link", link), "other": claims_module.current(organization, "node", a)}

    before = await folded()
    assert before == {"node": False, "link": False, "other": True}
    await sync_to_async(graphs.rebuild)(test_graph, table_projector)
    assert await folded() == before

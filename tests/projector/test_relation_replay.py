"""Relations must survive a reproject, because relations are evidence.

The honesty test, applied to edges. Until now `rebuild` replayed only
`evidence.Node` rows, so a graph with relations came back without them — the test
passed solely because no working code path could create one. An edge that cannot
be replayed is an edge the evidence does not actually own.

The other claim these tests hold up is the proposition/assertion split. Two labs
claiming the same synapse are two `Link` rows and one edge: the evidence base
keeps both claims so agreement stays countable, while a traversal sees the
connection once.
"""

import uuid

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from evidence import claims as claims_module
from evidence import models as evidence_models
from graph_engine.controller import GraphController

CREATE_ENTITY = """
    mutation CreateEntity($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { entity { id } }
    }
"""

CREATE_RELATION = """
    mutation CreateRelation($input: AssertRelationExistsInput!) {
        assertRelationExists(input: $input) { relation { id label } }
    }
"""

ARCHIVE_RELATION = """
    mutation ArchiveRelation($input: RetractRelationInput!) {
        retractRelation(input: $input) { relation { id } }
    }
"""

UPDATE_RELATION = """
    mutation UpdateRelation($input: UpdateRelationInput!) {
        updateRelation(input: $input) { relation { id } }
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
    return created.data["assertEntityExists"]["entity"]["id"]


async def _connect(api_schema: kante.Schema, ctx: HttpContext, category: core_models.RelationCategory, source: str, target: str) -> str:
    created = await api_schema.execute(
        CREATE_RELATION,
        variable_values={"input": {"term": category.key, "sourceId": source, "targetId": target}},
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertRelationExists"]["relation"]["id"]


def _count_edges(age_engine, graph: core_models.Graph, age_name: str) -> int:
    rows = age_engine.execute(graph, f"MATCH ()-[r:{age_name}]->() RETURN count(r) as c", {})
    return int(rows[0]["c"]) if rows else 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_relation_survives_a_rebuild(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
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
        return _count_edges(age_engine, test_graph, relation_category.age_name)

    assert await edges_before() == 1, "Asserting a relation must project an edge in the first place"

    @sync_to_async
    def drop_then_rebuild() -> dict:
        controller = GraphController(engine=age_engine)
        age_engine.drop_graph(test_graph.age_name, cascade=True)
        age_engine.create_graph(age_name=test_graph.age_name)
        return controller.rebuild_projection(test_graph)

    result = await drop_then_rebuild()

    assert result["nodes"] == 2
    assert result["edges"] == 1, "The relation must be reconstructed from evidence.Link alone"

    @sync_to_async
    def edges_after() -> int:
        return _count_edges(age_engine, test_graph, relation_category.age_name)

    assert await edges_after() == 1, "The edge must be present in AGE after the replay, not merely counted"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_two_assertions_make_two_rows_and_one_edge(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """Agreement is countable in the evidence base and collapsed in the projection.

    Deduplicating at write time would destroy the signal; keeping both edges in
    AGE would make every path query return the relation twice.
    """
    entity_category = await _cell_category(test_graph)
    relation_category = await _connected_to_category(test_graph)

    source = await _make_cell(api_schema, simple_api_context, entity_category)
    target = await _make_cell(api_schema, simple_api_context, entity_category)

    first = await _connect(api_schema, simple_api_context, relation_category, source, target)
    second = await _connect(api_schema, simple_api_context, relation_category, source, target)

    assert first != second, "Two assertions of the same relation are two distinct claims"

    @sync_to_async
    def rows_and_edges() -> tuple[int, int, int]:
        links = evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.RELATION)
        rows = age_engine.execute(
            test_graph,
            f"MATCH ()-[r:{relation_category.age_name}]->() RETURN r.__assertion_count as c",
            {},
        )
        return links.count(), _count_edges(age_engine, test_graph, relation_category.age_name), int(rows[0]["c"])

    link_count, edge_count, assertion_count = await rows_and_edges()

    assert link_count == 2, "Both claims must be kept"
    assert edge_count == 1, "The projection states the proposition once"
    assert assertion_count == 2, "The edge must record how many live claims stand behind it"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_archiving_one_of_two_assertions_keeps_the_edge(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """Retracting one claim does not retract the proposition.

    This is the whole reason assertions are kept separate from the edge they
    agree on. If one lab withdraws, the connection still stands on the other's
    evidence — with the agreement count down by one.
    """
    entity_category = await _cell_category(test_graph)
    relation_category = await _connected_to_category(test_graph)

    source = await _make_cell(api_schema, simple_api_context, entity_category)
    target = await _make_cell(api_schema, simple_api_context, entity_category)

    first = await _connect(api_schema, simple_api_context, relation_category, source, target)
    await _connect(api_schema, simple_api_context, relation_category, source, target)

    archived = await api_schema.execute(ARCHIVE_RELATION, variable_values={"input": {"id": first}}, context_value=simple_api_context)
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    @sync_to_async
    def state() -> tuple[int, int, int]:
        rows = age_engine.execute(
            test_graph,
            f"MATCH ()-[r:{relation_category.age_name}]->() RETURN r.__assertion_count as c",
            {},
        )
        events = evidence_models.Claim.objects.for_organization(test_graph.organization).filter(target_type="link", target_id=first)
        return _count_edges(age_engine, test_graph, relation_category.age_name), int(rows[0]["c"]), events.count()

    edge_count, assertion_count, lifecycle_rows = await state()

    assert edge_count == 1, "One surviving claim keeps the edge"
    assert assertion_count == 1, "The agreement count must fall to the surviving claim"
    assert lifecycle_rows == 1, "The retraction is a lifecycle row, never a delete"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_archiving_the_last_assertion_removes_the_edge_and_the_replay_agrees(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
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
        return _count_edges(age_engine, test_graph, relation_category.age_name)

    assert await after_archive() == 0, "A retracted relation leaves no edge behind"

    @sync_to_async
    def rebuild() -> dict:
        controller = GraphController(engine=age_engine)
        return controller.rebuild_projection(test_graph)

    result = await rebuild()
    assert result["edges"] == 0, "The replay must not resurrect a retracted relation"

    @sync_to_async
    def after_rebuild() -> int:
        return _count_edges(age_engine, test_graph, relation_category.age_name)

    assert await after_rebuild() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_updating_a_relation_replaces_the_claim_and_keeps_the_old_one(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """Update is archive-then-reassert, never an edit in place.

    Both the correction and what it corrected stay on the record — the same shape
    as `update_metric`. The edge survives throughout because the proposition is
    unchanged; only which claim states it moves.
    """
    entity_category = await _cell_category(test_graph)
    relation_category = await _connected_to_category(test_graph)

    source = await _make_cell(api_schema, simple_api_context, entity_category)
    target = await _make_cell(api_schema, simple_api_context, entity_category)
    original = await _connect(api_schema, simple_api_context, relation_category, source, target)

    updated = await api_schema.execute(
        UPDATE_RELATION,
        variable_values={"input": {"id": original, "sourceId": source, "targetId": target}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"
    replacement = updated.data["updateRelation"]["relation"]["id"]

    assert replacement != original, "An update must produce a new claim, not mutate the old one"

    @sync_to_async
    def state() -> tuple[str, str, int]:
        organization = test_graph.organization
        return (
            # `ClaimCurrent`, not a column on the link: the answer moved off the
            # log so the log could be immutable.
            claims_module.current(organization, "link", original),
            claims_module.current(organization, "link", replacement),
            _count_edges(age_engine, test_graph, relation_category.age_name),
        )

    original_status, replacement_status, edge_count = await state()

    assert original_status == False, "The superseded claim is retracted, not deleted"
    assert replacement_status == True
    assert edge_count == 1, "The proposition never stopped being stated, so the edge stands"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_relation_endpoints_key_on_uuids_not_vertex_ids(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """A relation stored against a vertex id would point at nothing after a replay.

    AGE reassigns vertex ids when a graph is dropped, which is precisely what
    `reproject` does — so the refs have to name the entity's own uuid.
    """
    entity_category = await _cell_category(test_graph)
    relation_category = await _connected_to_category(test_graph)

    source = await _make_cell(api_schema, simple_api_context, entity_category)
    target = await _make_cell(api_schema, simple_api_context, entity_category)
    await _connect(api_schema, simple_api_context, relation_category, source, target)

    @sync_to_async
    def refs() -> list[tuple[str, str]]:
        return list(
            evidence_models.Link.objects.for_organization(test_graph.organization)
            .filter(kind=evidence_models.Link.Kind.RELATION)
            .values_list("source_ref", "target_ref")
        )

    endpoints = await refs()
    assert endpoints, "Asserting a relation must record a Link row"
    for source_ref, target_ref in endpoints:
        for ref in (source_ref, target_ref):
            # A bare uuid: no graph prefix, and emphatically not an integer
            # vertex id. `UUID()` raising here is the assertion.
            uuid.UUID(ref)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_relation_reaches_every_view_declaring_its_word(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    second_graph: core_models.Graph,
    age_engine,
) -> None:
    """One claim, two edges — the edge half of "two views share a word".

    Node projection fanned out over every admitting view from the start, but edge
    correction did not: `create_relation` drew into the graph the caller's category
    belonged to, and the retraction paths reached for `_graph_for_ref`, whose own
    docstring admits it "returns an arbitrary one of the declarers". So a second
    view holding both endpoints saw no edge, and — worse — kept one after the claim
    behind it was retracted, since the retraction had been applied next door.

    With the write naming a word there is no caller-named graph left to prefer, so
    an arbitrary choice is no longer even defensible.
    """
    cells = await _cell_category(test_graph)
    connected = await _connected_to_category(test_graph)

    source = await _make_cell(api_schema, simple_api_context, cells)
    target = await _make_cell(api_schema, simple_api_context, cells)
    relation_id = await _connect(api_schema, simple_api_context, connected, source, target)

    @sync_to_async
    def edges() -> tuple[int, int]:
        return (
            _count_edges(age_engine, test_graph, connected.age_name),
            _count_edges(age_engine, second_graph, connected.age_name),
        )

    here, there = await edges()
    assert here == 1, "The edge is drawn in one view"
    assert there == 1, "And in the other, which declares the same word — from the one claim"

    archived = await api_schema.execute(
        ARCHIVE_RELATION,
        variable_values={"input": {"id": relation_id}},
        context_value=simple_api_context,
    )
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    here, there = await edges()
    assert here == 0, "Retracting removes the drawing here"
    assert there == 0, "And there — a retraction honoured in one view only is a projection lying"

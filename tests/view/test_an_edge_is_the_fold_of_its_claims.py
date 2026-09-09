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
from tests.support import claims, drawing, graphs, reads, rules, writes
from tests.support.graphs import AFTER, BEFORE, example_graph as _example_graph, rebuild as _rebuild
from tests.support.writes import CREATE_GRAPH
from evidence import writer
from tests.support.graphs import graph_declaring as _graph_declaring


UPDATE_RELATION = """
    mutation UpdateRelation($input: SupersedeRelationInput!) {
        supersedeRelation(input: $input) { link { id } }
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_two_assertions_make_two_rows_and_one_edge(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """Agreement is countable in the evidence base and collapsed in the projection.

    Deduplicating at write time would destroy the signal; keeping both edges in
    AGE would make every path query return the relation twice.
    """
    entity_category = await _cell_category(test_graph)
    relation_category = await _connected_to_category(test_graph)

    source = await writes.create_entity(api_schema, simple_api_context, entity_category.key, evidence=writes.roi(f"roi_{uuid.uuid4().hex[:8]}", None))
    target = await writes.create_entity(api_schema, simple_api_context, entity_category.key, evidence=writes.roi(f"roi_{uuid.uuid4().hex[:8]}", None))

    first = await writes.create_relation(api_schema, simple_api_context, relation_category.key, source, target)
    second = await writes.create_relation(api_schema, simple_api_context, relation_category.key, source, target)

    assert first != second, "Two assertions of the same relation are two distinct claims"

    @sync_to_async
    def rows_and_edges() -> tuple[int, int, int]:
        links = evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.RELATION)
        counts = drawing.edge_property_values(test_graph, relation_category.age_name, "__assertion_count")
        return links.count(), drawing.edge_count(test_graph, relation_category.age_name), int(counts[0])

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
    table_projector,
) -> None:
    """Retracting one claim does not retract the proposition.

    This is the whole reason assertions are kept separate from the edge they
    agree on. If one lab withdraws, the connection still stands on the other's
    evidence — with the agreement count down by one.
    """
    entity_category = await _cell_category(test_graph)
    relation_category = await _connected_to_category(test_graph)

    source = await writes.create_entity(api_schema, simple_api_context, entity_category.key, evidence=writes.roi(f"roi_{uuid.uuid4().hex[:8]}", None))
    target = await writes.create_entity(api_schema, simple_api_context, entity_category.key, evidence=writes.roi(f"roi_{uuid.uuid4().hex[:8]}", None))

    first = await writes.create_relation(api_schema, simple_api_context, relation_category.key, source, target)
    await writes.create_relation(api_schema, simple_api_context, relation_category.key, source, target)

    archived = await api_schema.execute(writes.RETRACT_RELATION, variable_values={"input": {"id": first}}, context_value=simple_api_context)
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    @sync_to_async
    def state() -> tuple[int, int, int]:
        counts = drawing.edge_property_values(test_graph, relation_category.age_name, "__assertion_count")
        events = evidence_models.Standing.objects.for_organization(test_graph.organization).filter(target_type="link", target_id=first)
        return drawing.edge_count(test_graph, relation_category.age_name), int(counts[0]), events.count()

    edge_count, assertion_count, lifecycle_rows = await state()

    assert edge_count == 1, "One surviving claim keeps the edge"
    assert assertion_count == 1, "The agreement count must fall to the surviving claim"
    assert lifecycle_rows == 1, "The retraction is a lifecycle row, never a delete"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_retraction_folds_survivors_under_the_rule_not_the_drawing(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """The survivor set of a correction comes from the rule, and the drawing
    is converged to it — never the other way round.

    Two observations `a` and `b` are claimed to be one cell *without* the view
    being redrawn (the claim is written straight to the log, as a replay would
    find it). Each is related to `c`. The write path used to ask the drawing
    which members `a` stood for and got "only `a`", so retracting `a -> c` found
    no survivor and erased an edge the next rebuild would draw again — the two
    disagreed exactly when the cache was behind. Now the rule answers, the
    individual is converged first, and the retraction leaves `b -> c` standing.
    """
    from tests.support import claims as claims_module_helpers

    entity_category = await _cell_category(test_graph)
    relation_category = await _connected_to_category(test_graph)

    a = await writes.create_entity(api_schema, simple_api_context, entity_category.key, evidence=writes.roi(f"roi_{uuid.uuid4().hex[:8]}", None))
    b = await writes.create_entity(api_schema, simple_api_context, entity_category.key, evidence=writes.roi(f"roi_{uuid.uuid4().hex[:8]}", None))
    c = await writes.create_entity(api_schema, simple_api_context, entity_category.key, evidence=writes.roi(f"roi_{uuid.uuid4().hex[:8]}", None))

    # The sameness claim lands in the log only; the drawing still shows two cells.
    await sync_to_async(claims_module_helpers.same)(test_graph.organization, a, b, "annotator")
    assert await sync_to_async(drawing.members_of)(test_graph, a) == [a], "nothing has redrawn the individual yet"

    first = await writes.create_relation(api_schema, simple_api_context, relation_category.key, a, c)
    await writes.create_relation(api_schema, simple_api_context, relation_category.key, b, c)

    @sync_to_async
    def converged() -> tuple[list[str], int]:
        return drawing.members_of(test_graph, a), drawing.edge_count(test_graph, relation_category.age_name)

    members, edges = await converged()
    assert members == sorted([a, b]), "the correction path converged the individual the rule describes"
    assert edges == 1, "one individual, one edge to c"

    archived = await api_schema.execute(writes.RETRACT_RELATION, variable_values={"input": {"id": first}}, context_value=simple_api_context)
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    @sync_to_async
    def after() -> tuple[int, list]:
        return drawing.edge_count(test_graph, relation_category.age_name), drawing.edge_property_values(test_graph, relation_category.age_name, "__assertion_count")

    edges, counts = await after()
    assert edges == 1, "b -> c still holds the edge up"
    assert counts == [1]

    @sync_to_async
    def rebuild() -> int:
        graphs.rebuild(test_graph, table_projector)
        return drawing.edge_count(test_graph, relation_category.age_name)

    assert await rebuild() == 1, "and a rebuild says the same"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_updating_a_relation_replaces_the_claim_and_keeps_the_old_one(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """Update is archive-then-reassert, never an edit in place.

    Both the correction and what it corrected stay on the record — the same shape
    as `update_metric`. The edge survives throughout because the proposition is
    unchanged; only which claim states it moves.
    """
    entity_category = await _cell_category(test_graph)
    relation_category = await _connected_to_category(test_graph)

    source = await writes.create_entity(api_schema, simple_api_context, entity_category.key, evidence=writes.roi(f"roi_{uuid.uuid4().hex[:8]}", None))
    target = await writes.create_entity(api_schema, simple_api_context, entity_category.key, evidence=writes.roi(f"roi_{uuid.uuid4().hex[:8]}", None))
    original = await writes.create_relation(api_schema, simple_api_context, relation_category.key, source, target)

    updated = await api_schema.execute(
        UPDATE_RELATION,
        variable_values={"input": {"id": original, "sourceId": source, "targetId": target}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"
    replacement = updated.data["supersedeRelation"]["link"]["id"]

    assert replacement != original, "An update must produce a new claim, not mutate the old one"

    @sync_to_async
    def state() -> tuple[str, str, int]:
        organization = test_graph.organization
        return (
            # `CurrentStanding`, not a column on the link: the answer moved off the
            # log so the log could be immutable.
            claims_module.current(organization, "link", original),
            claims_module.current(organization, "link", replacement),
            drawing.edge_count(test_graph, relation_category.age_name),
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
    table_projector,
) -> None:
    """A relation stored against a vertex id would point at nothing after a replay.

    AGE reassigns vertex ids when a graph is dropped, which is precisely what
    `reproject` does — so the refs have to name the entity's own uuid.
    """
    entity_category = await _cell_category(test_graph)
    relation_category = await _connected_to_category(test_graph)

    source = await writes.create_entity(api_schema, simple_api_context, entity_category.key, evidence=writes.roi(f"roi_{uuid.uuid4().hex[:8]}", None))
    target = await writes.create_entity(api_schema, simple_api_context, entity_category.key, evidence=writes.roi(f"roi_{uuid.uuid4().hex[:8]}", None))
    await writes.create_relation(api_schema, simple_api_context, relation_category.key, source, target)

    @sync_to_async
    def refs() -> list[tuple[str, str]]:
        return list(evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.RELATION).values_list("source_ref", "target_ref"))

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
    table_projector,
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

    source = await writes.create_entity(api_schema, simple_api_context, cells.key, evidence=writes.roi(f"roi_{uuid.uuid4().hex[:8]}", None))
    target = await writes.create_entity(api_schema, simple_api_context, cells.key, evidence=writes.roi(f"roi_{uuid.uuid4().hex[:8]}", None))
    relation_id = await writes.create_relation(api_schema, simple_api_context, connected.key, source, target)

    @sync_to_async
    def edges() -> tuple[int, int]:
        return (
            drawing.edge_count(test_graph, connected.age_name),
            drawing.edge_count(second_graph, connected.age_name),
        )

    here, there = await edges()
    assert here == 1, "The edge is drawn in one view"
    assert there == 1, "And in the other, which declares the same word — from the one claim"

    archived = await api_schema.execute(
        writes.RETRACT_RELATION,
        variable_values={"input": {"id": relation_id}},
        context_value=simple_api_context,
    )
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    here, there = await edges()
    assert here == 0, "Retracting removes the drawing here"
    assert there == 0, "And there — a retraction honoured in one view only is a projection lying"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_participation_is_projected_with_its_role(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """Both entities reach the event, on the right side, carrying their role."""
    source = await writes.create_entity(api_schema, simple_api_context, "Cell")
    target = await writes.create_entity(api_schema, simple_api_context, "Cell")
    await writes.create_event(api_schema, simple_api_context, "Mitosis", inputs=[{"role": "a", "entityId": source}], outputs=[{"role": "b", "entityId": target}])

    @sync_to_async
    def edges() -> list[tuple[str, str]]:
        return drawing.participations(test_graph)

    assert await edges() == [("CAME_OUT_OF", "b"), ("WENT_THROUGH", "a")], "An input and an output edge, each naming the role the schema gave it"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_participation_is_evidence(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The claim is a row, keyed on durable refs, before it is ever an edge."""
    source = await writes.create_entity(api_schema, simple_api_context, "Cell")
    target = await writes.create_entity(api_schema, simple_api_context, "Cell")
    await writes.create_event(api_schema, simple_api_context, "Mitosis", inputs=[{"role": "a", "entityId": source}], outputs=[{"role": "b", "entityId": target}])

    @sync_to_async
    def links() -> list[tuple[str, str, str]]:
        rows = evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind__in=("participates_as_input", "participates_as_output"))
        return sorted((row.kind, str(row.role), str(row.source_ref)) for row in rows)

    recorded = await links()
    assert len(recorded) == 2, "Both participations must be recorded as evidence"
    assert [(kind, role) for kind, role, _ in recorded] == [("participates_as_input", "a"), ("participates_as_output", "b")]
    for _, _, source_ref in recorded:
        # A bare uuid, not an AGE vertex id and not a graph-prefixed composite.
        # `UUID()` raising is the assertion.
        uuid.UUID(source_ref)


ASSERT_PARTICIPATION = """
    mutation AssertParticipation($input: AssertParticipationInput!) {
        assertParticipation(input: $input) { link { id } }
    }
"""
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_two_observers_can_claim_the_same_participation(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """Who took part is contestable, so agreement is countable.

    Two claims, one edge — the same shape relations already use. Before
    `assertParticipation` the only way to say anything about participants was
    `updateNaturalEvent`, which archived the event and made a new one, so a
    second opinion produced a second event.
    """
    source = await writes.create_entity(api_schema, simple_api_context, "Cell")
    target = await writes.create_entity(api_schema, simple_api_context, "Cell")
    event = await writes.create_event(api_schema, simple_api_context, "Mitosis", inputs=[{"role": "a", "entityId": source}], outputs=[{"role": "b", "entityId": target}])

    again = await api_schema.execute(
        writes.ASSERT_PARTICIPATION,
        variable_values={"input": {"event": event, "entity": source, "role": "a", "isInput": True}},
        context_value=simple_api_context,
    )
    assert again.errors is None, f"GraphQL errors: {again.errors}"

    @sync_to_async
    def state() -> tuple[int, list[tuple[str, str]], list[int]]:
        claims = evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.PARTICIPATES_AS_INPUT)
        return claims.count(), drawing.participations(test_graph), drawing.assertion_counts(test_graph, "WENT_THROUGH")

    claim_count, edges, counts = await state()

    assert claim_count == 2, "Both observers' claims are kept"
    assert edges == [("CAME_OUT_OF", "b"), ("WENT_THROUGH", "a")], "And collapse to one edge per participation"
    assert counts == [2], "The edge records how many live claims stand behind it"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_one_participation_claim_keeps_the_edge(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """One observer withdrawing does not undo the other's claim."""
    source = await writes.create_entity(api_schema, simple_api_context, "Cell")
    target = await writes.create_entity(api_schema, simple_api_context, "Cell")
    event = await writes.create_event(api_schema, simple_api_context, "Mitosis", inputs=[{"role": "a", "entityId": source}], outputs=[{"role": "b", "entityId": target}])

    second = await api_schema.execute(
        writes.ASSERT_PARTICIPATION,
        variable_values={"input": {"event": event, "entity": source, "role": "a", "isInput": True}},
        context_value=simple_api_context,
    )
    assert second.errors is None, f"GraphQL errors: {second.errors}"

    archived = await api_schema.execute(
        writes.RETRACT_PARTICIPATION,
        variable_values={"input": {"id": second.data["assertParticipation"]["link"]["id"]}},
        context_value=simple_api_context,
    )
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    @sync_to_async
    def state() -> tuple[list[tuple[str, str]], list[int], int]:
        events = evidence_models.Standing.objects.for_organization(test_graph.organization).filter(target_type="link")
        return drawing.participations(test_graph), drawing.assertion_counts(test_graph, "WENT_THROUGH"), events.count()

    edges, counts, lifecycle_rows = await state()

    assert edges == [("CAME_OUT_OF", "b"), ("WENT_THROUGH", "a")], "The surviving claim keeps the edge"
    assert counts == [1], "And the agreement count falls to it"
    assert lifecycle_rows == 1, "Retraction is a lifecycle row, never a delete"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_the_last_participation_claim_removes_the_edge(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """With no live claim the edge states nothing, and a replay must agree."""
    source = await writes.create_entity(api_schema, simple_api_context, "Cell")
    target = await writes.create_entity(api_schema, simple_api_context, "Cell")
    await writes.create_event(api_schema, simple_api_context, "Mitosis", inputs=[{"role": "a", "entityId": source}], outputs=[{"role": "b", "entityId": target}])

    @sync_to_async
    def the_input_claim() -> str:
        return str(evidence_models.Link.objects.for_organization(test_graph.organization).get(kind=evidence_models.Link.Kind.PARTICIPATES_AS_INPUT).pk)

    claim_id = await the_input_claim()

    archived = await api_schema.execute(writes.RETRACT_PARTICIPATION, variable_values={"input": {"id": claim_id}}, context_value=simple_api_context)
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    @sync_to_async
    def after() -> list[tuple[str, str]]:
        return drawing.participations(test_graph)

    assert await after() == [("CAME_OUT_OF", "b")], "The retracted input participation is gone; the output one stands"

    @sync_to_async
    def rebuild() -> tuple[dict, list[tuple[str, str]]]:
        result = graphs.rebuild(test_graph, table_projector)
        return result, drawing.participations(test_graph)

    result, edges = await rebuild()
    assert result["participations"] == 1, "A replay must not resurrect a retracted participation"
    assert edges == [("CAME_OUT_OF", "b")]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_relation_edges_fold_under_the_relation_categorys_clauses(api_schema, simple_api_context, table_projector) -> None:
    """Only Karl's post-Dec-5 connectivity claims draw IS_CONNECTED_TO edges."""
    graph_id = await _example_graph(api_schema, simple_api_context, "trust-relations")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        a = claims.mint(org, "Cell", "peter", asserted_at=BEFORE)
        b = claims.mint(org, "Cell", "peter", asserted_at=BEFORE)
        c = claims.mint(org, "Cell", "peter", asserted_at=BEFORE)
        claims.relate(org, "IS_CONNECTED_TO", a, b, "karl", asserted_at=AFTER)
        claims.relate(org, "IS_CONNECTED_TO", b, c, "peter", asserted_at=AFTER)
        claims.relate(org, "IS_CONNECTED_TO", c, a, "karl", asserted_at=BEFORE)
        _rebuild(graph_id, table_projector)
        return (
            drawing.edges_between(graph, a, b, "IS_CONNECTED_TO"),
            drawing.edges_between(graph, b, c, "IS_CONNECTED_TO"),
            drawing.edges_between(graph, c, a, "IS_CONNECTED_TO"),
        )

    karls_late, peters, karls_early = await build_and_read()
    assert karls_late == 1, "Karl after Dec 5 is the relation category's clause"
    assert peters == 0, "Peter is not trusted for this relation"
    assert karls_early == 0, "Karl before Dec 5 falls outside the clause"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_participations_fold_under_the_event_categorys_clauses(api_schema, simple_api_context, table_projector) -> None:
    """The event category's clauses govern its participation edges too."""
    graph_id = await _example_graph(api_schema, simple_api_context, "trust-participations")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        mother = claims.mint(org, "Cell", "peter", asserted_at=BEFORE)
        event = claims.mint(org, "Mitosis", "anyone", app_id="event-annotator", kind="NATURAL_EVENT")
        claims.participate(org, "Mitosis", mother, event, "anyone", app_id="event-annotator", role="mother")
        # A participation claimed through an app the event's clause does not
        # name is not drawn — same word, untrusted tool.
        other = claims.mint(org, "Cell", "peter", asserted_at=BEFORE)
        claims.participate(org, "Mitosis", other, event, "anyone", app_id="freehand", role="mother")
        _rebuild(graph_id, table_projector)
        return (
            drawing.edges_between(graph, mother, event),
            drawing.edges_between(graph, other, event),
        )

    trusted, untrusted = await build_and_read()
    assert trusted == 1, "a participation claimed through the trusted app draws"
    assert untrusted == 0, "one claimed through any other app does not"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_participation_lists_fold_under_the_event_categorys_clauses(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector) -> None:
    definition = {
        "extensions": {
            "entities": [{"key": "Cell"}],
            "events": [
                {
                    "key": "Mitosis",
                    "kind": "INTRINSIC",
                    "definition": rules.definition(rules.rule(rules.word("Mitosis"), rules.via("event-annotator"))),
                    "inputs": [{"key": "Cell", "role": "mother", "descriptor": {"keys": ["Cell"]}}],
                    "outputs": [],
                }
            ],
        }
    }
    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": {"name": "listed-honestly", "definition": definition}}, context_value=simple_api_context)
    assert made.errors is None, f"GraphQL errors: {made.errors}"
    graph_id = made.data["createGraph"]["id"]

    @sync_to_async
    def build():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        cell = claims.mint(org, "Cell", "peter")
        event = claims.mint(org, "Mitosis", "anyone", app_id="event-annotator", kind="NATURAL_EVENT")
        trusted = claims.participate(org, "Mitosis", cell, event, "anyone", app_id="event-annotator", role="mother")
        untrusted = claims.participate(org, "Mitosis", claims.mint(org, "Cell", "peter"), event, "anyone", app_id="freehand", role="mother")
        return str(trusted.pk), str(untrusted.pk)

    trusted_id, untrusted_id = await build()
    listed = await api_schema.execute(reads.INPUT_PARTICIPATIONS, variable_values={"graph": graph_id}, context_value=simple_api_context)
    assert listed.errors is None, f"GraphQL errors: {listed.errors}"
    ids = {row["id"] for row in listed.data["inputParticipations"]}
    assert trusted_id in ids, "the trusted app's participation is listed"
    assert untrusted_id not in ids, "one the event's clause refuses is not — the list agrees with the drawing"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_link_claims_and_their_retractions_fold_per_relation_category(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector, backend_stack) -> None:
    """Both halves of the relation category's trust apply: the **claim** must be
    by somebody its clauses count (an untrusted annotator's claim draws no edge
    at all), and its **standing** folds under the same predicate (an untrusted
    retraction does not take a trusted edge)."""
    graph_id = await _graph_declaring(api_schema, simple_api_context, "LinkCell")

    @sync_to_async
    def declare_relation():
        graph = core_models.Graph.objects.get(pk=graph_id)
        from core import enums

        core_models.RelationCategory.objects.create(
            graph=graph,
            key="touches",
            age_name="TOUCHES",
            label="touches",
            term=writer.ensure_term(graph.organization, enums.CategoryKindChoices.RELATION, "touches"),
            source_definition={},
            target_definition={},
            definition=rules.definition(rules.rule(rules.word("touches"), rules.by("curator"))),
        )
        return graph

    graph = await declare_relation()
    a = await writes.create_entity(api_schema, simple_api_context, "LinkCell")
    b = await writes.create_entity(api_schema, simple_api_context, "LinkCell")

    @sync_to_async
    def story():
        from evidence import models as evidence_models
        touches = core_models.RelationCategory.objects.get(graph=graph, key="touches")

        # An untrusted annotator's claim draws nothing in this view.
        bot_claim = writer.create_link(
            graph.organization,
            kind=evidence_models.Link.Kind.RELATION,
            source_ref=a,
            target_ref=b,
            assertion=writer.create_assertion(graph.organization, subject="bot", app_id="pytest"),
            term=touches.term,
        )
        graphs.rebuild(graph, table_projector)
        untrusted_claim = drawing.edge_count(graph, "TOUCHES")

        # The curator's claim does.
        writer.create_link(
            graph.organization,
            kind=evidence_models.Link.Kind.RELATION,
            source_ref=a,
            target_ref=b,
            assertion=writer.create_assertion(graph.organization, subject="curator", app_id="pytest"),
            term=touches.term,
        )
        graphs.rebuild(graph, table_projector)
        trusted_claim = drawing.edge_count(graph, "TOUCHES")

        # An untrusted retraction of the curator's claim changes nothing here.
        curator_link = evidence_models.Link.objects.for_organization(graph.organization).filter(kind=evidence_models.Link.Kind.RELATION, term=touches.term).exclude(pk=bot_claim.pk).get()
        writer.retract(graph.organization, curator_link, writer.create_assertion(graph.organization, subject="bot", app_id="pytest"))
        graphs.rebuild(graph, table_projector)
        untrusted_retraction = drawing.edge_count(graph, "TOUCHES")

        # The curator's own retraction takes the edge.
        writer.retract(graph.organization, curator_link, writer.create_assertion(graph.organization, subject="curator", app_id="pytest"))
        graphs.rebuild(graph, table_projector)
        trusted_retraction = drawing.edge_count(graph, "TOUCHES")

        return untrusted_claim, trusted_claim, untrusted_retraction, trusted_retraction

    untrusted_claim, trusted_claim, untrusted_retraction, trusted_retraction = await story()
    assert untrusted_claim == 0, "a claim by somebody this category does not count draws no edge"
    assert trusted_claim == 1, "the trusted claim draws"
    assert untrusted_retraction == 1, "an untrusted retraction does not take a trusted edge"
    assert trusted_retraction == 0, "the trusted retraction does"

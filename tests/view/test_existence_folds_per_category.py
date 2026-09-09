"""Existence is evidence, and the graph holds only what exists.

The rule: **the graph carries no lifecycle state.** If the evidence does not say
a node is there, the node is not in the projection — no vertex, no flag beside
one. That is the rule `_reproject_proposition` has always applied to edges, which
delete when the last claim behind them is retracted *"rather than lingering with
a lifecycle flag: `rebuild` would not recreate it, and a projection that
disagrees with a replay is the failure this layer is supposed to make
impossible."* Nodes were the last holdout.

Two things follow, and both are tested here rather than assumed:

- Retracting a node removes it and its edges from the drawing, while every
  `Node`, `Link` and `Standing` row survives untouched. The projection is a cache;
  the claims are not.
- Attesting is not "un-archiving". There is no state to reverse — somebody
  claims the thing is there, which is evidence of the same kind as somebody
  claiming it is not. Both stay on the record, and *which one a graph believes is
  its selector's decision*. The last test is that one, and it is the reason
  existence is a fold rather than a boolean.
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
from django.utils import timezone as django_timezone
from evidence import writer
from tests.support.graphs import graph_declaring as _graph_declaring


RETRACT_ENTITY = """
    mutation RetractEntity($input: RetractEntityInput!) {
        retractEntity(input: $input) { instance { id } drawings { graph { id } } }
    }
"""
ATTEST_ENTITY = """
    mutation AttestEntity($input: AttestEntityInput!) {
        attestEntity(input: $input) { instance { id } drawings { graph { id } } }
    }
"""
RETRACT_NATURAL_EVENT = """
    mutation RetractNaturalEvent($input: RetractNaturalEventInput!) {
        retractNaturalEvent(input: $input) { instance { id } drawings { graph { id } } }
    }
"""
async def _ais_with_length(api_schema: kante.Schema, ctx: HttpContext, graph: core_models.Graph, value: float) -> str:
    """An AIS carrying a measurement, so it has a derived property worth comparing."""
    category = await core_models.EntityCategory.objects.filter(graph=graph, key="AIS").afirst()
    assert category is not None, "The bio schema declares an AIS with a MEAN rollup over ROI"
    created = await api_schema.execute(
        writes.ASSERT_ENTITY_EXISTS,
        variable_values={
            "input": {
                "term": category.key,
                "supportingEvidence": [
                    {
                        "identifier": "ROI",
                        "object": f"roi_{uuid.uuid4().hex[:8]}",
                        "metrics": [{"key": "vector_length", "value": value, "valueKind": "FLOAT"}],
                    }
                ],
            }
        },
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertEntityExists"]["instance"]["id"]


def _vertices(table_projector, graph: core_models.Graph, node_id: str) -> int:
    return drawing.vertices_with_ref(graph, node_id)


def _edges(table_projector, graph: core_models.Graph, age_name: str) -> int:
    return drawing.edge_count(graph, age_name)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_archiving_a_natural_event_removes_its_vertex(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """The event archive path, which had no behavioural coverage at all.

    It was an inline copy of the entity flow in `api/mutations/`, with the target
    type hardcoded to a different string — which is exactly how the entity and
    event spellings came to disagree, and why an archived event was invisible to
    the code that stamped the projection. There is one controller path now.
    """
    source = await writes.create_entity(api_schema, simple_api_context, "Cell")
    target = await writes.create_entity(api_schema, simple_api_context, "Cell")
    event_id = await writes.create_event(api_schema, simple_api_context, "Mitosis", inputs=[{"role": "a", "entityId": source}], outputs=[{"role": "b", "entityId": target}])

    @sync_to_async
    def vertices() -> int:
        return _vertices(table_projector, test_graph, event_id)

    assert await vertices() == 1

    archived = await api_schema.execute(
        RETRACT_NATURAL_EVENT,
        variable_values={"input": {"id": event_id}},
        context_value=simple_api_context,
    )
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"
    assert archived.data["retractNaturalEvent"]["drawings"] == [], "No view draws a retracted event"

    assert await vertices() == 0, "A retracted event leaves no vertex behind"

    @sync_to_async
    def claim_says_retracted() -> bool:
        return evidence_models.Standing.objects.for_organization(test_graph.organization).filter(target_type="node", target_id=event_id, stands=False).exists()

    assert await claim_says_retracted(), "And the retraction is on the record as a claim"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_archiving_an_entity_removes_its_edges_but_keeps_the_claims(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """`DETACH` takes the drawing, never the evidence.

    An edge to a node that is not there is not in the view either, so it goes
    with the vertex. The `Link` rows behind those edges are claims somebody made
    and they survive completely — which is what makes the removal reversible by
    nothing more than new evidence.
    """
    relation_category = await core_models.RelationCategory.objects.filter(graph=test_graph, key="IS_CONNECTED_TO").afirst()
    assert relation_category is not None

    source = await writes.create_entity(api_schema, simple_api_context, "Cell")
    target = await writes.create_entity(api_schema, simple_api_context, "Cell")

    created = await api_schema.execute(
        writes.ASSERT_RELATION_EXISTS,
        variable_values={"input": {"term": relation_category.key, "sourceId": source, "targetId": target}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"

    @sync_to_async
    def edges() -> int:
        return _edges(table_projector, test_graph, relation_category.age_name)

    assert await edges() == 1, "The relation must be drawn before we take an endpoint away"

    archived = await api_schema.execute(RETRACT_ENTITY, variable_values={"input": {"id": source}}, context_value=simple_api_context)
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    assert await edges() == 0, "An edge to a node that is not there is not in the view"

    @sync_to_async
    def relation_claims() -> int:
        # Through the fold, not a column on the link — standing lives in
        # `CurrentStanding` now, so the log row cannot answer this itself.
        return claims_module.standing(
            evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.RELATION),
            "link",
        ).count()

    assert await relation_claims() == 1, "The claim that they are connected still stands — only the drawing went"

    # And a replay agrees, which is the property that says the two paths cannot
    # drift: `rebuild` declines to draw the same edge, for the same reason.
    @sync_to_async
    def rebuild() -> dict:
        return graphs.rebuild(test_graph, table_projector)

    result = await rebuild()
    assert result["edges"] == 0, "The replay must not draw an edge whose endpoint is not in the graph"
    assert await edges() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_attesting_a_retracted_entity_brings_it_back_unchanged(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """Attesting is new evidence, and it reconstructs from evidence alone.

    Nothing is remembered about what the vertex used to hold — it was destroyed.
    The node comes back because `reproject_refs` runs the same functions
    `rebuild` does, which is what makes a re-attested node and a replayed one the
    same node. If either had a path of its own they could differ, and the
    difference would be invisible until somebody reprojected.
    """
    entity_id = await _ais_with_length(api_schema, simple_api_context, test_graph, 42.0)

    before = await api_schema.execute(reads.NODE_PROPERTIES, variable_values={"id": entity_id, "graph": str(test_graph.id)}, context_value=simple_api_context)
    assert before.errors is None, f"GraphQL errors: {before.errors}"
    properties_before = before.data["node"]["properties"]
    assert properties_before.get("avg_length") == pytest.approx(42.0), "The rollup must have produced a value to compare against"

    archived = await api_schema.execute(RETRACT_ENTITY, variable_values={"input": {"id": entity_id}}, context_value=simple_api_context)
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    @sync_to_async
    def vertices() -> int:
        return _vertices(table_projector, test_graph, entity_id)

    assert await vertices() == 0

    attested = await api_schema.execute(ATTEST_ENTITY, variable_values={"input": {"id": entity_id}}, context_value=simple_api_context)
    assert attested.errors is None, f"GraphQL errors: {attested.errors}"
    assert attested.data["attestEntity"]["instance"]["id"] == entity_id
    assert attested.data["attestEntity"]["drawings"], "Attesting draws it again, and the result says where"

    assert await vertices() == 1, "The node is back, drawn from the evidence"

    after = await api_schema.execute(reads.NODE_PROPERTIES, variable_values={"id": entity_id, "graph": str(test_graph.id)}, context_value=simple_api_context)
    assert after.errors is None, f"GraphQL errors: {after.errors}"

    volatile = {"__last_derived"}
    assert {k: v for k, v in after.data["node"]["properties"].items() if k not in volatile} == {k: v for k, v in properties_before.items() if k not in volatile}, "Its derived values must be what they were, recomputed from the same metrics"

    @sync_to_async
    def claims() -> list[bool]:
        return list(evidence_models.Standing.objects.for_organization(test_graph.organization).filter(target_type="node", target_id=entity_id).order_by("at", "recorded_at").values_list("stands", flat=True))

    assert await claims() == [False, True], "Both claims stay on the record: nothing was undone, something was added"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_two_categories_can_disagree_about_whether_a_node_exists(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """The reason existence is a fold and not a flag.

    A retraction is somebody's claim, so a category whose clauses do not cover
    that claim is not bound by it (RFC 0009: the fold is per resolved category).
    Here the primitive Cell counts everyone and drops the node; rebuilt under a
    definition frozen before the retraction, the very same evidence keeps it —
    nothing rewritten.

    A cached boolean on `Node` could not express this, which is why there isn't
    one. It is also why the old `Node.status` column was the wrong shape rather
    than merely unwritten.
    """
    from asgiref.sync import sync_to_async
    from django.utils import timezone as django_timezone

    entity_id = await writes.create_entity(api_schema, simple_api_context, "Cell")
    cutoff = django_timezone.now()

    archived = await api_schema.execute(RETRACT_ENTITY, variable_values={"input": {"id": entity_id}}, context_value=simple_api_context)
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    @sync_to_async
    def vertices() -> int:
        return _vertices(table_projector, test_graph, entity_id)

    assert await vertices() == 0, "the primitive category counts the retraction, so the node goes"

    @sync_to_async
    def rebuild_frozen_before_the_retraction() -> int:
        category = core_models.EntityCategory.objects.get(graph=test_graph, key="Cell")
        category.definition = rules.definition(rules.rule(rules.word("Cell"), rules.before(cutoff)))
        category.save()
        graphs.rebuild(test_graph, table_projector)
        return _vertices(table_projector, test_graph, entity_id)

    assert await rebuild_frozen_before_the_retraction() == 1, "a category that does not count the retraction still holds the node"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_word_two_graphs_declare_is_seen_by_both(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    second_graph: core_models.Graph,
    table_projector,
) -> None:
    """One claim, two views — the reason the log names a term and not a category.

    Both graphs materialize the same schema, so both declare the word "AIS", and
    both reach the *same* `evidence.Term` for it. An entity claimed as an AIS is
    therefore in both, from one `Node` row and one `CLASSIFIES` claim.

    It used to be impossible. `Node.category` and `Link.category` pointed at a
    graph-scoped `core.Category`, so a claim belonged to whichever view happened
    to record it and the second projection could not read it however much
    vocabulary the two had in common — which quietly contradicted the axiom that
    evidence is shared across the organization.
    """
    from asgiref.sync import sync_to_async

    entity_id = await _ais_with_length(api_schema, simple_api_context, test_graph, 12.0)

    @sync_to_async
    def one_term_two_categories() -> tuple[int, int]:
        node = evidence_models.Instance.objects.for_organization(test_graph.organization).get(pk=entity_id)
        categories = core_models.Category.objects.filter(term_id=node.term_id)
        return categories.count(), categories.filter(graph__in=[test_graph, second_graph]).count()

    total, in_our_two = await one_term_two_categories()
    assert in_our_two == 2, "Both graphs must declare a category for the same word"
    assert total >= 2

    @sync_to_async
    def vertices() -> tuple[int, int]:
        return _vertices(table_projector, test_graph, entity_id), _vertices(table_projector, second_graph, entity_id)

    here, there = await vertices()
    assert here == 1, "The view the entity was created through holds it"
    assert there == 1, "And so does the other one, from the very same claim"

    # And a replay of the second graph reaches it too — it was never a copy, so
    # there is nothing for the two to drift apart about.
    @sync_to_async
    def rebuild_second() -> dict:
        return graphs.rebuild(second_graph, table_projector)

    result = await rebuild_second()
    assert result["nodes"] >= 1, "A replay of the second view reconstructs the node from the shared claim"
    assert (await vertices())[1] == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_clause_since_ignores_earlier_retractions(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """`since` is the lower half of belief time, and it scopes existence too.

    A category whose clause starts counting *after* a retraction was asserted is
    not bound by it: the fold sees no position at all, and silence means the
    node stands. The mirror of `as_of`, which recovers the belief *before* a
    retraction. Note the clause covers the classification too (RFC 0009: one
    rule), so the admitting claim has to fall inside the window as well — the
    node here is minted after the cutoff and the retraction back-dated before it.
    """
    from datetime import timedelta

    from asgiref.sync import sync_to_async
    from django.utils import timezone as django_timezone

    from tests.support import claims

    cutoff = django_timezone.now()

    @sync_to_async
    def story() -> int:
        org = test_graph.organization
        entity_id = claims.mint(org, "Cell", "late-annotator", asserted_at=cutoff + timedelta(hours=1))
        claims.retract_node(org, entity_id, "early-retractor", asserted_at=cutoff - timedelta(days=1))
        category = core_models.EntityCategory.objects.get(graph=test_graph, key="Cell")
        category.definition = rules.definition(rules.rule(rules.word("Cell"), rules.since(cutoff)))
        category.save()
        graphs.rebuild(test_graph, table_projector)
        return _vertices(table_projector, test_graph, entity_id)

    assert await story() == 1, "the retraction predates the window this category counts, so nothing says the node is absent"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_existence_folds_under_the_categorys_clauses(api_schema, simple_api_context, table_projector) -> None:
    """A retraction counts only when a clause of the node's category covers it."""
    graph_id = await _example_graph(api_schema, simple_api_context, "trust-existence")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        retracted = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        survives = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        # Peter retracting inside his clause's window counts; the same retraction
        # asserted after Dec 5 is outside every clause and counts for nothing.
        claims.retract_node(org, retracted, "peter", asserted_at=BEFORE)
        claims.retract_node(org, survives, "peter", asserted_at=AFTER)
        _rebuild(graph_id, table_projector)
        return drawing.vertices_with_ref(graph, retracted), drawing.vertices_with_ref(graph, survives)

    retracted_count, survives_count = await build_and_read()
    assert retracted_count == 0, "a covered retraction removes the node from this view"
    assert survives_count == 1, "a retraction no clause covers counts for nothing here"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_archiving_an_entity_removes_the_vertex_and_the_replay_agrees(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
):
    """A retracted entity is not in the graph, and a replay does not put it back.

    The graph carries no lifecycle state. If the evidence says a node is not
    there, it is not there — the same rule `_reproject_proposition` has always
    applied to edges, which delete rather than linger behind a flag.

    This used to assert the opposite: that the vertex survived stamped
    `archived`. Nothing filtered that flag, so a retracted entity stayed listable
    and remained a legal endpoint for new relations. And `rebuild` selected on
    `Node.status`, which nothing ever wrote — so the two paths agreed only
    because the cache was dead.

    The last assertion is the one that justifies deleting from Apache AGE at all:
    the `Node` row and its `Link` rows are untouched. Only the drawing goes.
    """
    from asgiref.sync import sync_to_async

    from evidence import models as evidence_models

    entity_category = await test_graph.aget_entity_def("AIS")

    create_mutation = """
        mutation CreateEntity($input: AssertEntityExistsInput!) {
            assertEntityExists(input: $input) { instance { id kind term { key } } }
        }
    """

    create_result = await api_schema.execute(
        create_mutation,
        variable_values={"input": {"term": entity_category.key}},
        context_value=simple_api_context,
    )

    assert create_result.errors is None, f"GraphQL errors: {create_result.errors}"
    entity_id = create_result.data["assertEntityExists"]["instance"]["id"]
    assert create_result.data["assertEntityExists"]["instance"]["term"]["key"] == "AIS"

    archive_mutation = """
        mutation ArchiveEntity($input: RetractEntityInput!) {
            retractEntity(input: $input) { instance { id } }
        }
    """

    @sync_to_async
    def vertex_count() -> int:
        return drawing.vertices_with_ref(test_graph, entity_id)

    assert await vertex_count() == 1, "The entity must be in the projection before it is retracted"

    archive_result = await api_schema.execute(
        archive_mutation,
        variable_values={"input": {"id": entity_id}},
        context_value=simple_api_context,
    )
    assert archive_result.errors is None, f"GraphQL errors: {archive_result.errors}"

    assert await vertex_count() == 0, "A retracted entity leaves no vertex behind"

    query = """
        query GetInstance($id: ID!) {
            instance(id: $id) { id drawnIn { graph { id } } }
        }
    """

    # **Reading the claim is not an error.** The retraction removed the *drawing*;
    # the claim is still in the log, which the assertions at the end of this test
    # check. A graph is a view, so "no view draws this" is an empty `drawnIn` — a
    # count, not a failed read — exactly as it is for a write under a word no view
    # declares (`docs/rfcs/0003-undrawn-nodes.md`). The claim-grain reader is
    # `instance(id:)`; `entity(id:, graph:)` is a view's answer and the view no
    # longer holds this node, which the refusal below pins.
    before = await api_schema.execute(query, variable_values={"id": entity_id}, context_value=simple_api_context)
    assert before.errors is None, f"GraphQL errors: {before.errors}"
    assert before.data["instance"]["id"] == entity_id, "The claim is readable: retraction took the drawing, not the node"
    assert before.data["instance"]["drawnIn"] == [], "And no view draws it any more"

    as_entity = await api_schema.execute(
        "query GetEntity($id: ID!, $graph: ID!) { entity(id: $id, graph: $graph) { id } }",
        variable_values={"id": entity_id, "graph": str(test_graph.id)},
        context_value=simple_api_context,
    )
    assert as_entity.errors, "A view read is that view's answer, and this view no longer holds the node"

    @sync_to_async
    def rebuild() -> dict:
        return graphs.rebuild(test_graph, table_projector)

    result = await rebuild()
    assert result["nodes"] == 0, "The replay must not recreate a node the evidence says is not there"
    assert await vertex_count() == 0, "And must not leave one in AGE either"

    after = await api_schema.execute(query, variable_values={"id": entity_id}, context_value=simple_api_context)
    assert after.errors is None, f"GraphQL errors: {after.errors}"
    assert after.data["instance"]["drawnIn"] == [], "A replay must not restore a retracted entity to any view"

    # The justification for deleting from AGE at all: the evidence is untouched.
    # Only the drawing went.
    @sync_to_async
    def evidence_survives() -> tuple[int, int, bool]:
        nodes = evidence_models.Instance.objects.for_organization(test_graph.organization).filter(pk=entity_id)
        links = evidence_models.Link.objects.for_organization(test_graph.organization).filter(source_ref=entity_id)
        claims = evidence_models.Standing.objects.for_organization(test_graph.organization).filter(target_type="node", target_id=entity_id)
        return nodes.count(), links.count(), claims.filter(stands=False).exists()

    node_count, link_count, retracted = await evidence_survives()
    assert node_count == 1, "The Node row survives — retraction is a claim, never a delete"
    assert link_count >= 1, "And so does the classification claim that says what it is"
    assert retracted, "With a claim on the record saying it no longer stands"


RETRACT_ENTITY_ID = """
    mutation R($input: RetractEntityInput!) {
        retractEntity(input: $input) { instance { id } }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_category_scoped_at_creation_does_not_count_an_unlisted_retractor(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector, backend_stack) -> None:
    """The write path folds existence under the category's clauses — no rebuild needed."""
    graph_id = await _graph_declaring(
        api_schema,
        simple_api_context,
        "SelCell",
        definition=rules.definition(rules.rule(rules.word("SelCell"), rules.by("annotator-this-view-trusts"))),
    )

    @sync_to_async
    def story():
        from evidence import models as evidence_models

        graph = core_models.Graph.objects.get(pk=graph_id)
        from tests.support import claims

        entity_id = claims.mint(graph.organization, "SelCell", "annotator-this-view-trusts")
        node = evidence_models.Instance.objects.for_organization(graph.organization).get(pk=entity_id)

        writer.retract(graph.organization, node, writer.create_assertion(graph.organization, subject="stranger", app_id="pytest"))
        graphs.rebuild(graph, table_projector)
        after_stranger = drawing.refs_with_label(graph, "SelCell")

        writer.retract(graph.organization, node, writer.create_assertion(graph.organization, subject="annotator-this-view-trusts", app_id="pytest"))
        graphs.rebuild(graph, table_projector)
        after_trusted = drawing.refs_with_label(graph, "SelCell")
        return entity_id, after_stranger, after_trusted

    entity_id, after_stranger, after_trusted = await story()
    assert after_stranger == [entity_id], "the retractor is not somebody this category counts, so its node stands"
    assert after_trusted == [], "the trusted annotator's own retraction takes it"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_as_of_clause_ignores_a_later_retraction(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector, backend_stack) -> None:
    graph_id = await _graph_declaring(api_schema, simple_api_context, "AsOfCell")
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AsOfCell")

    @sync_to_async
    def category_id():
        return str(core_models.EntityCategory.objects.get(graph_id=graph_id, key="AsOfCell").pk)

    updated = await api_schema.execute(
        writes.UPDATE_ENTITY_CATEGORY,
        variable_values={"input": {"id": await category_id(), "definition": rules.definition(rules.rule(rules.word("AsOfCell"), rules.before(django_timezone.now())))}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"

    retracted = await api_schema.execute(RETRACT_ENTITY_ID, variable_values={"input": {"id": entity_id}}, context_value=simple_api_context)
    assert retracted.errors is None

    @sync_to_async
    def drawn():
        return drawing.refs_with_label(core_models.Graph.objects.get(pk=graph_id), "AsOfCell")

    assert await drawn() == [entity_id], "the category is frozen at as_of; a retraction asserted after it is not part of what it believes"


JOHANNES = "johannes"


CHRISTIAN = "christian"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_existence_folds_per_category(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """Retracted by somebody one category counts and the other does not: the
    node keeps only the label whose rule still says it exists. No label left,
    no vertex."""

    await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def christian_retracts() -> tuple[str, set[str]]:
        node = claims.only_instance(test_graph)
        ais = graphs.define_entity(test_graph, "AIS", rules.definition(rules.rule(rules.word("AIS"))))
        graphs.define_entity(test_graph, "Excitatory", rules.definition(rules.rule(rules.word("AIS"), rules.by(JOHANNES))))
        claims.retract_classifications(test_graph, node.ref)
        claims.classify(test_graph, node.ref, ais, JOHANNES)
        claims.retract_node(test_graph.organization, node.ref, CHRISTIAN)
        graphs.rebuild(test_graph, table_projector)
        return str(node.ref), drawing.labels_of(test_graph, node.ref)

    ref, labels = await christian_retracts()
    assert labels == {"excitatory"}, "AIS counts Christian's retraction; Excitatory listens to Johannes only"

    @sync_to_async
    def johannes_retracts() -> int:
        claims.retract_node(test_graph.organization, ref, JOHANNES)
        graphs.rebuild(test_graph, table_projector)
        return drawing.vertices_with_ref(test_graph, ref)

    assert await johannes_retracts() == 0

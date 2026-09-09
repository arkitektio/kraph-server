"""Existence and edge trust through the API, at category grain (RFC 0009).

`Graph.selector` is gone. The scenarios this file pinned at graph grain survive,
respelled: a category's `definition` decides whose existence claims count for
its nodes and whose link claims draw its edges; editing the definition through
`updateEntityCategory` rebuilds the drawing before the mutation returns; there
is no `selector` field anywhere in the schema.
"""

import kante
import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone as django_timezone
from kante.context import HttpContext

from core import models as core_models
from evidence import writer
from tests.support import drawing, rules, writes
from tests.support.graphs import graph_declaring as _graph_declaring

UPDATE_ENTITY_CATEGORY = """
    mutation U($input: UpdateEntityCategoryInput!) {
        updateEntityCategory(input: $input) { id definition { rules { when { field operator value } } } }
    }
"""

RETRACT_ENTITY = """
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
        from graph_engine.controller import GraphController

        graph = core_models.Graph.objects.get(pk=graph_id)
        from tests.support import claims

        entity_id = claims.mint(graph.organization, "SelCell", "annotator-this-view-trusts")
        node = evidence_models.Instance.objects.for_organization(graph.organization).get(pk=entity_id)
        controller = GraphController(projector=table_projector)

        writer.retract(graph.organization, node, writer.create_assertion(graph.organization, subject="stranger", app_id="pytest"))
        controller.rebuild_projection(graph)
        after_stranger = drawing.refs_with_label(graph, "SelCell")

        writer.retract(graph.organization, node, writer.create_assertion(graph.organization, subject="annotator-this-view-trusts", app_id="pytest"))
        controller.rebuild_projection(graph)
        after_trusted = drawing.refs_with_label(graph, "SelCell")
        return entity_id, after_stranger, after_trusted

    entity_id, after_stranger, after_trusted = await story()
    assert after_stranger == [entity_id], "the retractor is not somebody this category counts, so its node stands"
    assert after_trusted == [], "the trusted annotator's own retraction takes it"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_updating_the_definition_reprojects_before_returning(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector, backend_stack) -> None:
    graph_id = await _graph_declaring(api_schema, simple_api_context, "UpCell")
    entity_id = await writes.create_entity(api_schema, simple_api_context, "UpCell")
    retract_cutoff = django_timezone.now()
    retracted = await api_schema.execute(RETRACT_ENTITY, variable_values={"input": {"id": entity_id}}, context_value=simple_api_context)
    assert retracted.errors is None

    @sync_to_async
    def drawn():
        return drawing.refs_with_label(core_models.Graph.objects.get(pk=graph_id), "UpCell")

    assert await drawn() == [], "a primitive category counts everyone, so the view drops the node"

    @sync_to_async
    def category_and_creator():
        from evidence import models as evidence_models

        graph = core_models.Graph.objects.get(pk=graph_id)
        creator = evidence_models.Instance.objects.for_organization(graph.organization).get(pk=entity_id).assertion.subject
        return str(core_models.EntityCategory.objects.get(graph_id=graph_id, key="UpCell").pk), creator

    category_pk, creator = await category_and_creator()
    # Trust the creator (so the classification stays admitted) plus somebody who
    # said nothing — but not the anonymous retraction's subject? The retraction
    # was made by the same request identity, so scope the clause to the creator
    # with an as_of *before* the retraction instead: same effect, no guessing.
    updated = await api_schema.execute(
        UPDATE_ENTITY_CATEGORY,
        variable_values={"input": {"id": category_pk, "definition": rules.definition(rules.rule(rules.word("UpCell"), rules.by("somebody-who-said-nothing", creator), rules.before(retract_cutoff)))}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"
    read_back = updated.data["updateEntityCategory"]["definition"]["rules"][0]["when"]
    assert {"field": "SUBJECT", "operator": "IN", "value": ["somebody-who-said-nothing", creator]} in read_back, f"the rule reads back: {read_back}"

    assert await drawn() == [entity_id], "the mutation rebuilt the drawing under the new rule — the anonymous retraction no longer counts"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_as_of_clause_ignores_a_later_retraction(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector, backend_stack) -> None:
    graph_id = await _graph_declaring(api_schema, simple_api_context, "AsOfCell")
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AsOfCell")

    @sync_to_async
    def category_id():
        return str(core_models.EntityCategory.objects.get(graph_id=graph_id, key="AsOfCell").pk)

    updated = await api_schema.execute(
        UPDATE_ENTITY_CATEGORY,
        variable_values={"input": {"id": await category_id(), "definition": rules.definition(rules.rule(rules.word("AsOfCell"), rules.before(django_timezone.now())))}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"

    retracted = await api_schema.execute(RETRACT_ENTITY, variable_values={"input": {"id": entity_id}}, context_value=simple_api_context)
    assert retracted.errors is None

    @sync_to_async
    def drawn():
        return drawing.refs_with_label(core_models.Graph.objects.get(pk=graph_id), "AsOfCell")

    assert await drawn() == [entity_id], "the category is frozen at as_of; a retraction asserted after it is not part of what it believes"


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
        from graph_engine.controller import GraphController

        controller = GraphController(projector=table_projector)
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
        controller.rebuild_projection(graph)
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
        controller.rebuild_projection(graph)
        trusted_claim = drawing.edge_count(graph, "TOUCHES")

        # An untrusted retraction of the curator's claim changes nothing here.
        curator_link = evidence_models.Link.objects.for_organization(graph.organization).filter(kind=evidence_models.Link.Kind.RELATION, term=touches.term).exclude(pk=bot_claim.pk).get()
        writer.retract(graph.organization, curator_link, writer.create_assertion(graph.organization, subject="bot", app_id="pytest"))
        controller.rebuild_projection(graph)
        untrusted_retraction = drawing.edge_count(graph, "TOUCHES")

        # The curator's own retraction takes the edge.
        writer.retract(graph.organization, curator_link, writer.create_assertion(graph.organization, subject="curator", app_id="pytest"))
        controller.rebuild_projection(graph)
        trusted_retraction = drawing.edge_count(graph, "TOUCHES")

        return untrusted_claim, trusted_claim, untrusted_retraction, trusted_retraction

    untrusted_claim, trusted_claim, untrusted_retraction, trusted_retraction = await story()
    assert untrusted_claim == 0, "a claim by somebody this category does not count draws no edge"
    assert trusted_claim == 1, "the trusted claim draws"
    assert untrusted_retraction == 1, "an untrusted retraction does not take a trusted edge"
    assert trusted_retraction == 0, "the trusted retraction does"

"""Existence semantics through the API: the selector is a mutation input now.

`Graph.selector` decides whose existence claims a view counts, and it used to be
settable only from Python. These tests pin the API surface — create with a
selector, change one and get a reprojected drawing back, read it back — and the
per-view existence fold it drives: a retraction by somebody a view does not
count leaves that view's node standing, at write time, not only after a rebuild.
The last test characterizes the deliberate asymmetry: *link* standing is
organization-wide (`CurrentStanding` folds with no selector), so link
retractions cannot be disagreed about per view.
"""

import kante
import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone as django_timezone
from kante.context import HttpContext

from core import models as core_models
from evidence import writer
from tests import drawing, writes

CREATE_GRAPH = """
    mutation G($input: CreateGraphInput!) {
        createGraph(input: $input) { id selector { assertionFilter { subjects } asOf } }
    }
"""

UPDATE_GRAPH = """
    mutation U($input: UpdateGraphInput!) {
        updateGraph(input: $input) { id selector { assertionFilter { subjects } asOf } }
    }
"""

RETRACT_ENTITY = """
    mutation R($input: RetractEntityInput!) {
        retractEntity(input: $input) { instance { id } }
    }
"""


async def _graph_declaring(api_schema, ctx, word: str, *, selector: dict | None = None) -> str:
    payload: dict = {"name": f"view-of-{word}", "definition": {"extensions": {"entities": [{"key": word}]}}}
    if selector is not None:
        payload["selector"] = selector
    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": payload}, context_value=ctx)
    assert made.errors is None, f"GraphQL errors: {made.errors}"
    return made.data["createGraph"]["id"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_view_scoped_at_creation_does_not_count_an_unlisted_retractor(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector, backend_stack) -> None:
    graph_id = await _graph_declaring(api_schema, simple_api_context, "SelCell", selector={"assertionFilter": {"subjects": ["annotator-this-view-trusts"]}})
    entity_id = await writes.create_entity(api_schema, simple_api_context, "SelCell")

    retracted = await api_schema.execute(RETRACT_ENTITY, variable_values={"input": {"id": entity_id}}, context_value=simple_api_context)
    assert retracted.errors is None, f"GraphQL errors: {retracted.errors}"

    @sync_to_async
    def drawn():
        return drawing.refs_with_label(core_models.Graph.objects.get(pk=graph_id), "SelCell")

    assert await drawn() == [entity_id], "the retractor is not somebody this view counts, so its node stands — at write time, not only after a rebuild"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_updating_the_selector_reprojects_before_returning(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector, backend_stack) -> None:
    graph_id = await _graph_declaring(api_schema, simple_api_context, "UpCell")
    entity_id = await writes.create_entity(api_schema, simple_api_context, "UpCell")
    retracted = await api_schema.execute(RETRACT_ENTITY, variable_values={"input": {"id": entity_id}}, context_value=simple_api_context)
    assert retracted.errors is None

    @sync_to_async
    def drawn():
        return drawing.refs_with_label(core_models.Graph.objects.get(pk=graph_id), "UpCell")

    assert await drawn() == [], "counting everyone, the view drops the node"

    updated = await api_schema.execute(
        UPDATE_GRAPH,
        variable_values={"input": {"id": graph_id, "selector": {"assertionFilter": {"subjects": ["somebody-who-said-nothing"]}}}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"
    assert updated.data["updateGraph"]["selector"]["assertionFilter"]["subjects"] == ["somebody-who-said-nothing"], "the scope reads back"

    assert await drawn() == [entity_id], "the mutation rebuilt the drawing under the new scope — no separate reproject call"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_as_of_bound_ignores_a_later_retraction(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector, backend_stack) -> None:
    graph_id = await _graph_declaring(api_schema, simple_api_context, "AsOfCell")
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AsOfCell")

    updated = await api_schema.execute(
        UPDATE_GRAPH,
        variable_values={"input": {"id": graph_id, "selector": {"asOf": django_timezone.now().isoformat()}}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"

    retracted = await api_schema.execute(RETRACT_ENTITY, variable_values={"input": {"id": entity_id}}, context_value=simple_api_context)
    assert retracted.errors is None

    @sync_to_async
    def drawn():
        return drawing.refs_with_label(core_models.Graph.objects.get(pk=graph_id), "AsOfCell")

    assert await drawn() == [entity_id], "the view is frozen at as_of; a retraction asserted after it is not part of what this view believes"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_link_retraction_is_organization_wide(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector, backend_stack) -> None:
    """The asymmetry, pinned as documented behavior.

    Instance existence folds per view (`resolve_categories` applies the graph's
    `claim_filter`); *claim* standing — links included — folds through
    `CurrentStanding` with no selector at all. So a relation retracted by
    somebody this view does not count still leaves its edge, in every view.
    Changing that would need a per-view standing fold, which RFC 0007 records
    as deliberately not built.
    """
    graph_id = await _graph_declaring(
        api_schema,
        simple_api_context,
        "LinkCell",
        selector={"assertionFilter": {"subjects": ["annotator-this-view-trusts"]}},
    )

    @sync_to_async
    def declare_relation():
        graph = core_models.Graph.objects.get(pk=graph_id)
        core_models.RelationCategory.objects.create(graph=graph, key="touches", age_name="TOUCHES", label="touches", source_definition={}, target_definition={})
        return graph

    graph = await declare_relation()
    a = await writes.create_entity(api_schema, simple_api_context, "LinkCell")
    b = await writes.create_entity(api_schema, simple_api_context, "LinkCell")
    link_id = await writes.create_relation(api_schema, simple_api_context, "touches", a, b)

    @sync_to_async
    def retract_link_as_untrusted_annotator_and_rebuild():
        from evidence import models as evidence_models
        from graph_engine.controller import GraphController

        link = evidence_models.Link.objects.for_organization(graph.organization).get(pk=link_id)
        assertion = writer.create_assertion(graph.organization, subject="somebody-this-view-ignores", app_id="pytest")
        writer.retract(graph.organization, link, assertion)
        GraphController(projector=table_projector).rebuild_projection(graph)
        return drawing.edge_count(graph, "TOUCHES")

    assert await retract_link_as_untrusted_annotator_and_rebuild() == 0, "link standing is organization-wide: the selector does not shield an edge, and this is deliberate"

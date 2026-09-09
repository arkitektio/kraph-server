"""A rule change redraws exactly the vertices the rule owns (A7).

The vertex is the answer, so changing the question rewrites it; a category
edit redraws its own nodes, in-request, and every assertion reads the value
back through the GraphQL surface after the mutation.

History: while the projection held only indexed properties and the API folded
the rest at query time, changing a category's properties was free, and the
`# TODO: Rematerialize` comments survived because the tests around them
checked names and shapes.
"""

import uuid
import kante
import pytest
from kante.context import HttpContext
from core import models as core_models
from asgiref.sync import sync_to_async
from django.utils import timezone as django_timezone
from tests.support import drawing, reads, rules, writes
from tests.support.graphs import graph_declaring as _graph_declaring


UPDATE_CATEGORY = """
    mutation UpdateEntityCategory($input: UpdateEntityCategoryInput!) {
        updateEntityCategory(input: $input) { id }
    }
"""
AVG_LENGTH = {"key": "avg_length", "valueKind": "FLOAT", "derivation": "ROLLUP", "rule": {"sourceNode": "ROI", "key": "vector_length", "aggregation": "MEAN"}}
MAX_LENGTH = {"key": "max_length", "valueKind": "FLOAT", "derivation": "ROLLUP", "rule": {"sourceNode": "ROI", "key": "vector_length", "aggregation": "MAX"}}
NAME = {"key": "name", "valueKind": "STRING", "derivation": "ROLLUP", "rule": {"sourceNode": "ToldYouSo", "key": "name", "aggregation": "LATEST"}}


async def _node(api_schema: kante.Schema, ctx: HttpContext, entity_id: str, graph) -> dict:
    result = await api_schema.execute(reads.NODE_PROPERTIES, variable_values={"id": entity_id, "graph": str(graph.id)}, context_value=ctx)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["node"]


async def _measured_ais(api_schema: kante.Schema, ctx: HttpContext, value: float = 40.0) -> str:
    """An `AIS` with one ROI measurement behind it, drawn into the projection."""
    created = await api_schema.execute(
        writes.ASSERT_ENTITY_EXISTS,
        variable_values={
            "input": {
                "term": "AIS",
                "supportingEvidence": [{"identifier": "ROI", "object": f"roi_{uuid.uuid4().hex[:8]}", "metrics": [{"key": "vector_length", "value": value, "valueKind": "FLOAT"}]}],
            }
        },
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertEntityExists"]["instance"]["id"]


async def _update_ais(api_schema: kante.Schema, ctx: HttpContext, category_id: int, properties: list[dict] | None = None, **extra) -> None:
    payload: dict = {"id": str(category_id), **extra}
    if properties is not None:
        payload["propertyDefinitions"] = properties

    result = await api_schema.execute(UPDATE_CATEGORY, variable_values={"input": payload}, context_value=ctx)
    assert result.errors is None, f"GraphQL errors: {result.errors}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_added_property_reaches_vertices_that_already_existed(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The case that made this task non-optional.

    Under the old split a new property needed no backfill — that was the stated
    reason for the split. Now nothing computes on read, so a property added after
    a vertex was drawn is absent from it until something redraws it, and the
    entity would answer queries as though the rule had never been written.
    """
    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").afirst()
    assert category is not None

    entity_id = await _measured_ais(api_schema, simple_api_context)
    before = (await _node(api_schema, simple_api_context, entity_id, test_graph))["properties"]
    assert before["avg_length"] == pytest.approx(40.0)
    assert "max_length" not in before, "The rule does not exist yet"

    await _update_ais(api_schema, simple_api_context, category.pk, properties=[AVG_LENGTH, NAME, MAX_LENGTH])

    after = (await _node(api_schema, simple_api_context, entity_id, test_graph))["properties"]
    assert after["max_length"] == pytest.approx(40.0), "A property added after the vertex was drawn must reach it"
    assert after["avg_length"] == pytest.approx(40.0), "And the properties that did not change must survive the redraw"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_removed_property_and_its_statistics_leave_the_vertex(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`SET` only adds, so a dropped property needs an explicit `REMOVE`.

    Otherwise a value no rule in the graph still derives stays on the vertex
    answering queries forever — and nothing would ever correct it, because the
    code that would have is exactly the code that stopped running. The statistics
    go with it: `__stat__avg_length__n` is meaningless once nothing computes
    `avg_length`.

    Note which removal is unreachable through this API.
    `EntityCategoryManager.aupdate_from_entity_definition` keeps the old
    definitions when the incoming list is empty (`property_defs or
    category.property_definitions`), so clearing the *last* property does
    nothing and the hash does not move. This drops one of two.
    """
    from graph_engine import projector

    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").afirst()
    assert category is not None

    entity_id = await _measured_ais(api_schema, simple_api_context)
    assert (await _node(api_schema, simple_api_context, entity_id, test_graph))["properties"]["avg_length"] == pytest.approx(40.0)

    # `name` stays; `avg_length` — the one with a value and statistics on the
    # vertex — goes.
    await _update_ais(api_schema, simple_api_context, category.pk, properties=[NAME])

    properties = (await _node(api_schema, simple_api_context, entity_id, test_graph))["properties"]
    assert "avg_length" not in properties, "A property no rule derives must not survive on the vertex"
    assert projector.statistic_key("avg_length", "n") not in properties, "Its statistics are as stale as the value"
    assert projector.statistic_key("avg_length", "spread") not in properties


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_redraw_stamps_the_schema_that_produced_it(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Which pins the versioning wiring and the redraw together.

    Editing a category fires `versioning`'s `post_save`, which emits a new
    `GraphSchema` before the resolver reaches the rematerialization; `project`
    then redraws under it. A vertex that did not gain the new property was not
    redrawn; `manage.py rematerialize --stale` finds its work through
    `Projection.schema_hash`, never through a stamp on the vertex.
    """
    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").afirst()
    assert category is not None

    entity_id = await _measured_ais(api_schema, simple_api_context)
    before = (await _node(api_schema, simple_api_context, entity_id, test_graph))["properties"]
    assert "max_length" not in before, "the new property does not exist yet"

    await _update_ais(api_schema, simple_api_context, category.pk, properties=[AVG_LENGTH, NAME, MAX_LENGTH])

    after = (await _node(api_schema, simple_api_context, entity_id, test_graph))["properties"]
    assert "max_length" in after, "a redrawn vertex carries what the schema that redrew it derives"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_node_that_derived_nothing_is_not_reported_stale(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The case that would make `manage.py rematerialize --stale` cry wolf.

    An entity with no measurements behind it derives no properties at all —
    `derive_properties` skips every rule whose structure kind has no evidence
    yet, which is the ordinary state of a freshly created node. `project` stamps
    `__schema_version` on it regardless, separately from the derived values, so
    "derived nothing" and "was never redrawn" stay distinguishable.

    If they were not, every empty node in the graph would report work forever,
    the cheap check would be useless, and an operator would be pushed back to a
    whole-graph `reproject` — the expensive thing `--stale` exists to avoid.
    """
    from io import StringIO

    from asgiref.sync import sync_to_async
    from django.core.management import call_command

    created = await api_schema.execute(
        writes.ASSERT_ENTITY_EXISTS,
        variable_values={"input": {"term": "Cell"}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"

    out = StringIO()
    await sync_to_async(call_command)("rematerialize", graph=test_graph.name, stale=True, dry_run=True, stdout=out)

    assert out.getvalue() == "", "A node that derived nothing is projected, not behind"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_relabelling_a_category_redraws_nothing(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The common edit must stay cheap.

    Most `updateEntityCategory` calls are presentation — a label, a colour, a
    description. None of that reaches a vertex, and the redraw is unbounded in
    the size of the graph, so the hash comparison in `_rematerialize` has to
    short-circuit rather than sweeping every vertex on a rename.
    """
    from api.mutations.schema import _rematerialize
    from asgiref.sync import sync_to_async

    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").afirst()
    assert category is not None

    await _measured_ais(api_schema, simple_api_context)

    fingerprint = await sync_to_async(_rematerialize.fingerprint)(category)
    await _update_ais(api_schema, simple_api_context, category.pk, label="Axon Initial Segment")

    reloaded = await core_models.EntityCategory.objects.aget(pk=category.pk)
    assert reloaded.label == "Axon Initial Segment", "The relabelling itself must land"
    assert await sync_to_async(_rematerialize.rematerialize_if_moved)(reloaded, fingerprint) == 0, "An edit that touches no rule must redraw nothing"


RETRACT_ENTITY = """
    mutation R($input: RetractEntityInput!) {
        retractEntity(input: $input) { instance { id } }
    }
"""


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
        writes.UPDATE_ENTITY_CATEGORY,
        variable_values={"input": {"id": category_pk, "definition": rules.definition(rules.rule(rules.word("UpCell"), rules.by("somebody-who-said-nothing", creator), rules.before(retract_cutoff)))}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"
    read_back = updated.data["updateEntityCategory"]["definition"]["rules"][0]["when"]
    assert {"field": "SUBJECT", "operator": "IN", "value": ["somebody-who-said-nothing", creator]} in read_back, f"the rule reads back: {read_back}"

    assert await drawn() == [entity_id], "the mutation rebuilt the drawing under the new rule — the anonymous retraction no longer counts"

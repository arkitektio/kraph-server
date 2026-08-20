"""A node list is a list of claims, and a node's kind is a fact about the claim.

Both used to come out of the projection, and both were wrong in the same direction —
the drawing was treated as the source rather than as the cache.

**Kind.** `RetrievedNode.node_type` fell back to matching the vertex *label* against
five fixed vocabulary words. A drawn vertex is labelled `category.age_name` ("Cell",
"Mitosis"), one view's rename of a word, so the match never hit and the default sent
everything to `"ENTITY"`: `node(id:)` reported a natural event as an `Entity`, and so
did every write's `drawings { node }`. It is read from `Node.kind` now, which
`create_vertex` writes onto the vertex as `type`.

**Membership.** The category-scoped lists ran `MATCH (n) WHERE n.category_id = $id`
in `category.graph`, so they answered "what has this view drawn" rather than "what
does this view's rule admit". A claim the projection had not caught up with was
missing from the list and appeared after a rebuild, with nothing about the claim
explaining the difference. They read `evidence.Node` now, through
`projector.refs_admitted_by` — the same function that decides which vertices get
drawn.
"""

import pytest
import kante
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from tests import writes

NODE_BY_ID = """
    query GetNode($id: ID!, $graph: ID!) {
        node(id: $id, graph: $graph) { __typename id }
    }
"""

ENTITIES = """
    query Entities($id: ID!, $filters: EntityFilter) {
        entities(entityCategoryId: $id, filters: $filters) { id }
    }
"""

NODES_IN_GRAPH = """
    query Nodes($graph: ID!) {
        nodes(graph: $graph) { __typename id }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_drawn_event_is_typed_as_an_event(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`node(id:, graph:)` on a natural event answers `NaturalEvent`, not `Entity`."""
    event_id = await writes.create_event(api_schema, simple_api_context, "Mitosis")

    read = await api_schema.execute(NODE_BY_ID, variable_values={"id": event_id, "graph": str(test_graph.id)}, context_value=simple_api_context)

    assert read.errors is None, f"GraphQL errors: {read.errors}"
    assert read.data["node"]["__typename"] == "NaturalEvent", "The kind comes from the claim; the label is the view's rename of a word"
    assert read.data["node"]["id"] == event_id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_claim_the_projection_has_not_drawn_is_still_listed(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """The list is the rule's answer, so a projection that is behind does not hide a claim.

    The vertex is deleted directly, which is what a projection lagging the log looks
    like — no retraction, no claim withdrawn, just a cache that has not caught up.
    Before this, the entity vanished from `entities(...)` until somebody reprojected.
    """
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS")
    category = await test_graph.aget_entity_def("AIS")

    listed_before = await api_schema.execute(ENTITIES, variable_values={"id": str(category.pk)}, context_value=simple_api_context)
    assert listed_before.errors is None, f"GraphQL errors: {listed_before.errors}"
    assert entity_id in {entity["id"] for entity in listed_before.data["entities"]}

    @sync_to_async
    def undraw() -> int:
        age_engine.execute(test_graph, f"MATCH (e:{category.age_name}) WHERE e.id = $eid DETACH DELETE e", {"eid": entity_id})
        rows = age_engine.execute(test_graph, f"MATCH (e:{category.age_name}) WHERE e.id = $eid RETURN count(e) as c", {"eid": entity_id})
        return int(rows[0]["c"]) if rows else 0

    assert await undraw() == 0, "The vertex is gone, and no claim was withdrawn"

    listed_after = await api_schema.execute(ENTITIES, variable_values={"id": str(category.pk)}, context_value=simple_api_context)
    assert listed_after.errors is None, f"GraphQL errors: {listed_after.errors}"
    assert entity_id in {entity["id"] for entity in listed_after.data["entities"]}, "The claim is what the category admits; the vertex is only how this view draws it"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_property_filters_are_refused_rather_than_ignored(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """A filter over derived properties is a question about a drawing, so it is refused.

    The refusal moved from the resolver to the schema: `EntityFilter` no longer
    carries `search`/`hasProperty`/`matches` at all, so the question cannot be
    asked. A claim carries no derived properties, and a node no view has drawn
    has none at all — quietly narrowing the list by what happens to be cached
    would be a wrong answer that looks right, and advertising an argument every
    call refused was the runtime version of the same lie.
    """
    category = await test_graph.aget_entity_def("AIS")

    refused = await api_schema.execute(
        ENTITIES,
        variable_values={"id": str(category.pk), "filters": {"search": "anything"}},
        context_value=simple_api_context,
    )

    assert refused.errors, "A property filter over a claim list must be refused"
    assert "search" in str(refused.errors[0]), f"Refused for the wrong reason: {refused.errors[0]}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_nodes_in_a_graph_are_not_only_entities(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`nodes(graph:)` means nodes.

    It was `list_entities`, which matched vertices labelled with one of the graph's
    *entity* categories — so an event drawn in the very same view never appeared in
    the list of that view's nodes.
    """
    entity_id = await writes.create_entity(api_schema, simple_api_context, "Cell")
    event_id = await writes.create_event(api_schema, simple_api_context, "Mitosis")

    listed = await api_schema.execute(NODES_IN_GRAPH, variable_values={"graph": str(test_graph.pk)}, context_value=simple_api_context)

    assert listed.errors is None, f"GraphQL errors: {listed.errors}"
    by_id = {node["id"]: node["__typename"] for node in listed.data["nodes"]}
    assert by_id.get(entity_id) == "Entity"
    assert by_id.get(event_id) == "NaturalEvent", "An event in the view is one of the view's nodes"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_listing_another_tenants_category_is_refused(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`entities(entityCategoryId:)` authorizes, which it did not.

    It fetched the category by bare primary key and relied on
    `GraphController._ensure_query_access` — a stub that returned unconditionally — so
    any member of any tenant could list another organization's entities by guessing an
    integer. Its sibling event lists checked; this one never had.
    """
    from authentikate.models import Membership, Organization

    @sync_to_async
    def foreign_category() -> int:
        other, _ = Organization.objects.get_or_create(slug="a-tenant-next-door")
        membership = Membership.objects.filter(organization=other).first()
        if membership is None:
            membership = Membership.objects.create(user=test_graph.membership.user, organization=other)
        graph = core_models.Graph.objects.create(
            name="NextDoor",
            membership=membership,
            organization=other,
            user=test_graph.user,
        )
        category = core_models.EntityCategory.objects.create(graph=graph, key="AIS", label="AIS", age_name="AIS")
        return category.pk

    category_id = await foreign_category()

    refused = await api_schema.execute(ENTITIES, variable_values={"id": str(category_id)}, context_value=simple_api_context)

    assert refused.errors, "Listing a category belonging to another organization must be refused"
    assert "not allowed" in str(refused.errors[0]).lower(), f"Refused for the wrong reason: {refused.errors[0]}"

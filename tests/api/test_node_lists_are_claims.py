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
from tests import drawing, writes

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
    query Nodes($graph: ID!, $filters: NodeFilters) {
        nodes(graph: $graph, filters: $filters) { __typename id }
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
    table_projector,
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
        table_projector.erase_nodes(test_graph, [entity_id])
        return drawing.vertices_with_ref(test_graph, entity_id)

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
    carries `hasProperty`/`matches` at all, so the question cannot be asked. A claim
    carries no derived properties, and a node no view has drawn has none at all —
    quietly narrowing the list by what happens to be cached would be a wrong answer
    that looks right, and advertising an argument every call refused was the runtime
    version of the same lie.

    `search` was refused here too, while it meant full-text over those same
    properties. It means the claim's own word now and is answered rather than
    refused — see `test_search_narrows_by_the_claims_own_word`.
    """
    category = await test_graph.aget_entity_def("AIS")

    refused = await api_schema.execute(
        ENTITIES,
        variable_values={"id": str(category.pk), "filters": {"hasProperty": "avg_length"}},
        context_value=simple_api_context,
    )

    assert refused.errors, "A property filter over a claim list must be refused"
    assert "hasProperty" in str(refused.errors[0]), f"Refused for the wrong reason: {refused.errors[0]}"


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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_search_narrows_by_the_claims_own_word(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`search` reads `Term.key`, so it narrows a claim list without asking the drawing.

    It used to mean full-text over a vertex's derived properties and was refused
    alongside `hasProperty` and `matches`. A term is a column of the log — the word
    the organization uses — so this is the same kind of question as ordering by
    `created_at`, and it is answerable at claim grain.
    """
    cell_id = await writes.create_entity(api_schema, simple_api_context, "Cell")
    ais_id = await writes.create_entity(api_schema, simple_api_context, "AIS")

    listed = await api_schema.execute(
        NODES_IN_GRAPH,
        variable_values={"graph": str(test_graph.pk), "filters": {"search": "Cell"}},
        context_value=simple_api_context,
    )

    assert listed.errors is None, f"GraphQL errors: {listed.errors}"
    found = {node["id"] for node in listed.data["nodes"]}
    assert cell_id in found, "The claim whose word matches is in the list"
    assert ais_id not in found, "A claim of a different word is not"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_search_finds_a_claim_the_projection_has_not_drawn(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """The search is over the log, so a projection that is behind does not hide a match.

    This is the property that makes `search` safe to answer where `hasProperty` and
    `matches` are not: a filter reading `Term.key` gives the same answer whether or
    not the view has drawn the node, and survives a reproject. A search that only
    found drawn vertices would be the refused behaviour wearing a new name.
    """
    cell_id = await writes.create_entity(api_schema, simple_api_context, "Cell")
    category = await test_graph.aget_entity_def("Cell")

    @sync_to_async
    def undraw() -> int:
        table_projector.erase_nodes(test_graph, [cell_id])
        return drawing.vertices_with_ref(test_graph, cell_id)

    assert await undraw() == 0, "The vertex is gone, and no claim was withdrawn"

    listed = await api_schema.execute(
        NODES_IN_GRAPH,
        variable_values={"graph": str(test_graph.pk), "filters": {"search": "Cell"}},
        context_value=simple_api_context,
    )

    assert listed.errors is None, f"GraphQL errors: {listed.errors}"
    assert cell_id in {node["id"] for node in listed.data["nodes"]}, "The word is the claim's, not the drawing's"

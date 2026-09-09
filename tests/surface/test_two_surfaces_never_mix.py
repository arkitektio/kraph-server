"""Two surfaces, never mixed silently (RFC 0025, C4).

A `Node` is one view's drawing of an individual: it names its view, the log
position it is as of, and the claim beneath it, and it answers its categories
from the view's rule rather than from the cache. Everything reached through an
edge's endpoint is a claim, because an edge carries no view.
"""

import pytest
from asgiref.sync import sync_to_async
from tests.support import drawing, graphs, reads, writes
import kante
from kante.context import HttpContext
from core import models as core_models
import uuid


NODE = """
    query N($id: ID!, $graph: ID!) {
        node(id: $id, graph: $graph) { id graph { id projection { projectedThroughSeq } } asOfSeq claim { id kind } ... on Entity { categoryIds } }
    }
"""
RELATION = """
    query R($id: ID!) {
        relation(id: $id) { id label category { id } source { __typename id drawnIn { graph { id } } } target { __typename id } }
    }
"""
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_node_names_its_view_its_position_and_its_claim(api_schema, simple_api_context, test_graph, table_projector) -> None:
    entity = await writes.create_entity(api_schema, simple_api_context, "AIS")

    read = await api_schema.execute(NODE, variable_values={"id": entity, "graph": str(test_graph.pk)}, context_value=simple_api_context)
    assert read.errors is None, f"GraphQL errors: {read.errors}"
    node = read.data["node"]
    assert node["graph"]["id"] == str(test_graph.pk)
    assert node["asOfSeq"] == node["graph"]["projection"]["projectedThroughSeq"], "as-of is the view's cursor"
    assert node["claim"] == {"id": entity, "kind": "ENTITY"}
    drawn_categories = node["categoryIds"]
    assert drawn_categories, "the rule admits it"

    # Behind the log: the vertex is gone, the rule still answers.
    await sync_to_async(table_projector.erase_nodes)(test_graph, [entity])
    assert await sync_to_async(drawing.vertices_with_ref)(test_graph, entity) == 0
    read = await api_schema.execute(NODE, variable_values={"id": entity, "graph": str(test_graph.pk)}, context_value=simple_api_context)
    assert read.errors is None, f"GraphQL errors: {read.errors}"
    assert read.data["node"]["categoryIds"] == drawn_categories, "categories come from the rule, not from the cache"
    assert read.data["node"]["graph"]["id"] == str(test_graph.pk)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_edge_reached_without_a_view_is_a_claim_with_claim_endpoints(api_schema, simple_api_context, test_graph) -> None:
    a = await writes.create_entity(api_schema, simple_api_context, "AIS")
    b = await writes.create_entity(api_schema, simple_api_context, "Cell")
    link = await writes.create_relation(api_schema, simple_api_context, "PART_OF", a, b)

    read = await api_schema.execute(RELATION, variable_values={"id": link}, context_value=simple_api_context)
    assert read.errors is None, f"GraphQL errors: {read.errors}"
    relation = read.data["relation"]
    assert relation["category"] is None, "no view was named, so no category is borrowed from one"
    assert relation["label"] == "relation", "the claim's kind, not one view's label"
    assert relation["source"]["__typename"] == "Instance" and relation["target"]["__typename"] == "Instance"
    assert relation["source"]["id"] == a
    assert [d["graph"]["id"] for d in relation["source"]["drawnIn"]] == [str(test_graph.pk)], "the claim says which views draw it"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_top_level_node_carries_no_borrowed_category(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Even when a view *does* draw it, the payload names no category.

    The claim is one thing and the several ways views draw it are another. A
    category belongs to a view, so the only honest place for one is inside a
    drawing — which is where every real category now is.

    It used to be a **null** `categoryId` on a graph-shaped payload. An `Instance` has
    no such field to be null: the claim names a word (`term`), and what a view makes
    of that word is the drawing's business.
    """
    result = await api_schema.execute(
        """
        mutation AssertEntityExists($input: AssertEntityExistsInput!) {
            assertEntityExists(input: $input) {
                instance { id term { key } }
                drawings { category { id } }
            }
        }
        """,
        variable_values={"input": {"term": "AIS", "supportingEvidence": []}},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    payload = result.data["assertEntityExists"]

    assert payload["instance"]["term"]["key"] == "AIS", "The claim names a word, not a view's rule for one"
    assert payload["drawings"], "while the view that drew it reports its category"
    assert payload["drawings"][0]["category"]["id"], "which is a real category"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_node_interface_fields_resolve_for_a_structure(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """None of the inherited identity fields may raise."""
    structure_id = await writes.create_structure(api_schema, simple_api_context, identifier="roi_test")

    result = await api_schema.execute(
        """
        query Structure($id: ID!) {
            structure(id: $id) {
                id
                identifier
                object
            }
        }
        """,
        variable_values={"id": structure_id},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    payload = result.data["structure"]
    assert payload["id"] == structure_id, "The primary key is the identity — there is no second, global one"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_drawn_in_names_exactly_the_views_a_node_read_accepts(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """RFC 0025: `Instance.drawnIn` lists the views that draw a claim, and
    `node(id:, graph:)` answers for exactly those — a view that does not draw it
    refuses the read rather than answering from another view's drawing."""
    node = await writes.create_entity(api_schema, simple_api_context, "Cell")
    elsewhere = await graphs.graph_declaring(api_schema, simple_api_context, f"Nothing_{uuid.uuid4().hex[:6]}")

    drawn_in = (await writes.execute(api_schema, simple_api_context, reads.DRAWN_IN, {"id": node}))["instance"]["drawnIn"]
    assert sorted(entry["graph"]["id"] for entry in drawn_in) == [str(test_graph.pk)]

    for entry in drawn_in:
        answered = await writes.execute(api_schema, simple_api_context, reads.NODE, {"id": node, "graph": entry["graph"]["id"]})
        assert answered["node"]["id"] == node

    refused = await api_schema.execute(reads.NODE, variable_values={"id": node, "graph": elsewhere}, context_value=simple_api_context)
    assert refused.errors, "a view that does not draw the node refuses the read"

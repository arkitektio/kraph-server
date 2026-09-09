"""Two surfaces, never mixed silently (RFC 0025).

A `Node` is one view's drawing of an individual: it names its view, the log
position it is as of, and the claim beneath it, and it answers its categories
from the view's rule rather than from the cache. Everything reached through an
edge's endpoint is a claim — an `Instance` — because an edge does not carry a
view a `Node` could be drawn in.
"""

import pytest
from asgiref.sync import sync_to_async

from tests.support import drawing, writes

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

NODES_BY_SEQ = """
    query L($graph: ID!) { nodes(graph: $graph, ordering: [{seq: DESC}]) { id } }
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
async def test_claim_lists_order_by_the_logs_own_order(api_schema, simple_api_context, test_graph) -> None:
    first = await writes.create_entity(api_schema, simple_api_context, "AIS")
    second = await writes.create_entity(api_schema, simple_api_context, "AIS")

    read = await api_schema.execute(NODES_BY_SEQ, variable_values={"graph": str(test_graph.pk)}, context_value=simple_api_context)
    assert read.errors is None, f"GraphQL errors: {read.errors}"
    ids = [row["id"] for row in read.data["nodes"]]
    assert ids.index(second) < ids.index(first), "the later act comes first under seq DESC"

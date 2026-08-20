"""Drawing a node twice leaves one vertex.

`create_vertex` was a bare Cypher `CREATE`, so `reproject_node` on an already
drawn node — `attest_node` on a standing node, `project_all` over a populated
namespace — duplicated it, while `project_all`'s docstring promised it was
"MERGE-shaped throughout". It is now: `create_vertex` merges on the id, and
`reproject_node` clears the old vertex first so a node whose label moved does not
leave its previous self under the previous label.
"""

import pytest
from asgiref.sync import sync_to_async

from core import models as core_models
from evidence import models as evidence_models
from graph_engine import projector
from graph_engine.controller import GraphController
from tests import writes


def _vertices_with_id(age_engine, graph: core_models.Graph, ref: str) -> int:
    rows = age_engine.execute(graph, "MATCH (e) WHERE e.id = $ref RETURN count(e) as c", {"ref": ref})
    return int(rows[0]["c"]) if rows else 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_reproject_node_twice_is_one_vertex(api_schema, simple_api_context, test_graph: core_models.Graph, age_engine) -> None:
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS", evidence=[{"identifier": "ROI", "object": "roi-1", "metrics": [{"key": "vector_length", "value": 12.0, "valueKind": "FLOAT"}]}])

    @sync_to_async
    def redraw_twice() -> int:
        controller = GraphController(engine=age_engine)
        node = evidence_models.Instance.objects.for_organization(test_graph.organization).select_related("term").get(pk=entity_id)
        projector.reproject_node(controller, test_graph, node)
        projector.reproject_node(controller, test_graph, node)
        return _vertices_with_id(age_engine, test_graph, entity_id)

    assert await redraw_twice() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_project_all_over_a_populated_namespace_converges(api_schema, simple_api_context, test_graph: core_models.Graph, age_engine) -> None:
    a = await writes.create_entity(api_schema, simple_api_context, "AIS")
    b = await writes.create_entity(api_schema, simple_api_context, "AIS")
    await writes.create_relation(api_schema, simple_api_context, "IS_CONNECTED_TO", a, b)

    @sync_to_async
    def count_after_two_passes() -> tuple[int, int, int]:
        controller = GraphController(engine=age_engine)
        projector.project_all(controller, test_graph)
        projector.project_all(controller, test_graph)
        vertices = age_engine.execute(test_graph, "MATCH (e) RETURN count(e) as c", {})
        edges = age_engine.execute(test_graph, "MATCH ()-[r]->() RETURN count(r) as c", {})
        return _vertices_with_id(age_engine, test_graph, a), int(vertices[0]["c"]), int(edges[0]["c"])

    one, vertices, edges = await count_after_two_passes()
    assert one == 1
    assert vertices == 2
    assert edges == 1

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
from tests import drawing, writes


def _vertices_with_id(table_projector, graph: core_models.Graph, ref: str) -> int:
    return drawing.vertices_with_ref(graph, ref)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_reproject_node_twice_is_one_vertex(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector) -> None:
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS", evidence=[{"identifier": "ROI", "object": "roi-1", "metrics": [{"key": "vector_length", "value": 12.0, "valueKind": "FLOAT"}]}])

    @sync_to_async
    def redraw_twice() -> int:
        controller = GraphController(projector=table_projector)
        node = evidence_models.Instance.objects.for_organization(test_graph.organization).select_related("term").get(pk=entity_id)
        projector.reproject_node(controller, test_graph, node)
        projector.reproject_node(controller, test_graph, node)
        return _vertices_with_id(table_projector, test_graph, entity_id)

    assert await redraw_twice() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_project_all_over_a_populated_namespace_converges(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector) -> None:
    a = await writes.create_entity(api_schema, simple_api_context, "AIS")
    b = await writes.create_entity(api_schema, simple_api_context, "AIS")
    await writes.create_relation(api_schema, simple_api_context, "IS_CONNECTED_TO", a, b)

    @sync_to_async
    def count_after_two_passes() -> tuple[int, int, int]:
        controller = GraphController(projector=table_projector)
        projector.project_all(controller, test_graph)
        projector.project_all(controller, test_graph)
        return _vertices_with_id(table_projector, test_graph, a), drawing.vertex_count(test_graph), drawing.edge_count(test_graph)

    one, vertices, edges = await count_after_two_passes()
    assert one == 1
    assert vertices == 2
    assert edges == 1

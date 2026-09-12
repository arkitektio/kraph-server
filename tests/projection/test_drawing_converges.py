"""Drawing converges: drawing a node twice leaves one vertex (A7).

`draw_node` is an upsert on `(graph, ref)` and `reproject_refs` erases first,
so a node whose label moved does not leave its previous self behind.
"""

import pytest
from asgiref.sync import sync_to_async
from core import models as core_models
from graph_engine import projector
from graph_engine.controller import GraphController
from tests.support import drawing, writes


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_reproject_refs_twice_is_one_vertex(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector) -> None:
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS", evidence=[{"identifier": "ROI", "object": "roi-1", "metrics": [{"key": "vector_length", "value": 12.0, "valueKind": "FLOAT"}]}])

    @sync_to_async
    def redraw_twice() -> int:
        controller = GraphController(projector=table_projector)
        projector.reproject_refs(controller, test_graph, [entity_id])
        projector.reproject_refs(controller, test_graph, [entity_id])
        return drawing.vertices_with_ref(test_graph, entity_id)

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
        return drawing.vertices_with_ref(test_graph, a), drawing.vertex_count(test_graph), drawing.edge_count(test_graph)

    one, vertices, edges = await count_after_two_passes()
    assert one == 1
    assert vertices == 2
    assert edges == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_redrawing_a_merged_individual_converges(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector) -> None:
    """`reproject_refs` through any member, twice, leaves one vertex with all its members."""
    a = await writes.create_entity(api_schema, simple_api_context, "AIS")
    b = await writes.create_entity(api_schema, simple_api_context, "AIS")
    await writes.merge(api_schema, simple_api_context, [a, b])

    @sync_to_async
    def redraw():
        controller = GraphController(projector=table_projector)
        projector.reproject_refs(controller, test_graph, [a])
        projector.reproject_refs(controller, test_graph, [b])
        projector.project_all(controller, test_graph)
        return drawing.vertex_count(test_graph, "AIS"), drawing.members_of(test_graph, a)

    assert await redraw() == (1, sorted([a, b]))

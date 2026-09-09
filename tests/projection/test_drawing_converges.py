"""Drawing a node twice leaves one vertex.

`create_vertex` was a bare Cypher `CREATE`, so redrawing an already drawn node —
`attest_node` on a standing node, `project_all` over a populated namespace —
duplicated it, while `project_all`'s docstring promised it was "MERGE-shaped
throughout". It is now: `create_vertex` merges on the id, and `reproject_refs`
erases the old vertex first so a node whose label moved does not leave its
previous self under the previous label.
"""

import pytest
from asgiref.sync import sync_to_async
from core import models as core_models
from graph_engine import projector
from graph_engine.controller import GraphController
from tests.support import drawing, writes
from tests.support.writes import ASSERT_SAME


def _vertices_with_id(table_projector, graph: core_models.Graph, ref: str) -> int:
    return drawing.vertices_with_ref(graph, ref)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_reproject_refs_twice_is_one_vertex(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector) -> None:
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS", evidence=[{"identifier": "ROI", "object": "roi-1", "metrics": [{"key": "vector_length", "value": 12.0, "valueKind": "FLOAT"}]}])

    @sync_to_async
    def redraw_twice() -> int:
        controller = GraphController(projector=table_projector)
        projector.reproject_refs(controller, test_graph, [entity_id])
        projector.reproject_refs(controller, test_graph, [entity_id])
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


async def _execute(api_schema, ctx, document: str, variables: dict) -> dict:
    result = await api_schema.execute(document, variable_values=variables, context_value=ctx)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data


async def _merge(api_schema, ctx, refs: list[str]) -> str:
    data = await _execute(api_schema, ctx, ASSERT_SAME, {"input": {"instances": refs}})
    return data["assertSameInstance"]["links"][0]["id"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_redrawing_a_merged_individual_converges(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector) -> None:
    """`reproject_refs` through any member, twice, leaves one vertex with all its members."""
    a = await writes.create_entity(api_schema, simple_api_context, "AIS")
    b = await writes.create_entity(api_schema, simple_api_context, "AIS")
    await _merge(api_schema, simple_api_context, [a, b])

    @sync_to_async
    def redraw():
        controller = GraphController(projector=table_projector)
        projector.reproject_refs(controller, test_graph, [a])
        projector.reproject_refs(controller, test_graph, [b])
        projector.project_all(controller, test_graph)
        return drawing.vertex_count(test_graph, "AIS"), drawing.members_of(test_graph, a)

    assert await redraw() == (1, sorted([a, b]))

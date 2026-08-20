"""Rendering a saved table query through the projector.

A plan is compiled by the projection kind in use and executed with the render
filter/order/page applied *structurally*; a legacy raw-Cypher row still renders,
but takes none of those.
"""

import pytest

from core import models as core_models
from graph_engine import input_models
from tests import writes


def test_a_legacy_raw_cypher_row_still_renders_but_takes_no_filter(graph_controller, test_graph: core_models.Graph) -> None:
    graph_query = core_models.GraphTableQuery.objects.create(graph=test_graph, key="legacy_render", label="Legacy", query="RETURN 1 AS value", columns=[{"key": "value", "type": "integer", "value_kind": "INT"}])

    rendered = graph_controller.render_graph_table_query(graph_query)
    assert rendered.graph_name == str(test_graph.age_name)
    assert len(rendered.rows) == 1 and rendered.rows[0]["value"] == 1

    with pytest.raises(ValueError, match="legacy"):
        graph_controller.render_graph_table_query(graph_query, order=input_models.RenderGraphTableOrder(key="value", direction="desc"))


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_plan_renders_with_a_structural_filter_order_and_page(api_schema, simple_api_context, graph_controller, test_graph: core_models.Graph) -> None:
    from asgiref.sync import sync_to_async

    for value in (10.0, 30.0, 20.0):
        await writes.create_entity(api_schema, simple_api_context, "AIS", evidence=[{"identifier": "ROI", "object": f"roi-{value}", "metrics": [{"key": "vector_length", "value": value, "valueKind": "FLOAT"}]}])

    @sync_to_async
    def render():
        from graph_engine.query_ir import TableQueryPlan

        plan = TableQueryPlan(
            matches=[input_models.MatchPathInput(title="p", nodes=["ais"], relations=[], node_categories=["AIS"])],
            returns=[input_models.ReturnStatementInput(path="p", node="ais", property="avg_length", alias="length"), input_models.ReturnStatementInput(path="p", node="ais", property="id", alias="node_id")],
        )
        graph_query = core_models.GraphTableQuery.objects.create(graph=test_graph, key="lengths", label="Lengths", plan=plan.to_stored(), columns=[{"key": "length", "type": "float"}])
        everything = graph_controller.render_graph_table_query(graph_query, order=input_models.RenderGraphTableOrder(key="length", direction="desc"))
        filtered = graph_controller.render_graph_table_query(
            graph_query,
            filters=input_models.RenderGraphTableFilter(key="length", operator=input_models.WhereOperator.GREATER_THAN, value=15),
            order=input_models.RenderGraphTableOrder(key="length", direction="asc"),
            pagination=input_models.RenderGraphTablePagination(limit=1, offset=0),
        )
        return [row["length"] for row in everything.rows], [row["length"] for row in filtered.rows]

    everything, filtered = await render()
    assert everything == [30.0, 20.0, 10.0]
    assert filtered == [20.0], "the filter applies to the returned alias — the case the old regex splice could never do"

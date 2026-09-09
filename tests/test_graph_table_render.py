"""Rendering a saved table query through the projector.

A plan is compiled by the projection kind in use and executed with the render
filter/order/page applied *structurally*; a legacy raw-Cypher row cannot render
at all — no projection kind executes Cypher.
"""

import pytest

from core import models as core_models
from graph_engine import input_models
from tests.support import writes


def test_a_legacy_raw_cypher_row_is_refused(graph_controller, test_graph: core_models.Graph) -> None:
    graph_query = core_models.GraphTableQuery.objects.create(graph=test_graph, key="legacy_render", label="Legacy", query="RETURN 1 AS value", columns=[{"key": "value", "type": "integer", "value_kind": "INT"}])

    with pytest.raises(ValueError, match="legacy"):
        graph_controller.render_graph_table_query(graph_query)


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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_relation_path_renders_through_the_namespace(api_schema, simple_api_context, graph_controller, test_graph: core_models.Graph) -> None:
    """A two-node path is one GRAPH_TABLE pattern with label dispatch."""
    from asgiref.sync import sync_to_async

    from tests.support import writes as writes_module

    cell_a = await writes_module.create_entity(api_schema, simple_api_context, "Cell")
    cell_b = await writes_module.create_entity(api_schema, simple_api_context, "Cell")
    await writes_module.create_relation(api_schema, simple_api_context, "IS_CONNECTED_TO", cell_a, cell_b)

    @sync_to_async
    def render():
        from graph_engine.query_ir import TableQueryPlan

        plan = TableQueryPlan(
            matches=[input_models.MatchPathInput(title="p", nodes=["a", "b"], relations=["IS_CONNECTED_TO"], relation_directions=[True], node_categories=["Cell", "Cell"])],
            returns=[input_models.ReturnStatementInput(path="p", node="a", property="id", alias="source_id"), input_models.ReturnStatementInput(path="p", node="b", property="id", alias="target_id")],
        )
        graph_query = core_models.GraphTableQuery.objects.create(graph=test_graph, key="connections", label="Connections", plan=plan.to_stored(), columns=[{"key": "source_id", "type": "string"}, {"key": "target_id", "type": "string"}])
        return graph_controller.render_graph_table_query(graph_query).rows

    rows = await render()
    assert [(row["source_id"], row["target_id"]) for row in rows] == [(cell_a, cell_b)], "the edge renders in its drawn direction, and only under its labels"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_optional_path_null_fills_like_optional_match(api_schema, simple_api_context, graph_controller, test_graph: core_models.Graph) -> None:
    """An optional path is a LEFT JOIN of its own GRAPH_TABLE: unmatched rows stay, with nulls."""
    from asgiref.sync import sync_to_async

    from tests.support import writes as writes_module

    await writes_module.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def render():
        from graph_engine.query_ir import TableQueryPlan

        plan = TableQueryPlan(
            matches=[
                input_models.MatchPathInput(title="p", nodes=["ais"], relations=[], node_categories=["AIS"]),
                input_models.MatchPathInput(title="q", nodes=["soma"], relations=[], node_categories=["Soma"], optional=True),
            ],
            returns=[input_models.ReturnStatementInput(path="p", node="ais", property="id", alias="ais_id"), input_models.ReturnStatementInput(path="q", node="soma", property="id", alias="soma_id")],
        )
        graph_query = core_models.GraphTableQuery.objects.create(graph=test_graph, key="optional", label="Optional", plan=plan.to_stored(), columns=[{"key": "ais_id", "type": "string"}, {"key": "soma_id", "type": "string"}])
        return graph_controller.render_graph_table_query(graph_query).rows

    rows = await render()
    assert len(rows) == 1
    assert rows[0]["ais_id"] is not None
    assert rows[0]["soma_id"] is None, "no Soma is drawn, so the optional path fills with null instead of dropping the row"

import pytest

from core import models as core_models
from graph_engine import input_models


@pytest.mark.django_db(transaction=True)
def test_render_graph_table_query_returns_rows(graph_controller, test_graph: core_models.Graph):
    graph_query = core_models.GraphTableQuery.objects.create(
        graph=test_graph,
        key="literal_table",
        name="Literal Table",
        description="simple literal query",
        kind="TABLE",
        query="RETURN 1 AS value",
        columns=[{"key": "value", "type": "integer", "value_kind": "INT"}],
    )

    rendered = graph_controller.render_graph_table_query(graph_query)

    assert rendered.graph_name == str(test_graph.age_name)
    assert len(rendered.rows) == 1
    assert rendered.rows[0]["value"] == 1


@pytest.mark.django_db(transaction=True)
def test_render_graph_table_query_applies_order_and_pagination(graph_controller, test_graph: core_models.Graph):
    graph_query = core_models.GraphTableQuery.objects.create(
        graph=test_graph,
        key="unwind_table",
        name="Unwind Table",
        description="query with variables",
        kind="TABLE",
        query="UNWIND [1, 2, 3] AS value RETURN value",
        columns=[{"key": "value", "type": "integer", "value_kind": "INT"}],
    )

    rendered = graph_controller.render_graph_table_query(
        graph_query,
        order=input_models.RenderGraphTableOrder(key="value", direction="desc"),
        pagination=input_models.RenderGraphTablePagination(limit=1, offset=0),
    )

    assert len(rendered.rows) == 1
    assert rendered.rows[0]["value"] == 3

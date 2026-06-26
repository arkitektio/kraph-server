import pytest
import kante
from kante.context import HttpContext

from core import models as core_models


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_and_render_graph_table_query_via_api(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    create_mutation = """
        mutation CreateGraphTableQueryThroughBuilder($input: CreateGraphTableQueryThroughBuilderInput!) {
            createGraphTableQueryThroughBuilder(input: $input) {
                id
            }
        }
    """

    create_result = await api_schema.execute(
        create_mutation,
        variable_values={
            "input": {
                "graph": str(test_graph.id),
                "key": "table_render_api_test",
                "name": "Table Render API Test",
                "columnInput": [
                    {
                        "kind": "VALUE",
                        "key": "node_value",
                        "type": "string",
                        "valueKind": "STRING",
                    }
                ],
                "builderArgs": {
                    "matchPaths": [
                        {
                            "title": "p0",
                            "nodes": ["n"],
                            "relations": [],
                        }
                    ],
                    "returnStatements": [
                        {
                            "path": "p0",
                            "node": "n",
                        }
                    ],
                },
            }
        },
        context_value=simple_api_context,
    )

    assert create_result.errors is None, f"GraphQL errors: {create_result.errors}"
    assert create_result.data is not None

    graph_query_id = create_result.data["createGraphTableQueryThroughBuilder"]["id"]

    render_query = """
        query RenderGraphTable($query: ID!) {
            renderGraphTable(query: $query) {
                graphName
                graph {
                    id
                }
                query {
                    id
                }
                rows
            }
        }
    """

    render_result = await api_schema.execute(
        render_query,
        variable_values={"query": graph_query_id},
        context_value=simple_api_context,
    )

    assert render_result.errors is None, f"GraphQL errors: {render_result.errors}"
    assert render_result.data is not None

    payload = render_result.data["renderGraphTable"]
    assert payload["graph"]["id"] == str(test_graph.id)
    assert payload["query"]["id"] == graph_query_id
    assert isinstance(payload["rows"], list)

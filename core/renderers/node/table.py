import json
from core.age import (
    RetrievedEntity,
    graph_cursor,
    RetrievedRelation,
    vertex_ag_to_retrieved_entity,
    to_entity_id,
)
import strawberry
from core import models, types, inputs
import re
import json
import re
import json
from kante.types import Info


def columns_to_age_string(columns: list[inputs.ColumnInput]):
    return ", ".join(f"{column.name} agtype" for column in columns)


def input_to_columns(columns: list[inputs.ColumnInput]) -> list[types.Column]:
    return [types.Column(**strawberry.asdict(column)) for column in columns]


def table(node_query: models.NodeQuery, node_id: str) -> types.Table:
    """
    Query the knowledge graph for information about a given entity.

    Args:
        query: The entity to search for in the knowledge graph.

    Returns:
        A dictionary containing information about the entity.
    """

    rows = []
    print("Called")

    tgraph = node_query.graph
    query = node_query.query
    columns = node_query.input_columns
    node_id = to_entity_id(node_id)
    print(tgraph.age_name)

    # First set the timeout
    real_query = f"""
    SELECT *
    FROM cypher(%s, $$
        {query}
    $$) as ({columns_to_age_string(columns)});
    """

    print(real_query, node_id)

    with graph_cursor() as cursor:
        cursor.execute(
            real_query,
            [tgraph.age_name, int(node_id)],
        )
        all_results = cursor.fetchall()

        print("The result", all_results)

        # Convert AGTYPE (JSON string) to Python dict

        for result in all_results:
            rows.append(result)

    return types.Table(rows=rows, columns=input_to_columns(columns), graph=tgraph)

import json
from core.age import (
    RetrievedEntity,
    graph_cursor,
    RetrievedRelation,
    vertex_ag_to_retrieved_entity,
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


def table(graph_query: models.GraphQuery) -> types.Table:
    """
    Query the knowledge graph for information about a given entity.

    Args:
        query: The entity to search for in the knowledge graph.

    Returns:
        A dictionary containing information about the entity.
    """

    rows = []
    print("Called")

    tgraph = graph_query.graph
    query = graph_query.query
    columns = graph_query.input_columns
    print(tgraph.age_name)

    # First set the timeout
    real_query = f"""
    SELECT *
    FROM cypher(%s, $$
        {query}
    $$) as ({columns_to_age_string(columns)});
    """

    print(real_query)

    with graph_cursor() as cursor:
        cursor.execute(
            real_query,
            [tgraph.age_name],
        )
        all_results = cursor.fetchall()

        print("The result", all_results)

        # Convert AGTYPE (JSON string) to Python dict

        for result in all_results:
            rows.append(result)

    return types.Table(rows=rows, columns=input_to_columns(columns), graph=tgraph)
